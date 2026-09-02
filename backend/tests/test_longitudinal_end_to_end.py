from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction
from app.services.longitudinal_report_generator import render_longitudinal_markdown
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import asyncio
import time
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
    assert 'AIReport.status == "generating"' in source


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
    assert report.status == "failed"
    assert report.error_stage == "prediction"


def test_terminal_report_is_not_overwritten_by_late_prediction_failure(monkeypatch):
    from app.services import longitudinal_report_generator as generator

    monkeypatch.setattr(
        generator,
        "run_longitudinal_prediction",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("late failure")),
    )
    report = SimpleNamespace(
        id=9,
        status="completed",
        error_message=None,
        error_stage=None,
        prediction_result={"saved": True},
        sources=[],
        content="saved",
        analysis_type="longitudinal_predictive",
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

    asyncio.run(collect())

    assert report.status == "completed"
    assert report.error_message is None
    assert report.content == "saved"


def test_prediction_timeout_converges_report_to_failed_timeout(monkeypatch):
    from app.services import longitudinal_report_generator as generator

    monkeypatch.setattr(generator, "PREDICTION_TIMEOUT_SECONDS", 0.001)

    def slow_prediction(*args, **kwargs):
        time.sleep(0.02)
        return {}

    monkeypatch.setattr(generator, "run_longitudinal_prediction", slow_prediction)
    report = SimpleNamespace(
        id=9,
        status="generating",
        error_message=None,
        error_stage=None,
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

    assert report.status == "failed"
    assert report.error_stage == "timeout"
    assert "timeout" in "".join(events)


def test_terminal_transition_uses_atomic_generating_guard():
    from app.services.longitudinal_report_generator import (
        _transition_report_from_generating,
    )

    report = SimpleNamespace(status="completed", content="saved")

    class Query:
        def __init__(self):
            self.criteria = ()

        def filter(self, *criteria):
            self.criteria = criteria
            return self

        def first(self):
            return report

        def update(self, values, synchronize_session=False):
            assert len(self.criteria) == 2
            assert synchronize_session is False
            if report.status != "generating":
                return 0
            for key, value in values.items():
                setattr(report, key, value)
            return 1

    query = Query()
    db = MagicMock()
    db.query.return_value = query

    changed = _transition_report_from_generating(
        db,
        9,
        status="failed",
        error_stage="prediction",
        error_message="longitudinal_prediction_failed",
    )

    assert changed is False
    assert report.status == "completed"
    assert report.content == "saved"
    db.commit.assert_called_once_with()


def test_persistence_failure_rolls_back_and_converges_to_failed_persistence():
    from app.services import longitudinal_report_generator as generator

    report = SimpleNamespace(
        id=9,
        status="generating",
        error_message=None,
        error_stage=None,
        prediction_result=None,
        sources=None,
        content=None,
        generation_fingerprint=None,
        analysis_type=None,
    )

    class Query:
        def __init__(self, db):
            self.db = db

        def filter(self, *criteria):
            return self

        def first(self):
            return report

        def update(self, values, synchronize_session=False):
            if report.status != "generating":
                return 0
            self.db.pending = dict(values)
            return 1

    class DB:
        def __init__(self):
            self.pending = None
            self.fail_next_commit = True
            self.rollback_count = 0

        def query(self, model):
            return Query(self)

        def commit(self):
            if self.fail_next_commit:
                self.fail_next_commit = False
                raise RuntimeError("database path and secret")
            for key, value in (self.pending or {}).items():
                setattr(report, key, value)
            self.pending = None

        def rollback(self):
            self.rollback_count += 1
            self.pending = None

    db = DB()

    async def collect():
        return [
            event
            async for event in generator.generate_longitudinal_report(
                db, 9, {}, [], FATTY_LIVER_ADAPTER, model_registry={}
            )
        ]

    events = asyncio.run(collect())

    assert report.status == "failed"
    assert report.error_stage == "persistence"
    assert report.error_message == "longitudinal_prediction_failed"
    assert db.rollback_count == 1
    assert "database path and secret" not in "".join(events)


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
