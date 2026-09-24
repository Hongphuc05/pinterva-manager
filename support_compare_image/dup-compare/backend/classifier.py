"""
Rule-based classifier, threshold lấy từ config.py (configurable), KHÔNG
hard-code. Chỉ trả về 2 tag: TRUNG / KHONG_TRUNG (đã bỏ 4 tag chi tiết cũ
EXACT_DUPLICATE/SAME_FORM_DIFFERENT_COLOR/SAME_FORM_DIFFERENT_CUSTOM_NAME/
DIFFERENT_DESIGN theo yêu cầu). Lý do chi tiết (exact/khác màu/khác custom
text) vẫn nằm trong `reasons` để biết VÌ SAO, chỉ không còn là tag riêng.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .config import THRESHOLDS
from .signals import phash_max_distance

CLASS_TRUNG = "TRUNG"
CLASS_KHONG_TRUNG = "KHONG_TRUNG"


@dataclass
class ClassificationResult:
    classification: str
    is_duplicate: bool
    confidence: float
    reasons: List[str] = field(default_factory=list)


def classify(
    visual_similarity: float,
    phash_dist: int,
    color_de: float,
    ssim_value: Optional[float],  # None = không tải được ảnh cũ, bỏ qua bước SSIM
    hash_size: int = 16,
) -> ClassificationResult:
    t = THRESHOLDS
    reasons: List[str] = []
    max_dist = phash_max_distance(hash_size)

    reasons.append(
        f"Visual embedding similarity = {visual_similarity:.3f} "
        f"(ngưỡng same-form: {t.design_similarity_threshold}, "
        f"ngưỡng exact: {t.exact_visual_similarity_threshold})"
    )
    reasons.append(
        f"pHash distance = {phash_dist}/{max_dist} bit "
        f"(ngưỡng exact: <= {t.exact_phash_max_distance})"
    )
    reasons.append(
        "SSIM = không tính được (không tải được ảnh cũ)" if ssim_value is None else
        f"SSIM = {ssim_value:.3f} (ngưỡng tối thiểu để coi là cùng design: "
        f"{t.design_ssim_min_threshold})"
    )
    reasons.append(
        f"Color Delta-E (LAB) = {color_de:.2f} (ngưỡng đổi màu: {t.color_delta_e_threshold})"
    )

    if (
        phash_dist <= t.exact_phash_max_distance
        and visual_similarity >= t.exact_visual_similarity_threshold
    ):
        reasons.append("=> pHash rất gần + visual similarity cực cao: ảnh gần như y hệt.")
        return ClassificationResult(CLASS_TRUNG, True, min(1.0, visual_similarity), reasons)

    if visual_similarity >= t.design_similarity_threshold:
        if ssim_value is not None and ssim_value < t.design_ssim_min_threshold:
            reasons.append(
                f"=> Visual similarity cao nhưng SSIM quá thấp "
                f"({ssim_value:.3f} < {t.design_ssim_min_threshold}): cấu trúc/họa tiết "
                f"khác nhau nhiều, không tính là cùng design dù sim cao."
            )
            return ClassificationResult(
                CLASS_KHONG_TRUNG, False, max(0.0, 1.0 - visual_similarity), reasons
            )
        if color_de >= t.color_delta_e_threshold:
            reasons.append(
                f"=> Bố cục/artwork giống nhau nhưng màu sản phẩm lệch "
                f"(ΔE={color_de:.2f} >= {t.color_delta_e_threshold}): đổi màu."
            )
        else:
            reasons.append(
                "=> Bố cục/artwork giống nhau, màu không lệch đáng kể "
                "(có thể khác custom text NAME/YEAR/NUMBER — chưa có OCR để xác nhận)."
            )
        return ClassificationResult(CLASS_TRUNG, True, visual_similarity, reasons)

    reasons.append("=> Visual similarity dưới ngưỡng same-form: hai thiết kế khác nhau.")
    return ClassificationResult(
        CLASS_KHONG_TRUNG, False, max(0.0, 1.0 - visual_similarity), reasons
    )
