"""Contracts for synthetic engineering cases, separate from clinical releases."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


GENERATOR_VERSION = "synthetic-prediction.v1"
SCHEMA_VERSION = "synthetic_prediction_cases.v1"
Disease = Literal["ad", "fatty_liver"]
Pool = Literal["development_pool", "challenge_pool"]


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GenerationConfig(StrictRecord):
    seed: int = Field(default=20260914, ge=0, strict=True)
    patients_per_disease: int = Field(default=120, gt=0, strict=True)
    challenge_per_disease: int = Field(default=40, gt=0, strict=True)

    @model_validator(mode="after")
    def require_development_pool(self):
        if self.challenge_per_disease >= self.patients_per_disease:
            raise ValueError("development_pool_required")
        return self


class SyntheticSource(StrictRecord):
    is_synthetic: Literal[True] = True
    source_kind: Literal["synthetic"] = "synthetic"
    generator_version: Literal["synthetic-prediction.v1"] = GENERATOR_VERSION
    run_id: str | None = None


class SyntheticPatient(StrictRecord):
    subject_id: str = Field(min_length=1)
    dependency_group_id: str = Field(min_length=1)
    disease: Disease
    age: int = Field(ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: Literal["mci", "dementia", "pre_cirrhosis", "cirrhosis"]
    diagnosis_status: Literal["confirmed", "unknown", "excluded"]
    anchor_date: date
    diagnosis_known_on: date | None
    history_coverage: Literal["complete", "unknown"]
    source: SyntheticSource

    @model_validator(mode="after")
    def match_disease_stage(self):
        stages = {"ad": {"mci", "dementia"}, "fatty_liver": {"pre_cirrhosis", "cirrhosis"}}
        if self.baseline_stage not in stages[self.disease]:
            raise ValueError("baseline_stage_disease_conflict")
        return self


class SyntheticObservation(StrictRecord):
    observation_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    indicator: Literal["mmse", "alt"]
    measured_on: date | None
    known_on: date | None
    value: float | None
    unit: str | None
    method: str | None
    observation_kind: Literal["actual", "planned"]
    role: Literal["history", "anchor", "followup"]
    horizon_months: Literal[6, 12] | None
    observation_status: Literal["observed", "confirmed_unobserved", "pending_observation"]
    source: SyntheticSource

    @model_validator(mode="after")
    def consistent_observation(self):
        if (self.role == "followup") != (self.horizon_months is not None):
            raise ValueError("observation_horizon_mismatch")
        if self.observation_status != "observed" and self.value is not None:
            raise ValueError("unobserved_value_present")
        if self.observation_status == "observed" and self.measured_on is None:
            raise ValueError("measurement_date_required")
        if self.known_on and self.measured_on and self.known_on < self.measured_on:
            raise ValueError("known_before_measurement")
        if self.value is not None:
            if self.value < 0 or (self.indicator == "mmse" and self.value > 30):
                raise ValueError("measurement_out_of_bounds")
        return self


class InputObservation(StrictRecord):
    observation_id: str
    indicator: Literal["mmse", "alt"]
    measured_on: date
    known_on: date
    value: float
    unit: str
    method: str


class PredictionInput(StrictRecord):
    sample_id: str
    subject_id: str
    dependency_group_id: str
    task_id: str
    horizon_months: Literal[6, 12]
    anchor_date: date
    anchor_observation_id: str | None
    input_observations: list[InputObservation]
    input_status: Literal["available", "unavailable"]
    input_reason: str | None
    history_coverage: Literal["complete", "unknown"]
    history_state: Literal["confirmed_none", "observed", "unknown"]
    source: SyntheticSource

    @model_validator(mode="after")
    def enforce_input_boundary(self):
        if any(o.measured_on > self.anchor_date or o.known_on > self.anchor_date
               for o in self.input_observations):
            raise ValueError("future_input")
        ids = [o.observation_id for o in self.input_observations]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_input_observation")
        if self.input_status == "available" and self.anchor_observation_id not in ids:
            raise ValueError("anchor_input_missing")
        return self


class FollowupOutcome(StrictRecord):
    sample_id: str
    subject_id: str
    horizon_months: Literal[6, 12]
    nominal_date: date
    observation_id: str | None
    actual_date: date | None
    value: float | None
    status: Literal["fixture_observed_at_nominal", "pending_window", "confirmed_unobserved",
                    "pending_observation", "pending_comparability", "incomparable",
                    "invalid_observation", "conflicting_observations"]

    @model_validator(mode="after")
    def require_scoring_evidence(self):
        if self.status == "fixture_observed_at_nominal":
            if self.actual_date != self.nominal_date or self.value is None:
                raise ValueError("nominal_target_evidence_missing")
        if self.status in {"confirmed_unobserved", "pending_observation"} and self.value is not None:
            raise ValueError("unobserved_target_value")
        return self
