from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction
from app.services.longitudinal_report_generator import render_longitudinal_markdown
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import asyncio
import json
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
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 10, "unit": "U/L"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "alt", "value": 11.3, "unit": "U/L"}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    markdown = render_longitudinal_markdown(result.model_dump(mode="json"), [
        {"source_type": "reference_range", "indicator": "ALT", "unit": "U/L", "lower": 7, "upper": 40, "provenance": "reference_standard"},
        {"source_type": "similar_case", "patient_label": "P001", "overlap_features": ["alt", "ast"], "provenance": "reference"},
    ])

    assert markdown.count("| alt |") == 1
    assert "| alt | 10.00 | 11.30 | 1.30 |" in markdown
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


def test_ad_mmse_moca_signals_survive_without_outcome_model():
    visits = [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "MMSE", "value": mmse, "unit": "分"},
                {"name": "MoCA", "value": moca, "unit": "分"},
            ],
        }
        for visit_date, mmse, moca in [
            ("2024-01-01", 28, 25),
            ("2024-06-01", 25, 22),
            ("2024-12-31", 22, 18),
        ]
    ]

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci"}, visits, AD_ADAPTER, {}
    )

    names = {item.indicator for item in result.progression_signals.signals}
    assert {"mmse", "moca"}.issubset(names)
    assert all(
        item.used_by_outcome_model is False
        for item in result.progression_signals.signals
    )


def test_signal_provenance_and_limitations_do_not_leak_sensitive_values():
    visits = [
        {
            "visit_date": visit_date,
            "indicators": [{"name": "ALT", "value": value, "unit": "U/L"}],
        }
        for visit_date, value in [
            ("2024-01-01", 20),
            ("2024-06-01", 35),
            ("2024-12-31", 60),
        ]
    ]
    result = run_longitudinal_prediction(
        {"baseline_stage": None}, visits, FATTY_LIVER_ADAPTER, {}
    )
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    for secret in (
        "postgresql://",
        "password",
        "Traceback",
        "C:\\Users\\",
        "P001",
    ):
        assert secret not in serialized


def test_report_generator_passes_safe_standard_sources_to_prediction(monkeypatch):
    from app.services import longitudinal_report_generator as generator

    visits = [
        {
            "visit_date": visit_date,
            "indicators": [{"name": "ALT", "value": value, "unit": "U/L"}],
        }
        for visit_date, value in [
            ("2024-01-01", 20),
            ("2024-06-01", 35),
            ("2024-12-31", 60),
        ]
    ]
    prediction = run_longitudinal_prediction(
        {"baseline_stage": None}, visits, FATTY_LIVER_ADAPTER, {}
    )
    captured = {}

    def fake_prediction(*args, **kwargs):
        captured.update(kwargs)
        return prediction

    monkeypatch.setattr(generator, "run_longitudinal_prediction", fake_prediction)
    sources = [
        {
            "source_type": "reference_range",
            "indicator": "ALT",
            "unit": "U/L",
            "lower": 7,
            "upper": 40,
            "standard_version_id": 3,
            "standard_rule_id": 2,
        }
    ]
    report = SimpleNamespace(
        id=10,
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
                db,
                10,
                {"baseline_stage": None},
                visits,
                FATTY_LIVER_ADAPTER,
                model_registry={},
                sources=sources,
            )
        ]

    asyncio.run(collect())

    assert captured["standard_sources"] == sources
