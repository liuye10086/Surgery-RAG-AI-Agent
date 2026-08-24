"""Disease-specific labels and metadata for longitudinal progression models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass(frozen=True)
class DiseaseProgressionAdapter:
    dataset: str
    disease_name: str
    stage_order: tuple[str, ...]
    event_fields: tuple[str, ...]
    minimum_visits: int = 2
    key_indicators: tuple[str, ...] = ()
    synthetic_data_warning: str = "训练数据包含按规则生成或重组合成病例"

    def _metadata(self, patient: dict[str, Any]) -> dict[str, Any]:
        metadata = patient.get("metadata") or patient.get("case_metadata") or {}
        return metadata if isinstance(metadata, dict) else {}

    def _event_date(self, patient: dict[str, Any]) -> date | None:
        event_dates = patient.get("event_dates") or self._metadata(patient).get("event_dates") or {}
        dates = [_date(event_dates.get(field)) for field in self.event_fields]
        return min((item for item in dates if item is not None), default=None)

    def outcome_label(self, patient: dict[str, Any], as_of: date, horizon: timedelta) -> int | None:
        event = self._event_date(patient)
        if event is not None:
            return int(as_of < event <= as_of + horizon)
        final = patient.get("final_stage", self._metadata(patient).get("final_stage"))
        if final in (None, ""):
            return None
        # A known stable baseline is a valid negative label.  A progressed
        # final stage without an event date is not temporally estimable and
        # must stay unknown rather than being converted to a negative.
        if str(final) == self.stage_order[0]:
            return 0
        if self.dataset == "ad":
            try:
                return 0 if float(final) < 1 else None
            except (TypeError, ValueError):
                return None
        return None

    def stage_label(self, patient: dict[str, Any], as_of: date) -> str | None:
        event_dates = patient.get("event_dates") or self._metadata(patient).get("event_dates") or {}
        for field, stage in zip(self.event_fields, self.stage_order[1:]):
            if (event := _date(event_dates.get(field))) is not None and event <= as_of:
                return stage
        final = patient.get("final_stage", self._metadata(patient).get("final_stage"))
        if final in self.stage_order:
            return str(final)
        if self.stage_order:
            return self.stage_order[0]
        return None


FATTY_LIVER_ADAPTER = DiseaseProgressionAdapter(
    dataset="fatty_liver", disease_name="脂肪肝",
    stage_order=("fatty_liver", "cirrhosis", "hcc"),
    event_fields=("cirrhosis_date", "hcc_date"),
    key_indicators=("alt", "ast", "ggt", "tbil", "alb", "plt", "afp"),
)
AD_ADAPTER = DiseaseProgressionAdapter(
    dataset="ad", disease_name="阿尔茨海默病",
    stage_order=("normal", "mci", "dementia"),
    event_fields=("dementia_date",),
    key_indicators=("mmse", "moca", "cdr", "plasma_nfl", "plasma_ptau217"),
)

ADAPTERS = {item.dataset: item for item in (FATTY_LIVER_ADAPTER, AD_ADAPTER)}


def get_progression_adapter(dataset: str) -> DiseaseProgressionAdapter:
    try:
        return ADAPTERS[dataset]
    except KeyError as exc:
        raise ValueError(f"Unsupported progression dataset: {dataset}") from exc
