"""Strict shared contracts for longitudinal model artifacts and runtime state."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


REGISTRY_SCHEMA_VERSION = "longitudinal_model_registry.v1"
ARTIFACT_METADATA_SCHEMA_VERSION = "longitudinal_outcome_artifact.v1"
REVIEW_RECORD_SCHEMA_VERSION = "longitudinal_model_review.v1"
RELEASE_RECORD_SCHEMA_VERSION = "longitudinal_model_release.v1"

Sha256 = str
ArtifactLifecycle = Literal["candidate", "reviewed", "enabled"]
RuntimeLoadStatus = Literal["available", "missing", "incompatible", "disabled"]
ArtifactType = Literal["outcome", "stage", "trend"]
RoutingStatus = Literal["selected", "not_estimable"]
BaselineStage = Literal[
    "pre_cirrhosis",
    "cirrhosis",
    "suspected_cirrhosis",
    "hcc",
    "normal",
    "mci",
    "pre_dementia",
    "dementia",
]
TaskName = Literal[
    "fatty_liver.pre_cirrhosis_to_progression",
    "fatty_liver.cirrhosis_to_hcc",
    "ad.pre_dementia_to_dementia",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)


class RegistryTaskContract(StrictModel):
    task: TaskName
    dataset: Literal["fatty_liver", "ad"]
    disease: Literal["脂肪肝", "阿尔茨海默病"]
    current_state: Literal["pre_cirrhosis", "cirrhosis", "pre_dementia"]
    target: Literal["cirrhosis_or_hcc", "hcc", "dementia"]
    horizon_days: Literal[365] = 365
    dataset_file: str
    artifact_stem: str


class BaselineStageRoute(StrictModel):
    dataset: str
    routing_status: RoutingStatus
    normalized_stage: BaselineStage | None = None
    task: TaskName | None = None
    reason_code: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def selected_requires_task(self):
        if self.routing_status == "selected" and self.task is None:
            raise ValueError("selected route requires a task")
        if self.routing_status == "not_estimable" and self.task is not None:
            raise ValueError("not estimable route cannot select a task")
        return self


TASK_CONTRACTS: dict[TaskName, RegistryTaskContract] = {
    "fatty_liver.pre_cirrhosis_to_progression": RegistryTaskContract(
        task="fatty_liver.pre_cirrhosis_to_progression",
        dataset="fatty_liver",
        disease="脂肪肝",
        current_state="pre_cirrhosis",
        target="cirrhosis_or_hcc",
        dataset_file="fatty_liver/real_train.jsonl",
        artifact_stem="fatty_liver_pre_cirrhosis_to_progression_365d",
    ),
    "fatty_liver.cirrhosis_to_hcc": RegistryTaskContract(
        task="fatty_liver.cirrhosis_to_hcc",
        dataset="fatty_liver",
        disease="脂肪肝",
        current_state="cirrhosis",
        target="hcc",
        dataset_file="fatty_liver/real_train.jsonl",
        artifact_stem="fatty_liver_cirrhosis_to_hcc_365d",
    ),
    "ad.pre_dementia_to_dementia": RegistryTaskContract(
        task="ad.pre_dementia_to_dementia",
        dataset="ad",
        disease="阿尔茨海默病",
        current_state="pre_dementia",
        target="dementia",
        dataset_file="ad/real_train.jsonl",
        artifact_stem="ad_pre_dementia_to_dementia_365d",
    ),
}


def feature_order_sha256(feature_names: list[str] | tuple[str, ...]) -> str:
    payload = json.dumps(list(feature_names), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class FeatureContract(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_features.v1"]
    feature_version: Literal["longitudinal_fixed_window_features.v1"]
    feature_names: list[str] = Field(min_length=1)
    feature_order_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    numeric_features: list[str]
    categorical_features: list[str]
    required_features: list[str]
    allowed_missing_features: list[str]
    input_container: Literal["pandas_dataframe"]
    numeric_imputation: Literal["median_add_indicator"]
    categorical_imputation: Literal["most_frequent"]

    @model_validator(mode="after")
    def validate_feature_contract(self):
        if any(not name.strip() for name in self.feature_names):
            raise ValueError("feature names must be non-empty")
        if len(self.feature_names) != len(set(self.feature_names)):
            raise ValueError("feature names must be unique")
        known = set(self.feature_names)
        if set(self.numeric_features) | set(self.categorical_features) != known:
            raise ValueError("numeric and categorical features must cover feature names")
        if set(self.numeric_features) & set(self.categorical_features):
            raise ValueError("numeric and categorical features must be disjoint")
        if not set(self.required_features).issubset(known):
            raise ValueError("required features must belong to feature names")
        if not set(self.allowed_missing_features).issubset(known):
            raise ValueError("allowed missing features must belong to feature names")
        if set(self.required_features) & set(self.allowed_missing_features):
            raise ValueError("required features cannot be allowed missing")
        if self.feature_order_sha256 != feature_order_sha256(self.feature_names):
            raise ValueError("feature order hash mismatch")
        return self


class DatasetContract(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"]
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    data_content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    training_file_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")


class PackageCompatibility(StrictModel):
    python: str = Field(min_length=1)
    scikit_learn: str = Field(min_length=1)
    joblib: str = Field(min_length=1)
    numpy: str = Field(min_length=1)
    pandas: str = Field(min_length=1)


class ModelContract(StrictModel):
    model_id: str = Field(min_length=1, max_length=160)
    model_name: str = Field(min_length=1, max_length=160)
    model_version: str = Field(min_length=1, max_length=80)
    algorithm: str = Field(min_length=1, max_length=120)
    artifact_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    packages: PackageCompatibility


class ScoreContract(StrictModel):
    semantics: Literal["model_score", "calibrated_probability", "clinical_probability"]
    positive_class: Literal[1]
    threshold: float = Field(ge=0.0, le=1.0)
    minimum: float = Field(ge=0.0, le=1.0)
    maximum: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_range(self):
        if self.minimum >= self.maximum:
            raise ValueError("score range must be increasing")
        if not self.minimum <= self.threshold <= self.maximum:
            raise ValueError("threshold must fall within score range")
        return self


class CalibrationContract(StrictModel):
    status: Literal["not_calibrated", "calibrated"]
    method: str | None = None

    @model_validator(mode="after")
    def calibrated_requires_method(self):
        if self.status == "calibrated" and not (self.method or "").strip():
            raise ValueError("calibrated artifacts require a method")
        if self.status == "not_calibrated" and self.method is not None:
            raise ValueError("uncalibrated artifacts cannot name a method")
        return self


class ArtifactAuditContract(StrictModel):
    leakage_status: Literal["passed", "review_required", "blocked"]
    clinical_validity_claim: Literal[False] = False
    code_version: str = Field(min_length=1, max_length=120)


class ArtifactMetadata(StrictModel):
    schema_version: Literal["longitudinal_outcome_artifact.v1"]
    artifact_type: Literal["outcome"]
    task: TaskName
    dataset: Literal["fatty_liver", "ad"]
    disease: Literal["脂肪肝", "阿尔茨海默病"]
    current_state: Literal["pre_cirrhosis", "cirrhosis", "pre_dementia"]
    target: Literal["cirrhosis_or_hcc", "hcc", "dementia"]
    horizon_days: Literal[365]
    feature_contract: FeatureContract
    dataset_contract: DatasetContract
    model_contract: ModelContract
    score_contract: ScoreContract
    calibration: CalibrationContract
    audit: ArtifactAuditContract
    status: Literal["candidate"]
    production_enabled: Literal[False]
    created_at: datetime

    @model_validator(mode="after")
    def validate_task_and_score_semantics(self):
        contract = TASK_CONTRACTS[self.task]
        actual = (
            self.dataset,
            self.disease,
            self.current_state,
            self.target,
            self.horizon_days,
        )
        expected = (
            contract.dataset,
            contract.disease,
            contract.current_state,
            contract.target,
            contract.horizon_days,
        )
        if actual != expected:
            raise ValueError("artifact fields do not match task contract")
        if self.calibration.status != "calibrated" and self.score_contract.semantics != "model_score":
            raise ValueError("uncalibrated output must use model_score semantics")
        return self


class ReviewRecord(StrictModel):
    schema_version: Literal["longitudinal_model_review.v1"]
    review_id: str = Field(min_length=1, max_length=180)
    task: TaskName
    model_id: str = Field(min_length=1, max_length=160)
    status: Literal["reviewed"]
    production_enabled: Literal[False]
    reviewer: str = Field(min_length=1, max_length=120)
    reviewed_at: datetime
    note: str = Field(min_length=1, max_length=2000)
    model_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    model_path: str = Field(min_length=1)
    metadata_path: str = Field(min_length=1)


class ReleaseRecord(StrictModel):
    schema_version: Literal["longitudinal_model_release.v1"]
    release_id: str = Field(min_length=1, max_length=180)
    review_id: str = Field(min_length=1, max_length=180)
    task: TaskName
    model_id: str = Field(min_length=1, max_length=160)
    status: Literal["enabled"]
    production_enabled: bool
    enabled_by: str = Field(min_length=1, max_length=120)
    enabled_at: datetime
    model_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    metadata_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    review_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    model_path: str = Field(min_length=1)
    metadata_path: str = Field(min_length=1)
    review_path: str = Field(min_length=1)


class ModelRuntimeStatus(StrictModel):
    artifact_type: ArtifactType
    task: TaskName | None = None
    status: RuntimeLoadStatus
    reason_code: str = Field(min_length=1, max_length=120)
    lifecycle_status: ArtifactLifecycle | None = None
    model_id: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    artifact_sha256: Sha256 | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    target: str | None = None
    horizon_days: int | None = None
    feature_version: str | None = None
    score_semantics: str | None = None
    calibration_status: str | None = None

    @model_validator(mode="after")
    def available_requires_identity(self):
        if self.status == "available":
            required = (
                self.task,
                self.model_id,
                self.model_name,
                self.model_version,
                self.artifact_sha256,
                self.target,
                self.horizon_days,
                self.feature_version,
                self.score_semantics,
                self.calibration_status,
            )
            if any(value in (None, "") for value in required):
                raise ValueError("available model status requires complete identity")
            if self.lifecycle_status != "enabled":
                raise ValueError("available model status requires enabled lifecycle")
        return self


class LoadedModelEntry(StrictModel):
    status: ModelRuntimeStatus
    metadata: ArtifactMetadata | None = None
    model: Any | None = Field(default=None, exclude=True)


class LongitudinalModelRegistry(StrictModel):
    schema_version: Literal["longitudinal_model_registry.v1"] = REGISTRY_SCHEMA_VERSION
    dataset: Literal["fatty_liver", "ad"]
    outcomes: dict[TaskName, LoadedModelEntry]
    stage: ModelRuntimeStatus
    trend: ModelRuntimeStatus


class ArtifactValidationResult(StrictModel):
    status: ModelRuntimeStatus
    metadata: ArtifactMetadata | None = None
    model_path: str | None = None
    metadata_path: str | None = None
    release_path: str | None = None
    prediction_executed: Literal[False] = False
