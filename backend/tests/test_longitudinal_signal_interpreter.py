import pytest
from types import SimpleNamespace


def test_signal_schema_rejects_unknown_fields_and_requires_stable_levels():
    from pydantic import ValidationError

    from app.schemas.longitudinal_report import LongitudinalSignal

    signal = LongitudinalSignal(
        indicator="alt",
        display_name="谷丙转氨酶",
        unit="U/L",
        first_value=20,
        latest_value=60,
        absolute_change=40,
        relative_change=2.0,
        observation_count=3,
        observation_span_days=365,
        observed_direction="rising",
        disease_attention_direction="rising",
        reference_status="above_range",
        reference_rule_id=1,
        reference_version_id=3,
        attention_level="priority",
        reason_codes=["directional_change", "latest_above_reference"],
        used_by_outcome_model=True,
        model_feature_names=["alt.delta", "alt.last"],
        model_contribution_status="not_supported",
        model_contribution=None,
        provenance={"standard_version_id": 3, "standard_rule_id": 1},
        limitations=[],
    )

    assert signal.attention_level == "priority"
    assert signal.model_contribution is None
    with pytest.raises(ValidationError):
        LongitudinalSignal.model_validate({**signal.model_dump(), "unexpected": True})


def test_v2_defaults_to_empty_signal_result_but_v1_contract_is_unchanged():
    from app.schemas.longitudinal_report import (
        LongitudinalPredictionResultV1,
        LongitudinalPredictionResultV2,
    )

    field = LongitudinalPredictionResultV2.model_fields["progression_signals"]
    assert field.default_factory().signals == []
    assert "progression_signals" not in LongitudinalPredictionResultV1.model_fields


def test_fatty_liver_alt_rising_and_alb_falling_use_disease_direction():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {
                "visit_date": "2024-01-01",
                "indicators": [
                    {"name": "ALT", "value": 20, "unit": "U/L"},
                    {"name": "ALB", "value": 45, "unit": "g/L"},
                ],
            },
            {
                "visit_date": "2024-06-01",
                "indicators": [
                    {"name": "ALT", "value": 35, "unit": "U/L"},
                    {"name": "ALB", "value": 40, "unit": "g/L"},
                ],
            },
            {
                "visit_date": "2024-12-31",
                "indicators": [
                    {"name": "ALT", "value": 60, "unit": "U/L"},
                    {"name": "ALB", "value": 32, "unit": "g/L"},
                ],
            },
        ],
    )

    by_name = {item.indicator: item for item in result.signals}
    assert by_name["alt"].observed_direction == "rising"
    assert by_name["alt"].disease_attention_direction == "rising"
    assert by_name["alb"].observed_direction == "falling"
    assert by_name["alb"].disease_attention_direction == "falling"


def test_three_observation_rule_uses_all_values_and_does_not_take_recent_window():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {
                "visit_date": "2020-01-01",
                "indicators": [{"name": "ALT", "value": 10, "unit": "U/L"}],
            },
            {
                "visit_date": "2020-06-01",
                "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}],
            },
            {
                "visit_date": "2021-01-01",
                "indicators": [{"name": "ALT", "value": 15, "unit": "U/L"}],
            },
            {
                "visit_date": "2021-06-01",
                "indicators": [{"name": "ALT", "value": 30, "unit": "U/L"}],
            },
        ],
    )

    signal = next(item for item in result.signals if item.indicator == "alt")
    assert signal.observation_count == 4
    assert signal.first_value == 10
    assert signal.latest_value == 30
    assert signal.absolute_change == 20
    assert "persistent_direction" not in signal.reason_codes


def test_ad_cdr_is_stage_related_observation_and_ptau_aliases_are_not_merged():
    from app.services.longitudinal_signal_interpreter import (
        canonicalize_indicator,
        interpret_observation_signals,
    )

    assert canonicalize_indicator("ad", "plasma_nfl")[0] == "nfl"
    assert canonicalize_indicator("ad", "plasma_ptau217")[0] == "p-tau217"
    assert canonicalize_indicator("ad", "ptau181")[0] is None
    result = interpret_observation_signals(
        dataset="ad",
        visits=[
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "CDR", "value": 0.5, "unit": "分"}],
            },
            {
                "visit_date": "2024-06-01",
                "indicators": [{"name": "CDR", "value": 1, "unit": "分"}],
            },
            {
                "visit_date": "2024-12-31",
                "indicators": [{"name": "CDR", "value": 1, "unit": "分"}],
            },
        ],
    )

    signal = next(item for item in result.signals if item.indicator == "cdr")
    assert signal.attention_level == "attention"
    assert any("阶段相关" in text for text in signal.limitations)


def test_formal_reference_hit_records_version_rule_and_priority():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}],
            },
            {
                "visit_date": "2024-06-01",
                "indicators": [{"name": "ALT", "value": 35, "unit": "U/L"}],
            },
            {
                "visit_date": "2024-12-31",
                "indicators": [{"name": "ALT", "value": 60, "unit": "U/L"}],
            },
        ],
        standard_sources=[
            {
                "source_type": "reference_range",
                "indicator": "ALT",
                "unit": "U/L",
                "lower": 7,
                "upper": 40,
                "standard_version_id": 3,
                "standard_rule_id": 2,
                "applicability_hash": "a",
            }
        ],
    )

    signal = result.signals[0]
    assert signal.reference_status == "above_range"
    assert signal.reference_version_id == 3
    assert signal.reference_rule_id == 2
    assert signal.attention_level == "priority"


@pytest.mark.parametrize(
    ("units", "expected"),
    [
        ([None, None, None], "unit_missing"),
        (["U/L", "mg/L", "U/L"], "unit_conflict"),
        (["IU/L", "IU/L", "IU/L"], "unsupported_unit"),
    ],
)
def test_unit_problem_never_emits_range_abnormality(units, expected):
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {
                "visit_date": f"2024-0{i + 1}-01",
                "indicators": [{"name": "ALT", "value": value, "unit": unit}],
            }
            for i, (value, unit) in enumerate(zip([20, 35, 60], units))
        ],
        standard_sources=[
            {
                "source_type": "reference_range",
                "indicator": "ALT",
                "unit": "U/L",
                "lower": 7,
                "upper": 40,
                "standard_version_id": 3,
                "standard_rule_id": 2,
            }
        ],
    )

    signal = result.signals[0] if result.signals else result.omitted_indicators[0]
    reason_codes = (
        signal.reason_codes if hasattr(signal, "reason_codes") else signal["reason_codes"]
    )
    assert expected in reason_codes
    assert getattr(signal, "reference_status", None) not in {
        "above_range",
        "below_range",
    }


def test_standard_unit_mismatch_is_unsupported_and_never_classified():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {
                "visit_date": f"2024-0{index + 1}-01",
                "indicators": [{"name": "ALT", "value": value, "unit": "U/L"}],
            }
            for index, value in enumerate([20, 35, 60])
        ],
        standard_sources=[
            {
                "source_type": "reference_range",
                "indicator": "ALT",
                "unit": "mg/L",
                "lower": 7,
                "upper": 40,
                "standard_version_id": 3,
                "standard_rule_id": 2,
            }
        ],
    )

    signal = result.signals[0]
    assert signal.reference_status == "unsupported_unit"
    assert "unsupported_unit" in signal.reason_codes
    assert signal.attention_level == "attention"


def test_ad_evidence_only_standard_allows_direction_but_not_above_below():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    result = interpret_observation_signals(
        dataset="ad",
        visits=[
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "MMSE", "value": 28, "unit": "分"}],
            },
            {
                "visit_date": "2024-06-01",
                "indicators": [{"name": "MMSE", "value": 25, "unit": "分"}],
            },
            {
                "visit_date": "2024-12-31",
                "indicators": [{"name": "MMSE", "value": 22, "unit": "分"}],
            },
        ],
        standard_sources=[
            {
                "source_type": "standard_evidence",
                "indicator": "MMSE",
                "unit": "分",
                "standard_version_id": 4,
                "standard_rule_id": 28,
                "machine_actionability": "evidence-only",
            }
        ],
    )

    signal = result.signals[0]
    assert signal.observed_direction == "falling"
    assert signal.reference_status == "reference_not_applicable"
    assert signal.reference_status not in {"above_range", "below_range"}
    assert signal.reference_version_id == 4
    assert signal.reference_rule_id == 28
    assert "reference_not_applicable" in signal.reason_codes


def test_available_outcome_maps_raw_indicator_to_real_derived_features_without_predict():
    from app.services.longitudinal_signal_interpreter import map_signal_model_features

    status = SimpleNamespace(
        status="available", task="fatty_liver.pre_cirrhosis_to_progression"
    )
    used, features, reasons = map_signal_model_features(
        "alt",
        raw_indicator="alt",
        outcome_status=status,
        feature_names=["alt.first", "alt.last", "alt.delta", "sex"],
    )

    assert used is True
    assert features == ["alt.delta", "alt.first", "alt.last"]
    assert reasons == []


def test_unavailable_or_unmapped_outcome_never_claims_model_use():
    from app.services.longitudinal_signal_interpreter import map_signal_model_features

    unavailable = SimpleNamespace(status="missing")
    assert (
        map_signal_model_features(
            "alt",
            raw_indicator="alt",
            outcome_status=unavailable,
            feature_names=["alt.last"],
        )[0]
        is False
    )
    available = SimpleNamespace(status="available")
    used, _, reasons = map_signal_model_features(
        "cdr",
        raw_indicator="cdr",
        outcome_status=available,
        feature_names=["mmse.last"],
    )
    assert used is False
    assert "feature_not_used" in reasons


def test_priority_precedes_attention_and_ties_use_change_strength():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    visits = [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "ALT", "value": alt, "unit": "U/L"},
                {"name": "AST", "value": ast, "unit": "U/L"},
                {"name": "ALB", "value": alb, "unit": "g/L"},
                {"name": "PLT", "value": plt, "unit": "10⁹/L"},
            ],
        }
        for visit_date, alt, ast, alb, plt in [
            ("2024-01-01", 20, 20, 45, 250),
            ("2024-06-01", 30, 40, 40, 220),
            ("2024-12-31", 40, 60, 32, 180),
        ]
    ]
    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=visits,
        standard_sources=[
            {
                "source_type": "reference_range",
                "indicator": "ALB",
                "unit": "g/L",
                "lower": 35,
                "upper": 55,
                "standard_version_id": 3,
                "standard_rule_id": 8,
            }
        ],
    )

    assert [item.indicator for item in result.signals] == [
        "alb",
        "ast",
        "alt",
        "plt",
    ]


def test_repeat_calculation_is_identical_and_no_three_signal_padding():
    from app.services.longitudinal_signal_interpreter import (
        interpret_observation_signals,
    )

    visits = [
        {
            "visit_date": "2024-01-01",
            "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}],
        },
        {
            "visit_date": "2024-06-01",
            "indicators": [{"name": "ALT", "value": 21, "unit": "U/L"}],
        },
        {
            "visit_date": "2024-12-31",
            "indicators": [{"name": "ALT", "value": 22, "unit": "U/L"}],
        },
    ]
    first = interpret_observation_signals(
        dataset="fatty_liver", visits=visits
    ).model_dump(mode="json")
    second = interpret_observation_signals(
        dataset="fatty_liver", visits=visits
    ).model_dump(mode="json")

    assert first == second
    assert len(first["signals"]) == 1
    assert first["summary"]["signal_count"] == 1
    assert first["summary"]["summary_code"] == "signals_available"
    assert first["signals"][0]["reason_codes"][-1] == "contribution_unavailable"
