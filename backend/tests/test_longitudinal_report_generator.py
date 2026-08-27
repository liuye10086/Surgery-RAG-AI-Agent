from app.services.longitudinal_report_generator import render_longitudinal_markdown


def _prediction():
    return {
        "disease": {"name": "脂肪肝"},
        "observation": {"visit_count": 2, "observation_span_days": 30, "indicators": {}},
        "outcome_prediction": {
            "risk_band": "low",
            "risk_score": 0.2,
            "stage_projection": {"status": "not_estimated", "likely_next_stage": None, "stage_candidates": []},
        },
        "trend_predictions": [],
        "warnings": [],
    }


def _v2_prediction():
    prediction = _prediction()
    prediction["schema_version"] = "longitudinal_prediction.v2"
    prediction["model_status"] = {
        "outcome": {
            "artifact_type": "outcome",
            "task": "fatty_liver.pre_cirrhosis_to_progression",
            "status": "disabled",
            "reason_code": "lifecycle_not_enabled",
            "lifecycle_status": "candidate",
        },
        "stage": {
            "artifact_type": "stage",
            "status": "missing",
            "reason_code": "stage_model_missing",
        },
        "trend": {
            "artifact_type": "trend",
            "status": "missing",
            "reason_code": "trend_model_missing",
        },
    }
    prediction["outcome_prediction"]["risk_score"] = None
    prediction["outcome_prediction"]["risk_band"] = None
    return prediction


def _v2_prediction_with_signals(signals):
    prediction = _v2_prediction()
    prediction["progression_signals"] = {
        "schema_version": "longitudinal_signal_interpretation.v1",
        "signals": signals,
        "omitted_indicators": [],
        "summary": {
            "signal_count": len(signals),
            "omitted_count": 0,
            "minimum_observations": 3,
            "summary_code": (
                "signals_available" if signals else "insufficient_key_signals"
            ),
        },
    }
    return prediction


def test_report_renders_evidence_only_warning():
    content = render_longitudinal_markdown(_prediction(), [{
        "source_type": "standard_evidence",
        "indicator": "FDG-PET SUVR",
        "applicability_warning": "缺少适用条件：platform",
        "standard_version_id": 3,
        "standard_rule_id": 8,
    }])

    assert "仅供证据参考，未进入计算" in content
    assert "缺少适用条件：platform" in content


def test_report_source_snapshot_is_renderable_without_recalculation():
    source = {
        "source_type": "reference_range",
        "indicator": "ALT",
        "unit": "U/L",
        "lower": 7,
        "upper": 40,
        "lower_inclusive": True,
        "upper_inclusive": False,
        "standard_version_id": 12,
        "standard_rule_id": 9,
        "applicability_hash": "abc",
        "applicability": {"sex": "male"},
    }

    content = render_longitudinal_markdown(_prediction(), [source])

    assert "参考范围：ALT（U/L）" in content


def test_v2_report_renders_independent_model_statuses():
    content = render_longitudinal_markdown(_v2_prediction())
    assert "365 天结局模型：未启用，因此未计算风险分数" in content
    assert "阶段模型：尚未配置，因此未预测下一阶段" in content
    assert "趋势模型：尚未配置，仅展示已观察到的指标变化" in content


def test_renderer_accepts_historical_v1_payload():
    content = render_longitudinal_markdown(_prediction())
    assert "纵向进展预测报告" in content


def test_report_renders_structured_signal_reasons_in_chinese():
    prediction = _v2_prediction_with_signals(
        [
            {
                "indicator": "alt",
                "display_name": "谷丙转氨酶",
                "unit": "U/L",
                "first_value": 20,
                "latest_value": 60,
                "absolute_change": 40,
                "relative_change": 2.0,
                "observation_count": 3,
                "observation_span_days": 365,
                "observed_direction": "rising",
                "disease_attention_direction": "rising",
                "reference_status": "above_range",
                "attention_level": "priority",
                "reason_codes": [
                    "directional_change",
                    "latest_above_reference",
                ],
                "used_by_outcome_model": False,
                "model_feature_names": [],
                "model_contribution_status": "unavailable",
                "model_contribution": None,
                "provenance": {
                    "standard_version_id": 3,
                    "standard_rule_id": 2,
                },
                "limitations": [],
            }
        ]
    )

    content = render_longitudinal_markdown(prediction)

    assert "谷丙转氨酶" in content
    assert "上升" in content
    assert "最新值高于适用参考范围" in content
    assert "暂无可靠的个体模型贡献信息" in content


def test_report_does_not_pad_missing_signals_and_v1_still_renders():
    content = render_longitudinal_markdown(_v2_prediction_with_signals([]))

    assert "当前没有足够的关键进展信号" in content
    assert "progression_signal" not in content
    assert "纵向进展预测报告" in render_longitudinal_markdown(_prediction())
