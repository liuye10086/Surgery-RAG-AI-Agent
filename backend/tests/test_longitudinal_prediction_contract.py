from app.services.disease_progression import FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import prediction_result_to_dict, run_longitudinal_prediction


def test_result_contains_outcome_stage_and_trend_sections():
    result = run_longitudinal_prediction(
        {"id": 1},
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 30}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    assert result.schema_version == "longitudinal_prediction.v1"
    assert result.outcome_prediction.stage_projection.status == "not_estimated"
    assert result.trend_predictions[0].forecast.status == "direction_only"
    assert prediction_result_to_dict(result)["schema_version"] == "longitudinal_prediction.v1"


def test_unavailable_stage_never_emits_stage_guess():
    result = run_longitudinal_prediction(
        {},
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 30}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    assert result.outcome_prediction.stage_projection.likely_next_stage is None
    assert any("未加载" in warning for warning in result.warnings)
