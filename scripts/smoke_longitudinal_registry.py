"""Real-data, patient-safe smoke runner for a disposable P0-05 registry."""

from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
for item in (ROOT, BACKEND):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_model_registry import load_active_model_registry
from app.services.longitudinal_prediction import run_longitudinal_prediction


SENSITIVE = re.compile(
    r"patient_id|patient_label|postgresql://|password|traceback|(?:^|[^A-Z0-9])[PA]\d{3}(?:[^A-Z0-9]|$)",
    re.IGNORECASE,
)


def assert_safe_payload(payload: dict[str, Any]) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if SENSITIVE.search(serialized):
        raise ValueError("sensitive_output_detected")


def _date(value: str | None) -> date | None:
    text = (value or "").strip()
    return date.fromisoformat(text) if text else None


def _read(path: Path) -> list[dict[str, str]]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _indicator_rows(row: dict[str, str]) -> list[dict[str, object]]:
    indicators = []
    for name, raw in row.items():
        if name in {"patient_id", "visit_date"} or raw in (None, ""):
            continue
        indicators.append({"name": name, "value": float(raw), "unit": "source_unit"})
    return indicators


def _prefix_matches(
    dataset: str,
    patient: dict[str, str],
    prefix: list[dict[str, str]],
    scenario: str,
) -> bool:
    cutoff = _date(prefix[-1]["visit_date"])
    if cutoff is None:
        return False
    if dataset == "fatty_liver":
        cirrhosis = _date(patient.get("cirrhosis_date"))
        hcc = _date(patient.get("hcc_date"))
        if scenario == "pre_cirrhosis":
            return cirrhosis is None or cutoff < cirrhosis
        if scenario == "cirrhosis":
            return cirrhosis is not None and cirrhosis <= cutoff and (
                hcc is None or cutoff < hcc
            )
    if dataset == "ad" and scenario == "mci":
        dementia = _date(patient.get("dementia_date"))
        return dementia is None or cutoff < dementia
    return False


def load_online_smoke_case(
    dataset: str,
    patients_csv: Path,
    visits_csv: Path,
    scenario: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    patients = sorted(_read(patients_csv), key=lambda row: row["patient_id"])
    visits_by_patient: dict[str, list[dict[str, str]]] = {}
    for visit in _read(visits_csv):
        visits_by_patient.setdefault(visit["patient_id"], []).append(visit)
    for rows in visits_by_patient.values():
        rows.sort(key=lambda row: row["visit_date"])

    for patient in patients:
        rows = visits_by_patient.get(patient["patient_id"], [])
        for end in range(3, len(rows) + 1):
            prefix = rows[:end]
            if not _prefix_matches(dataset, patient, prefix, scenario):
                continue
            case = {
                "sex": patient.get("sex") or None,
                "baseline_stage": scenario,
            }
            visits = [
                {
                    "visit_date": row["visit_date"],
                    "indicators": _indicator_rows(row),
                    "notes": None,
                }
                for row in prefix
            ]
            return case, visits
    raise ValueError("smoke_fixture_not_found")


def _result_summary(result) -> dict[str, object]:
    outcome = result.model_status.outcome
    outcome_payload = {
        "task": outcome.task,
        "status": outcome.status,
        "reason_code": outcome.reason_code,
        "model_version": outcome.model_version,
        "artifact_sha256": outcome.artifact_sha256,
        "target": outcome.target,
        "horizon_days": outcome.horizon_days,
        "feature_version": outcome.feature_version,
        "score_semantics": outcome.score_semantics,
        "calibration_status": outcome.calibration_status,
        "risk_score": result.outcome_prediction.risk_score,
        "risk_band": result.outcome_prediction.risk_band,
    }
    stage = result.model_status.stage
    trend_items = list(result.trend_predictions)
    payload = {
        "schema_version": result.schema_version,
        "observation_visit_count": result.observation.get("visit_count"),
        "outcome": outcome_payload,
        "stage": {
            "status": stage.status,
            "reason_code": stage.reason_code,
            "model_version": stage.model_version,
            "likely_next_stage": result.outcome_prediction.stage_projection.likely_next_stage,
        },
        "trends": {
            "required_count": len(trend_items),
            "available_count": sum(
                item.model_status.status == "available" for item in trend_items
            ),
            "items": [
                {
                    "indicator": item.indicator,
                    "status": item.model_status.status,
                    "reason_code": item.model_status.reason_code,
                    "direction": item.forecast.direction,
                }
                for item in trend_items
            ],
        },
    }
    release_set = getattr(result, "release_set", None)
    if release_set is not None:
        payload.update(
            release_set_id=release_set.release_set_id,
            release_set_sha256=release_set.release_set_sha256,
            data_release_id=release_set.data_release_id,
            split_sha256=release_set.split_sha256,
        )
    assert_safe_payload(payload)
    return payload


def run_smoke(registry_dir: Path, data_root: Path) -> dict[str, object]:
    root = Path(data_root)
    scenarios = [
        (
            "fatty_liver_pre_cirrhosis",
            FATTY_LIVER_ADAPTER,
            "pre_cirrhosis",
            root / "longitudinal_300" / "patients.csv",
            root / "longitudinal_300" / "visits.csv",
        ),
        (
            "fatty_liver_cirrhosis",
            FATTY_LIVER_ADAPTER,
            "cirrhosis",
            root / "longitudinal_300" / "patients.csv",
            root / "longitudinal_300" / "visits.csv",
        ),
        (
            "ad_mci",
            AD_ADAPTER,
            "mci",
            root / "ad_longitudinal_300" / "patients.csv",
            root / "ad_longitudinal_300" / "visits.csv",
        ),
    ]
    results = {}
    registries = {
        "fatty_liver": load_active_model_registry("fatty_liver", registry_dir),
        "ad": load_active_model_registry("ad", registry_dir),
    }
    for name, adapter, stage, patients, visits in scenarios:
        case, timeline = load_online_smoke_case(
            adapter.dataset, patients, visits, stage
        )
        prediction = run_longitudinal_prediction(
            case, timeline, adapter, registries[adapter.dataset]
        )
        results[name] = _result_summary(prediction)

    case, timeline = load_online_smoke_case(
        "fatty_liver",
        root / "longitudinal_300" / "patients.csv",
        root / "longitudinal_300" / "visits.csv",
        "pre_cirrhosis",
    )
    case["baseline_stage"] = "suspected_cirrhosis"
    uncertain = run_longitudinal_prediction(
        case, timeline, FATTY_LIVER_ADAPTER, registries["fatty_liver"]
    )
    results["fatty_liver_suspected_cirrhosis"] = _result_summary(uncertain)
    if results["fatty_liver_suspected_cirrhosis"]["outcome"]["risk_score"] is not None:
        raise ValueError("uncertain_stage_returned_score")
    payload = {"status": "passed", "scenarios": results}
    assert_safe_payload(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = run_smoke(args.registry_dir, args.data_root)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": {
                        "code": "longitudinal_registry_smoke_failed",
                        "message": "纵向模型 registry smoke test 未通过",
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
