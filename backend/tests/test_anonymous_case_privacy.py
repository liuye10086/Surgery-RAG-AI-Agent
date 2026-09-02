from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.api.operator import download_report_pdf
from app.services.longitudinal_report_generator import render_longitudinal_markdown
from app.services.longitudinal_case_service import build_input_snapshot


def test_new_case_snapshot_uses_anonymous_code_and_excludes_legacy_label():
    case = SimpleNamespace(
        disease_id=1,
        patient_label="张三",
        anonymous_case_code="CASE-7F3K-92LM",
        age=55,
        sex="male",
        baseline_stage="pre_cirrhosis",
        disease=SimpleNamespace(name="脂肪肝", code="fatty_liver"),
    )
    snapshot = build_input_snapshot(case, [], {})
    assert snapshot["anonymous_case_code"] == "CASE-7F3K-92LM"
    assert "patient_label" not in snapshot


def test_report_source_prefers_anonymous_code_over_sensitive_legacy_label():
    prediction = {
        "disease": {"name": "脂肪肝"},
        "observation": {"visit_count": 0, "observation_span_days": 0, "indicators": {}},
        "outcome_prediction": {"stage_projection": {}},
        "model_status": {},
        "progression_signals": {"signals": [], "summary": {"signal_count": 0}},
        "warnings": [],
    }
    sources = [{
        "source_type": "similar_case",
        "patient_label": "张三",
        "anonymous_case_code": "CASE-7F3K-92LM",
        "overlap_features": ["alt"],
    }]
    rendered = render_longitudinal_markdown(
        prediction, sources, {"anonymous_case_code": "CASE-7F3K-92LM", "visits": []}
    )
    assert "张三" not in rendered
    assert "CASE-7F3K-92LM" in rendered


def test_report_source_without_anonymous_code_uses_placeholder_not_legacy_label():
    prediction = {
        "disease": {"name": "脂肪肝"},
        "observation": {"visit_count": 0, "observation_span_days": 0, "indicators": {}},
        "outcome_prediction": {"stage_projection": {}},
        "model_status": {},
        "progression_signals": {"signals": [], "summary": {"signal_count": 0}},
        "warnings": [],
    }
    rendered = render_longitudinal_markdown(
        prediction,
        [{"source_type": "similar_case", "patient_label": "住院号123456", "overlap_features": ["alt"]}],
        {"visits": []},
    )
    assert "住院号123456" not in rendered
    assert "旧来源未设置匿名编号" in rendered


def test_pdf_filename_uses_anonymous_code_when_saved_title_is_sensitive():
    report = SimpleNamespace(
        id=17,
        user_id=5,
        title="张三纵向进展预测报告",
        query="张三",
        content="已保存正文",
        prediction_result={},
        status="completed",
        download_count=0,
        operator_case=SimpleNamespace(anonymous_case_code="CASE-7F3K-92LM"),
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = report
    with patch("app.api.operator.generate_pdf", return_value=b"%PDF"):
        response = download_report_pdf(17, db=db, current_user=SimpleNamespace(id=5))
    disposition = response.headers["Content-Disposition"]
    assert "张三" not in disposition
    assert "CASE-7F3K-92LM" in disposition


def test_pdf_title_uses_safe_report_id_when_legacy_report_has_no_anonymous_code():
    report = SimpleNamespace(
        id=18,
        user_id=5,
        title="住院号123456-张三报告",
        query="住院号123456",
        content="已保存正文",
        prediction_result={},
        status="completed",
        download_count=0,
        operator_case=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = report
    with patch("app.api.operator.generate_pdf", return_value=b"%PDF") as generate:
        download_report_pdf(18, db=db, current_user=SimpleNamespace(id=5))
    assert generate.call_args.args[1] == "报告-18"
