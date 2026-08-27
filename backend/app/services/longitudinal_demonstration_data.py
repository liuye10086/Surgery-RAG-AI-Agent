"""Reproducible synthetic timelines for end-to-end demonstration training only."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


GENERATOR_VERSION = "longitudinal-demonstration.v1"
DEFAULT_SEED = 20260827
_VISIT_DATES = tuple(
    (date(2017, 1, 1) + timedelta(days=300 * index)).isoformat()
    for index in range(10)
)


def _indicator_rows(values: dict[str, float]) -> list[dict[str, object]]:
    return [
        {"name": name, "value": round(value, 4), "unit": ""}
        for name, value in sorted(values.items())
    ]


def _fatty_values(patient_index: int, visit_index: int) -> dict[str, float]:
    bases = {
        "alt": 42.0,
        "ast": 34.0,
        "ggt": 48.0,
        "tbil": 16.0,
        "alb": 39.0,
        "plt": 210.0,
        "afp": 5.0,
    }
    multipliers = (0.95, 1.0, 1.0, 1.0, 1.12, 1.12, 0.98, 0.98, 1.10, 1.10)
    patient_factor = 1.0 + (patient_index % 7 - 3) * 0.012
    return {
        name: base * patient_factor * multipliers[visit_index]
        for name, base in bases.items()
    }


def _ad_values(patient_index: int, visit_index: int) -> dict[str, float]:
    cdr = (0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 0.5, 1.0, 1.0)
    mmse = (27.0, 26.0, 25.0, 25.0, 28.0, 28.0, 23.0, 23.0, 26.0, 26.0)
    moca = (24.0, 23.0, 22.0, 22.0, 25.0, 25.0, 20.0, 20.0, 23.0, 23.0)
    nfl = (20.0, 21.0, 22.0, 22.0, 26.0, 26.0, 20.0, 20.0, 24.0, 24.0)
    ptau = (0.70, 0.72, 0.74, 0.74, 0.88, 0.88, 0.70, 0.70, 0.84, 0.84)
    offset = (patient_index % 5 - 2) * 0.1
    return {
        "cdr": cdr[visit_index],
        "mmse": mmse[visit_index] + offset,
        "moca": moca[visit_index] + offset,
        "plasma_nfl": nfl[visit_index] + offset,
        "plasma_ptau217": ptau[visit_index] + offset * 0.01,
    }


def _patient_rows(
    *,
    disease: str,
    patient_index: int,
    seed: int,
) -> list[dict[str, Any]]:
    if disease == "fatty_liver":
        disease_name = "脂肪肝"
        source_dataset = "fatty_liver_demonstration_v1"
        patient_label = f"FL-DEMO-{patient_index:03d}"
        final_stage = "hcc"
        event_dates = {
            "cirrhosis_date": _VISIT_DATES[5],
            "hcc_date": _VISIT_DATES[8],
        }
        value_builder = _fatty_values
    else:
        disease_name = "阿尔茨海默病"
        source_dataset = "ad_demonstration_v1"
        patient_label = f"AD-DEMO-{patient_index:03d}"
        final_stage = "1"
        event_dates = {"dementia_date": _VISIT_DATES[6]}
        value_builder = _ad_values

    age = 52 + patient_index % 24
    sex = "female" if patient_index % 2 else "male"
    rows: list[dict[str, Any]] = []
    for visit_index, visit_date in enumerate(_VISIT_DATES):
        values = value_builder(patient_index, visit_index)
        rows.append(
            {
                "record_id": f"{disease}-{patient_index}-{visit_index}",
                "disease_name": disease_name,
                "patient_label": patient_label,
                "indicators": _indicator_rows(values),
                "metadata": {
                    "visit_date": visit_date,
                    "patient_age": age,
                    "sex": sex,
                    "final_stage": final_stage,
                    "event_dates": event_dates,
                    "source_dataset": source_dataset,
                    "is_synthetic": True,
                    "import_version": GENERATOR_VERSION,
                    "synthetic_purpose": "demonstration_training_only",
                    "generator_seed": seed,
                },
            }
        )
    return rows


def build_demonstration_case_rows(
    *,
    patients_per_disease: int = 30,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    if patients_per_disease < 15:
        raise ValueError("demonstration_patient_support_insufficient")
    rows: list[dict[str, Any]] = []
    for disease in ("fatty_liver", "ad"):
        for patient_index in range(1, patients_per_disease + 1):
            rows.extend(
                _patient_rows(
                    disease=disease,
                    patient_index=patient_index,
                    seed=seed,
                )
            )
    return rows
