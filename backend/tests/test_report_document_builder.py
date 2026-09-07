import pytest
from backend.tests.report_document_fixtures import build_demo_document
from app.services.report_document_builder import (
    relative_change_text,
    calendar_positions,
)


@pytest.mark.parametrize("disease", ["fatty_liver", "ad"])
def test_every_visit_and_identity_is_present(disease):
    doc = build_demo_document(disease)
    assert doc.identity.age == 62
    assert len(doc.sections) == 11
    assert (
        len(
            [
                table
                for table in doc.sections[3].tables
                if table.title.startswith("访视")
            ]
        )
        == 3
    )
    text = str(doc.sections[1].model_dump())
    for value in ["62", "女", "CASE-ABCD-2345"]:
        assert value in text
    assert all(s.paragraphs or any(t.rows for t in s.tables) for s in doc.sections)


def test_percent_and_calendar_are_not_misrepresented():
    assert relative_change_text(10, 0.5, "consistent") == "+50.00%"
    assert "不计算" in relative_change_text(0, None, "consistent")
    assert "单位不可比较" in relative_change_text(10, 0.5, "conflict")
    assert calendar_positions(["2025-01-01", "2025-01-02", "2025-04-11"]) == [
        0,
        0.01,
        1,
    ]


def test_failed_trend_has_separate_invocation_and_success_counts():
    doc = build_demo_document("ad", bad_trend=True)
    assert doc.summary.invoked_model_count == 4
    assert doc.summary.available_model_count == 3
    assert any(
        i.task.endswith(".mmse") and i.code == "prediction_failed"
        for i in doc.review_items
        if i.task
    )
