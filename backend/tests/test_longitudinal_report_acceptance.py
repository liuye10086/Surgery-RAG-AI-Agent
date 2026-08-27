import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.operator import download_report_pdf
from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction
from app.services.longitudinal_report_generator import render_longitudinal_markdown
from app.services.pdf_generator import _markdown_to_safe_html


REQUIRED_SECTIONS = (
    "报告摘要",
    "病例与预测范围",
    "数据质量与适用性",
    "已观察到的纵向变化",
    "未来 365 天进展风险",
    "阶段模型和下一次随访趋势的可用状态",
    "关键进展信号",
    "参考标准和相似病例",
    "不确定性与局限性",
    "人工复核重点",
    "模型和数据技术附录",
)


def _fatty_liver_visits():
    return [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "ALT", "value": alt, "unit": "U/L"},
                {"name": "ALB", "value": alb, "unit": "g/L"},
            ],
        }
        for visit_date, alt, alb in (
            ("2024-01-01", 20, 45),
            ("2024-06-01", 35, 39),
            ("2024-12-31", 60, 32),
        )
    ]


def _ad_visits():
    return [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "MMSE", "value": mmse, "unit": "分"},
                {"name": "MoCA", "value": moca, "unit": "分"},
                {"name": "CDR", "value": cdr, "unit": "分"},
            ],
        }
        for visit_date, mmse, moca, cdr in (
            ("2024-01-01", 28, 25, 0.5),
            ("2024-06-01", 25, 22, 1.0),
            ("2024-12-31", 22, 18, 1.0),
        )
    ]


def _outcome_visit(day: str, value: float):
    return {
        "visit_date": day,
        "indicators": [{"name": "ALT", "value": value, "unit": "U/L"}],
    }


def _outcome_metadata():
    from app.schemas.longitudinal_model_registry import ArtifactMetadata

    names = [
        "age",
        "visit_count",
        "observation_span_days",
        "days_since_previous_visit",
        "alt.first",
        "alt.last",
        "alt.time_slope_per_day",
        "alt.missing_ratio",
        "sex",
    ]
    order_hash = hashlib.sha256(
        json.dumps(names, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ArtifactMetadata.model_validate(
        {
            "schema_version": "longitudinal_outcome_artifact.v1",
            "artifact_type": "outcome",
            "task": "fatty_liver.pre_cirrhosis_to_progression",
            "dataset": "fatty_liver",
            "disease": "脂肪肝",
            "current_state": "pre_cirrhosis",
            "target": "cirrhosis_or_hcc",
            "horizon_days": 365,
            "feature_contract": {
                "schema_version": "longitudinal_fixed_window_features.v1",
                "feature_version": "longitudinal_fixed_window_features.v1",
                "feature_names": names,
                "feature_order_sha256": order_hash,
                "numeric_features": names[:-1],
                "categorical_features": ["sex"],
                "required_features": [
                    "visit_count",
                    "observation_span_days",
                    "days_since_previous_visit",
                ],
                "allowed_missing_features": [
                    "age",
                    "alt.first",
                    "alt.last",
                    "alt.time_slope_per_day",
                    "alt.missing_ratio",
                    "sex",
                ],
                "input_container": "pandas_dataframe",
                "numeric_imputation": "median_add_indicator",
                "categorical_imputation": "most_frequent",
            },
            "dataset_contract": {
                "schema_version": "longitudinal_fixed_window_dataset.v1",
                "manifest_sha256": "a" * 64,
                "data_content_sha256": "b" * 64,
                "training_file_sha256": "c" * 64,
            },
            "model_contract": {
                "model_id": "acceptance-model",
                "model_name": "logistic_regression",
                "model_version": "2026.08.27.1",
                "algorithm": "logistic_regression",
                "artifact_sha256": "d" * 64,
                "packages": {
                    "python": "3.11",
                    "scikit_learn": "1.9.0",
                    "joblib": "1.5.3",
                    "numpy": "2.3.5",
                    "pandas": "3.0.3",
                },
            },
            "score_contract": {
                "semantics": "model_score",
                "positive_class": 1,
                "threshold": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "calibration": {"status": "not_calibrated", "method": None},
            "audit": {
                "leakage_status": "passed",
                "clinical_validity_claim": False,
                "code_version": "acceptance-test",
            },
            "status": "candidate",
            "production_enabled": False,
            "created_at": "2026-08-27T00:00:00Z",
        }
    )


class _OutcomeScoreModel:
    classes_ = [0, 1]

    def predict_proba(self, rows):
        assert list(rows.columns)[-1] == "sex"
        return [[0.25, 0.75]]


def _assert_complete_plain_report(content: str):
    for title in REQUIRED_SECTIONS:
        assert title in content
    for internal in ("progression_signal", "likely_rising", "direction_only"):
        assert internal not in content
    assert "不构成诊断或治疗建议" in content


def test_fatty_liver_three_visit_report_keeps_p006_signals_and_full_table():
    sources = [
        {
            "source_type": "reference_range",
            "indicator": "ALT",
            "unit": "U/L",
            "lower": 7,
            "upper": 40,
            "standard_version_id": 3,
            "standard_rule_id": 2,
            "provenance": "approved_standard",
        }
    ]
    result = run_longitudinal_prediction(
        {"baseline_stage": None},
        _fatty_liver_visits(),
        FATTY_LIVER_ADAPTER,
        {},
        standard_sources=sources,
    )
    payload = result.model_dump(mode="json")
    content = render_longitudinal_markdown(payload, sources)

    _assert_complete_plain_report(content)
    assert "| alt | 20.00 | 60.00 | 40.00 | 3 次 | U/L |" in content
    assert "| alb | 45.00 | 32.00 | -13.00 | 3 次 | g/L |" in content
    assert len(result.progression_signals.signals) == 2
    assert all(signal.model_contribution is None for signal in result.progression_signals.signals)
    pdf_html = _markdown_to_safe_html(content, payload)
    assert pdf_html.count("已观察值趋势图") == 2


def test_ad_three_visit_report_keeps_cdr_as_stage_related_observation():
    result = run_longitudinal_prediction(
        {"baseline_stage": "mci"},
        _ad_visits(),
        AD_ADAPTER,
        {},
    )
    content = render_longitudinal_markdown(result.model_dump(mode="json"))

    _assert_complete_plain_report(content)
    assert {signal.indicator for signal in result.progression_signals.signals} == {
        "mmse",
        "moca",
        "cdr",
    }
    assert "阶段相关" in content
    assert "阶段模型：尚未配置，因此未预测下一阶段" in content
    assert "CDR 阶段模型结论" not in content


def test_outcome_can_be_available_while_stage_remains_unavailable():
    from app.schemas.longitudinal_model_registry import (
        LoadedModelEntry,
        LongitudinalModelRegistry,
        ModelRuntimeStatus,
    )
    from app.services.longitudinal_model_registry import empty_optional_model_status
    metadata = _outcome_metadata()
    status = ModelRuntimeStatus(
        artifact_type="outcome",
        task=metadata.task,
        status="available",
        reason_code="artifact_available",
        lifecycle_status="enabled",
        model_id=metadata.model_contract.model_id,
        model_name=metadata.model_contract.model_name,
        model_version=metadata.model_contract.model_version,
        artifact_sha256=metadata.model_contract.artifact_sha256,
        target=metadata.target,
        horizon_days=metadata.horizon_days,
        feature_version=metadata.feature_contract.feature_version,
        score_semantics=metadata.score_contract.semantics,
        calibration_status=metadata.calibration.status,
    )
    registry = LongitudinalModelRegistry(
        dataset="fatty_liver",
        outcomes={
            metadata.task: LoadedModelEntry(
                status=status,
                metadata=metadata,
                model=_OutcomeScoreModel(),
            )
        },
        stage=empty_optional_model_status("stage", "stage_model_missing"),
        trend=empty_optional_model_status("trend", "trend_model_missing"),
    )
    result = run_longitudinal_prediction(
        {"baseline_stage": "pre_cirrhosis", "sex": "female"},
        [
            _outcome_visit("2024-01-01", 10),
            _outcome_visit("2024-06-01", 20),
            _outcome_visit("2024-12-31", 30),
        ],
        FATTY_LIVER_ADAPTER,
        registry,
    )
    content = render_longitudinal_markdown(result.model_dump(mode="json"))

    assert result.outcome_prediction.risk_score == 0.75
    assert result.model_status.stage.status == "missing"
    assert "365 天结局模型：已启用并参与本次推理" in content
    assert "阶段模型：尚未配置，因此未预测下一阶段" in content
    assert "模型分数：0.75" in content


def test_complete_v3_report_separates_observation_outcome_stage_and_trend():
    from backend.tests.test_longitudinal_prediction_contract import (
        _ad_visits as complete_ad_visits,
        _complete_ad_suite,
    )

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        complete_ad_visits(),
        AD_ADAPTER,
        _complete_ad_suite(),
    )
    content = render_longitudinal_markdown(result.model_dump(mode="json"), [])

    assert "已观察到的纵向变化" in content
    assert "未来 365 天进展风险" in content
    assert "下一疾病阶段预测" in content
    assert "下一次访视指标趋势预测" in content
    assert "模型分数，不代表临床概率" in content
    assert "已观察方向" in content
    assert "模型预测方向" in content
    assert "dementia" not in content
    assert "direction_only" not in content


def test_missing_standard_and_unit_conflict_degrade_without_fabrication():
    visits = [
        {
            "visit_date": visit_date,
            "indicators": [{"name": "ALT", "value": value, "unit": unit}],
        }
        for visit_date, value, unit in (
            ("2024-01-01", 20, "U/L"),
            ("2024-06-01", 35, "mg/L"),
            ("2024-12-31", 60, "U/L"),
        )
    ]
    result = run_longitudinal_prediction(
        {"baseline_stage": None}, visits, FATTY_LIVER_ADAPTER, {}
    )
    payload = result.model_dump(mode="json")
    content = render_longitudinal_markdown(payload, [])

    assert "当前没有可用的正式参考标准" in content
    assert "无法安全比较" in content
    assert "仅表格：单位问题，未绘制趋势或判断异常" in content
    assert "参考范围：" not in content
    assert "ALT 已观察值趋势图" not in _markdown_to_safe_html(content, payload)


def test_pdf_failure_returns_safe_message_without_local_details():
    report = SimpleNamespace(
        id=21,
        user_id=5,
        title="匿名报告",
        content="持久化正文",
        prediction_result={},
        status="completed",
        download_count=0,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = report
    secret = r"C:\private\chromium.exe Traceback password"

    with patch("app.api.operator.generate_pdf", side_effect=RuntimeError(secret)):
        with pytest.raises(HTTPException) as raised:
            download_report_pdf(21, db=db, current_user=SimpleNamespace(id=5))

    assert raised.value.status_code == 500
    assert raised.value.detail == "PDF 生成暂时失败，请稍后重试"
    assert secret not in raised.value.detail
