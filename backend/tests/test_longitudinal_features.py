"""Historical-prefix and missingness contracts for longitudinal features."""

import pytest

from app.services.longitudinal_features import (
    build_feature_vector,
    build_prefixes,
    sort_visits,
    summarize_observation,
)


def _visit(day: str, value: float | None = 1) -> dict:
    return {
        "visit_date": day,
        "indicators": [
            {"name": "ALT", "value": value, "unit": "U/L"}
        ],
    }


def test_prefixes_never_include_future_visits():
    visits = [_visit("2024-01-01"), _visit("2024-06-01"), _visit("2025-01-01")]

    prefixes = build_prefixes(visits, minimum_visits=2)

    assert len(prefixes) == 2
    assert prefixes[0]["as_of"] == "2024-06-01"
    assert len(prefixes[0]["visits"]) == 2
    assert [item["visit_date"] for item in prefixes[0]["visits"]] == [
        "2024-01-01",
        "2024-06-01",
    ]


def test_observation_summary_reports_span_and_missingness():
    visits = [
        _visit("2024-01-01", 10),
        {"visit_date": "2024-06-01", "indicators": []},
        _visit("2025-01-01", 12),
    ]

    result = summarize_observation(visits)

    assert result["visit_count"] == 3
    assert result["observation_span_days"] == 366
    assert result["missingness_summary"]["alt"] == pytest.approx(1 / 3)
    assert result["indicators"]["alt"]["latest_reference_status"] == "unknown"


def test_sort_visits_rejects_duplicate_dates():
    with pytest.raises(ValueError, match="日期重复"):
        sort_visits([_visit("2024-01-01"), _visit("2024-01-01")])


def test_feature_vector_follows_requested_model_order_and_nan_for_missing():
    visits = [_visit("2024-01-01", 10), _visit("2024-06-01", 20)]

    vector = build_feature_vector(visits, ["alt.last", "alt.first", "ast.last"])

    assert vector[:2] == [20.0, 10.0]
    assert vector[2] != vector[2]  # NaN, delegated to model imputation.


def test_reference_status_honors_exclusive_bounds():
    visits = [
        {
            "visit_date": "2024-01-01",
            "indicators": [
                {
                    "name": "ALT",
                    "value": 40,
                    "unit": "U/L",
                    "upper": 40,
                    "upper_inclusive": False,
                }
            ],
        }
    ]

    assert summarize_observation(visits)["indicators"]["alt"][
        "latest_reference_status"
    ] == "above_range"


def test_latest_valid_value_reuses_prior_reference_metadata():
    visits = [
        {
            "visit_date": "2024-01-01",
            "indicators": [{"name": "ALT", "value": 10, "upper": 40}],
        },
        {
            "visit_date": "2024-06-01",
            "indicators": [{"name": "ALT", "value": 50}],
        },
    ]

    assert summarize_observation(visits)["indicators"]["alt"][
        "latest_reference_status"
    ] == "above_range"


def test_duplicate_indicator_names_in_one_visit_are_rejected():
    with pytest.raises(ValueError, match="重复使用指标"):
        summarize_observation(
            [
                {
                    "visit_date": "2024-01-01",
                    "indicators": [
                        {"name": "ALT", "value": 10},
                        {"name": "alt", "value": 11},
                    ],
                }
            ]
        )


def test_feature_vector_normalizes_indicator_name_case():
    assert build_feature_vector([_visit("2024-01-01", 10)], ["ALT.last"]) == [10.0]


def test_observation_summary_has_one_canonical_indicator_entry_for_mixed_case():
    result = summarize_observation([
        _visit("2024-01-01", 10),
        {"visit_date": "2024-06-01", "indicators": [{"name": "alt", "value": 20}]},
    ])

    assert list(result["indicators"]) == ["alt"]
    assert list(result["missingness_summary"]) == ["alt"]
