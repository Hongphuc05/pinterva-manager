"""
Visual embedding service — tách interface riêng để sau này swap DINOv2 sang
DINOv3 (hoặc model khác) mà không phải sửa code gọi nó (main.py, classifier.py).

Có 2 implementation:
- DinoV2Embedder: model khuyến nghị thật (DINOv2, HuggingFace transformers).
  Cần mạng ra ngoài tới huggingface.co để tải checkpoint lần đầu.
- ClassicalFallbackEmbedder: không cần mạng, không cần GPU, dùng HOG
  (Histogram of Oriented Gradients) trên ảnh grayscale để xấp xỉ "cấu trúc/
  bố cục" của thiết kế. Đây KHÔNG phải model khuyến nghị — chỉ là phao cứu
  sinh để demo chạy được ở môi trường không có internet ra HuggingFace.
  Độ chính xác sẽ thấp hơn DINOv2/DINOv3 nhiều, đặc biệt với ảnh có nền/pose
  phức tạp.

get_embedder() tự chọn backend: thử load DINOv2 trước, nếu lỗi (mạng bị
chặn, model chưa tải được, thiếu dependency...) thì fallback tự động và
log rõ lý do. Kết quả trả về luôn kèm field "backend" để người dùng biết
đang test với model nào — tránh hiểu nhầm số liệu là từ DINOv2 trong khi
thực ra đang chạy fallback.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

import numpy as np
from PIL import Image

from .config import MODEL_CONFIG

logger = logging.getLogger("dup_compare.embedding")


class VisualEmbedder(ABC):
    name: str = "abstract"

    @abstractmethod
    def encode(self, image: Image.Image) -> np.ndarray:
        """Trả về vector embedding đã L2-normalize (norm = 1)."""
        raise NotImplementedError

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        # Vector đã normalize nên cosine = dot product; vẫn chia norm cho an toàn.
        denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1e-8
        sim = float(np.dot(a, b) / denom)
        # Clip để tránh sai số float đẩy ra ngoài [-1, 1]
        return max(-1.0, min(1.0, sim))


class DinoV2Embedder(VisualEmbedder):
    """Model khuyến nghị: DINOv2 (đổi sang DINOv3 chỉ bằng cách đổi
    EMBEDDING_MODEL_NAME trong config, không cần sửa code)."""

    def __init__(self, model_name: str):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.name = model_name
        self._torch = torch
        self.processor = AutoImageProcessor.from_pretrained(model_name)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = AutoModel.from_pretrained(model_name).to(self.device)
        self.model.eval()

    def encode(self, image: Image.Image) -> np.ndarray:
        return self.encode_batch([image])[0]

    def encode_batch(self, images: List[Image.Image]) -> np.ndarray:
        """(N, dim) float32, mỗi dòng đã L2-normalize. encode() đi qua đúng hàm
        này để embedding backfill theo batch và embedding lẻ cùng một code path."""
        torch = self._torch
        inputs = self.processor(
            images=[im.convert("RGB") for im in images], return_tensors="pt"
        ).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
        # mean-pool patch tokens (bỏ [CLS]) — ổn định hơn CLS riêng lẻ cho
        # bài toán so sánh structural similarity theo kinh nghiệm chung.
        pooled = outputs.last_hidden_state[:, 1:].mean(dim=1).cpu().numpy().astype(np.float32)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled / np.maximum(norms, 1e-8)


class ClassicalFallbackEmbedder(VisualEmbedder):
    """Fallback không cần mạng/GPU: HOG (structure) nối với histogram màu
    Hue-only (ít nhạy độ sáng) để có một proxy thô cho "cùng bố cục design".
    KHÔNG dùng cho production — chỉ để pipeline chạy được khi chưa tải được
    DINOv2/DINOv3."""

    name = "classical-hog-fallback (KHÔNG phải model khuyến nghị — chỉ demo offline)"

    def __init__(self, image_size: int = 256):
        from skimage.feature import hog
        from skimage.color import rgb2gray

        self._hog = hog
        self._rgb2gray = rgb2gray
        self.image_size = image_size

    def encode(self, image: Image.Image) -> np.ndarray:
        img = image.convert("RGB").resize((self.image_size, self.image_size))
        arr = np.asarray(img) / 255.0
        gray = self._rgb2gray(arr)
        hog_vec = self._hog(
            gray,
            orientations=9,
            pixels_per_cell=(16, 16),
            cells_per_block=(2, 2),
            feature_vector=True,
        )
        vec = hog_vec.astype(np.float32)
        norm = np.linalg.norm(vec) or 1e-8
        return vec / norm


_embedder_singleton: Optional[VisualEmbedder] = None


def get_embedder() -> VisualEmbedder:
    global _embedder_singleton
    if _embedder_singleton is not None:
        return _embedder_singleton

    if MODEL_CONFIG.force_backend == "classical":
        logger.warning("EMBEDDING_BACKEND=classical -> ép dùng fallback theo cấu hình.")
        _embedder_singleton = ClassicalFallbackEmbedder()
        return _embedder_singleton

    try:
        _embedder_singleton = DinoV2Embedder(MODEL_CONFIG.embedding_model_name)
        logger.info(
            "Đã load model embedding khuyến nghị: %s (device=%s)",
            MODEL_CONFIG.embedding_model_name,
            _embedder_singleton.device,
        )
    except Exception as exc:  # network bị chặn, thiếu dependency, model gated...
        logger.warning(
            "Không load được %s (%s: %s). Fallback sang classical embedder — "
            "CHỈ để demo, không phản ánh chất lượng model khuyến nghị thật.",
            MODEL_CONFIG.embedding_model_name,
            type(exc).__name__,
            exc,
        )
        _embedder_singleton = ClassicalFallbackEmbedder()

    return _embedder_singleton
