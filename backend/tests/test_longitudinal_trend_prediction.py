from app.services.disease_progression import ADAPTERS, derive_next_visit_direction, predict_indicator_trends


def test_direction_label_uses_relative_tolerance():
    assert derive_next_visit_direction(100, 102, tolerance=0.05) == "stable"
    assert derive_next_visit_direction(100, 120, tolerance=0.05) == "rising"
    assert derive_next_visit_direction(100, 80, tolerance=0.05) == "falling"


def test_missing_trend_model_does_not_turn_observed_slope_into_forecast():
    result = predict_indicator_trends(
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "mmse", "value": 28}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "mmse", "value": 24}]},
        ],
        ADAPTERS["ad"],
    )
    assert result == []


def test_registry_trend_model_receives_latest_value_and_none_model_stays_empty():
    class FakeModel:
        def __init__(self):
            self.seen = None

        def predict(self, vectors):
            self.seen = vectors
            return ["rising"]

    model = FakeModel()
    visits = [
        {"visit_date": "2024-01-01", "indicators": [{"name": "mmse", "value": 20}]},
        {"visit_date": "2024-06-01", "indicators": [{"name": "mmse", "value": 24}]},
    ]
    result = predict_indicator_trends(visits, ADAPTERS["ad"], {"mmse": {"model": model}})
    assert model.seen == [[24.0]]
    assert result[0]["forecast"]["direction"] == "likely_rising"

    fallback = predict_indicator_trends(
        visits,
        ADAPTERS["ad"],
        {"mmse": {"model": None}},
    )
    assert fallback == []
