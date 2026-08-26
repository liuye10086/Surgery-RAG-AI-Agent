from app.services.disease_progression import FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction
from app.services.longitudinal_report_generator import render_longitudinal_markdown
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import asyncio
import pytest


def test_structured_prediction_and_report_keep_required_sections():
    result = run_longitudinal_prediction(
        {"patient_label": "case-A", "baseline_stage": "pre_cirrhosis"},
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


def test_longitudinal_stream_has_explicit_client_cancel_state_handling():
    source = Path(__file__).parents[1].joinpath(
        "app/services/longitudinal_report_generator.py"
    ).read_text(encoding="utf-8")
    assert "asyncio.CancelledError" in source
    assert '"cancelled"' in source
    assert 'report.status == "generating"' in source


def test_report_formats_numbers_and_typed_evidence_without_duplicates():
    result = run_longitudinal_prediction(
        {"patient_label": "case-A", "baseline_stage": "pre_cirrhosis"},
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 10}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "alt", "value": 11.3}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    markdown = render_longitudinal_markdown(result.model_dump(mode="json"), [
        {"source_type": "reference_range", "indicator": "ALT", "unit": "U/L", "lower": 7, "upper": 40, "provenance": "reference_standard"},
        {"source_type": "similar_case", "patient_label": "P001", "overlap_features": ["alt", "ast"], "provenance": "reference"},
    ])

    assert markdown.count("alt: 首次") == 1
    assert "变化 1.30" in markdown
    assert "模型分数：0.70" in render_longitudinal_markdown({
        **result.model_dump(mode="json"),
        "outcome_prediction": {
            **result.model_dump(mode="json")["outcome_prediction"],
            "risk_score": 0.7,
        },
    })
    assert "参考范围：ALT（U/L），[7.00, 40.00]" in markdown
    assert "相似病例：P001；关联指标：alt、ast（reference）" in markdown


@pytest.mark.parametrize(
    "secret",
    [
        r"C:\private\model.joblib",
        "P001",
        "postgresql://user:password@localhost/private",
        "Traceback (most recent call last)",
    ],
)
def test_prediction_failure_does_not_leak_sensitive_details(secret, monkeypatch):
    from app.services import longitudinal_report_generator as generator

    monkeypatch.setattr(
        generator,
        "run_longitudinal_prediction",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError(secret)),
    )
    report = SimpleNamespace(
        id=9,
        status="generating",
        error_message=None,
        prediction_result=None,
        sources=None,
        content=None,
        analysis_type=None,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = report

    async def collect():
        return [
            event
            async for event in generator.generate_longitudinal_report(
                db, 9, {}, [], FATTY_LIVER_ADAPTER, model_registry={}
            )
        ]

    events = asyncio.run(collect())
    serialized = "".join(events) + str(report.error_message)
    assert secret not in serialized
    assert "longitudinal_prediction_failed" in serialized
