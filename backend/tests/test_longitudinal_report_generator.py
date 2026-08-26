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
