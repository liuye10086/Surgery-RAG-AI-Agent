"""Strict contracts shared by outcome, stage, and trend model bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.longitudinal_model_registry import (
    CalibrationContract,
    FeatureContract,
    ModelContract,
)


MODEL_ARTIFACT_SCHEMA_VERSION = "longitudinal_model_artifact.v2"
EVALUATION_SCHEMA_VERSION = "longitudinal_model_evaluation.v1"
ArtifactType = Literal["outcome", "stage", "trend"]
Sha256 = str


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HorizonContract(StrictModel):
    kind: Literal["days", "next_visit"]
    value: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_value(self):
        if self.kind == "days" and self.value is None:
            raise ValueError("day horizon requires a value")
        if self.kind == "next_visit" and self.value is not None:
            raise ValueError("next visit horizon cannot name a day count")
        return self


class DatasetContractV2(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"]
    manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    data_content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    training_file: str = Field(min_length=1)
    training_file_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_relative_training_file(self):
        normalized = self.training_file.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
            raise ValueError("training file must be a safe relative path")
        return self


class OutputContract(StrictModel):
    kind: Literal["binary", "multiclass"]
    classes: list[str] = Field(min_length=2)
    score_semantics: Literal["model_score", "calibrated_probability"]
    positive_class: str | None = None
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    ordered: bool | None = None
    projected_value_supported: bool = False
    prediction_interval_supported: bool = False

    @model_validator(mode="after")
    def validate_output_shape(self):
        if self.projected_value_supported or self.prediction_interval_supported:
            raise ValueError("current model suite supports direction/class output only")
        if len(self.classes) != len(set(self.classes)) or any(
            not value.strip() for value in self.classes
        ):
            raise ValueError("output classes must be unique and non-empty")
        if self.kind == "binary":
            if len(self.classes) != 2:
                raise ValueError("binary output requires exactly two classes")
            if self.positive_class not in self.classes or self.threshold is None:
                raise ValueError("binary output requires positive class and threshold")
            if self.ordered is not None:
                raise ValueError("binary output cannot declare ordered classes")
        else:
            if self.positive_class is not None or self.threshold is not None:
                raise ValueError("multiclass output cannot declare binary fields")
            if self.ordered is None:
                raise ValueError("multiclass output must declare ordering")
        return self


class ArtifactAuditContractV2(StrictModel):
    leakage_status: Literal["passed", "review_required", "blocked"]
    locked_test_used_for_selection: Literal[False] = False
    synthetic_in_formal_metrics: bool = False
    synthetic_purpose: Literal["demonstration_training_only"] | None = None
    clinical_validity_claim: Literal[False] = False
    code_version: str = Field(min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_synthetic_boundary(self):
        if self.synthetic_in_formal_metrics:
            if (
                self.synthetic_purpose != "demonstration_training_only"
                or self.leakage_status != "review_required"
            ):
                raise ValueError("synthetic metrics require demonstration review")
        elif self.synthetic_purpose is not None:
            raise ValueError("synthetic purpose requires synthetic metrics")
        return self


class ArtifactMetadataV2(StrictModel):
    schema_version: Literal["longitudinal_model_artifact.v2"]
    artifact_type: ArtifactType
    task: str = Field(min_length=1, max_length=200)
    dataset: Literal["fatty_liver", "ad"]
    target: str = Field(min_length=1, max_length=160)
    horizon: HorizonContract
    feature_contract: FeatureContract
    dataset_contract: DatasetContractV2
    split_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    model_contract: ModelContract
    output_contract: OutputContract
    calibration: CalibrationContract
    audit: ArtifactAuditContractV2
    status: Literal["candidate"]
    production_enabled: Literal[False]
    created_at: datetime

    @model_validator(mode="after")
    def validate_artifact_contract(self):
        if not self.task.startswith(f"{self.dataset}."):
            raise ValueError("task does not belong to dataset")
        if (
            self.calibration.status != "calibrated"
            and self.output_contract.score_semantics != "model_score"
        ):
            raise ValueError("uncalibrated output must use model_score semantics")
        if (
            self.calibration.status == "calibrated"
            and self.output_contract.score_semantics != "calibrated_probability"
        ):
            raise ValueError("calibrated output must use calibrated probability semantics")
        expected_kind = "binary" if self.artifact_type == "outcome" else "multiclass"
        if self.output_contract.kind != expected_kind:
            raise ValueError("artifact type and output kind mismatch")
        if self.artifact_type == "trend" and self.output_contract.classes != [
            "rising",
            "stable",
            "falling",
        ]:
            raise ValueError("trend output classes must use the fixed direction contract")
        return self


class MulticlassMetrics(StrictModel):
    class_order: list[str] = Field(min_length=2)
    class_support: dict[str, int]
    macro_f1: float | None = Field(default=None, ge=0.0, le=1.0)
    balanced_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    confusion_matrix: list[list[int]]
    unavailable_metrics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_matrix(self):
        size = len(self.class_order)
        if len(self.class_order) != len(set(self.class_order)):
            raise ValueError("class order must be unique")
        if set(self.class_support) != set(self.class_order):
            raise ValueError("class support must cover fixed class order")
        if len(self.confusion_matrix) != size or any(
            len(row) != size for row in self.confusion_matrix
        ):
            raise ValueError("confusion matrix must follow fixed class order")
        if any(value < 0 for row in self.confusion_matrix for value in row):
            raise ValueError("confusion matrix counts cannot be negative")
        return self


class EvaluationArtifact(StrictModel):
    schema_version: Literal["longitudinal_model_evaluation.v1"] = (
        EVALUATION_SCHEMA_VERSION
    )
    artifact_type: ArtifactType
    task: str = Field(min_length=1, max_length=200)
    dataset: Literal["fatty_liver", "ad"]
    dataset_manifest_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    data_content_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    training_file_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    split_sha256: Sha256 = Field(pattern=r"^[0-9a-f]{64}$")
    selection_metrics: dict[str, Any]
    locked_test_metrics: dict[str, Any]
    baselines: dict[str, Any]
    class_support: dict[str, int]
    locked_test_used_for_selection: Literal[False] = False


class BundleValidationStatus(StrictModel):
    status: Literal["available", "missing", "incompatible"]
    reason_code: str = Field(min_length=1, max_length=120)


class BundleValidationResult(StrictModel):
    status: BundleValidationStatus
    metadata: ArtifactMetadataV2 | None = None
    prediction_executed: Literal[False] = False
