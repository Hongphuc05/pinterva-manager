"""
Chạy toàn bộ dataset đã gán nhãn tay (data/labeled_examples/manifest.json)
qua ĐÚNG embedding_backend đang cấu hình (DINOv2 nếu máy có mạng) để lấy số
thật (sim/pHash/ssim/ΔE) cho từng cặp, so với nhãn TRUNG/KHONG_TRUNG con
người đã gán, và với kết quả classify() hiện tại — để calibrate lại
threshold/logic trong backend/classifier.py bằng SỐ THẬT, không đoán suông.

Chạy (đứng ở thư mục dup-compare/): python3 calibrate_dataset.py
"""
import json

from PIL import Image

from backend.classifier import classify
from backend.config import DATA_DIR
from backend.embedding import get_embedder
from backend.signals import color_delta_e, phash_distance, ssim_score

LABELED_DIR = DATA_DIR / "labeled_examples"


def main():
    manifest = json.loads((LABELED_DIR / "manifest.json").read_text(encoding="utf-8"))
    embedder = get_embedder()
    print(f"embedding_backend = {embedder.name}")
    if "fallback" in embedder.name.lower():
        print(
            "!! Đang chạy fallback cổ điển (không phải DINOv2) — số dưới đây "
            "KHÔNG dùng để calibrate threshold cho model thật.\n"
        )
    else:
        print()

    header = f"{'id':<8}{'nhan_nguoi':<14}{'sim':>8}{'phash':>7}{'ssim':>8}{'dE':>8}{'du_doan':>14}"
    print(header)
    print("-" * len(header))

    n_wrong = 0
    for pair in manifest["pairs"]:
        img_a = Image.open(LABELED_DIR / pair["image_a"]).convert("RGB")
        img_b = Image.open(LABELED_DIR / pair["image_b"]).convert("RGB")

        emb_a, emb_b = embedder.encode(img_a), embedder.encode(img_b)
        sim = embedder.cosine_similarity(emb_a, emb_b)
        p_dist = phash_distance(img_a, img_b)
        ssim_v = ssim_score(img_a, img_b)
        de = color_delta_e(img_a, img_b)
        result = classify(sim, p_dist, de, ssim_v)

        label = pair["label"]
        mark = "" if label == result.classification else "  <-- SAI"
        if mark:
            n_wrong += 1
        print(
            f"{pair['id']:<8}{label:<14}{sim:>8.4f}{p_dist:>7}{ssim_v:>8.4f}"
            f"{de:>8.2f}{result.classification:>14}{mark}"
        )

    print(f"\n{n_wrong}/{len(manifest['pairs'])} cặp đang bị classify() phân loại sai so với nhãn người gán.")


if __name__ == "__main__":
    main()
