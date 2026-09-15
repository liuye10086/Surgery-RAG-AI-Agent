"""Reproducible synthetic observations; no training or database access."""

from calendar import monthrange
from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import math

import numpy as np

from app.services.indicator_validation import INDICATOR_CONTRACTS

from app.schemas.synthetic_prediction_cases import (
    GENERATOR_VERSION, FollowupOutcome, GenerationConfig, PredictionInput,
    SyntheticObservation, SyntheticPatient, SyntheticSource,
)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def add_calendar_months(day: date, months: int) -> date:
    absolute = day.year * 12 + day.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, min(day.day, monthrange(year, month0 + 1)[1]))


def _seed(seed: int, disease: str, pool: str, index: int, component: str) -> int:
    payload = canonical_json([seed, disease, pool, index, component]).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:16], "big")


def _source() -> dict:
    return SyntheticSource().model_dump(exclude_none=True)


def _dump(record) -> dict:
    return record.model_dump(mode="json")


def _generate_patient(config: GenerationConfig, disease: str, pool: str, index: int):
    def rng(component):
        return np.random.Generator(np.random.PCG64(_seed(config.seed, disease, pool, index, component)))

    identity = hashlib.sha256(canonical_json([GENERATOR_VERSION, config.seed, disease, pool, index]).encode()).hexdigest()[:24]
    subject = "SYN-" + identity
    profile_rng, visits_rng, trajectory_rng = rng("profile"), rng("visits"), rng("trajectory")
    first_day, last_day = date(2023, 1, 1), date(2024, 6, 30)
    anchor = first_day + timedelta(days=int(visits_rng.integers(0, (last_day - first_day).days + 1)))
    n_pre = int(visits_rng.choice([0, 1, 2, 4, 6]))
    history_days = sorted(anchor - timedelta(days=int(d)) for d in visits_rng.choice(np.arange(1, 541), size=n_pre, replace=False))
    ad = disease == "ad"
    patient = _dump(SyntheticPatient(
        subject_id=subject, dependency_group_id="SIM-GROUP-" + identity, disease=disease,
        age=int(profile_rng.integers(45, 86)), sex=str(profile_rng.choice(["male", "female"])),
        baseline_stage=str(profile_rng.choice(["mci", "dementia"] if ad else ["pre_cirrhosis", "cirrhosis"])),
        diagnosis_status="confirmed", anchor_date=anchor, diagnosis_known_on=anchor,
        history_coverage="complete", source=_source(),
    ))
    slope_range, amplitude_range = (0.7, 0.25) if ad else (0.45, 0.20)
    noise_range = (0.02, 0.10) if pool == "development_pool" else (0.10, 0.20)
    parameters = {
        "b": float(trajectory_rng.uniform(-1.5, 1.5) if ad else trajectory_rng.uniform(math.log(15), math.log(180))),
        "s": float(trajectory_rng.uniform(-slope_range, slope_range)),
        "a": float(trajectory_rng.uniform(-amplitude_range, amplitude_range)),
        "k": float(trajectory_rng.uniform(-slope_range, slope_range)),
        "c": int(trajectory_rng.integers(60, 241)), "period": int(trajectory_rng.integers(120, 361)),
        "phi": float(trajectory_rng.uniform(0, 2 * math.pi)),
        "sigma": float(trajectory_rng.uniform(*noise_range)),
    }
    mechanism = ("linear", "curved")[index % 2] if pool == "development_pool" else ("piecewise", "periodic")[index % 2]
    observations, reasons = [], []

    def observation(day, role, index_or_horizon, *, status="observed", missing=False, late=False):
        component = f"measurement:{role}:{index_or_horizon}"
        value = None
        if day is not None and status == "observed" and not missing:
            t = (day - anchor).days
            z = parameters["b"] + parameters["s"] * t / 365
            if mechanism == "curved":
                z += parameters["a"] * (t / 365) ** 2
            elif mechanism == "piecewise":
                z += parameters["k"] * max(0, t - parameters["c"]) / 365
            elif mechanism == "periodic":
                z += parameters["a"] * math.sin(2 * math.pi * t / parameters["period"] + parameters["phi"])
            z += float(rng(component).normal(0, parameters["sigma"]))
            value = float(math.floor(30 / (1 + math.exp(-z)) + 0.5)) if ad else round(math.exp(z), 1)
        row = SyntheticObservation(
            observation_id=f"{subject}:{role}:{index_or_horizon}", subject_id=subject,
            indicator="mmse" if ad else "alt", measured_on=day,
            known_on=(anchor + timedelta(days=7) if late else day), value=value,
            unit="分" if ad else "U/L", method="synthetic_fixture", observation_kind="actual",
            role=role, horizon_months=index_or_horizon if role == "followup" else None,
            observation_status=status, source=_source(),
        )
        observations.append(_dump(row))
        if missing or late or status != "observed":
            reasons.append({"observation_id": row.observation_id, "missing_value": missing,
                            "late_available": late, "status": status})

    for index_in_history, day in enumerate(history_days):
        missing_rng = rng(f"missingness:history:{index_in_history}")
        observation(day, "history", index_in_history, missing=bool(missing_rng.random() < 0.1), late=bool(missing_rng.random() < 0.1))
    observation(anchor, "anchor", 0)
    for horizon in (6, 12):
        draw = float(rng(f"missingness:followup:{horizon}").random())
        nominal = add_calendar_months(anchor, horizon)
        if draw < 0.9:
            offset = 0 if draw < 0.7 else -7 if draw < 0.8 else 21
            observation(nominal + timedelta(days=offset), "followup", horizon)
        else:
            observation(None, "followup", horizon, status="confirmed_unobserved" if draw < 0.95 else "pending_observation")
    audit = {"subject_id": subject, "dependency_group_id": patient["dependency_group_id"], "pool": pool,
             "mechanism": mechanism, "parameters": parameters, "missingness": reasons,
             "component_seed_fingerprints": {key: hashlib.sha256(str(_seed(config.seed, disease, pool, index, key)).encode()).hexdigest()
                                             for key in ("profile", "trajectory", "visits", "measurement:anchor:0", "missingness:followup:6", "missingness:followup:12")}}
    return patient, observations, audit


def _group_observations(observations):
    grouped = defaultdict(list)
    seen = defaultdict(list)
    for row in observations:
        key = (row["subject_id"], row["observation_id"])
        if row in seen[key]:
            continue
        seen[key].append(row)
        grouped[row["subject_id"]].append(row)
    return grouped


def _valid_measurement(row, indicator, anchor_date=None):
    value = row.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False
    if value < 0 or (indicator == "mmse" and value > 30):
        return False
    if row.get("indicator") != indicator or _canonical_unit(row, indicator) is None:
        return False
    if row.get("observation_kind") != "actual" or row.get("observation_status") != "observed":
        return False
    if not row.get("measured_on") or not row.get("method"):
        return False
    if row.get("known_on") and row["known_on"] < row["measured_on"]:
        return False
    if anchor_date is not None:
        return bool(row.get("known_on") and row["known_on"] <= anchor_date and row["measured_on"] <= anchor_date)
    return True


def _canonical_unit(row, indicator):
    disease = "ad" if indicator == "mmse" else "fatty_liver"
    units = INDICATOR_CONTRACTS[disease][indicator].units
    raw = row.get("unit")
    if isinstance(raw, str) and raw.strip().casefold() in {unit.casefold() for unit in units}:
        return units[0]
    return None


def build_prediction_inputs(patients: list[dict], observations: list[dict]) -> list[dict]:
    """Only project information actually available by the fixed anchor."""
    grouped, packets = _group_observations(observations), []
    fields = ("observation_id", "indicator", "measured_on", "known_on", "value", "unit", "method")
    for patient in sorted(patients, key=lambda p: p["subject_id"]):
        subject, anchor_date = patient["subject_id"], patient["anchor_date"]
        indicator = "mmse" if patient["disease"] == "ad" else "alt"
        rows = grouped[subject]
        anchors = [r for r in rows if r.get("role") == "anchor" and r.get("measured_on") == anchor_date]
        valid_anchor = len(anchors) == 1 and _valid_measurement(anchors[0], indicator, anchor_date)
        reason = None
        if patient.get("diagnosis_status") != "confirmed":
            reason = "population_not_confirmed"
        elif not patient.get("diagnosis_known_on") or patient["diagnosis_known_on"] > anchor_date:
            reason = "population_not_known_at_anchor"
        elif not valid_anchor:
            reason = "anchor_unavailable"
        history = [r for r in rows if r.get("role") == "history" and r.get("measured_on") and r["measured_on"] < anchor_date]
        eligible_history = [r for r in history if _valid_measurement(r, indicator, anchor_date)
                            and valid_anchor and r["method"] == anchors[0]["method"]]
        history_state = "observed"
        if patient["history_coverage"] != "complete" or len(eligible_history) != len(history):
            history_state = "unknown"
        elif not history:
            history_state = "confirmed_none"
        selected = [*eligible_history, *([anchors[0]] if valid_anchor else [])]
        selected.sort(key=lambda r: (r["measured_on"], r["observation_id"]))
        known_rows = [r for r in rows if r.get("role") in {"history", "anchor"}
                      and r.get("indicator") == indicator and r.get("measured_on")
                      and r["measured_on"] <= anchor_date and r.get("known_on")
                      and r["known_on"] <= anchor_date and r.get("observation_kind") == "actual"]
        duplicate_dates = len({r["measured_on"] for r in known_rows}) != len(known_rows)
        if duplicate_dates:
            reason = "conflicting_history"
            selected = [anchors[0]] if valid_anchor else []
            history_state = "unknown"
        for horizon in (6, 12):
            packets.append(_dump(PredictionInput(
                sample_id=f"{subject}:{horizon}m", subject_id=subject,
                dependency_group_id=patient["dependency_group_id"],
                task_id=f"{patient['disease']}.{indicator}.{horizon}m", horizon_months=horizon,
                anchor_date=anchor_date, anchor_observation_id=anchors[0]["observation_id"] if valid_anchor else None,
                input_observations=[{**{key: deepcopy(r[key]) for key in fields},
                                     "unit": _canonical_unit(r, indicator)} for r in selected],
                input_status="available" if reason is None else "unavailable", input_reason=reason,
                history_coverage=patient["history_coverage"], history_state=history_state, source=patient["source"],
            )))
    return packets


def build_followup_outcomes(patients: list[dict], observations: list[dict]) -> list[dict]:
    grouped, outcomes = _group_observations(observations), []
    for patient in sorted(patients, key=lambda p: p["subject_id"]):
        subject = patient["subject_id"]
        indicator = "mmse" if patient["disease"] == "ad" else "alt"
        anchors = [r for r in grouped[subject] if r.get("role") == "anchor" and r.get("measured_on") == patient["anchor_date"]]
        for horizon in (6, 12):
            nominal = add_calendar_months(date.fromisoformat(patient["anchor_date"]), horizon).isoformat()
            rows = [r for r in grouped[subject] if r.get("role") == "followup" and r.get("horizon_months") == horizon]
            row = rows[0] if len(rows) == 1 else None
            value = None
            if len(rows) > 1:
                status = "conflicting_observations"
            elif row is None or row.get("observation_kind") == "planned":
                status = "pending_observation"
            elif row.get("observation_status") in {"confirmed_unobserved", "pending_observation"}:
                status = row["observation_status"]
            elif len(anchors) != 1 or not anchors[0].get("method") or not row.get("method"):
                status = "pending_comparability"
            elif row["method"] != anchors[0]["method"]:
                status = "incomparable"
            elif not _valid_measurement(row, indicator):
                status = "invalid_observation"
            else:
                value = row["value"]
                status = "fixture_observed_at_nominal" if row["measured_on"] == nominal else "pending_window"
            outcomes.append(_dump(FollowupOutcome(
                sample_id=f"{subject}:{horizon}m", subject_id=subject, horizon_months=horizon,
                nominal_date=nominal, observation_id=row["observation_id"] if row else None,
                actual_date=row.get("measured_on") if row else None, value=value, status=status,
            )))
    return outcomes


def generate_cohort(config: GenerationConfig) -> dict:
    patients, observations, audit = [], [], []
    for disease in ("ad", "fatty_liver"):
        for pool, count in (("development_pool", config.patients_per_disease - config.challenge_per_disease),
                            ("challenge_pool", config.challenge_per_disease)):
            for index in range(count):
                patient, rows, record = _generate_patient(config, disease, pool, index)
                patients.append(patient)
                observations.extend(rows)
                audit.append(record)
    return {"patients": sorted(patients, key=lambda p: p["subject_id"]),
            "observations": sorted(observations, key=lambda o: o["observation_id"]),
            "prediction_inputs": build_prediction_inputs(patients, observations),
            "followup_outcomes": build_followup_outcomes(patients, observations),
            "generation_audit": sorted(audit, key=lambda a: a["subject_id"])}
