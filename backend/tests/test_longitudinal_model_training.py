import pytest
import hashlib
import json
from datetime import date
from pathlib import Path
from pydantic import ValidationError

from app.schemas.longitudinal_model_training import (
    MODEL_TRAINING_SCHEMA_VERSION,
    TASK_SPECS,
    FoldMetrics,
    ModelMetadata,
)
from app.schemas.longitudinal_model_registry import ArtifactMetadata


def _sample(*, disease="fatty_liver", current_state="pre_cirrhosis", target_event="cirrhosis_or_hcc", label=1, group="a"):
    from app.schemas.longitudinal_dataset import FixedWindowSample
    payload = {
        "identity": {
            "disease": disease,
            "disease_name": "脂肪肝" if disease == "fatty_liver" else "阿尔茨海默病",
            "source_dataset": "fixture",
            "patient_label": f"P-{group}",
            "group_id": "patient.v1." + group * 64,
            "is_synthetic": False,
            "as_of": "2024-01-01",
            "current_state": current_state,
            "target_event": target_event,
            "history_visit_count": 3,
            "history_start": "2023-01-01",
        },
        "features": {
            "age": 60,
            "sex": "female",
            "visit_count": 3,
            "observation_span_days": 365,
            "days_since_previous_visit": 180,
            "indicators": {
                "alt": {
                    "first": 10.0, "last": 12.0, "minimum": 10.0, "maximum": 12.0,
                    "mean": 11.0, "delta": 2.0, "time_slope_per_day": 0.01,
                    "recent_delta": 1.0, "rises_count": 2, "falls_count": 0,
                    "n_observations": 3, "missing_ratio": 0.0,
                }
            },
        },
        "label": {
            "status": "positive" if label else "negative",
            "training_label": label,
            "reason_code": "target_event_within_window" if label else "full_window_observed_without_event",
            "window_start": "2024-01-02",
            "window_end": "2024-12-31",
            "target_event": target_event,
            "event_type": "cirrhosis_date" if label and disease == "fatty_liver" else ("dementia_date" if label else None),
            "event_date": "2024-06-01" if label else None,
            "last_followup_date": "2025-01-01",
        },
    }
    return FixedWindowSample.model_validate(payload)


def _manifest_export(tmp_path: Path, samples: list[dict], disease="fatty_liver"):
    root = tmp_path
    (root / disease).mkdir(parents=True, exist_ok=True)
    train = root / disease / "real_train.jsonl"
    train.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in samples), encoding="utf-8")
    files = {f"{disease}/real_train.jsonl": hashlib.sha256(train.read_bytes()).hexdigest()}
    stable = {"schema_version": "longitudinal_fixed_window_dataset.v1", "minimum_visits": 3, "horizon_days": 365, "summary": {}, "files": files}
    content_hash = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest = {**stable, "data_content_sha256": content_hash}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def _valid_metadata_kwargs(**overrides):
    payload = {
        "schema_version": MODEL_TRAINING_SCHEMA_VERSION,
        "task": "ad.pre_dementia_to_dementia",
        "dataset_manifest_sha256": "a" * 64,
        "data_content_sha256": "b" * 64,
        "dataset_file_sha256": "c" * 64,
        "feature_order_sha256": "d" * 64,
        "status": "candidate",
        "production_enabled": False,
        "clinical_validity_claim": False,
    }
    payload.update(overrides)
    return payload


def test_task_specs_are_exact_and_distinct():
    assert set(TASK_SPECS) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "ad.pre_dementia_to_dementia",
    }
    assert TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"].target_event == "cirrhosis_or_hcc"
    assert TASK_SPECS["fatty_liver.cirrhosis_to_hcc"].target_event == "hcc"
    assert TASK_SPECS["ad.pre_dementia_to_dementia"].target_event == "dementia"


def test_metadata_rejects_non_candidate_status():
    with pytest.raises(ValidationError):
        ModelMetadata(**_valid_metadata_kwargs(status="enabled", production_enabled=True, clinical_validity_claim=True))


def test_training_task_specs_reuse_shared_registry_contracts():
    from app.schemas.longitudinal_model_registry import TASK_CONTRACTS

    assert TASK_SPECS["fatty_liver.cirrhosis_to_hcc"].target_event == TASK_CONTRACTS["fatty_liver.cirrhosis_to_hcc"].target
    assert TASK_SPECS["ad.pre_dementia_to_dementia"].current_state == TASK_CONTRACTS["ad.pre_dementia_to_dementia"].current_state


def test_evaluation_records_unestimable_metrics_without_zero_filling():
    metrics = FoldMetrics(
        fold=1,
        train_patient_count=4,
        validation_patient_count=2,
        positive_patient_count=0,
        negative_patient_count=2,
        pr_auc=None,
        roc_auc=None,
        unavailable_metrics=["pr_auc", "roc_auc"],
    )
    assert metrics.pr_auc is None
    assert "roc_auc" in metrics.unavailable_metrics


def test_reader_accepts_only_p003_real_train_and_manifest(tmp_path):
    from app.services.longitudinal_model_training import read_dataset_manifest, read_real_train_samples
    samples = [_sample(label=0, group="a").model_dump(mode="json"), _sample(label=1, group="b").model_dump(mode="json")]
    _manifest_export(tmp_path, samples)
    dataset = read_dataset_manifest(tmp_path)
    loaded = read_real_train_samples(tmp_path, "fatty_liver")
    assert dataset.schema_version == "longitudinal_fixed_window_dataset.v1"
    assert len(loaded) == 2


def test_reader_rejects_legacy_or_outcome_fields(tmp_path):
    from app.services.longitudinal_model_training import ModelInputError, read_real_train_samples
    raw = _sample(label=1, group="a").model_dump(mode="json")
    raw["features"]["final_stage"] = "hcc"
    _manifest_export(tmp_path, [raw])
    with pytest.raises(ModelInputError, match="forbidden"):
        read_real_train_samples(tmp_path, "fatty_liver")


def test_reader_rejects_manifest_hash_mismatch(tmp_path):
    from app.services.longitudinal_model_training import ModelInputError, read_dataset_manifest
    _manifest_export(tmp_path, [_sample(label=1, group="a").model_dump(mode="json")])
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["fatty_liver/real_train.jsonl"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelInputError, match="hash"):
        read_dataset_manifest(tmp_path)


def test_task_filter_and_feature_catalog_exclude_identity_fields():
    from app.services.longitudinal_model_training import build_feature_catalog, select_task_samples
    rows = select_task_samples([_sample(label=0, group="a"), _sample(label=1, group="b")], "fatty_liver.pre_cirrhosis_to_progression")
    catalog = build_feature_catalog(rows, TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"])
    assert {row.sample.identity.current_state for row in rows} == {"pre_cirrhosis"}
    assert "alt.last" in catalog.feature_names
    assert "patient_label" not in catalog.feature_names


def test_locked_group_split_is_disjoint_and_reproducible():
    from app.services.longitudinal_model_training import make_locked_group_split, select_task_samples
    rows = select_task_samples([_sample(label=i % 2, group=format(i, "x")) for i in range(10)], "fatty_liver.pre_cirrhosis_to_progression")
    first = make_locked_group_split(rows, seed=42, test_fraction=0.2)
    second = make_locked_group_split(rows, seed=42, test_fraction=0.2)
    assert set(first.development_groups).isdisjoint(first.locked_test_groups)
    assert first.model_dump() == second.model_dump()


def test_preprocessor_has_training_fitted_imputer_and_sex_encoder():
    from app.services.longitudinal_model_training import build_feature_catalog, make_preprocessor, select_task_samples
    rows = select_task_samples([_sample(label=0, group="a"), _sample(label=1, group="b")], "fatty_liver.pre_cirrhosis_to_progression")
    preprocessor = make_preprocessor(build_feature_catalog(rows, TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"]), scale_numeric=True)
    transformers = {item[0]: item[1] for item in preprocessor.transformers}
    assert "numeric" in transformers
    assert "sex" in transformers
    assert transformers["numeric"].named_steps["imputer"].strategy == "median"


def test_model_candidates_are_limited_to_logistic_and_random_forest():
    from app.services.longitudinal_model_training import make_model_candidates
    candidates = make_model_candidates(seed=42)
    assert set(candidates) == {"logistic_regression", "random_forest"}


def test_development_cv_uses_grouped_stratified_folds():
    from app.services.longitudinal_model_training import run_development_cv, select_task_samples
    rows = select_task_samples([_sample(label=i % 2, group=format(i, "x")) for i in range(12)], "fatty_liver.pre_cirrhosis_to_progression")
    result = run_development_cv(rows, TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"], seed=42)
    assert result.split_method == "StratifiedGroupKFold"
    for fold in result.folds:
        assert set(fold.train_groups).isdisjoint(fold.validation_groups)


def test_candidate_bundle_contains_complete_p005_metadata(tmp_path):
    from app.schemas.longitudinal_model_training import DatasetInput
    from app.services.longitudinal_model_training import (
        select_task_samples,
        train_task_to_candidate,
        write_candidate_bundle,
    )
    from scripts.check_model_artifacts import sha256_file

    task = TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"]
    rows = select_task_samples(
        [_sample(label=i % 2, group=format(i, "x")) for i in range(12)],
        task.task,
    )
    dataset = DatasetInput(
        dataset_dir=str(tmp_path / "dataset"),
        schema_version="longitudinal_fixed_window_dataset.v1",
        manifest_sha256="a" * 64,
        data_content_sha256="b" * 64,
        file_sha256="c" * 64,
    )
    result = train_task_to_candidate(rows, task, dataset, tmp_path / "fit", seed=42)
    bundle = write_candidate_bundle(result, tmp_path / "bundles")
    metadata = ArtifactMetadata.model_validate_json(
        bundle.metadata_path.read_text(encoding="utf-8")
    )

    assert metadata.status == "candidate"
    assert metadata.production_enabled is False
    assert metadata.artifact_type == "outcome"
    assert metadata.horizon_days == 365
    assert metadata.model_contract.artifact_sha256 == sha256_file(bundle.model_path)
    assert bundle.model_path.name == "fatty_liver_pre_cirrhosis_to_progression_365d.joblib"
    assert bundle.metadata_path.name == "fatty_liver_pre_cirrhosis_to_progression_365d.meta.json"
    assert metadata.feature_contract.feature_names[-1] == "sex"
    assert "age" in metadata.feature_contract.allowed_missing_features
    assert metadata.feature_contract.input_container == "pandas_dataframe"
    assert metadata.score_contract.semantics == "model_score"
    assert metadata.calibration.status == "not_calibrated"


def test_candidate_bundle_is_task_scoped_and_never_overwrites(tmp_path):
    from app.schemas.longitudinal_model_training import DatasetInput
    from app.services.longitudinal_model_training import (
        select_task_samples,
        train_task_to_candidate,
        write_candidate_bundle,
    )

    task = TASK_SPECS["ad.pre_dementia_to_dementia"]
    rows = select_task_samples(
        [
            _sample(
                disease="ad",
                current_state="pre_dementia",
                target_event="dementia",
                label=i % 2,
                group=format(i, "x"),
            )
            for i in range(12)
        ],
        task.task,
    )
    dataset = DatasetInput(
        dataset_dir=str(tmp_path / "dataset"),
        schema_version="longitudinal_fixed_window_dataset.v1",
        manifest_sha256="a" * 64,
        data_content_sha256="b" * 64,
        file_sha256="c" * 64,
    )
    result = train_task_to_candidate(rows, task, dataset, tmp_path / "fit", seed=42)
    first = write_candidate_bundle(result, tmp_path / "bundles")
    assert first.bundle_dir.name == "ad_pre_dementia_to_dementia_365d"
    with pytest.raises(FileExistsError):
        write_candidate_bundle(result, tmp_path / "bundles")
