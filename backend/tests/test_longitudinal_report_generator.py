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
