from app.services import longitudinal_report_generator as report_generator


def _prediction():
    return {
        "schema_version": "longitudinal_prediction.v2",
        "disease": {"dataset": "fatty_liver", "name": "脂肪肝"},
        "observation": {
            "visit_count": 3,
            "observation_span_days": 410,
            "first_visit_date": "2025-06-01",
            "last_visit_date": "2026-07-16",
            "missingness_summary": {},
            "indicators": {
                "ALT": {
                    "first": 42,
                    "last": 68,
                    "delta": 26,
                    "n_observations": 3,
                    "slope": 0.06,
                }
            },
        },
        "outcome_prediction": {
            "risk_band": None,
            "risk_score": None,
            "stage_projection": {
                "status": "not_estimated",
                "likely_next_stage": None,
                "stage_candidates": [],
            },
            "confidence": {},
        },
        "trend_predictions": [],
        "evidence": {},
        "warnings": ["未来365天结局模型未参与本次推理"],
        "model_status": {
            "outcome": {"status": "missing", "reason_code": "release_record_missing"},
            "stage": {"status": "missing", "reason_code": "stage_model_missing"},
            "trend": {"status": "missing", "reason_code": "trend_model_missing"},
        },
        "progression_signals": {
            "schema_version": "longitudinal_signal_interpretation.v1",
            "signals": [],
            "omitted_indicators": [],
            "summary": {"signal_count": 0, "omitted_count": 0},
        },
    }


def test_complete_report_has_eleven_sections_and_plain_language():
    content = report_generator.render_longitudinal_markdown(
        _prediction(), [], {"baseline_stage": "pre_cirrhosis"}
    )
    for title in (
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
    ):
        assert title in content
    assert "progression_signal" not in content
    assert "likely_rising" not in content
    assert "direction_only" not in content
    assert "数据够用" in content
    assert "365 天风险模型" in content


def test_report_view_exposes_chart_and_table_display_modes():
    assert hasattr(report_generator, "build_report_view")
    view = report_generator.build_report_view(
        _prediction(), [], {"visits": [{"indicators": [{"name": "ALT", "unit": "U/L"}]}]}
    )
    assert view.indicator_table["ALT"].render_mode == "chart_and_table"


def test_report_view_marks_unit_conflict_as_table_only():
    prediction = _prediction()
    prediction["observation"]["indicators"]["甘油三酯"] = {
        "first": 1.2,
        "last": 1.8,
        "delta": 0.6,
        "n_observations": 3,
    }
    snapshot = {
        "visits": [
            {"indicators": [{"name": "甘油三酯", "unit": "mmol/L"}]},
            {"indicators": [{"name": "甘油三酯", "unit": "mg/dL"}]},
            {"indicators": [{"name": "甘油三酯", "unit": "mmol/L"}]},
        ]
    }
    view = report_generator.build_report_view(prediction, [], snapshot)
    assert view.indicator_table["甘油三酯"].render_mode == "table_only_unit_problem"


def test_observed_changes_are_persisted_as_a_complete_markdown_table():
    prediction = _prediction()
    prediction["observation"]["indicators"].update({
        "体重": {
            "first": 80,
            "last": 79,
            "delta": -1,
            "n_observations": 2,
            "unit": "kg",
            "unit_state": "consistent",
        },
        "甘油三酯": {
            "first": 1.2,
            "last": 180,
            "delta": None,
            "n_observations": 3,
            "unit": None,
            "unit_state": "conflict",
        },
    })
    content = report_generator.render_longitudinal_markdown(prediction)

    assert "| 指标 | 首次值 | 最近值 | 变化 | 有效观察 | 单位 | 展示说明 |" in content
    assert "| ALT | 42.00 | 68.00 | 26.00 | 3 次 |" in content
    assert "| 体重 | 80.00 | 79.00 | -1.00 | 2 次 | kg | 仅表格：有效观察不足 3 次 |" in content
    assert "| 甘油三酯 | 1.20 | 180.00 | 无法安全比较 | 3 次 | 单位不一致或缺失 | 仅表格：单位问题，未绘制趋势或判断异常 |" in content
