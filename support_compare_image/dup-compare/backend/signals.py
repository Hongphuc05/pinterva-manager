"""
Các signal cổ điển, không cần deep model, chạy CPU, không cần mạng:
- pHash (perceptual hash) cho exact/near-exact duplicate.
- SSIM cho verification sâu hơn khi cần.
- Color difference (Delta-E trong không gian LAB) để phát hiện đổi màu áo.

OCR CHƯA được tích hợp trong bản MVP này (xem README) — mọi field liên quan
tới OCR trong output đều để null/placeholder, không bịa số liệu.

Các hàm "_from_..." làm việc trên giá trị đã precompute (hex hash, LAB mean)
để dùng khi so với pool trong DB — tránh phải mở lại ảnh cũ chỉ để tính lại
pHash/color mà DB đã lưu sẵn. SSIM thì bắt buộc phải mở ảnh (per-pixel), nên
chỉ tính cho Top-K candidate, không tính cho toàn bộ pool.
"""
from __future__ import annotations

import imagehash
import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
from skimage.color import rgb2lab, deltaE_cie76

PHASH_SIZE = 16  # 256-bit hash, nhạy hơn mặc định 8 (64-bit)


def compute_phash(image: Image.Image, hash_size: int = PHASH_SIZE) -> imagehash.ImageHash:
    return imagehash.phash(image.convert("RGB"), hash_size=hash_size)


def phash_distance(img_a: Image.Image, img_b: Image.Image, hash_size: int = PHASH_SIZE) -> int:
    """Khoảng cách Hamming giữa 2 perceptual hash tính trực tiếp từ ảnh."""
    return int(compute_phash(img_a, hash_size) - compute_phash(img_b, hash_size))


def phash_distance_from_hex(hex_a: str, hex_b: str) -> int:
    """So 2 pHash đã lưu dạng hex string trong DB — không cần mở lại ảnh."""
    return int(imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b))


def phash_max_distance(hash_size: int = PHASH_SIZE) -> int:
    return hash_size * hash_size


def ssim_score(img_a: Image.Image, img_b: Image.Image, size: int = 256) -> float:
    """SSIM trên ảnh grayscale đã resize cùng kích thước. Chỉ dùng làm
    verification bổ sung cho Top-K — SSIM rất nhạy với lệch vị trí/góc chụp
    nên không dùng làm tín hiệu chính để tìm duplicate."""
    a = np.asarray(img_a.convert("L").resize((size, size)))
    b = np.asarray(img_b.convert("L").resize((size, size)))
    score, _ = ssim(a, b, full=True)
    return float(score)


def mean_lab(image: Image.Image, size: int = 128) -> tuple:
    """Màu trung bình LAB của 1 ảnh — tính 1 lần, lưu vào DB, tái dùng khi
    so sánh thay vì mở lại ảnh."""
    arr = np.asarray(image.convert("RGB").resize((size, size))) / 255.0
    lab = rgb2lab(arr).reshape(-1, 3).mean(axis=0)
    return (float(lab[0]), float(lab[1]), float(lab[2]))


def color_delta_e_from_lab(lab_a: tuple, lab_b: tuple) -> float:
    return float(deltaE_cie76(np.array(lab_a), np.array(lab_b)))


def color_delta_e(img_a: Image.Image, img_b: Image.Image, size: int = 128) -> float:
    """Delta-E (CIE76) tính trực tiếp từ 2 ảnh (dùng cho endpoint /compare 1-1).

    GIỚI HẠN CỦA BẢN MVP: tính trên toàn bộ ảnh (chưa có garment mask từ
    bước segmentation), nên background/ánh sáng khác nhau có thể làm sai
    lệch số này. Trong kiến trúc production nên tính trên vùng đã mask
    garment (xem đề xuất cloth-segmentation ở phần kiến trúc trước đó).
    """
    return color_delta_e_from_lab(mean_lab(img_a, size), mean_lab(img_b, size))
