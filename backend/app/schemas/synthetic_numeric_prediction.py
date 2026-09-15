"""Strict engineering-only contracts; source authenticity is an admission concern."""

from datetime import date
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from app.schemas.synthetic_prediction_cases import InputObservation, PredictionInput


INPUT_VERSION = "synthetic_numeric_input.v1"
Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, pattern=r"\S")]
InputReason = Literal["anchor_unavailable", "population_not_confirmed",
                      "population_not_known_at_anchor", "conflicting_history"]


def _calendar_date(value):
    if type(value) is date or isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise ValueError("calendar_date_required")


def _integer_month(value):
    if type(value) is not int:
        raise ValueError("integer_horizon_required")
    return value


CalendarDate = Annotated[date, BeforeValidator(_calendar_date)]
Horizon = Annotated[Literal[6, 12], BeforeValidator(_integer_month)]


class StrictNumericModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")


class NumericPacketSource(StrictNumericModel):
    source_kind: Literal["synthetic"]
    is_synthetic: Literal[True]
    generator_version: Literal["synthetic-prediction.v1"]
    run_id: Identifier

    @field_validator("is_synthetic", mode="before")
    @classmethod
    def explicit_synthetic(cls, value):
        if value is not True:
            raise ValueError("synthetic_source_required")
        return value


class NumericSourceIdentity(NumericPacketSource):
    manifest_sha256: Sha
    input_file_sha256: Sha


class NumericObservation(InputObservation):
    model_config = StrictNumericModel.model_config
    observation_id: Identifier
    measured_on: CalendarDate
    known_on: CalendarDate
    value: float = Field(strict=True, ge=0)
    method: Identifier

    @model_validator(mode="after")
    def valid_measurement(self):
        if self.known_on < self.measured_on:
            raise ValueError("known_before_measurement")
        if self.unit != ("分" if self.indicator == "mmse" else "U/L"):
            raise ValueError("numeric_unit_mismatch")
        if self.indicator == "mmse" and self.value > 30:
            raise ValueError("measurement_out_of_bounds")
        return self


class NumericPredictionInput(PredictionInput):
    model_config = StrictNumericModel.model_config
    sample_id: Identifier
    subject_id: Identifier
    dependency_group_id: Identifier
    horizon_months: Horizon
    anchor_date: CalendarDate
    input_observations: list[NumericObservation]
    source: NumericPacketSource
    input_reason: InputReason | None

    @model_validator(mode="after")
    def valid_numeric_packet(self):
        if (self.input_status == "available") != (self.input_reason is None):
            raise ValueError("input_status_reason_mismatch")
        expected_suffix = f'.{self.horizon_months}m'
        if self.task_id not in (f'ad.mmse{expected_suffix}', f'fatty_liver.alt{expected_suffix}'):
            raise ValueError("numeric_task_mismatch")
        indicator = "mmse" if self.task_id.startswith("ad.") else "alt"
        rows = self.input_observations
        if any(r.indicator != indicator for r in rows):
            raise ValueError("numeric_indicator_mismatch")
        if len({r.measured_on for r in rows}) != len(rows):
            raise ValueError("conflicting_input_dates")
        anchor = next((r for r in rows if r.observation_id == self.anchor_observation_id), None)
        if self.anchor_observation_id is not None and (anchor is None or anchor.measured_on != self.anchor_date):
            raise ValueError("anchor_identity_mismatch")
        if any(r.measured_on == self.anchor_date and r != anchor for r in rows):
            raise ValueError("anchor_identity_mismatch")
        if self.input_reason == "anchor_unavailable" and anchor is not None:
            raise ValueError("anchor_status_mismatch")
        if len({r.method for r in rows}) > 1:
            raise ValueError("incomparable_input_method")
        prior = [r for r in rows if r.measured_on < self.anchor_date]
        if self.input_reason == "conflicting_history" and (self.history_state != "unknown" or prior):
            raise ValueError("conflicting_history_state_mismatch")
        if self.history_state == "confirmed_none" and (prior or self.history_coverage != "complete"):
            raise ValueError("history_state_mismatch")
        if self.history_state == "observed" and (not prior or self.history_coverage != "complete"):
            raise ValueError("history_state_mismatch")
        return self


class SyntheticNumericInput(StrictNumericModel):
    schema_version: Literal["synthetic_numeric_input.v1"] = INPUT_VERSION
    disease_code: Literal["ad", "fatty_liver"]
    subject_id: Identifier
    dependency_group_id: Identifier
    anchor_date: CalendarDate
    source: NumericSourceIdentity
    packets: list[NumericPredictionInput] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def same_subject_and_input(self):
        if {p.horizon_months for p in self.packets} != {6, 12}:
            raise ValueError("two_numeric_horizons_required")
        if len({p.sample_id for p in self.packets}) != 2:
            raise ValueError("duplicate_sample_identity")
        source = self.source.model_dump(exclude={"manifest_sha256", "input_file_sha256"})
        shared = []
        for p in self.packets:
            if (p.subject_id, p.dependency_group_id, p.anchor_date) != (
                self.subject_id, self.dependency_group_id, self.anchor_date
            ) or p.source.model_dump() != source or not p.task_id.startswith(self.disease_code + "."):
                raise ValueError("numeric_input_identity_mismatch")
            fields = p.model_dump(mode="json", exclude={"sample_id", "task_id", "horizon_months"})
            fields["input_observations"].sort(key=lambda r: (r["measured_on"], r["observation_id"]))
            shared.append(fields)
        if shared[0] != shared[1]:
            raise ValueError("numeric_horizon_inputs_differ")
        return self


class NumericAlgorithmIdentity(StrictNumericModel):
    model_id: Literal["last_value"] = "last_value"
    algorithm_version: Literal["synthetic_numeric.last_value.v1"] = "synthetic_numeric.last_value.v1"
    input_schema_version: Literal["synthetic_numeric_input.v1"] = INPUT_VERSION
    implementation_sha256: Sha
    parameters_sha256: Sha
    clinical_validity_claim: Literal[False] = False
    production_enabled: Literal[False] = False

    @field_validator("clinical_validity_claim", "production_enabled", mode="before")
    @classmethod
    def engineering_only(cls, value):
        if value is not False:
            raise ValueError("engineering_only")
        return value


class NumericTaskPrediction(StrictNumericModel):
    task_id: str
    indicator: Literal["mmse", "alt"]
    unit: Literal["分", "U/L"]
    horizon_months: Horizon
    target_date: CalendarDate
    status: Literal["available", "unavailable"]
    value: float | None = Field(strict=True, ge=0)
    reason: InputReason | None

    @model_validator(mode="after")
    def valid_value_state(self):
        if self.status == "available":
            if self.value is None or self.reason is not None:
                raise ValueError("numeric_result_status_mismatch")
        elif self.value is not None or self.reason is None:
            raise ValueError("numeric_result_status_mismatch")
        if self.indicator == "mmse" and self.value is not None and self.value > 30:
            raise ValueError("measurement_out_of_bounds")
        return self


class SyntheticNumericPrediction(StrictNumericModel):
    schema_version: Literal["synthetic_numeric_prediction.v1"] = "synthetic_numeric_prediction.v1"
    disease_code: Literal["ad", "fatty_liver"]
    subject_id: Identifier
    dependency_group_id: Identifier
    anchor_date: CalendarDate
    source: NumericSourceIdentity
    input_sha256: Sha
    algorithm: NumericAlgorithmIdentity
    predictions: list[NumericTaskPrediction] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def valid_tasks_and_dates(self):
        from app.services.synthetic_prediction_cases import add_calendar_months

        if {p.horizon_months for p in self.predictions} != {6, 12}:
            raise ValueError("two_numeric_horizons_required")
        indicator, unit = ("mmse", "分") if self.disease_code == "ad" else ("alt", "U/L")
        for p in self.predictions:
            if (p.task_id, p.indicator, p.unit, p.target_date) != (
                f"{self.disease_code}.{indicator}.{p.horizon_months}m", indicator, unit,
                add_calendar_months(self.anchor_date, p.horizon_months)
            ):
                raise ValueError("numeric_result_task_mismatch")
        return self
