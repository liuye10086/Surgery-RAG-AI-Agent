from app.services.disease_progression import ADAPTERS, derive_next_visit_direction, predict_indicator_trends


def test_direction_label_uses_relative_tolerance():
    assert derive_next_visit_direction(100, 102, tolerance=0.05) == "stable"
    assert derive_next_visit_direction(100, 120, tolerance=0.05) == "rising"
    assert derive_next_visit_direction(100, 80, tolerance=0.05) == "falling"


def test_direction_only_forecast_has_no_future_value():
    result = predict_indicator_trends(
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "mmse", "value": 28}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "mmse", "value": 24}]},
        ],
        ADAPTERS["ad"],
    )
    assert result[0]["forecast"]["status"] == "direction_only"
    assert result[0]["forecast"]["projected_value"] is None
    assert result[0]["forecast"]["prediction_interval"] is None
