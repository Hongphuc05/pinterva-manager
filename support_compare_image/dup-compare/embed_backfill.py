"""
Backfill embedding cho ~100k ảnh preview Printerval đã crawl vào Postgres VPS
(schema support_compare_image). Chạy trên máy có GPU, Postgres qua SSH tunnel:

  ssh -N -L 15432:127.0.0.1:5432 USER@VPS_HOST          (terminal riêng, giữ mở)
  $env:DATABASE_URL = "postgresql://USER:PASS@127.0.0.1:15432/DB"
  py embed_backfill.py --limit 200                        (pilot)
  py embed_backfill.py                                    (full; chạy lại = tiếp chỗ dở)

- Asset đã có embedding cùng model_version -> bỏ qua (resume an toàn).
- Tải/đọc ảnh lỗi -> fetch_status='failed' + last_error, không làm dừng cả lượt.
  Muốn thử lại: UPDATE support_compare_image.image_assets
                SET fetch_status='pending' WHERE fetch_status='failed';
- Mỗi chunk (mặc định 512 ảnh) ghi DB 1 transaction; đứt tunnel chỉ mất chunk dở.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import psycopg
from PIL import Image
from tqdm import tqdm

from backend.config import MODEL_CONFIG
from backend.embedding import DinoV2Embedder
from backend.signals import compute_phash, mean_lab

S = "support_compare_image"
PENDING_WHERE = f"""
    a.fetch_status <> 'failed'
    AND NOT EXISTS (SELECT 1 FROM {S}.image_embeddings e
                    WHERE e.asset_id = a.id AND e.model_version = %(model)s)
"""
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
}


def fetch(row):
    """Chạy trong thread pool: tải ảnh + tính pHash/LAB (CPU) để GPU không phải chờ."""
    asset_id, url = row
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        # convert("RGB") giống hệt scan.py để embedding 2 phía cùng tiền xử lý
        img = Image.open(io.BytesIO(data)).convert("RGB")
        return asset_id, img, data, str(compute_phash(img)), mean_lab(img), None
    except Exception as exc:  # link chết, 403, ảnh hỏng...
        return asset_id, None, None, None, None, f"{type(exc).__name__}: {exc}"[:500]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, help="chỉ xử lý N ảnh (pilot)")
    ap.add_argument("--chunk", type=int, default=512, help="số ảnh mỗi lần ghi DB")
    ap.add_argument("--batch", type=int, default=64, help="batch size GPU")
    ap.add_argument("--workers", type=int, default=16, help="số thread tải ảnh")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not db_url:
        print("ERROR: thiếu biến môi trường DATABASE_URL", file=sys.stderr)
        return 2

    emb = DinoV2Embedder(MODEL_CONFIG.embedding_model_name)
    model = emb.name
    print(f"model={model} device={emb.device}")
    if emb.device != "cuda":
        print("CẢNH BÁO: không thấy CUDA, sẽ chạy CPU rất chậm", file=sys.stderr)
    chunk = min(args.chunk, args.limit) if args.limit else args.chunk

    with psycopg.connect(db_url) as conn, ThreadPoolExecutor(args.workers) as pool:
        total = conn.execute(
            f"SELECT COUNT(*) FROM {S}.image_assets a WHERE {PENDING_WHERE}", {"model": model}
        ).fetchone()[0]
        conn.commit()
        if args.limit:
            total = min(total, args.limit)
        print(f"cần embed: {total} ảnh")

        last_id = UUID(int=0)

        def next_chunk():
            nonlocal last_id
            rows = conn.execute(
                f"SELECT a.id, a.url FROM {S}.image_assets a "
                f"WHERE {PENDING_WHERE} AND a.id > %(last)s ORDER BY a.id LIMIT %(n)s",
                {"model": model, "last": last_id, "n": chunk},
            ).fetchall()
            if rows:
                last_id = rows[-1][0]
            return [pool.submit(fetch, r) for r in rows]

        bar = tqdm(total=total, unit="img")
        done = failed = 0
        futures = next_chunk()
        while futures:
            # Tải trước chunk sau trong lúc GPU xử lý chunk này.
            more = not args.limit or done + len(futures) < args.limit
            nxt = next_chunk() if more else []

            results = [f.result() for f in futures]
            ok = [r for r in results if r[1] is not None]
            bad = [(r[5], r[0]) for r in results if r[1] is None]

            emb_rows, meta_rows = [], []
            for i in range(0, len(ok), args.batch):
                part = ok[i : i + args.batch]
                vecs = emb.encode_batch([r[1] for r in part])
                for (aid, img, data, phash, lab, _), v in zip(part, vecs):
                    emb_rows.append((aid, model, v.tobytes(), len(v), phash, *lab))
                    meta_rows.append((hashlib.sha256(data).hexdigest(), len(data), img.width, img.height, aid))

            with conn.cursor() as cur:
                if emb_rows:
                    cur.executemany(
                        f"INSERT INTO {S}.image_embeddings "
                        "(asset_id, model_version, embedding, embedding_dim, phash, color_l, color_a, color_b) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                        emb_rows,
                    )
                    cur.executemany(
                        f"UPDATE {S}.image_assets SET fetch_status = 'embedded', last_error = NULL, "
                        "content_sha256 = %s, byte_size = %s, width = %s, height = %s WHERE id = %s",
                        meta_rows,
                    )
                if bad:
                    cur.executemany(
                        f"UPDATE {S}.image_assets SET fetch_status = 'failed', last_error = %s WHERE id = %s",
                        bad,
                    )
            conn.commit()

            done += len(results)
            failed += len(bad)
            bar.update(len(results))
            bar.set_postfix(failed=failed)
            futures = nxt
        bar.close()

    print(f"xong: {done} ảnh, lỗi {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
