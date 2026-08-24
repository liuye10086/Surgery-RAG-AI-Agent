from app.services.disease_progression import FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction
from app.services.longitudinal_report_generator import render_longitudinal_markdown


def test_structured_prediction_and_report_keep_required_sections():
    result = run_longitudinal_prediction(
        {"patient_label": "case-A"},
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 45, "unit": "U/L"}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    markdown = render_longitudinal_markdown(result.model_dump(mode="json"), [{"patient_label": "P151", "provenance": "synthetic"}])
    for heading in ("报告摘要", "已观察到的纵向变化", "未来指标趋势预测", "疾病阶段与进展结局预测", "不确定性与局限性", "技术附录"):
        assert heading in markdown
    assert "合成" in markdown or "synthetic" in markdown
    assert "不构成诊断" in markdown
