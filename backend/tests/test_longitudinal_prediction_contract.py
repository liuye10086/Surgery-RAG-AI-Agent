from app.services.disease_progression import FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import prediction_result_to_dict, run_longitudinal_prediction


class _ScoreModel:
    classes_ = [0, 1]

    def __init__(self):
        self.calls = 0

    def predict_proba(self, rows):
        self.calls += 1
        assert list(rows.columns)[-1] == "sex"
        return [[0.25, 0.75]]


def test_safe_outcome_call_uses_selected_task_and_metadata_contract():
    from app.schemas.longitudinal_model_registry import LoadedModelEntry, ModelRuntimeStatus
    from app.services.longitudinal_task_routing import route_outcome_task
    from app.services.longitudinal_prediction import _run_outcome_model
    from backend.tests.test_longitudinal_features import _inference_metadata, _visit

    metadata = _inference_metadata()
    model = _ScoreModel()
    entry = LoadedModelEntry(
        status=ModelRuntimeStatus(
            artifact_type="outcome",
            task=metadata.task,
            status="available",
            reason_code="artifact_available",
            lifecycle_status="enabled",
            model_id=metadata.model_contract.model_id,
            model_name=metadata.model_contract.model_name,
            model_version=metadata.model_contract.model_version,
            artifact_sha256=metadata.model_contract.artifact_sha256,
            target=metadata.target,
            horizon_days=metadata.horizon_days,
            feature_version=metadata.feature_contract.feature_version,
            score_semantics=metadata.score_contract.semantics,
            calibration_status=metadata.calibration.status,
        ),
        metadata=metadata,
        model=model,
    )
    result = _run_outcome_model(
        route_outcome_task("fatty_liver", "pre_cirrhosis"),
        entry,
        {"sex": "female"},
        [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
    )
    assert result.risk_score == 0.75
    assert result.risk_band == "高"
    assert result.status.status == "available"
    assert model.calls == 1


def test_outcome_call_refuses_task_mismatch_without_invoking_model():
    from app.schemas.longitudinal_model_registry import LoadedModelEntry, ModelRuntimeStatus
    from app.services.longitudinal_task_routing import route_outcome_task
    from app.services.longitudinal_prediction import _run_outcome_model
    from backend.tests.test_longitudinal_features import _inference_metadata, _visit

    metadata = _inference_metadata()
    model = _ScoreModel()
    entry = LoadedModelEntry(
        status=ModelRuntimeStatus(
            artifact_type="outcome",
            task=metadata.task,
            status="disabled",
            reason_code="task_mismatch",
            lifecycle_status="enabled",
        ),
        metadata=metadata,
        model=model,
    )
    result = _run_outcome_model(
        route_outcome_task("fatty_liver", "cirrhosis"),
        entry,
        {},
        [_visit("2024-01-01", 10), _visit("2024-06-01", 20), _visit("2024-12-31", 30)],
    )
    assert result.risk_score is None
    assert result.status.reason_code == "task_mismatch"
    assert model.calls == 0


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
    assert result.schema_version == "longitudinal_prediction.v2"
    assert result.outcome_prediction.stage_projection.status == "not_estimated"
    assert result.trend_predictions == []
    assert result.model_status.outcome.status in {"missing", "disabled"}
    assert result.model_status.stage.reason_code == "stage_model_missing"
    assert result.model_status.trend.reason_code == "trend_model_missing"
    assert prediction_result_to_dict(result)["schema_version"] == "longitudinal_prediction.v2"


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
    assert result.model_status.stage.status == "missing"


def test_unavailable_outcome_emits_no_risk_but_keeps_observation_and_evidence():
    result = run_longitudinal_prediction(
        {"baseline_stage": None},
        [
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 30}]},
            {"visit_date": "2024-12-31", "indicators": [{"name": "ALT", "value": 40}]},
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )
    assert result.outcome_prediction.risk_score is None
    assert result.outcome_prediction.risk_band is None
    assert result.observation["indicators"]["alt"]["last"] == 40
    assert result.evidence == {}
    assert result.model_status.outcome.reason_code == "baseline_stage_missing"


def test_prediction_v2_contains_signals_when_outcome_is_unavailable():
    from backend.tests.test_longitudinal_features import _visit

    result = run_longitudinal_prediction(
        {"baseline_stage": None},
        [
            _visit("2024-01-01", 20),
            _visit("2024-06-01", 35),
            _visit("2024-12-31", 60),
        ],
        FATTY_LIVER_ADAPTER,
        {},
    )

    assert (
        result.progression_signals.schema_version
        == "longitudinal_signal_interpretation.v1"
    )
    signal = result.progression_signals.signals[0]
    assert signal.used_by_outcome_model is False
    assert "model_unavailable" in signal.reason_codes


def test_prediction_signal_does_not_change_outcome_score():
    from app.schemas.longitudinal_model_registry import (
        LoadedModelEntry,
        LongitudinalModelRegistry,
        ModelRuntimeStatus,
    )
    from app.services.longitudinal_model_registry import empty_optional_model_status
    from backend.tests.test_longitudinal_features import _inference_metadata, _visit

    metadata = _inference_metadata()
    model = _ScoreModel()
    status = ModelRuntimeStatus(
        artifact_type="outcome",
        task=metadata.task,
        status="available",
        reason_code="artifact_available",
        lifecycle_status="enabled",
        model_id=metadata.model_contract.model_id,
        model_name=metadata.model_contract.model_name,
        model_version=metadata.model_contract.model_version,
        artifact_sha256=metadata.model_contract.artifact_sha256,
        target=metadata.target,
        horizon_days=metadata.horizon_days,
        feature_version=metadata.feature_contract.feature_version,
        score_semantics=metadata.score_contract.semantics,
        calibration_status=metadata.calibration.status,
    )
    registry = LongitudinalModelRegistry(
        dataset="fatty_liver",
        outcomes={
            metadata.task: LoadedModelEntry(
                status=status,
                metadata=metadata,
                model=model,
            )
        },
        stage=empty_optional_model_status("stage", "stage_model_missing"),
        trend=empty_optional_model_status("trend", "trend_model_missing"),
    )
    result = run_longitudinal_prediction(
        {"baseline_stage": "pre_cirrhosis", "sex": "female"},
        [
            _visit("2024-01-01", 10),
            _visit("2024-06-01", 20),
            _visit("2024-12-31", 30),
        ],
        FATTY_LIVER_ADAPTER,
        registry,
    )

    assert result.outcome_prediction.risk_score == 0.75
    assert model.calls == 1
    signal = result.progression_signals.signals[0]
    assert signal.used_by_outcome_model is True
    assert signal.model_feature_names == [
        "alt.first",
        "alt.last",
        "alt.missing_ratio",
        "alt.time_slope_per_day",
    ]
    assert signal.model_contribution is None


def test_prediction_v2_uses_passed_standard_snapshot():
    from backend.tests.test_longitudinal_features import _visit

    result = run_longitudinal_prediction(
        {"baseline_stage": None},
        [
            _visit("2024-01-01", 20),
            _visit("2024-06-01", 35),
            _visit("2024-12-31", 60),
        ],
        FATTY_LIVER_ADAPTER,
        {},
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

    assert result.progression_signals.signals[0].attention_level == "priority"


class _MulticlassModel:
    def __init__(self, prediction, probabilities=None, *, raises=False):
        self.prediction = prediction
        self.probabilities = probabilities or [0.1, 0.8, 0.1]
        self.raises = raises
        self.classes_ = ["rising", "stable", "falling"]

    def predict(self, rows):
        if self.raises:
            raise ValueError("private failure")
        return [self.prediction]

    def predict_proba(self, rows):
        if self.raises:
            raise ValueError("private failure")
        return [self.probabilities]


def _v2_metadata(artifact_type, task, *, indicator=None):
    from backend.tests.test_longitudinal_model_suite_schema import valid_metadata
    from app.schemas.longitudinal_model_suite import ArtifactMetadataV2

    payload = valid_metadata(artifact_type)
    payload.update(task=task)
    if artifact_type == "outcome":
        payload.update(target="dementia")
    elif artifact_type == "stage":
        payload.update(target="next_stage")
    else:
        payload.update(
            target=f"next_visit_direction:{indicator}",
            horizon={"kind": "next_visit", "value": None},
        )
    payload["model_contract"]["model_id"] = task.replace(".", "-")
    return ArtifactMetadataV2.model_validate(payload)


def _suite_entry(metadata, model, artifact_type):
    from app.schemas.longitudinal_model_registry import ModelRuntimeStatus, SuiteModelEntry

    return SuiteModelEntry(
        status=ModelRuntimeStatus(
            artifact_type=artifact_type,
            task=metadata.task,
            status="available",
            reason_code="artifact_available",
            lifecycle_status="enabled",
            model_id=metadata.model_contract.model_id,
            model_name=metadata.model_contract.model_name,
            model_version=metadata.model_contract.model_version,
            artifact_sha256=metadata.model_contract.artifact_sha256,
            target=metadata.target,
            horizon_days=metadata.horizon.value,
            feature_version=metadata.feature_contract.feature_version,
            score_semantics=metadata.output_contract.score_semantics,
            calibration_status=metadata.calibration.status,
        ),
        metadata=metadata,
        model=model,
    )


def _complete_ad_suite(*, bad_stage=False, bad_mmse=False):
    from app.schemas.longitudinal_model_registry import LoadedDiseaseModelSuite

    outcome_meta = _v2_metadata(
        "outcome", "ad.pre_dementia_to_dementia"
    )
    stage_meta = _v2_metadata("stage", "ad.next_stage")
    mmse_meta = _v2_metadata(
        "trend", "ad.next_visit_trend.mmse", indicator="mmse"
    )
    moca_meta = _v2_metadata(
        "trend", "ad.next_visit_trend.moca", indicator="moca"
    )
    return LoadedDiseaseModelSuite(
        dataset="ad",
        release_set_id="ad-set-v1",
        release_set_sha256="1" * 64,
        data_release_id="ad-data-v1",
        split_sha256="2" * 64,
        outcomes={
            outcome_meta.task: _suite_entry(
                outcome_meta, _ScoreModel(), "outcome"
            )
        },
        stage=_suite_entry(
            stage_meta,
            _MulticlassModel("dementia", raises=bad_stage),
            "stage",
        ),
        trends={
            "mmse": _suite_entry(
                mmse_meta,
                _MulticlassModel("falling", raises=bad_mmse),
                "trend",
            ),
            "moca": _suite_entry(
                moca_meta, _MulticlassModel("stable"), "trend"
            ),
        },
    )


def _ad_visits():
    return [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "MMSE", "value": mmse},
                {"name": "MoCA", "value": moca},
            ],
        }
        for visit_date, mmse, moca in [
            ("2024-01-01", 28, 25),
            ("2024-06-01", 25, 22),
            ("2024-12-31", 22, 18),
        ]
    ]


def test_v3_result_uses_one_release_set_for_outcome_stage_and_trends():
    from app.services.disease_progression import AD_ADAPTER

    suite = _complete_ad_suite()
    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        suite,
    )

    assert result.schema_version == "longitudinal_prediction.v3"
    assert result.release_set.release_set_id == suite.release_set_id
    assert result.model_status.outcome.status == "available"
    assert result.model_status.stage.status == "available"
    assert result.outcome_prediction.stage_projection.status == "available"
    assert result.trend_predictions
    assert {item.model_status.status for item in result.trend_predictions} == {
        "available"
    }


def test_v3_stage_projection_never_regresses_before_current_stage():
    from app.services.disease_progression import AD_ADAPTER

    suite = _complete_ad_suite()
    suite = suite.__class__(
        **{
            **suite.__dict__,
            "stage": _suite_entry(
                suite.stage.metadata,
                _MulticlassModel("stay_normal"),
                "stage",
            ),
        }
    )
    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        suite,
    )

    assert result.outcome_prediction.stage_projection.likely_next_stage == "stay_mci"
    assert {
        item["stage"]
        for item in result.outcome_prediction.stage_projection.stage_candidates
    }.isdisjoint({"stay_normal", "normal"})


def test_v3_stage_projection_normalizes_current_stage_transition_to_stay():
    from app.services.disease_progression import AD_ADAPTER

    suite = _complete_ad_suite()
    suite = suite.__class__(
        **{
            **suite.__dict__,
            "stage": _suite_entry(
                suite.stage.metadata,
                _MulticlassModel("mci"),
                "stage",
            ),
        }
    )

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        suite,
    )

    assert result.outcome_prediction.stage_projection.likely_next_stage == "stay_mci"


def test_one_broken_trend_model_does_not_remove_other_predictions():
    from app.services.disease_progression import AD_ADAPTER

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        _complete_ad_suite(bad_mmse=True),
    )
    by_indicator = {item.indicator: item for item in result.trend_predictions}
    assert by_indicator["mmse"].model_status.reason_code == "prediction_failed"
    assert by_indicator["moca"].forecast.direction == "stable"
    assert result.outcome_prediction.risk_score is not None
    assert result.outcome_prediction.stage_projection.likely_next_stage is not None


def test_incompatible_stage_emits_no_guess_but_keeps_outcome_and_trends():
    from app.services.disease_progression import AD_ADAPTER

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        _complete_ad_suite(bad_stage=True),
    )
    assert result.model_status.stage.status == "incompatible"
    assert result.outcome_prediction.stage_projection.status == "not_estimated"
    assert result.outcome_prediction.risk_score is not None
    assert result.trend_predictions
