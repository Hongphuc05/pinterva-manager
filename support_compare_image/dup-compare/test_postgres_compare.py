from uuid import uuid4

import numpy as np
from backend.postgres_compare import (
    CandidateResult,
    HistoricalImage,
    _candidate_indexes,
    _first_image_url,
    _pick_overall,
)


def _historical(external_order_id: str, value: float) -> HistoricalImage:
    vector = np.array([value, 1.0 - value, 0.0], dtype=np.float32)
    vector /= np.linalg.norm(vector)
    return HistoricalImage(
        asset_id=uuid4(),
        job_id=uuid4(),
        external_order_id=external_order_id,
        product_name="Product",
        image_url="https://example.test/image.png",
        embedding=vector,
        embedding_dim=3,
        model_version="test-model",
        phash="0" * 64,
        color_lab=(50.0, 0.0, 0.0),
    )


def test_primary_preview_prefers_thumbnail_then_gallery() -> None:
    assert _first_image_url("https://cdn.test/thumb.png", ["https://cdn.test/gallery.png"]) == "https://cdn.test/thumb.png"
    assert _first_image_url(None, ["/gallery.png"]) == "https://printerval.com/gallery.png"


def test_candidate_selection_excludes_same_external_order() -> None:
    pool = [_historical("DJ-self", 1.0), _historical("DJ-old", 0.99)]
    matrix = np.stack([row.embedding for row in pool])
    query = pool[0].embedding

    selected = _candidate_indexes(
        pool,
        matrix,
        query,
        external_order_id="DJ-self",
        top_k=5,
        exclude_self=True,
    )

    assert len(selected) == 1
    assert pool[selected[0][0]].external_order_id == "DJ-old"


def test_overall_decision_uses_highest_similarity_candidate() -> None:
    historical = _historical("DJ-old", 0.99)
    candidates = [
        CandidateResult(
            historical=historical,
            rank=1,
            visual_similarity=0.91,
            phash_distance=20,
            ssim=0.20,
            color_delta_e=0.0,
            classification="KHONG_TRUNG",
            confidence=0.09,
            reasons=[],
        ),
        CandidateResult(
            historical=historical,
            rank=2,
            visual_similarity=0.90,
            phash_distance=1,
            ssim=0.99,
            color_delta_e=0.0,
            classification="TRUNG",
            confidence=0.90,
            reasons=[],
        ),
    ]

    assert _pick_overall(candidates) == ("KHONG_TRUNG", False)
