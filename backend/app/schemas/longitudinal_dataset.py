"""Strict schemas for the P0-03 fixed-window longitudinal dataset."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DATASET_SCHEMA_VERSION = "longitudinal_fixed_window_dataset.v1"

DiseaseKey = Literal["fatty_liver", "ad"]
LabelStatus = Literal[
    "positive",
    "negative",
    "insufficient_observation",
    "not_applicable",
]
CurrentState = Literal[
    "pre_cirrhosis",
    "cirrhosis",
    "hcc",
    "pre_dementia",
    "dementia",
]
TargetEvent = Literal["cirrhosis_or_hcc", "hcc", "dementia", "none"]
ReasonCode = Literal[
    "target_already_reached",
    "target_event_within_window",
    "progressed_without_target_date",
    "target_event_after_window",
    "full_window_observed_without_event",
    "followup_ends_before_window",
]
EventType = Literal["cirrhosis_date", "hcc_date", "dementia_date"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IndicatorHistoryFeatures(StrictModel):
    first: float | None
    last: float | None
    minimum: float | None
    maximum: float | None
    mean: float | None
    delta: float | None
    time_slope_per_day: float | None
    recent_delta: float | None
    rises_count: int = Field(ge=0)
    falls_count: int = Field(ge=0)
    n_observations: int = Field(ge=0)
    missing_ratio: float = Field(ge=0, le=1)


class HistoricalFeatures(StrictModel):
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Literal["male", "female"] | None = None
    visit_count: int = Field(ge=3)
    observation_span_days: int = Field(ge=0)
    days_since_previous_visit: int = Field(ge=0)
    indicators: dict[str, IndicatorHistoryFeatures]


class SampleIdentity(StrictModel):
    disease: DiseaseKey
    disease_name: str = Field(min_length=1)
    source_dataset: str = Field(min_length=1)
    patient_label: str = Field(min_length=1)
    group_id: str = Field(pattern=r"^patient\.v1\.[0-9a-f]{64}$")
    is_synthetic: bool
    source_document: str | None = None
    import_version: str | None = None
    as_of: date
    current_state: CurrentState
    target_event: TargetEvent
    history_visit_count: int = Field(ge=3)
    history_start: date


class LabelAudit(StrictModel):
    status: LabelStatus
    training_label: Literal[0, 1] | None
    reason_code: ReasonCode
    window_start: date
    window_end: date
    target_event: TargetEvent
    event_type: EventType | None = None
    event_date: date | None = None
    last_followup_date: date

    @model_validator(mode="after")
    def validate_status_and_evidence(self):
        expected_label = {
            "positive": 1,
            "negative": 0,
            "insufficient_observation": None,
            "not_applicable": None,
        }[self.status]
        if self.training_label != expected_label:
            raise ValueError("标签状态与训练值不一致")

        expected_status = {
            "target_already_reached": "not_applicable",
            "target_event_within_window": "positive",
            "progressed_without_target_date": "insufficient_observation",
            "target_event_after_window": "negative",
            "full_window_observed_without_event": "negative",
            "followup_ends_before_window": "insufficient_observation",
        }[self.reason_code]
        if self.status != expected_status:
            raise ValueError("标签原因与状态不一致")

        dated_reasons = {
            "target_already_reached",
            "target_event_within_window",
            "target_event_after_window",
        }
        has_complete_event = self.event_type is not None and self.event_date is not None
        if self.reason_code in dated_reasons and not has_complete_event:
            raise ValueError("该标签原因必须包含事件类型和日期")
        if self.reason_code not in dated_reasons and (
            self.event_type is not None or self.event_date is not None
        ):
            raise ValueError("该标签原因不得包含事件证据")
        return self


class FixedWindowSample(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"] = (
        DATASET_SCHEMA_VERSION
    )
    identity: SampleIdentity
    features: HistoricalFeatures
    label: LabelAudit

    @model_validator(mode="after")
    def validate_sample_boundaries(self):
        if self.identity.history_visit_count != self.features.visit_count:
            raise ValueError("历史访视数量不一致")
        if self.identity.target_event != self.label.target_event:
            raise ValueError("预测目标不一致")
        if self.label.window_start != self.identity.as_of + timedelta(days=1):
            raise ValueError("窗口开始日期不正确")
        if self.label.window_end != self.identity.as_of + timedelta(days=365):
            raise ValueError("窗口结束日期不正确")
        if self.identity.history_start > self.identity.as_of:
            raise ValueError("历史起点不得晚于 as_of")
        return self


class CohortCounts(StrictModel):
    patient_count: int = Field(ge=0)
    candidate_patient_count: int = Field(ge=0)
    trainable_patient_count: int = Field(ge=0)
    visit_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    insufficient_observation_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    trainable_count: int = Field(ge=0)
    label_reason_counts: dict[ReasonCode, int]

    @model_validator(mode="after")
    def validate_counts(self):
        status_total = (
            self.positive_count
            + self.negative_count
            + self.insufficient_observation_count
            + self.not_applicable_count
        )
        if status_total != self.candidate_count:
            raise ValueError("候选样本状态统计不一致")
        if self.positive_count + self.negative_count != self.trainable_count:
            raise ValueError("可训练样本统计不一致")
        if sum(self.label_reason_counts.values()) != self.candidate_count:
            raise ValueError("标签原因统计不一致")
        if not (
            self.trainable_patient_count
            <= self.candidate_patient_count
            <= self.patient_count
        ):
            raise ValueError("患者统计不一致")
        return self


class DiseaseDatasetSummary(StrictModel):
    disease: DiseaseKey
    disease_name: str = Field(min_length=1)
    source_datasets: list[str]
    real: CohortCounts
    synthetic: CohortCounts
    reordered_patient_count: int = Field(ge=0)


class DatasetAuditSummary(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"] = (
        DATASET_SCHEMA_VERSION
    )
    minimum_visits: Literal[3] = 3
    horizon_days: Literal[365] = 365
    diseases: dict[DiseaseKey, DiseaseDatasetSummary]

    @model_validator(mode="after")
    def validate_disease_entries(self):
        expected = {"fatty_liver", "ad"}
        if set(self.diseases) != expected:
            raise ValueError("摘要必须同时包含脂肪肝和 AD")
        for key, value in self.diseases.items():
            if value.disease != key:
                raise ValueError("疾病摘要键和值不一致")
        return self
