from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.operator import download_report_pdf, get_report
from app.services.longitudinal_report_generator import render_longitudinal_markdown


def test_report_content_is_rendered_from_saved_snapshot_without_recalculation():
    prediction = {
        "schema_version": "longitudinal_prediction.v2",
        "disease": {"name": "脂肪肝"},
        "observation": {"visit_count": 3, "observation_span_days": 365, "indicators": {}},
        "outcome_prediction": {"risk_band": None, "risk_score": None, "stage_projection": {"status": "not_estimated"}},
        "model_status": {
            "outcome": {"status": "missing"}, "stage": {"status": "missing"}, "trend": {"status": "missing"}
        },
        "progression_signals": {"signals": [], "summary": {"signal_count": 0}},
        "warnings": [],
    }
    snapshot = {"patient_label": "匿名病例", "visits": [{"visit_date": "2025-01-01", "indicators": []}]}
    content_before = render_longitudinal_markdown(prediction, [], snapshot)
    snapshot["patient_label"] = "后来修改的标签"
    content_after = render_longitudinal_markdown(prediction, [], {"patient_label": "匿名病例", "visits": [{"visit_date": "2025-01-01", "indicators": []}]})
    assert content_after == content_before


def test_pdf_template_keeps_summary_signal_and_review_blocks_together():
    from pathlib import Path

    template = Path(__file__).parents[1].joinpath("app/templates/report_pdf.html").read_text(encoding="utf-8")
    assert "break-inside: avoid" in template
    assert ".report-summary" in template
    assert ".signal-block" in template
    assert ".review-block" in template


def _saved_report(content="生成时保存的完整正文"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=17,
        user_id=5,
        title="匿名纵向报告",
        query="匿名病例",
        department_ids=[],
        content=content,
        sources=[],
        retrieval_meta={},
        status="completed",
        error_message=None,
        download_count=0,
        analysis_type="longitudinal_predictive",
        disease_id=1,
        operator_case_id=8,
        indicators=[],
        prediction_result={"schema_version": "longitudinal_prediction.v2"},
        input_snapshot={"patient_label": "生成时标签"},
        created_at=now,
        updated_at=now,
    )


def _db_returning(report):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = report
    return db


def test_history_detail_returns_saved_content_after_case_changes(monkeypatch):
    from app.services import longitudinal_report_generator

    report = _saved_report()
    db = _db_returning(report)
    current_user = SimpleNamespace(id=5)
    case = {"patient_label": "生成时标签"}
    monkeypatch.setattr(
        longitudinal_report_generator,
        "run_longitudinal_prediction",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("打开历史报告时不应重新预测")
        ),
    )

    before = get_report(17, db=db, current_user=current_user)
    case["patient_label"] = "后来修改的标签"
    after = get_report(17, db=db, current_user=current_user)

    assert before.content == "生成时保存的完整正文"
    assert after.content == before.content
    assert after.input_snapshot["patient_label"] == "生成时标签"


def test_pdf_download_uses_saved_content_verbatim():
    report = _saved_report("网页、历史和 PDF 共用的正文")
    db = _db_returning(report)

    with patch("app.api.operator.generate_pdf", return_value=b"%PDF-test") as generate:
        response = download_report_pdf(
            17,
            db=db,
            current_user=SimpleNamespace(id=5),
        )

    generate.assert_called_once_with(
        "网页、历史和 PDF 共用的正文",
        "匿名纵向报告",
        report.prediction_result,
    )
    assert response.media_type == "application/pdf"
    assert report.download_count == 1
