"""
SQLite store cho pool ảnh + kết quả match.

Chọn SQLite cho bản test local này (không cần server, 1 file, đủ cho vài
nghìn ảnh) theo đúng yêu cầu "chưa cần lớn". Schema cố tình đặt tên/cấu trúc
gần giống bảng `product_images` + `duplicate_matches` đã thiết kế ở kiến
trúc production (Postgres+pgvector) — sau này migrate chỉ đổi driver/nơi
lưu, không đổi tư duy đọc/ghi.

QUAN TRỌNG: embedding chỉ so sánh được trong CÙNG model_version. Khi đổi
model (DINOv2 -> DINOv3, hay bật lại DINOv2 sau khi từng chạy fallback
classical), các ảnh cũ trong DB với model_version khác sẽ KHÔNG được đưa
vào pool so sánh — tránh so sánh 2 vector không cùng không gian, dẫn tới
kết quả vô nghĩa. Xem cảnh báo trong scan.py.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    file_name TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('old', 'new')),
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,
    phash TEXT NOT NULL,
    color_l REAL NOT NULL,
    color_a REAL NOT NULL,
    color_b REAL NOT NULL,
    classification TEXT,
    is_duplicate INTEGER,
    model_version TEXT NOT NULL,
    processing_version TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    new_image_id INTEGER NOT NULL REFERENCES images(id),
    matched_image_id INTEGER NOT NULL REFERENCES images(id),
    visual_similarity REAL NOT NULL,
    phash_distance INTEGER NOT NULL,
    ssim REAL NOT NULL,
    color_delta_e REAL NOT NULL,
    classification TEXT NOT NULL,
    confidence REAL NOT NULL,
    classifier_version TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@dataclass
class ImageRow:
    id: int
    file_path: str
    file_name: str
    source: str
    embedding: np.ndarray
    phash: str
    color_lab: tuple
    classification: Optional[str]
    is_duplicate: Optional[bool]
    model_version: str


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def image_exists(conn: sqlite3.Connection, file_path: str) -> bool:
    cur = conn.execute("SELECT 1 FROM images WHERE file_path = ?", (file_path,))
    return cur.fetchone() is not None


def insert_image(
    conn: sqlite3.Connection,
    file_path: str,
    file_name: str,
    source: str,
    embedding: np.ndarray,
    phash: str,
    color_lab: tuple,
    model_version: str,
    processing_version: str,
    classification: Optional[str] = None,
    is_duplicate: Optional[bool] = None,
) -> int:
    emb = embedding.astype(np.float32)
    cur = conn.execute(
        """INSERT INTO images
           (file_path, file_name, source, embedding, embedding_dim, phash,
            color_l, color_a, color_b, classification, is_duplicate,
            model_version, processing_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            file_path,
            file_name,
            source,
            emb.tobytes(),
            emb.shape[0],
            phash,
            float(color_lab[0]),
            float(color_lab[1]),
            float(color_lab[2]),
            classification,
            None if is_duplicate is None else int(is_duplicate),
            model_version,
            processing_version,
        ),
    )
    return cur.lastrowid


def get_pool(conn: sqlite3.Connection, model_version: str) -> List[ImageRow]:
    """Lấy toàn bộ ảnh CÙNG model_version để so sánh (khác model_version bị
    loại — embedding không cùng không gian vector)."""
    cur = conn.execute(
        """SELECT id, file_path, file_name, source, embedding, phash,
                  color_l, color_a, color_b, classification, is_duplicate,
                  model_version
           FROM images WHERE model_version = ?""",
        (model_version,),
    )
    rows = []
    for r in cur.fetchall():
        emb = np.frombuffer(r[4], dtype=np.float32)
        rows.append(
            ImageRow(
                id=r[0],
                file_path=r[1],
                file_name=r[2],
                source=r[3],
                embedding=emb,
                phash=r[5],
                color_lab=(r[6], r[7], r[8]),
                classification=r[9],
                is_duplicate=None if r[10] is None else bool(r[10]),
                model_version=r[11],
            )
        )
    return rows


def count_other_model_versions(conn: sqlite3.Connection, model_version: str) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM images WHERE model_version != ?", (model_version,)
    )
    return cur.fetchone()[0]


def insert_match(
    conn: sqlite3.Connection,
    new_image_id: int,
    matched_image_id: int,
    visual_similarity: float,
    phash_distance: int,
    ssim: float,
    color_delta_e: float,
    classification: str,
    confidence: float,
    classifier_version: str,
) -> int:
    cur = conn.execute(
        """INSERT INTO matches
           (new_image_id, matched_image_id, visual_similarity, phash_distance,
            ssim, color_delta_e, classification, confidence, classifier_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_image_id,
            matched_image_id,
            visual_similarity,
            phash_distance,
            ssim,
            color_delta_e,
            classification,
            confidence,
            classifier_version,
        ),
    )
    return cur.lastrowid


def get_matches_for_image(conn: sqlite3.Connection, new_image_id: int) -> List[dict]:
    cur = conn.execute(
        """SELECT m.matched_image_id, i.file_name, i.file_path, m.visual_similarity,
                  m.phash_distance, m.ssim, m.color_delta_e, m.classification, m.confidence
           FROM matches m JOIN images i ON i.id = m.matched_image_id
           WHERE m.new_image_id = ? ORDER BY m.visual_similarity DESC""",
        (new_image_id,),
    )
    cols = [
        "matched_image_id", "file_name", "file_path", "visual_similarity",
        "phash_distance", "ssim", "color_delta_e", "classification", "confidence",
    ]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def pool_stats(conn: sqlite3.Connection) -> dict:
    cur = conn.execute(
        "SELECT source, COUNT(*) FROM images GROUP BY source"
    )
    stats = {"old": 0, "new": 0}
    for source, n in cur.fetchall():
        stats[source] = n
    return stats


def reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    get_connection(db_path).close()
