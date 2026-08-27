"""Strict contracts for P0-04 longitudinal outcome training."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.longitudinal_model_registry import TASK_CONTRACTS

MODEL_TRAINING_SCHEMA_VERSION = "longitudinal_outcome_model_training.v1"

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

class TaskSpec(StrictModel):
    task: str
    disease: Literal["fatty_liver", "ad"]
    current_state: str
    target_event: str
    dataset_file: str

TASK_SPECS = {
    name: TaskSpec(
        task=name,
        disease=contract.dataset,
        current_state=contract.current_state,
        target_event=contract.target,
        dataset_file=contract.dataset_file,
    )
    for name, contract in TASK_CONTRACTS.items()
}

class DatasetInput(StrictModel):
    dataset_dir: str
    schema_version: str
    run_id: str | None = None
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_sha256_by_path: dict[str, str]
    group_split_file: str | None = None
    group_split_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    training_profile: Literal["real_only", "synthetic_demonstration"] = "real_only"
    training_file_by_disease: dict[str, str] = Field(default_factory=dict)
    timeline_file_by_disease: dict[str, str] = Field(default_factory=dict)
    clinical_validity_claim: Literal[False] = False

    @model_validator(mode="after")
    def validate_file_hashes(self):
        if not self.file_sha256_by_path:
            raise ValueError("manifest_files_missing")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in self.file_sha256_by_path.values()
        ):
            raise ValueError("manifest_file_hash_invalid")
        if (self.group_split_file is None) != (self.group_split_sha256 is None):
            raise ValueError("group_split_contract_incomplete")
        if self.group_split_file is not None:
            if self.file_sha256_by_path.get(self.group_split_file) != self.group_split_sha256:
                raise ValueError("group_split_hash_mismatch")
        return self

    def file_sha256(self, relative_path: str) -> str:
        try:
            return self.file_sha256_by_path[relative_path]
        except KeyError as exc:
            raise ValueError("training_file_missing_from_manifest") from exc

class InputAudit(StrictModel):
    sample_count: int = Field(ge=0)
    patient_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    synthetic_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    forbidden_feature_hits: list[str] = Field(default_factory=list)

class GroupSplit(StrictModel):
    development_groups: list[str]
    locked_test_groups: list[str]
    development_indices: list[int]
    locked_test_indices: list[int]
    seed: int
    test_fraction: float
    group_overlap_check: Literal["passed", "failed"]

class FoldMetrics(StrictModel):
    fold: int = Field(ge=1)
    train_patient_count: int = Field(ge=0)
    validation_patient_count: int = Field(ge=0)
    positive_patient_count: int = Field(ge=0)
    negative_patient_count: int = Field(ge=0)
    train_groups: list[str] = Field(default_factory=list)
    validation_groups: list[str] = Field(default_factory=list)
    pr_auc: float | None = None
    roc_auc: float | None = None
    unavailable_metrics: list[str] = Field(default_factory=list)

class BinaryMetrics(StrictModel):
    pr_auc: float | None = None
    roc_auc: float | None = None
    brier_score: float | None = None
    sensitivity: float | None = None
    specificity: float | None = None
    ppv: float | None = None
    npv: float | None = None
    f1: float | None = None
    confusion_matrix: list[list[int]]
    unavailable_metrics: list[str] = Field(default_factory=list)

class EvaluationSummary(StrictModel):
    split_method: str
    requested_fold_count: int = Field(ge=1)
    folds: list[FoldMetrics] = Field(default_factory=list)
    aggregate: dict[str, Any] = Field(default_factory=dict)
    locked_test: BinaryMetrics | None = None

class LeakageAudit(StrictModel):
    group_overlap: bool = False
    future_visit_detected: bool = False
    forbidden_feature_hits: list[str] = Field(default_factory=list)
    duplicate_rows: int = Field(ge=0, default=0)
    test_used_for_selection: bool = False
    synthetic_in_formal_metrics: bool = False
    cross_task_split_mismatch: bool = False
    source_family_overlap: bool = False
    near_duplicate_source_overlap: bool = False
    high_score_warning: bool = False
    leakage_review_required: bool = False
    status: Literal["passed", "review_required", "blocked"] = "passed"

class ModelMetadata(StrictModel):
    schema_version: Literal["longitudinal_outcome_model_training.v1"]
    task: str
    dataset_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    data_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_order_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["candidate", "reviewed", "enabled"] = "candidate"
    production_enabled: bool = False
    clinical_validity_claim: bool = False
    leakage_audit: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    evaluation: dict[str, Any] = Field(default_factory=dict)
    threshold: dict[str, Any] = Field(default_factory=dict)
    calibration: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_candidate_safety(self):
        if self.status != "candidate":
            raise ValueError("training phase only permits candidate artifacts")
        if self.production_enabled or self.clinical_validity_claim:
            raise ValueError("candidate artifact cannot be production enabled or claim clinical validity")
        return self
