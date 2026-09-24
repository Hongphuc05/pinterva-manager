"""
Cấu hình threshold & model cho module so sánh ảnh trùng lặp.

Toàn bộ threshold đọc từ biến môi trường để dễ calibrate sau này bằng
dataset thật, không hard-code trong logic classifier.
"""
import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def _i(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


@dataclass(frozen=True)
class Thresholds:
    # --- Exact / near-exact duplicate ---
    # pHash là hash 256-bit (hash_size=16), khoảng cách Hamming càng nhỏ
    # càng giống nhau. <=6 thường coi là gần như y hệt (resize/nén nhẹ).
    exact_phash_max_distance: int = _i("EXACT_PHASH_MAX_DISTANCE", 6)
    exact_visual_similarity_threshold: float = _f("EXACT_SIMILARITY_THRESHOLD", 0.97)

    # --- Same form/design (áp dụng cho cả DIFFERENT_COLOR và DIFFERENT_CUSTOM_NAME) ---
    design_similarity_threshold: float = _f("DESIGN_SIMILARITY_THRESHOLD", 0.85)
    # Gate bổ sung: chỉ riêng visual_similarity cao là chưa đủ (2 mockup cùng
    # dạng áo/màu nền vẫn có thể ra sim cao dù họa tiết khác hẳn). Calibrate
    # trên data/labeled_examples (pair01-06, DINOv2 thật): 4 cặp TRUNG có
    # ssim 0.70-0.96, 2 cặp KHONG_TRUNG có ssim 0.30-0.49 -> đặt ở giữa dải
    # trống. Mẫu còn nhỏ, cần chỉnh lại khi có thêm dataset thật.
    design_ssim_min_threshold: float = _f("DESIGN_SSIM_MIN_THRESHOLD", 0.60)

    # --- Color ---
    # Delta-E (CIE76) trong không gian LAB. >~10 là khác biệt màu có thể nhận
    # ra rõ bằng mắt thường; số này CẦN calibrate lại trên ảnh sản phẩm thật.
    color_delta_e_threshold: float = _f("COLOR_DIFFERENCE_THRESHOLD", 12.0)

    # --- OCR (placeholder, chưa dùng trong bản MVP này) ---
    ocr_similarity_threshold: float = _f("OCR_SIMILARITY_THRESHOLD", 0.90)


@dataclass(frozen=True)
class ModelConfig:
    # Model embedding chính theo khuyến nghị. Nếu môi trường không có mạng
    # tới Hugging Face (bị chặn bởi egress policy, ví dụ trong sandbox này),
    # hệ thống tự fallback sang classical embedder (xem embedding.py) và báo
    # rõ trong response để không đánh lừa người dùng.
    embedding_model_name: str = os.environ.get(
        "EMBEDDING_MODEL_NAME", "facebook/dinov2-base"
    )
    # Đặt biến này = "classical" để ép dùng fallback (test/offline/dev)
    force_backend: str = os.environ.get("EMBEDDING_BACKEND", "auto")

    model_version: str = os.environ.get("MODEL_VERSION", "dinov2-base-v1")
    processing_version: str = os.environ.get("PROCESSING_VERSION", "mvp-0.2.0")


# Top-K candidate lấy ra từ vector search (brute-force ở quy mô nhỏ) để chạy
# comparison sâu (pHash/SSIM/color). Không hard-code trong logic, đọc ở đây.
TOP_K_CANDIDATES = _i("TOP_K_CANDIDATES", 5)

THRESHOLDS = Thresholds()
MODEL_CONFIG = ModelConfig()
