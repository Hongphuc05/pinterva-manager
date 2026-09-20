from app.application.sanitization import (
    sanitize_order_detail_for_designer,
    sanitize_order_summary_for_designer,
)


def _summary(**overrides):
    item = {
        "id": "order-1",
        "version": 1,
        "external_order_id": "DJ4021305",
        "state": "QC_PENDING",
        "note_outsource": "https://drive.google.com/submitted-result",
        "previous_note_outsource": "old upstream note",
        "designer_note": "old note",
        "fix_approved_by_admin": False,
        "designer_note_released_for_fix": False,
    }
    item.update(overrides)
    return item


def test_designer_summary_hides_upstream_note_and_old_admin_note_outside_released_fix():
    result = sanitize_order_summary_for_designer(_summary()).model_dump()

    assert result["note_outsource"] == ""
    assert result["previous_note_outsource"] is None
    assert result["designer_note"] == ""


def test_designer_detail_only_exposes_explicit_admin_note_for_released_fix():
    result = sanitize_order_detail_for_designer(
        _summary(
            state="REVISION",
            fix_approved_by_admin=True,
            designer_note="Sửa lại logo theo mockup Admin đã kiểm tra.",
            designer_note_released_for_fix=True,
            result_versions=[{"drive_url": "https://drive.google.com/submitted-result"}],
        )
    ).model_dump()

    assert result["note_outsource"] == ""
    assert result["previous_note_outsource"] is None
    assert result["designer_note"] == "Sửa lại logo theo mockup Admin đã kiểm tra."
    assert result["result_versions"] == []


def test_designer_detail_keeps_an_explicitly_released_note_visible_while_fix_is_doing():
    result = sanitize_order_detail_for_designer(
        _summary(
            state="IN_PROGRESS",
            designer_note="Sửa phần tay áo theo bản mockup Admin đã duyệt.",
            designer_note_released_for_fix=True,
        )
    ).model_dump()

    assert result["note_outsource"] == ""
    assert result["designer_note"] == "Sửa phần tay áo theo bản mockup Admin đã duyệt."


def test_designer_detail_exposes_template_note_only_after_admin_resolves_task():
    result = sanitize_order_detail_for_designer(
        _summary(
            state="IN_PROGRESS",
            template_missing=False,
            designer_note="Temp: https://example.com/template",
            designer_note_released_for_fix=True,
        )
    ).model_dump()

    assert result["note_outsource"] == ""
    assert result["designer_note"] == "Temp: https://example.com/template"
