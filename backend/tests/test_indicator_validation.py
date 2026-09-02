import pytest


def test_indicator_contract_rejects_unknown_and_cross_disease_indicators():
    from app.services.indicator_validation import IndicatorValidationError, validate_indicators

    with pytest.raises(IndicatorValidationError, match="属于疾病 ad.*fatty_liver"):
        validate_indicators(
            "fatty_liver",
            [{"name": "mmse", "value": 20, "unit": "分"}],
        )

    with pytest.raises(IndicatorValidationError, match="属于疾病 fatty_liver.*ad"):
        validate_indicators(
            "ad",
            [{"name": "alt", "value": 20, "unit": "U/L"}],
        )


def test_indicator_contract_separates_invalid_data_from_clinical_abnormality():
    from app.services.indicator_validation import validate_indicators

    result = validate_indicators(
        "fatty_liver",
        [{"name": "alt", "value": 500, "unit": "U/L"}],
        reference_ranges={"alt": {"lower": 7, "upper": 50}},
    )

    assert result.is_valid
    assert result.items[0].clinical_status == "above_reference"
    assert result.items[0].safety_status == "within_safe_range"


@pytest.mark.parametrize(
    "indicator",
    [
        {"name": "", "value": 1, "unit": "U/L"},
        {"name": "alt", "value": 1, "unit": ""},
        {"name": "alt", "value": float("nan"), "unit": "U/L"},
        {"name": "alt", "value": float("inf"), "unit": "U/L"},
    ],
)
def test_indicator_contract_rejects_malformed_values(indicator):
    from app.services.indicator_validation import IndicatorValidationError, validate_indicators

    with pytest.raises(IndicatorValidationError):
        validate_indicators("fatty_liver", [indicator])


def test_indicator_contract_reports_truly_unknown_indicator_clearly():
    from app.services.indicator_validation import IndicatorValidationError, validate_indicators

    with pytest.raises(IndicatorValidationError, match="未知指标 mystery_marker.*ad"):
        validate_indicators(
            "ad",
            [{"name": "mystery_marker", "value": 1, "unit": "pg/mL"}],
        )
