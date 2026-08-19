from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import random
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


EXTENSION_SEED = 20260819
EXTENSION_VERSION = "1.0.0"
BASE_GENERATOR_PATH = Path(__file__).with_name("generate_ad_longitudinal.py")


def _load_base_generator():
    spec = importlib.util.spec_from_file_location(
        "ad_longitudinal_base_generator", BASE_GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {BASE_GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE_GENERATOR = _load_base_generator()
ARTIFACT_NAMES = BASE_GENERATOR.ARTIFACT_NAMES
APPROVED_BASELINE_HASHES = {
    "patients": "0c3a0b5fb0f27b09f06996d5f40083f3ccde541d8c5721605b5f5d3be1c50b06",
    "visits": "31dc61f540eb1a9d61a9599362d75d33ccbe3b6a229e8529c971e61e65798052",
    "quality": "ee212cb57fdfe4bd7376bc7910ec059a1848e23b2d601e3a29ff0bb7b5769e64",
    "extracted_cases": "4a9132f7365b1cb9262c01bba7fd1d2c063e3d69538902b726d8684560d703c4",
    "provenance": "a2ec9a5ea72b9aea9c5bc64b3e3059f95e3150cb144e8a446c1a4fa8694ee9bb",
}


@dataclass(frozen=True)
class ExtensionConfig:
    seed: int = EXTENSION_SEED
    extension_count: int = 150
    cohort_counts: tuple[tuple[str, int], ...] = (("ad_progression", 124), ("mixed", 26))
    stage_counts: tuple[tuple[str, int], ...] = (
        ("0", 5),
        ("0.5", 10),
        ("1", 55),
        ("2", 45),
        ("3", 35),
    )
    path_counts: tuple[tuple[str, int], ...] = (
        ("r1", 25),
        ("r2", 25),
        ("r1_r2", 25),
        ("non_rule_progression", 45),
        ("stable", 30),
    )


@dataclass
class BaselineData:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    quality: dict[str, Any]
    extracted_cases: list[dict[str, Any]]
    provenance: str


@dataclass(frozen=True)
class FeaturePools:
    patient_ids_by_cohort: dict[str, tuple[str, ...]]
    patient_ids_by_stage: dict[str, tuple[str, ...]]
    classification_reasons_by_cohort: dict[str, tuple[tuple[str, ...], ...]]


@dataclass(frozen=True)
class SyntheticProfile:
    patient_id: str
    cohort_group: str
    final_stage: str
    age: int
    sex: str
    apoe: str
    gene_mutation: str
    classification_reasons: tuple[str, ...]
    source_components: dict[str, str]
    outcome_source: str = "generated_stage_assignment"


@dataclass
class ExtensionResult:
    profiles: list[SyntheticProfile]
    extension_patients: list[dict[str, str]]
    extension_visits: list[dict[str, str]]
    paths: dict[str, str]
    assigned_path_mismatches: list[dict[str, str]]
    generated_lost_to_followup_ids: list[str]


@dataclass
class CombinedDataset:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    extension: ExtensionResult


def load_baseline(baseline_dir: Path) -> BaselineData:
    """Read the five immutable artifacts produced by the original generator."""
    baseline_dir = Path(baseline_dir)
    artifact_names = BASE_GENERATOR.ARTIFACT_NAMES

    try:
        patients_path = baseline_dir / artifact_names["patients"]
        visits_path = baseline_dir / artifact_names["visits"]
        with patients_path.open(encoding="utf-8", newline="") as handle:
            patient_reader = csv.DictReader(handle)
            _require_csv_headers(
                patient_reader.fieldnames, BASE_GENERATOR.PATIENT_HEADERS, patients_path
            )
            patients = list(patient_reader)
        with visits_path.open(encoding="utf-8", newline="") as handle:
            visit_reader = csv.DictReader(handle)
            _require_csv_headers(
                visit_reader.fieldnames, BASE_GENERATOR.VISIT_HEADERS, visits_path
            )
            visits = list(visit_reader)

        quality = json.loads(
            (baseline_dir / artifact_names["quality"]).read_text(encoding="utf-8")
        )
        extracted_cases = json.loads(
            (baseline_dir / artifact_names["extracted_cases"]).read_text(encoding="utf-8")
        )
        provenance = (baseline_dir / artifact_names["provenance"]).read_text(
            encoding="utf-8"
        )
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read baseline artifacts from {baseline_dir}") from error

    _validate_baseline(patients, visits, quality, extracted_cases)
    return BaselineData(
        patients=patients,
        visits=visits,
        quality=quality,
        extracted_cases=extracted_cases,
        provenance=provenance,
    )


def _require_csv_headers(
    actual: list[str] | None, expected: list[str], artifact_path: Path
) -> None:
    if actual != expected:
        raise ValueError(f"Unexpected CSV headers in {artifact_path.name}")


def _validate_baseline(
    patients: list[dict[str, str]],
    visits: list[dict[str, str]],
    quality: dict[str, Any],
    extracted_cases: list[dict[str, Any]],
) -> None:
    expected_ids = [f"P{number:03d}" for number in range(1, 151)]
    actual_ids = [patient.get("patient_id") for patient in patients]
    if actual_ids != expected_ids:
        raise ValueError("Baseline patients must be the continuous range P001 through P150")
    if len(visits) != 672:
        raise ValueError("Baseline visits must contain 672 rows")
    if quality.get("patient_count") != 150:
        raise ValueError("Baseline quality report must record 150 patients")
    if len(extracted_cases) != 150:
        raise ValueError("Baseline extracted cases must contain 150 rows")


def baseline_artifact_hashes(baseline_dir: Path) -> dict[str, str]:
    """Return SHA-256 digests for every original-generator artifact."""
    baseline_dir = Path(baseline_dir)
    try:
        return {
            key: hashlib.sha256((baseline_dir / filename).read_bytes()).hexdigest()
            for key, filename in BASE_GENERATOR.ARTIFACT_NAMES.items()
        }
    except OSError as error:
        raise ValueError(f"Cannot hash baseline artifacts from {baseline_dir}") from error


def clone_baseline_rows(baseline: BaselineData) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return independent row copies suitable for extension-only mutation."""
    return ([dict(row) for row in baseline.patients], [dict(row) for row in baseline.visits])


def build_feature_pools(baseline: BaselineData) -> FeaturePools:
    """Construct independently sampled source pools from the locked baseline audit."""
    outcome_audit = baseline.quality.get("outcome_assignment_audit", {})
    baseline_ids = {patient["patient_id"] for patient in baseline.patients}
    if outcome_audit and set(outcome_audit) != baseline_ids:
        raise ValueError("Baseline outcome audit must cover every patient")
    patient_ids_by_cohort: dict[str, list[str]] = defaultdict(list)
    patient_ids_by_stage: dict[str, list[str]] = defaultdict(list)
    for patient in baseline.patients:
        patient_id = patient["patient_id"]
        patient_ids_by_cohort[patient["cohort_group"]].append(patient_id)
        audited_stage = outcome_audit.get(patient_id, {}).get(
            "assigned_final_stage", patient["final_stage"]
        )
        if audited_stage != patient["final_stage"]:
            raise ValueError("Baseline patient stage conflicts with the outcome audit")
        patient_ids_by_stage[audited_stage].append(patient_id)

    # The audit record, rather than an inferred genetic label, owns cohort rationale.
    reasons_by_id = {
        record["patient_id"]: tuple(record.get("classification_reasons", ()))
        for record in baseline.extracted_cases
    }
    classification_reasons_by_cohort: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for cohort, patient_ids in patient_ids_by_cohort.items():
        for patient_id in patient_ids:
            reasons = reasons_by_id.get(patient_id, ())
            if cohort == "ad_progression":
                # The exceptional B37/C9ORF72 rationale is not a reusable default.
                reasons = tuple(
                    reason for reason in reasons if "c9orf72" not in reason.lower()
                )
            if reasons:
                classification_reasons_by_cohort[cohort].append(reasons)

    return FeaturePools(
        patient_ids_by_cohort={
            cohort: tuple(patient_ids)
            for cohort, patient_ids in patient_ids_by_cohort.items()
        },
        patient_ids_by_stage={
            stage: tuple(patient_ids) for stage, patient_ids in patient_ids_by_stage.items()
        },
        classification_reasons_by_cohort={
            cohort: tuple(reason_sets)
            for cohort, reason_sets in classification_reasons_by_cohort.items()
        },
    )


def _sample_distinct_sources(
    patient_ids: tuple[str, ...], rng: random.Random
) -> dict[str, str]:
    component_names = (
        "demographics_patient_id",
        "static_marker_patient_id",
        "classification_reason_patient_id",
        "baseline_biomarker_patient_id",
        "trajectory_patient_id",
    )
    if not patient_ids:
        raise ValueError("Feature pool cannot be empty")
    selected = list(patient_ids)
    rng.shuffle(selected)
    return {
        name: selected[index % len(selected)]
        for index, name in enumerate(component_names)
    }


def _profile_reasons(
    cohort: str, source_patient_id: str, reasons_by_id: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    reasons = reasons_by_id.get(source_patient_id, ())
    if cohort == "mixed":
        return tuple(sorted(set(reasons) | {"explicit_competing_diagnosis"}))
    reasons = tuple(reason for reason in reasons if reason != "explicit_competing_diagnosis")
    reasons = tuple(reason for reason in reasons if "c9orf72" not in reason.lower())
    return reasons or (
        "documented_or_biomarker_supported_ad",
        "no_primary_competing_diagnosis",
    )


def build_extension_profiles(
    baseline: BaselineData, config: ExtensionConfig
) -> list[SyntheticProfile]:
    """Build 150 independent patient blueprints with locked cohort/stage quotas."""
    pools = build_feature_pools(baseline)
    rng = random.Random(config.seed)
    patients_by_id = {patient["patient_id"]: patient for patient in baseline.patients}
    reasons_by_id = {
        record["patient_id"]: tuple(record.get("classification_reasons", ()))
        for record in baseline.extracted_cases
    }
    cohorts = [
        cohort for cohort, count in config.cohort_counts for _ in range(count)
    ]
    stages = [stage for stage, count in config.stage_counts for _ in range(count)]
    if len(cohorts) != config.extension_count or len(stages) != config.extension_count:
        raise ValueError("Extension quotas must equal extension_count")

    # Shuffle independent label lists so patient IDs do not encode cohort or outcome.
    rng.shuffle(cohorts)
    rng.shuffle(stages)

    profiles: list[SyntheticProfile] = []
    for number, (cohort, stage) in enumerate(zip(cohorts, stages), start=151):
        sources = _sample_distinct_sources(pools.patient_ids_by_cohort[cohort], rng)
        demographic_source = patients_by_id[sources["demographics_patient_id"]]
        static_source = patients_by_id[sources["static_marker_patient_id"]]
        source_age = int(demographic_source["age"])
        profiles.append(
            SyntheticProfile(
                patient_id=f"P{number:03d}",
                cohort_group=cohort,
                final_stage=stage,
                age=max(30, min(100, source_age + rng.randint(-4, 4))),
                sex=demographic_source["sex"],
                apoe=static_source["apoe"],
                gene_mutation=static_source["gene_mutation"],
                classification_reasons=_profile_reasons(
                    cohort,
                    sources["classification_reason_patient_id"],
                    reasons_by_id,
                ),
                source_components=sources,
            )
        )
    return profiles


def assign_extension_paths(
    profiles: list[SyntheticProfile], config: ExtensionConfig
) -> dict[str, str]:
    """Assign fixed path quotas while reserving the approved stable stage mix."""
    if len(profiles) != config.extension_count:
        raise ValueError("Profiles must equal the configured extension count")
    profiles_by_stage: dict[str, list[SyntheticProfile]] = defaultdict(list)
    for profile in profiles:
        profiles_by_stage[profile.final_stage].append(profile)
    stable = list(profiles_by_stage["0"]) + list(profiles_by_stage["0.5"])
    rng = random.Random(config.seed)
    cdr_one = list(profiles_by_stage["1"])
    rng.shuffle(cdr_one)
    stable.extend(cdr_one[:15])
    if Counter(profile.final_stage for profile in stable) != {"0": 5, "0.5": 10, "1": 15}:
        raise ValueError("Stable patients do not meet the approved stage contract")

    remaining = [
        profile
        for profile in profiles
        if profile.patient_id not in {stable_profile.patient_id for stable_profile in stable}
    ]
    if any(profile.final_stage not in {"1", "2", "3"} for profile in remaining):
        raise ValueError("Progression paths require final stage 1, 2, or 3")
    rng.shuffle(remaining)
    path_counts = dict(config.path_counts)
    expected_remaining = sum(
        path_counts[path] for path in ("r1_r2", "r1", "r2", "non_rule_progression")
    )
    if len(remaining) != expected_remaining:
        raise ValueError("Progression path quotas do not cover non-stable profiles")

    paths = {profile.patient_id: "stable" for profile in stable}
    offset = 0
    for path in ("r1_r2", "r1", "r2", "non_rule_progression"):
        for profile in remaining[offset : offset + path_counts[path]]:
            paths[profile.patient_id] = path
        offset += path_counts[path]
    if Counter(paths.values()) != path_counts:
        raise ValueError("Assigned paths do not match the approved quotas")
    return paths


def _timeline(rng: random.Random, minimum_visits: int = 3) -> list[date]:
    visit_count = rng.randint(minimum_visits, 6)
    span_days = rng.randint(730, 1830)
    last = BASE_GENERATOR.DATA_CUTOFF - timedelta(days=rng.randint(0, 900))
    first = last - timedelta(days=span_days)
    internal = sorted(rng.sample(range(1, span_days), visit_count - 2))
    return [first, *(first + timedelta(days=days) for days in internal), last]


def _first_values(
    baseline: BaselineData, patient_id: str, fields: list[str]
) -> dict[str, float]:
    rows = sorted(
        (row for row in baseline.visits if row["patient_id"] == patient_id),
        key=lambda row: row["visit_date"],
    )
    first = rows[0] if rows else {}
    values: dict[str, float] = {}
    for field in fields:
        raw = first.get(field, "")
        if raw != "":
            values[field] = float(raw)
        else:
            low, high = BASE_GENERATOR.SAFETY_BOUNDS[field]
            values[field] = (low + high) / 2
    return values


def _source_baseline(
    baseline: BaselineData, profile: SyntheticProfile
) -> tuple[dict[str, float], dict[str, float]]:
    single = _first_values(
        baseline,
        profile.source_components["baseline_biomarker_patient_id"],
        BASE_GENERATOR.SINGLE_MEASUREMENT_FIELDS,
    )
    trajectory = _first_values(
        baseline,
        profile.source_components["trajectory_patient_id"],
        BASE_GENERATOR.LONGITUDINAL_FIELDS,
    )
    return single, trajectory


def _perturb(name: str, value: float, rng: random.Random, fraction: float = 0.08) -> float:
    return BASE_GENERATOR._clip(name, value * rng.uniform(1 - fraction, 1 + fraction))


def _single_markers(
    source: dict[str, float], path: str, rng: random.Random
) -> dict[str, float]:
    values = {
        field: _perturb(field, source[field], rng)
        for field in BASE_GENERATOR.SINGLE_MEASUREMENT_FIELDS
        if field != "abeta_ratio"
    }
    if path in {"r1", "r1_r2"}:
        values["abeta42"] = min(values["abeta42"], 520.0)
        values["ptau181"] = max(values["ptau181"], 66.0)
    else:
        values["abeta42"] = max(values["abeta42"], 560.0)
    values["abeta_ratio"] = BASE_GENERATOR._clip(
        "abeta_ratio", values["abeta42"] / values["abeta40"]
    )
    return values


def _cdr_values(profile: SyntheticProfile, path: str, count: int) -> list[float]:
    if path == "stable":
        return [float(profile.final_stage)] * count
    return BASE_GENERATOR._cdr_sequence(profile.final_stage, count)


def _cognitive_values(
    source: dict[str, float], path: str, count: int, rng: random.Random
) -> tuple[list[float], list[float]]:
    starts = {
        field: _perturb(field, source[field], rng, 0.04) for field in ("mmse", "moca")
    }
    results: dict[str, list[float]] = {}
    for field in ("mmse", "moca"):
        start = starts[field]
        if path == "stable":
            values = [BASE_GENERATOR._clip(field, start + rng.uniform(-0.6, 0.6)) for _ in range(count)]
            values[0] = start
        else:
            decline = rng.uniform(2.0, 6.0)
            values = [
                BASE_GENERATOR._clip(field, start - decline * index / (count - 1))
                for index in range(count)
            ]
        results[field] = values
    return results["mmse"], results["moca"]


def _inflammation_values(
    source: dict[str, float], path: str, count: int, rng: random.Random
) -> tuple[list[float], list[float], list[float]]:
    gfap_base = _perturb("gfap", source["gfap"], rng)
    crp_base = _perturb("crp", source["crp"], rng)
    hcy_base = _perturb("homocysteine", source["homocysteine"], rng)
    if path in {"r1", "r1_r2"}:
        gfap_base = min(gfap_base, 430.0)
    if path in {"r2", "r1_r2"}:
        hcy_base = min(hcy_base, 35.0)
    gfap = [BASE_GENERATOR._clip("gfap", gfap_base + rng.uniform(-3, 3)) for _ in range(count)]
    crp = [BASE_GENERATOR._clip("crp", crp_base + rng.uniform(-0.2, 0.2)) for _ in range(count)]
    hcy = [BASE_GENERATOR._clip("homocysteine", hcy_base + rng.uniform(-0.3, 0.3)) for _ in range(count)]
    gfap[0], crp[0], hcy[0] = gfap_base, crp_base, hcy_base
    if path in {"r1", "r1_r2"}:
        early_rise = BASE_GENERATOR._clip("gfap", gfap_base + 6.0)
        gfap[1] = early_rise
        tail_start = min(max(gfap[-3], early_rise + 2.0), 460.0)
        gfap[-3:] = [tail_start, tail_start + 15.0, tail_start + 30.0]
    else:
        tail_start = min(gfap[-3], 480.0)
        gfap[-3:] = [tail_start, tail_start + 10.0, tail_start + 5.0]
    if path in {"r2", "r1_r2"}:
        tail_start = min(max(crp[-3], 0.2), 16.0)
        crp[-3:] = [tail_start, tail_start + 1.0, tail_start + 2.0]
        hcy[-1] = BASE_GENERATOR._clip("homocysteine", hcy[0] + 3.0)
    else:
        tail_start = min(max(crp[-3], 0.2), 18.0)
        crp[-3:] = [tail_start, tail_start + 1.0, tail_start + 0.5]
        hcy[-1] = BASE_GENERATOR._clip("homocysteine", hcy[0] - 0.5)
    return gfap, crp, hcy


def generate_extension(
    baseline: BaselineData, config: ExtensionConfig
) -> ExtensionResult:
    profiles = build_extension_profiles(baseline, config)
    paths = assign_extension_paths(profiles, config)
    rng = random.Random(config.seed + 300)
    lost_ids = sorted(
        profile.patient_id
        for profile in rng.sample(profiles, max(1, config.extension_count // 40))
    )
    lost_set = set(lost_ids)
    patients: list[dict[str, str]] = []
    visits: list[dict[str, str]] = []
    for profile in profiles:
        path = paths[profile.patient_id]
        dates = _timeline(rng, minimum_visits=4 if path in {"r1", "r1_r2"} else 3)
        single_source, trajectory_source = _source_baseline(baseline, profile)
        cdrs = _cdr_values(profile, path, len(dates))
        mmse, moca = _cognitive_values(trajectory_source, path, len(dates), rng)
        gfap, crp, hcy = _inflammation_values(trajectory_source, path, len(dates), rng)
        single = _single_markers(single_source, path, rng)
        patient_rows: list[dict[str, str]] = []
        for index, visit_date in enumerate(dates):
            row = {header: "" for header in BASE_GENERATOR.VISIT_HEADERS}
            row.update(
                {
                    "patient_id": profile.patient_id,
                    "visit_date": visit_date.isoformat(),
                    "cdr": BASE_GENERATOR._format_number(cdrs[index], 1),
                    "mmse": BASE_GENERATOR._format_number(mmse[index], 1),
                    "moca": BASE_GENERATOR._format_number(moca[index], 1),
                    "gfap": BASE_GENERATOR._format_number(gfap[index], 1),
                    "crp": BASE_GENERATOR._format_number(crp[index], 2),
                    "homocysteine": BASE_GENERATOR._format_number(hcy[index], 2),
                }
            )
            if index == 0:
                for field, value in single.items():
                    row[field] = BASE_GENERATOR._format_number(
                        value, 4 if field == "abeta_ratio" else 2
                    )
            patient_rows.append(row)
        visits.extend(patient_rows)
        reached = [row["visit_date"] for row in patient_rows if float(row["cdr"]) >= 1]
        patients.append(
            {
                "patient_id": profile.patient_id,
                "age": str(profile.age),
                "sex": profile.sex,
                "cohort_group": profile.cohort_group,
                "apoe": profile.apoe,
                "gene_mutation": profile.gene_mutation,
                "final_stage": profile.final_stage,
                "dementia_date": reached[0] if reached else "",
                "last_followup_date": patient_rows[-1]["visit_date"],
                "lost_to_followup": "yes" if profile.patient_id in lost_set else "no",
            }
        )
    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in visits:
        by_patient[row["patient_id"]].append(row)
    mismatches = [
        {
            "patient_id": patient_id,
            "assigned_path": assigned,
            "detected_path": BASE_GENERATOR.detect_rule_path(by_patient[patient_id]),
        }
        for patient_id, assigned in paths.items()
        if BASE_GENERATOR.detect_rule_path(by_patient[patient_id]) != assigned
    ]
    return ExtensionResult(profiles, patients, visits, paths, mismatches, lost_ids)


def build_combined_dataset(
    baseline: BaselineData, config: ExtensionConfig
) -> CombinedDataset:
    """Append a deterministic extension without mutating any baseline row."""
    patients, visits = clone_baseline_rows(baseline)
    extension = generate_extension(baseline, config)
    patients.extend(dict(row) for row in extension.extension_patients)
    visits.extend(
        dict(row)
        for row in sorted(
            extension.extension_visits,
            key=lambda row: (row["patient_id"], row["visit_date"]),
        )
    )
    return CombinedDataset(patients, visits, extension)


def validate_combined_dataset(
    patients: list[dict[str, str]],
    visits: list[dict[str, str]],
    paths: dict[str, str],
) -> dict[str, object]:
    """Validate the complete 300-patient contract independently of the base validator."""
    errors: list[str] = []
    expected_ids = [f"P{i:03d}" for i in range(1, 301)]
    patient_ids = [row.get("patient_id", "") for row in patients]
    if patient_ids != expected_ids:
        errors.append("patient_ids_not_continuous")
    if len(patients) != 300:
        errors.append(f"patient_count={len(patients)}")
    if Counter(row.get("final_stage", "") for row in patients) != Counter(
        {"0": 10, "0.5": 20, "1": 110, "2": 90, "3": 70}
    ):
        errors.append("stage_distribution_mismatch")
    if Counter(row.get("cohort_group", "") for row in patients) != Counter(
        {"ad_progression": 248, "mixed": 52}
    ):
        errors.append("cohort_distribution_mismatch")

    if set(paths) != set(expected_ids):
        errors.append("path_patient_ids_mismatch")
    if Counter(paths.values()) != Counter(
        {
            "r1": 50,
            "r2": 50,
            "r1_r2": 50,
            "non_rule_progression": 90,
            "stable": 60,
        }
    ):
        errors.append("path_distribution_mismatch")

    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in visits:
        patient_id = row.get("patient_id", "")
        by_patient[patient_id].append(row)
        if patient_id not in expected_ids:
            errors.append(f"orphan_visit:{patient_id or '<empty>'}")
        for field, (low, high) in BASE_GENERATOR.SAFETY_BOUNDS.items():
            raw = row.get(field, "")
            if raw == "":
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                errors.append(f"numeric:{patient_id}:{field}:{raw}")
                continue
            if not low <= value <= high:
                errors.append(f"safety_bound:{patient_id}:{field}:{value}")

    patient_map = {
        row.get("patient_id", ""): row
        for row in patients
        if row.get("patient_id", "")
    }
    for patient_id in expected_ids:
        input_rows = by_patient.get(patient_id, [])
        input_date_values = [row.get("visit_date", "") for row in input_rows]
        if input_date_values != sorted(input_date_values):
            errors.append(f"visit_order:{patient_id}")
        rows = sorted(input_rows, key=lambda row: row.get("visit_date", ""))
        if not 3 <= len(rows) <= 6:
            errors.append(f"visit_count:{patient_id}:{len(rows)}")
            continue
        try:
            dates = [date.fromisoformat(row.get("visit_date", "")) for row in rows]
        except (TypeError, ValueError):
            errors.append(f"visit_dates:{patient_id}")
            continue
        if dates != sorted(set(dates)):
            errors.append(f"visit_dates:{patient_id}")
        span = (dates[-1] - dates[0]).days
        if not 730 <= span <= 1830:
            errors.append(f"visit_span:{patient_id}:{span}")
        if dates[-1] > BASE_GENERATOR.DATA_CUTOFF:
            errors.append(f"cutoff:{patient_id}")

        for field in BASE_GENERATOR.LONGITUDINAL_FIELDS:
            if sum(row.get(field, "") != "" for row in rows) < 3:
                errors.append(f"longitudinal_missing:{patient_id}:{field}")
        for field in BASE_GENERATOR.SINGLE_MEASUREMENT_FIELDS:
            if rows[0].get(field, "") == "" or any(
                row.get(field, "") != "" for row in rows[1:]
            ):
                errors.append(f"single_measurement:{patient_id}:{field}")

        patient = patient_map.get(patient_id)
        if patient is None:
            errors.append(f"missing_patient:{patient_id}")
            continue
        if rows[-1].get("cdr", "") != patient.get("final_stage", ""):
            errors.append(f"final_stage:{patient_id}")
        try:
            reached = [
                row["visit_date"] for row in rows if float(row.get("cdr", "")) >= 1
            ]
        except (TypeError, ValueError):
            errors.append(f"cdr_numeric:{patient_id}")
            reached = []
        if patient.get("dementia_date", "") != (reached[0] if reached else ""):
            errors.append(f"dementia_date:{patient_id}")
        if patient.get("last_followup_date", "") != rows[-1].get("visit_date", ""):
            errors.append(f"last_followup:{patient_id}")
        if patient_id in paths:
            try:
                cdr_values = [float(row.get("cdr", "")) for row in rows]
            except (TypeError, ValueError):
                cdr_values = []
            if cdr_values:
                invalid_cdrs = [
                    value for value in cdr_values if value not in {0.0, 0.5, 1.0, 2.0, 3.0}
                ]
                for value in invalid_cdrs:
                    errors.append(f"cdr_value:{patient_id}:{value:g}")
                if paths[patient_id] == "stable":
                    if len(set(cdr_values)) != 1:
                        errors.append(f"stable_cdr:{patient_id}")
                elif any(
                    current < previous
                    for previous, current in zip(cdr_values, cdr_values[1:])
                ):
                    errors.append(f"cdr_monotonic:{patient_id}")
            try:
                detected = BASE_GENERATOR.detect_rule_path(rows)
            except (KeyError, TypeError, ValueError, IndexError):
                errors.append(f"path_detection:{patient_id}")
            else:
                if detected != paths[patient_id]:
                    errors.append(f"path:{patient_id}:{paths[patient_id]}:{detected}")

    return {"errors": errors, "error_count": len(errors)}


def duplicate_signature_report(
    patients: list[dict[str, str]], visits: list[dict[str, str]]
) -> dict[str, object]:
    """Report complete patient-plus-ordered-visit duplicates, ignoring identity only."""
    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for visit in visits:
        by_patient[visit.get("patient_id", "")].append(visit)

    groups: dict[tuple[object, ...], list[str]] = defaultdict(list)
    patient_fields = [
        field for field in BASE_GENERATOR.PATIENT_HEADERS if field != "patient_id"
    ]
    visit_fields = [
        field for field in BASE_GENERATOR.VISIT_HEADERS if field != "patient_id"
    ]
    for patient in patients:
        patient_id = patient.get("patient_id", "")
        ordered_visits = sorted(
            by_patient.get(patient_id, []), key=lambda row: row.get("visit_date", "")
        )
        patient_signature = tuple(patient.get(field, "") for field in patient_fields)
        visit_signature = tuple(
            tuple(visit.get(field, "") for field in visit_fields)
            for visit in ordered_visits
        )
        groups[(patient_signature, visit_signature)].append(patient_id)

    duplicate_groups = [
        sorted(patient_ids)
        for patient_ids in groups.values()
        if len(patient_ids) > 1
    ]
    duplicate_groups.sort()
    return {"complete_duplicate_groups": duplicate_groups}


def _sorted_counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _summary(values: list[float]) -> dict[str, float] | None:
    if not values:
        return None
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {
        name: round(percentile(fraction), 6)
        for name, fraction in (
            ("min", 0.0),
            ("p25", 0.25),
            ("median", 0.5),
            ("p75", 0.75),
            ("max", 1.0),
        )
    }


def _dataset_summary(
    patients: list[dict[str, str]],
    visits: list[dict[str, str]],
    paths: dict[str, str],
) -> dict[str, Any]:
    patient_ids = {row["patient_id"] for row in patients}
    selected_visits = [row for row in visits if row["patient_id"] in patient_ids]
    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in selected_visits:
        by_patient[row["patient_id"]].append(row)
    visit_counts = [len(rows) for rows in by_patient.values()]
    spans = [
        (
            date.fromisoformat(max(row["visit_date"] for row in rows))
            - date.fromisoformat(min(row["visit_date"] for row in rows))
        ).days
        for rows in by_patient.values()
        if rows
    ]
    numeric_summary: dict[str, dict[str, float] | None] = {}
    missing_rates: dict[str, float] = {}
    numeric_fields = [
        field
        for field in BASE_GENERATOR.VISIT_HEADERS
        if field not in {"patient_id", "visit_date"}
    ]
    for field in numeric_fields:
        values = [float(row[field]) for row in selected_visits if row[field] != ""]
        numeric_summary[field] = _summary(values)
        missing_rates[field] = round(
            1.0 - len(values) / len(selected_visits), 6
        ) if selected_visits else 0.0
    return {
        "patient_count": len(patients),
        "visit_count": len(selected_visits),
        "stage_counts": _sorted_counts([row["final_stage"] for row in patients]),
        "cohort_counts": _sorted_counts([row["cohort_group"] for row in patients]),
        "path_counts": _sorted_counts(
            [paths[patient_id] for patient_id in sorted(patient_ids)]
        ),
        "lost_to_followup_counts": _sorted_counts(
            [row["lost_to_followup"] for row in patients]
        ),
        "missing_rate_by_field": missing_rates,
        "numeric_summary": numeric_summary,
        "visit_count_distribution": {
            str(count): occurrences
            for count, occurrences in sorted(Counter(visit_counts).items())
        },
        "visit_count_summary": _summary([float(value) for value in visit_counts]),
        "followup_span_days_summary": _summary([float(value) for value in spans]),
    }


def build_quality_report(
    baseline_dir: Path,
    baseline: BaselineData,
    combined: CombinedDataset,
    config: ExtensionConfig,
) -> dict[str, Any]:
    """Build the complete audit record for the immutable baseline plus extension."""
    baseline_paths = {
        patient_id: audit["assigned_path"]
        for patient_id, audit in baseline.quality["path_assignment_audit"].items()
    }
    all_paths = {**baseline_paths, **combined.extension.paths}
    by_patient: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in combined.visits:
        by_patient[row["patient_id"]].append(row)
    path_audit = {
        patient_id: {
            "assigned_path": assigned_path,
            "detected_path": BASE_GENERATOR.detect_rule_path(by_patient[patient_id]),
        }
        for patient_id, assigned_path in sorted(all_paths.items())
    }
    path_mismatches = [
        {"patient_id": patient_id, **audit}
        for patient_id, audit in path_audit.items()
        if audit["assigned_path"] != audit["detected_path"]
    ]
    validation = validate_combined_dataset(
        combined.patients, combined.visits, all_paths
    )
    duplicates = duplicate_signature_report(combined.patients, combined.visits)
    baseline_summary = _dataset_summary(
        baseline.patients, baseline.visits, baseline_paths
    )
    extension_summary = _dataset_summary(
        combined.extension.extension_patients,
        combined.extension.extension_visits,
        combined.extension.paths,
    )
    overall_summary = _dataset_summary(
        combined.patients, combined.visits, all_paths
    )
    extension_outcomes = {
        profile.patient_id: {
            "source": profile.outcome_source,
            "assigned_final_stage": profile.final_stage,
        }
        for profile in combined.extension.profiles
    }
    extension_sources = {
        profile.patient_id: dict(profile.source_components)
        for profile in combined.extension.profiles
    }
    return {
        "baseline_directory": Path(baseline_dir).name,
        "baseline_artifact_sha256": baseline_artifact_hashes(baseline_dir),
        "baseline_generator_version": baseline.quality["generator_version"],
        "extension_version": EXTENSION_VERSION,
        "extension_seed": config.seed,
        "patient_count": overall_summary["patient_count"],
        "visit_count": overall_summary["visit_count"],
        "baseline_patient_count": baseline_summary["patient_count"],
        "baseline_visit_count": baseline_summary["visit_count"],
        "extension_patient_count": extension_summary["patient_count"],
        "extension_visit_count": extension_summary["visit_count"],
        "stage_counts": overall_summary["stage_counts"],
        "cohort_counts": overall_summary["cohort_counts"],
        "path_counts": overall_summary["path_counts"],
        "baseline_stage_counts": baseline_summary["stage_counts"],
        "baseline_cohort_counts": baseline_summary["cohort_counts"],
        "baseline_path_counts": baseline_summary["path_counts"],
        "extension_stage_counts": extension_summary["stage_counts"],
        "extension_cohort_counts": extension_summary["cohort_counts"],
        "extension_path_counts": extension_summary["path_counts"],
        "dataset_summaries": {
            "baseline": baseline_summary,
            "extension": extension_summary,
            "overall": overall_summary,
        },
        "baseline_patient_ids": [f"P{i:03d}" for i in range(1, 151)],
        "generated_extension_patient_ids": [f"P{i:03d}" for i in range(151, 301)],
        "path_assignment_audit": path_audit,
        "extension_outcome_assignment_audit": extension_outcomes,
        "extension_source_components": extension_sources,
        "generated_lost_to_followup_ids": sorted(
            row["patient_id"]
            for row in combined.patients
            if row["lost_to_followup"] == "yes"
        ),
        "extension_generated_lost_to_followup_ids": (
            combined.extension.generated_lost_to_followup_ids
        ),
        "duplicate_check": duplicates,
        "allowed_uses": [
            "data_import_pipeline_testing",
            "rule_detection_mechanism_validation",
            "statistical_and_ui_regression_testing",
            "synthetic_longitudinal_workflow_demonstration",
        ],
        "prohibited_uses": [
            "real_world_clinical_evidence_claims",
            "diagnostic_or_treatment_decisions",
            "unlabelled_clinical_research_source_data",
            "claims_that_extension_patients_came_from_new_case_documents",
            "claims_that_r1_or_r2_are_independent_clinical_discoveries",
        ],
        "validation": validation,
        "assigned_path_mismatches": path_mismatches,
    }


def build_extracted_cases(
    baseline: BaselineData, extension: ExtensionResult
) -> list[dict[str, Any]]:
    """Deep-copy baseline audit rows and append extension-only source audits."""
    records = json.loads(json.dumps(baseline.extracted_cases, ensure_ascii=False))
    records.extend(
        {
            "patient_id": profile.patient_id,
            "source_case_id": None,
            "record_type": "stratified_recombination_extension",
            "cohort_group": profile.cohort_group,
            "classification_reasons": list(profile.classification_reasons),
            "apoe": profile.apoe,
            "gene_mutation": profile.gene_mutation,
            "assigned_final_stage": profile.final_stage,
            "assigned_path": extension.paths[profile.patient_id],
            "outcome_source": profile.outcome_source,
            "source_components": dict(profile.source_components),
        }
        for profile in extension.profiles
    )
    return records


def build_provenance(report: dict[str, Any]) -> str:
    """Describe synthetic construction and the non-clinical evidence boundary."""
    hashes = "\n".join(
        f"- `{name}`: SHA-256 `{digest}`"
        for name, digest in sorted(report["baseline_artifact_sha256"].items())
    )
    return f"""# AD 300 例纵向数据集来源与使用边界

## 数据构成

- P001–P150：逐行、逐字段继承已审核的 150 例基线，患者与访视记录未修改。
- P151–P300：使用固定种子 `{report['extension_seed']}` 进行分层重组，独立组合人口学、静态标志、分类理由、基线指标与轨迹来源。
- 扩展器版本：`{report['extension_version']}`；基线生成器版本：`{report['baseline_generator_version']}`。
- 新增 CDR：0=5、0.5=10、1=55、2=45、3=35。
- 新增队列：ad_progression=124、mixed=26。
- 新增路径：R1=25、R2=25、R1+R2=25、non_rule_progression=45、stable=30。

## 基线五项 SHA-256

{hashes}

## 规则信号边界

R1、R2 与 R1+R2 是为数据导入、规则检测与回归流程验证而有意植入的合成信号，不是从新增病例文档中独立发现的临床规律，也不得被解释为新的因果关系或通用临床阈值。

## 允许用途与禁止用途

本数据集可用于导入、接口、UI、统计、规则检测机制、敏感性和算法回归测试。P151–P300 不对应新的病例原文或真实随访，不得声称来自新增 Word 病例，不得作为真实世界临床证据、诊疗依据或未经说明的临床研究原始数据。
"""


def _write_csv(
    path: Path, headers: list[str], rows: list[dict[str, str]]
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_and_write(
    baseline_dir: Path,
    output_dir: Path,
    config: ExtensionConfig | None = None,
) -> dict[str, Path]:
    """Generate, gate, and atomically publish all five extension artifacts."""
    config = config or ExtensionConfig()
    baseline_dir = Path(baseline_dir)
    output_dir = Path(output_dir)
    actual_hashes = baseline_artifact_hashes(baseline_dir)
    if actual_hashes != APPROVED_BASELINE_HASHES:
        mismatched = sorted(
            key
            for key in APPROVED_BASELINE_HASHES
            if actual_hashes.get(key) != APPROVED_BASELINE_HASHES[key]
        )
        raise ValueError(
            "Baseline artifacts do not match the approved AD150 hashes: "
            + ", ".join(mismatched)
        )
    baseline = load_baseline(baseline_dir)
    combined = build_combined_dataset(baseline, config)
    report = build_quality_report(baseline_dir, baseline, combined, config)
    if report["validation"]["errors"]:
        raise ValueError(
            f"Combined dataset validation failed: {report['validation']['errors']}"
        )
    if report["assigned_path_mismatches"]:
        raise ValueError(
            "Path assignment validation failed: "
            f"{report['assigned_path_mismatches']}"
        )
    if report["duplicate_check"]["complete_duplicate_groups"]:
        raise ValueError(
            f"Complete duplicate patients detected: {report['duplicate_check']}"
        )
    extracted = build_extracted_cases(baseline, combined.extension)
    provenance = build_provenance(report)

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent)
    )
    try:
        _write_csv(
            temporary / ARTIFACT_NAMES["patients"],
            BASE_GENERATOR.PATIENT_HEADERS,
            combined.patients,
        )
        _write_csv(
            temporary / ARTIFACT_NAMES["visits"],
            BASE_GENERATOR.VISIT_HEADERS,
            combined.visits,
        )
        (temporary / ARTIFACT_NAMES["quality"]).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / ARTIFACT_NAMES["extracted_cases"]).write_text(
            json.dumps(extracted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (temporary / ARTIFACT_NAMES["provenance"]).write_text(
            provenance, encoding="utf-8"
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in ARTIFACT_NAMES.values():
            (temporary / filename).replace(output_dir / filename)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {key: output_dir / filename for key, filename in ARTIFACT_NAMES.items()}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extend the reviewed AD longitudinal dataset to 300 patients."
    )
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=EXTENSION_SEED)
    args = parser.parse_args()
    paths = generate_and_write(
        args.baseline_dir, args.output_dir, ExtensionConfig(seed=args.seed)
    )
    report = json.loads(paths["quality"].read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "patient_count": report["patient_count"],
                "extension_patient_count": report["extension_patient_count"],
                "stage_counts": report["stage_counts"],
                "extension_stage_counts": report["extension_stage_counts"],
                "cohort_counts": report["cohort_counts"],
                "extension_cohort_counts": report["extension_cohort_counts"],
                "validation_error_count": report["validation"]["error_count"],
                "outputs": {key: str(path) for key, path in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
