"""Historical-prefix and missingness contracts for longitudinal features."""

import pytest
import hashlib
import json
import pandas

from app.schemas.longitudinal_model_registry import ArtifactMetadata

from app.services.longitudinal_features import (
    build_feature_vector,
    build_prefixes,
    sort_visits,
    summarize_fixed_window_history,
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


def test_observation_summary_persists_series_and_unit_state_for_rendering():
    visits = [
        _visit("2024-01-01", 10),
        _visit("2024-06-01", 12),
        _visit("2025-01-01", 14),
    ]

    alt = summarize_observation(visits)["indicators"]["alt"]

    assert alt["unit"] == "U/L"
    assert alt["unit_state"] == "consistent"
    assert alt["series"] == [
        {"visit_date": "2024-01-01", "value": 10.0, "unit": "U/L"},
        {"visit_date": "2024-06-01", "value": 12.0, "unit": "U/L"},
        {"visit_date": "2025-01-01", "value": 14.0, "unit": "U/L"},
    ]


def test_observation_summary_marks_conflicting_units():
    visits = [
        _visit("2024-01-01", 10),
        {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 12, "unit": "IU/L"}]},
        _visit("2025-01-01", 14),
    ]

    alt = summarize_observation(visits)["indicators"]["alt"]

    assert alt["unit"] is None
    assert alt["unit_state"] == "conflict"


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


def test_fixed_window_history_uses_actual_days_and_full_prefix():
    visits = [
        _visit("2024-01-01", 10),
        _visit("2024-01-11", 20),
        _visit("2024-04-10", 30),
    ]

    result = summarize_fixed_window_history(visits)
    alt = result["indicators"]["alt"]

    assert result["visit_count"] == 3
    assert result["observation_span_days"] == 100
    assert result["days_since_previous_visit"] == 90
    assert alt["first"] == 10
    assert alt["last"] == 30
    assert alt["minimum"] == 10
    assert alt["maximum"] == 30
    assert alt["mean"] == pytest.approx(20)
    assert alt["delta"] == 20
    assert alt["recent_delta"] == 10
    assert alt["time_slope_per_day"] == pytest.approx(0.16483516484)
    assert alt["rises_count"] == 2
    assert alt["falls_count"] == 0


def test_fixed_window_history_records_missing_indicator_without_imputation():
    visits = [
        _visit("2024-01-01", 10),
        {"visit_date": "2024-02-01", "indicators": []},
        _visit("2024-03-01", 20),
    ]

    alt = summarize_fixed_window_history(visits)["indicators"]["alt"]

    assert alt["n_observations"] == 2
    assert alt["missing_ratio"] == pytest.approx(1 / 3)
    assert alt["mean"] == 15


def test_fixed_window_history_keeps_single_measurement_without_invented_trend():
    result = summarize_fixed_window_history(
        [
            _visit("2024-01-01", None),
            _visit("2024-02-01", 10),
            _visit("2024-03-01", None),
        ]
    )["indicators"]["alt"]

    assert result["first"] == 10
    assert result["last"] == 10
    assert result["time_slope_per_day"] is None
    assert result["recent_delta"] is None
    assert result["missing_ratio"] == pytest.approx(2 / 3)


def test_future_visit_cannot_change_existing_prefix_features():
    prefix = [
        _visit("2024-01-01", 10),
        _visit("2024-02-01", 20),
        _visit("2024-03-01", 30),
    ]
    before = summarize_fixed_window_history(prefix)

    summarize_fixed_window_history(prefix + [_visit("2025-01-01", 999)])

    assert summarize_fixed_window_history(prefix) == before


def _inference_metadata(*, required_features=None):
    names = [
        "age",
        "visit_count",
        "observation_span_days",
        "days_since_previous_visit",
        "alt.first",
        "alt.last",
        "alt.time_slope_per_day",
        "alt.missing_ratio",
        "sex",
    ]
    order_hash = hashlib.sha256(
        json.dumps(names, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    required = required_features or [
        "visit_count",
        "observation_span_days",
        "days_since_previous_visit",
    ]
    return ArtifactMetadata.model_validate(
        {
            "schema_version": "longitudinal_outcome_artifact.v1",
            "artifact_type": "outcome",
            "task": "fatty_liver.pre_cirrhosis_to_progression",
            "dataset": "fatty_liver",
            "disease": "脂肪肝",
            "current_state": "pre_cirrhosis",
            "target": "cirrhosis_or_hcc",
            "horizon_days": 365,
            "feature_contract": {
                "schema_version": "longitudinal_fixed_window_features.v1",
                "feature_version": "longitudinal_fixed_window_features.v1",
                "feature_names": names,
                "feature_order_sha256": order_hash,
                "numeric_features": names[:-1],
                "categorical_features": ["sex"],
                "required_features": required,
                "allowed_missing_features": [name for name in names if name not in required],
                "input_container": "pandas_dataframe",
                "numeric_imputation": "median_add_indicator",
                "categorical_imputation": "most_frequent",
            },
            "dataset_contract": {
                "schema_version": "longitudinal_fixed_window_dataset.v1",
                "manifest_sha256": "a" * 64,
                "data_content_sha256": "b" * 64,
                "training_file_sha256": "c" * 64,
            },
            "model_contract": {
                "model_id": "fatty-model",
                "model_name": "logistic_regression",
                "model_version": "2026.08.26.1",
                "algorithm": "logistic_regression",
                "artifact_sha256": "d" * 64,
                "packages": {
                    "python": "3.11",
                    "scikit_learn": "1.9.0",
                    "joblib": "1.5.3",
                    "numpy": "2.3.5",
                    "pandas": "3.0.3",
                },
            },
            "score_contract": {
                "semantics": "model_score",
                "positive_class": 1,
                "threshold": 0.5,
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "calibration": {"status": "not_calibrated", "method": None},
            "audit": {
                "leakage_status": "passed",
                "clinical_validity_claim": False,
                "code_version": "test",
            },
            "status": "candidate",
            "production_enabled": False,
            "created_at": "2026-08-26T00:00:00Z",
        }
    )


def test_inference_features_match_metadata_order_and_container():
    from app.services.longitudinal_features import build_fixed_window_inference_features

    frame = build_fixed_window_inference_features(
        {"sex": "female", "baseline_stage": "pre_cirrhosis"},
        [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
        _inference_metadata(),
    )
    assert isinstance(frame, pandas.DataFrame)
    assert list(frame.columns) == _inference_metadata().feature_contract.feature_names
    assert frame.shape == (1, 9)
    assert frame.loc[0, "visit_count"] == 3
    assert frame.loc[0, "observation_span_days"] == 365
    assert frame.loc[0, "alt.time_slope_per_day"] is not None


def test_online_age_is_missing_and_never_guessed():
    from app.services.longitudinal_features import build_fixed_window_inference_features

    frame = build_fixed_window_inference_features(
        {"patient_label": "年龄70岁的病例", "sex": "male", "notes": "患者约70岁"},
        [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
        _inference_metadata(),
    )
    assert pandas.isna(frame.loc[0, "age"])


def test_online_age_uses_the_explicit_case_value():
    from app.services.longitudinal_features import build_fixed_window_inference_features

    frame = build_fixed_window_inference_features(
        {"age": 70, "sex": "male"},
        [
            _visit("2024-01-01", 10),
            _visit("2024-06-01", 20),
            _visit("2024-12-31", 30),
        ],
        _inference_metadata(required_features=["age", "visit_count"]),
    )
    assert frame.loc[0, "age"] == 70


def test_required_online_age_is_rejected_instead_of_guessed():
    from app.services.longitudinal_features import (
        InferenceContractError,
        build_fixed_window_inference_features,
    )

    with pytest.raises(InferenceContractError) as error:
        build_fixed_window_inference_features(
            {"patient_label": "70岁", "sex": "female"},
            [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
            _inference_metadata(required_features=["age", "visit_count"]),
        )
    assert error.value.code == "required_feature_missing"


def test_non_finite_raw_indicator_is_rejected():
    from app.services.longitudinal_features import (
        InferenceContractError,
        build_fixed_window_inference_features,
    )

    visits = [_visit("2024-01-01", 10), _visit("2024-06-01", float("inf")), _visit("2024-12-31", 30)]
    with pytest.raises(InferenceContractError) as error:
        build_fixed_window_inference_features({}, visits, _inference_metadata())
    assert error.value.code == "non_finite_feature"
