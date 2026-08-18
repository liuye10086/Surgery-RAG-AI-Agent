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
ARTIFACT_NAMES = {
    "patients": "patients.csv",
    "visits": "visits.csv",
    "quality": "quality_report.json",
    "provenance": "DATA_PROVENANCE.md",
    "extracted_cases": "extracted_cases.json",
}
DATA_CUTOFF = date(2026, 8, 18)
BASE_GENERATOR_PATH = Path(__file__).with_name("generate_fatty_liver_longitudinal.py")


def _load_base_generator():
    spec = importlib.util.spec_from_file_location(
        "fatty_liver_150_base_generator", BASE_GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {BASE_GENERATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE_GENERATOR = _load_base_generator()


@dataclass(frozen=True)
class ExtensionConfig:
    seed: int = EXTENSION_SEED
    extension_count: int = 150
    progression_count: int = 118
    mixed_count: int = 32
    fatty_liver_count: int = 75
    cirrhosis_count: int = 50
    hcc_count: int = 25


@dataclass
class BaselineData:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    quality: dict[str, Any]
    provenance: str
    extracted_cases: list[dict[str, Any]]


@dataclass(frozen=True)
class FeaturePools:
    progression_patient_ids: tuple[str, ...]
    mixed_patient_ids: tuple[str, ...]
    ages_by_cohort: dict[str, tuple[int, ...]]
    sexes_by_cohort: dict[str, tuple[str, ...]]
    metabolic_reason_pool: tuple[str, ...]
    competing_reason_pool: tuple[str, ...]
    reasons_by_cohort: dict[str, tuple[tuple[str, ...], ...]]


@dataclass(frozen=True)
class SyntheticProfile:
    patient_id: str
    cohort_group: str
    final_stage: str
    age: int
    sex: str
    classification_reasons: tuple[str, ...]
    source_components: dict[str, str]
    outcome_source: str = "generated_stage_assignment"


@dataclass
class ExtensionResult:
    profiles: list[SyntheticProfile]
    extension_patients: list[dict[str, Any]]
    extension_visits: list[dict[str, Any]]
    paths: dict[str, str]
    assigned_path_mismatches: list[dict[str, str]]
    generated_lost_to_followup_ids: list[str]


@dataclass
class CombinedDataset:
    patients: list[dict[str, Any]]
    visits: list[dict[str, Any]]
    extension: ExtensionResult


def load_baseline(baseline_dir: Path) -> BaselineData:
    baseline_dir = Path(baseline_dir)
    with (baseline_dir / ARTIFACT_NAMES["patients"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        patients = list(csv.DictReader(handle))
    with (baseline_dir / ARTIFACT_NAMES["visits"]).open(
        encoding="utf-8", newline=""
    ) as handle:
        visits = list(csv.DictReader(handle))
    quality = json.loads(
        (baseline_dir / ARTIFACT_NAMES["quality"]).read_text(encoding="utf-8")
    )
    provenance = (baseline_dir / ARTIFACT_NAMES["provenance"]).read_text(
        encoding="utf-8"
    )
    extracted_cases = json.loads(
        (baseline_dir / ARTIFACT_NAMES["extracted_cases"]).read_text(
            encoding="utf-8"
        )
    )
    return BaselineData(patients, visits, quality, provenance, extracted_cases)


def baseline_artifact_hashes(baseline_dir: Path) -> dict[str, str]:
    baseline_dir = Path(baseline_dir)
    return {
        name: hashlib.sha256((baseline_dir / filename).read_bytes()).hexdigest()
        for name, filename in ARTIFACT_NAMES.items()
    }


def clone_baseline_rows(
    baseline: BaselineData,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return (
        [dict(row) for row in baseline.patients],
        [dict(row) for row in baseline.visits],
    )


def build_feature_pools(baseline: BaselineData) -> FeaturePools:
    patients_by_id = {row["patient_id"]: row for row in baseline.patients}
    audit = baseline.quality["cohort_classification_reasons"]
    progression_ids: list[str] = []
    mixed_ids: list[str] = []
    reasons_by_cohort: dict[str, list[tuple[str, ...]]] = {
        "fatty_liver_progression": [],
        "mixed": [],
    }
    metabolic: set[str] = set()
    competing: set[str] = set()
    for patient_id in sorted(audit):
        item = audit[patient_id]
        cohort = item["cohort_group"]
        reasons = tuple(sorted(item["reasons"]))
        if cohort == "fatty_liver_progression" and not any(
            reason.startswith("competing_") for reason in reasons
        ):
            progression_ids.append(patient_id)
            reasons_by_cohort[cohort].append(reasons)
        elif cohort == "mixed":
            mixed_ids.append(patient_id)
            reasons_by_cohort[cohort].append(reasons)
        metabolic.update(
            reason for reason in reasons if reason.startswith("metabolic_")
        )
        competing.update(reason for reason in reasons if reason.startswith("competing_"))

    ages_by_cohort = {
        cohort: tuple(
            int(patients_by_id[patient_id]["age"])
            for patient_id in patient_ids
            if patients_by_id[patient_id]["age"] != ""
        )
        for cohort, patient_ids in (
            ("fatty_liver_progression", progression_ids),
            ("mixed", mixed_ids),
        )
    }
    sexes_by_cohort = {
        cohort: tuple(patients_by_id[patient_id]["sex"] for patient_id in patient_ids)
        for cohort, patient_ids in (
            ("fatty_liver_progression", progression_ids),
            ("mixed", mixed_ids),
        )
    }
    return FeaturePools(
        progression_patient_ids=tuple(progression_ids),
        mixed_patient_ids=tuple(mixed_ids),
        ages_by_cohort=ages_by_cohort,
        sexes_by_cohort=sexes_by_cohort,
        metabolic_reason_pool=tuple(sorted(metabolic)),
        competing_reason_pool=tuple(sorted(competing)),
        reasons_by_cohort={
            cohort: tuple(sorted(set(reason_sets)))
            for cohort, reason_sets in reasons_by_cohort.items()
        },
    )


def _shuffled_labels(rng: random.Random, counts: dict[str, int]) -> list[str]:
    labels = [label for label, count in counts.items() for _ in range(count)]
    rng.shuffle(labels)
    return labels


def build_extension_profiles(
    baseline: BaselineData, config: ExtensionConfig
) -> list[SyntheticProfile]:
    if config.progression_count + config.mixed_count != config.extension_count:
        raise ValueError("Extension cohort counts do not match extension_count")
    if (
        config.fatty_liver_count + config.cirrhosis_count + config.hcc_count
        != config.extension_count
    ):
        raise ValueError("Extension stage counts do not match extension_count")

    pools = build_feature_pools(baseline)
    rng = random.Random(config.seed)
    cohort_labels = _shuffled_labels(
        rng,
        {
            "fatty_liver_progression": config.progression_count,
            "mixed": config.mixed_count,
        },
    )
    stage_labels = _shuffled_labels(
        rng,
        {
            "fatty_liver": config.fatty_liver_count,
            "cirrhosis": config.cirrhosis_count,
            "hcc": config.hcc_count,
        },
    )

    profiles: list[SyntheticProfile] = []
    patient_by_id = {row["patient_id"]: row for row in baseline.patients}
    reserved_r1_demographics = {"cirrhosis": 13, "hcc": 5}
    for offset, (cohort, stage) in enumerate(zip(cohort_labels, stage_labels), 151):
        patient_ids = (
            pools.progression_patient_ids
            if cohort == "fatty_liver_progression"
            else pools.mixed_patient_ids
        )
        eligible_demographic_ids = [
            patient_id
            for patient_id in patient_ids
            if patient_by_id[patient_id]["sex"] == "male"
            and int(patient_by_id[patient_id]["age"]) >= 55
        ]
        reserve_r1 = reserved_r1_demographics.get(stage, 0) > 0
        did_reserve_r1 = False
        if reserve_r1 and eligible_demographic_ids:
            demographic_source = rng.choice(eligible_demographic_ids)
            reserved_r1_demographics[stage] -= 1
            did_reserve_r1 = True
        else:
            demographic_source = rng.choice(patient_ids)
        reason_source = rng.choice(patient_ids)
        if len(patient_ids) > 1 and reason_source == demographic_source:
            reason_source = patient_ids[(patient_ids.index(reason_source) + 1) % len(patient_ids)]
        source_age = int(patient_by_id[demographic_source]["age"])
        age = max(16, min(85, source_age + rng.randint(-4, 4)))
        if did_reserve_r1:
            age = max(51, age)
        sex = patient_by_id[demographic_source]["sex"]

        audit_reasons = baseline.quality["cohort_classification_reasons"][reason_source][
            "reasons"
        ]
        if cohort == "fatty_liver_progression":
            metabolic = sorted(
                reason for reason in audit_reasons if reason.startswith("metabolic_")
            )
            if pools.metabolic_reason_pool and rng.random() < 0.45:
                extra = rng.choice(pools.metabolic_reason_pool)
                if extra not in metabolic:
                    metabolic.append(extra)
            reasons = tuple(
                ["documented_fatty_liver", *sorted(metabolic), "eligible_no_competing_etiology"]
            )
        else:
            reasons_list = sorted(
                reason
                for reason in audit_reasons
                if reason != "eligible_no_competing_etiology"
            )
            if not any(reason.startswith("competing_") for reason in reasons_list):
                alternatives = [
                    reason
                    for reason in reasons_list
                    if reason
                    in {
                        "advanced_stage_without_fatty_prephase",
                        "hcc_first_presentation_without_documented_progression",
                        "insufficient_fatty_liver_evidence",
                        "insufficient_patient_level_narrative",
                    }
                ]
                if not alternatives:
                    reasons_list.append(rng.choice(pools.competing_reason_pool))
            reasons = tuple(reasons_list)

        baseline_source = rng.choice(patient_ids)
        profiles.append(
            SyntheticProfile(
                patient_id=f"P{offset:03d}",
                cohort_group=cohort,
                final_stage=stage,
                age=age,
                sex=sex,
                classification_reasons=reasons,
                source_components={
                    "demographics_patient_id": demographic_source,
                    "reason_template_patient_id": reason_source,
                    "baseline_trajectory_patient_id": baseline_source,
                },
            )
        )
    return profiles


def assign_extension_paths(
    profiles: list[SyntheticProfile], rng: random.Random
) -> dict[str, str]:
    paths = {profile.patient_id: "stable" for profile in profiles}
    cirrhosis_r1_candidates = [
        profile
        for profile in profiles
        if profile.final_stage == "cirrhosis"
        and profile.sex == "male"
        and profile.age > 50
    ]
    hcc_r1_candidates = [
        profile
        for profile in profiles
        if profile.final_stage == "hcc"
        and profile.sex == "male"
        and profile.age > 50
    ]
    rng.shuffle(cirrhosis_r1_candidates)
    rng.shuffle(hcc_r1_candidates)
    if len(cirrhosis_r1_candidates) < 13 or len(hcc_r1_candidates) < 5:
        raise ValueError("Insufficient male patients over 50 for approved R1 quotas")
    for profile in cirrhosis_r1_candidates[:8]:
        paths[profile.patient_id] = "r1"
    for profile in cirrhosis_r1_candidates[8:13]:
        paths[profile.patient_id] = "r1_r2"
    for profile in hcc_r1_candidates[:5]:
        paths[profile.patient_id] = "r1_r2"

    hcc_r2_candidates = [
        profile
        for profile in profiles
        if profile.final_stage == "hcc" and paths[profile.patient_id] == "stable"
    ]
    rng.shuffle(hcc_r2_candidates)
    for profile in hcc_r2_candidates[:10]:
        paths[profile.patient_id] = "r2"

    for profile in profiles:
        if profile.final_stage not in {"cirrhosis", "hcc"}:
            continue
        if paths[profile.patient_id] == "stable":
            paths[profile.patient_id] = "non_rule_progression"
    return paths


def _source_baselines(
    baseline: BaselineData, source_patient_id: str
) -> dict[str, float]:
    rows = [
        row for row in baseline.visits if row["patient_id"] == source_patient_id
    ]
    result: dict[str, float] = {}
    for indicator in BASE_GENERATOR.INDICATORS:
        value = next(
            (float(row[indicator]) for row in rows if row[indicator] != ""),
            float(BASE_GENERATOR.DEFAULT_BASELINES[indicator]),
        )
        result[indicator] = value
    return result


def _timeline(rng: random.Random) -> list[date]:
    visit_count = rng.randint(3, 6)
    span_days = rng.randint(730, 1830)
    days_before_cutoff = rng.randint(0, 900)
    last = DATA_CUTOFF - timedelta(days=days_before_cutoff)
    first = last - timedelta(days=span_days)
    internal = sorted(rng.sample(range(1, span_days), visit_count - 2))
    return [first, *(first + timedelta(days=days) for days in internal), last]


def _trajectory_value(
    indicator: str,
    baseline_value: float,
    progress: float,
    index: int,
    visit_count: int,
    path: str,
    stage: str,
    rng: random.Random,
) -> float:
    gentle = {
        "alt": 0.12,
        "ast": 0.16,
        "ggt": 0.18,
        "tbil": 0.15,
        "alb": -0.08,
        "waist": 0.03,
        "bmi": 0.03,
    }
    stage_factor = 0.0 if stage == "fatty_liver" else (0.5 if stage == "cirrhosis" else 0.8)
    value = baseline_value * (1.0 + gentle.get(indicator, 0.0) * stage_factor * progress)
    value += rng.gauss(0.0, max(abs(baseline_value) * 0.025, 0.03))

    tail_position = index - (visit_count - 3)
    if indicator == "hba1c":
        if path in {"r1", "r1_r2"} and tail_position >= 0:
            value = baseline_value + (0.35, 0.85, 1.45)[tail_position]
        else:
            value = baseline_value + (0.10 if index % 2 == 0 else -0.08)
    elif indicator == "plt":
        if path in {"r1", "r1_r2"}:
            if tail_position >= 0:
                value = baseline_value * (0.88, 0.74, 0.62)[tail_position]
            else:
                value = baseline_value * (1.0 - 0.02 * index)
        else:
            value = baseline_value * (1.0 + (0.02, -0.01, 0.01)[index % 3])
    elif indicator == "afp":
        if path in {"r2", "r1_r2"} and tail_position >= 0:
            value = baseline_value + (1.5, 4.5, 10.0)[tail_position]
        else:
            value = baseline_value + (0.2 if index % 2 == 0 else -0.1)
    return value


def generate_extension(
    baseline: BaselineData, config: ExtensionConfig
) -> ExtensionResult:
    profiles = build_extension_profiles(baseline, config)
    rng = random.Random(config.seed + 300)
    paths = assign_extension_paths(profiles, rng)
    patients: list[dict[str, Any]] = []
    visits: list[dict[str, Any]] = []
    lost_ids = sorted(
        profile.patient_id
        for profile in rng.sample(profiles, max(1, config.extension_count // 37))
    )
    lost_set = set(lost_ids)

    for profile in profiles:
        timeline = _timeline(rng)
        path = paths[profile.patient_id]
        source_id = profile.source_components["baseline_trajectory_patient_id"]
        baselines = _source_baselines(baseline, source_id)
        for indicator in baselines:
            baselines[indicator] *= rng.uniform(0.88, 1.12)

        cirrhosis_date = ""
        hcc_date = ""
        if profile.final_stage == "cirrhosis":
            cirrhosis_date = timeline[-2].isoformat()
        elif profile.final_stage == "hcc":
            hcc_date = timeline[-1].isoformat()
            if len(timeline) >= 3 and rng.random() < 0.75:
                cirrhosis_date = timeline[-2].isoformat()
        patients.append(
            {
                "patient_id": profile.patient_id,
                "age": profile.age,
                "sex": profile.sex,
                "cohort_group": profile.cohort_group,
                "fatty_liver_date": timeline[0].isoformat(),
                "final_stage": profile.final_stage,
                "cirrhosis_date": cirrhosis_date,
                "hcc_date": hcc_date,
                "last_followup_date": timeline[-1].isoformat(),
                "lost_to_followup": "yes" if profile.patient_id in lost_set else "no",
            }
        )
        for index, visit_date in enumerate(timeline):
            progress = index / (len(timeline) - 1)
            row: dict[str, Any] = {
                "patient_id": profile.patient_id,
                "visit_date": visit_date.isoformat(),
            }
            for indicator in BASE_GENERATOR.INDICATORS:
                row[indicator] = BASE_GENERATOR._round_value(
                    indicator,
                    _trajectory_value(
                        indicator,
                        baselines[indicator],
                        progress,
                        index,
                        len(timeline),
                        path,
                        profile.final_stage,
                        rng,
                    ),
                )
            visits.append(row)

    r1_ids, r2_ids = BASE_GENERATOR._actual_rule_memberships(patients, visits)
    mismatches: list[dict[str, str]] = []
    for patient_id, path in paths.items():
        if path in {"r1", "r1_r2"} and patient_id not in r1_ids:
            mismatches.append(
                {"patient_id": patient_id, "assigned_path": path, "missing_rule": "r1"}
            )
        if path in {"r2", "r1_r2"} and patient_id not in r2_ids:
            mismatches.append(
                {"patient_id": patient_id, "assigned_path": path, "missing_rule": "r2"}
            )
        if path == "stable" and (patient_id in r1_ids or patient_id in r2_ids):
            mismatches.append(
                {"patient_id": patient_id, "assigned_path": path, "missing_rule": "unexpected_rule"}
            )
    return ExtensionResult(profiles, patients, visits, paths, mismatches, lost_ids)


def build_combined_dataset(
    baseline: BaselineData, config: ExtensionConfig
) -> CombinedDataset:
    patients, visits = clone_baseline_rows(baseline)
    extension = generate_extension(baseline, config)
    patients.extend(dict(row) for row in extension.extension_patients)
    visits.extend(
        dict(row)
        for row in sorted(
            extension.extension_visits,
            key=lambda item: (item["patient_id"], item["visit_date"]),
        )
    )
    return CombinedDataset(patients, visits, extension)


def validate_combined_dataset(
    patients: list[dict[str, Any]],
    visits: list[dict[str, Any]],
    expected_count: int = 300,
) -> dict[str, Any]:
    errors: list[str] = []
    if len(patients) != expected_count:
        errors.append(
            f"patients row count is {len(patients)}, expected {expected_count}"
        )
    expected_ids = [f"P{i:03d}" for i in range(1, expected_count + 1)]
    patient_ids = [row.get("patient_id") for row in patients]
    if patient_ids != expected_ids:
        errors.append(f"patient_id values are not consecutive P001-P{expected_count:03d}")
    allowed = {
        "sex": {"male", "female"},
        "cohort_group": {"fatty_liver_progression", "mixed"},
        "final_stage": {"fatty_liver", "cirrhosis", "hcc"},
        "lost_to_followup": {"yes", "no"},
    }
    by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in visits:
        by_patient[row.get("patient_id", "")].append(row)
    if set(by_patient) - set(patient_ids):
        errors.append("visits contains orphan patient IDs")

    for patient in patients:
        patient_id = patient["patient_id"]
        try:
            age = int(patient["age"])
        except (TypeError, ValueError):
            errors.append(f"{patient_id}: age is not an integer")
            age = -1
        if not 1 <= age <= 85:
            errors.append(f"{patient_id}: age out of range")
        for field_name, values in allowed.items():
            if patient[field_name] not in values:
                errors.append(f"{patient_id}: invalid {field_name}")

        patient_visits = by_patient.get(patient_id, [])
        if not 3 <= len(patient_visits) <= 6:
            errors.append(
                f"{patient_id}: visit count {len(patient_visits)} outside 3-6"
            )
            continue
        try:
            dates = [date.fromisoformat(row["visit_date"]) for row in patient_visits]
        except (TypeError, ValueError):
            errors.append(f"{patient_id}: invalid visit date")
            continue
        if dates != sorted(set(dates)):
            errors.append(f"{patient_id}: visit dates not strictly increasing")
        span_days = (dates[-1] - dates[0]).days
        if span_days < 730:
            errors.append(f"{patient_id}: follow-up span below 24 months")
        if span_days > 1830:
            errors.append(f"{patient_id}: follow-up span above 60 months")
        if dates[-1] > DATA_CUTOFF:
            errors.append(f"{patient_id}: follow-up exceeds data cutoff")
        if patient["last_followup_date"] != dates[-1].isoformat():
            errors.append(f"{patient_id}: last_followup_date mismatch")

        try:
            fatty = date.fromisoformat(patient["fatty_liver_date"])
            cirrhosis = (
                date.fromisoformat(patient["cirrhosis_date"])
                if patient["cirrhosis_date"]
                else None
            )
            hcc = (
                date.fromisoformat(patient["hcc_date"])
                if patient["hcc_date"]
                else None
            )
        except (TypeError, ValueError):
            errors.append(f"{patient_id}: invalid event date")
            continue
        stage = patient["final_stage"]
        if fatty > dates[-1]:
            errors.append(f"{patient_id}: fatty_liver_date after follow-up")
        if stage == "fatty_liver" and (cirrhosis or hcc):
            errors.append(f"{patient_id}: fatty_liver stage has event dates")
        if stage == "cirrhosis" and not (
            cirrhosis and fatty < cirrhosis <= dates[-1] and not hcc
        ):
            errors.append(f"{patient_id}: invalid cirrhosis date logic")
        if stage == "hcc" and not (hcc and fatty < hcc <= dates[-1]):
            errors.append(f"{patient_id}: invalid hcc date logic")
        if cirrhosis and hcc and not cirrhosis < hcc:
            errors.append(f"{patient_id}: cirrhosis_date must precede hcc_date")

        for indicator in ("plt", "hba1c", "afp"):
            count = sum(row[indicator] != "" for row in patient_visits)
            if count < 3:
                errors.append(f"{patient_id}: {indicator} has only {count} values")
        for row in patient_visits:
            for indicator in BASE_GENERATOR.INDICATORS:
                value = row[indicator]
                if value == "":
                    continue
                try:
                    numeric_value = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{patient_id}: {indicator} is not numeric")
                    continue
                low, high = BASE_GENERATOR.SAFETY_BOUNDS[indicator]
                if not low <= numeric_value <= high:
                    errors.append(
                        f"{patient_id}: {indicator}={value} outside bounds"
                    )

    expected_stage_counts = Counter(
        {
            "fatty_liver": expected_count // 2,
            "cirrhosis": expected_count // 3,
            "hcc": expected_count // 6,
        }
    )
    stage_counts = Counter(row["final_stage"] for row in patients)
    if expected_count == 300 and stage_counts != expected_stage_counts:
        errors.append(f"unexpected stage counts: {dict(stage_counts)}")
    if expected_count == 300:
        cohort_counts = Counter(row["cohort_group"] for row in patients)
        expected_cohorts = Counter({"fatty_liver_progression": 236, "mixed": 64})
        if cohort_counts != expected_cohorts:
            errors.append(f"unexpected cohort counts: {dict(cohort_counts)}")
    return {"errors": errors, "error_count": len(errors)}


def _duplicate_groups(signatures: dict[str, tuple[Any, ...]]) -> list[list[str]]:
    groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for patient_id, signature in signatures.items():
        groups[signature].append(patient_id)
    return sorted(
        (sorted(patient_ids) for patient_ids in groups.values() if len(patient_ids) > 1),
        key=lambda patient_ids: patient_ids[0],
    )


def duplicate_signature_report(
    patients: list[dict[str, Any]], visits: list[dict[str, Any]]
) -> dict[str, Any]:
    by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in visits:
        by_patient[row["patient_id"]].append(row)
    patient_signatures: dict[str, tuple[Any, ...]] = {}
    trajectory_signatures: dict[str, tuple[Any, ...]] = {}
    complete_signatures: dict[str, tuple[Any, ...]] = {}
    for patient in patients:
        patient_id = patient["patient_id"]
        patient_signature = tuple(
            str(patient[header])
            for header in BASE_GENERATOR.PATIENT_HEADERS
            if header != "patient_id"
        )
        patient_rows = by_patient[patient_id]
        first_date = date.fromisoformat(patient_rows[0]["visit_date"])
        trajectory_signature = tuple(
            (
                (date.fromisoformat(row["visit_date"]) - first_date).days,
                *(str(row[indicator]) for indicator in BASE_GENERATOR.INDICATORS),
            )
            for row in patient_rows
        )
        patient_signatures[patient_id] = patient_signature
        trajectory_signatures[patient_id] = trajectory_signature
        complete_signatures[patient_id] = (patient_signature, trajectory_signature)
    patient_only = _duplicate_groups(patient_signatures)
    trajectory_only = _duplicate_groups(trajectory_signatures)
    complete = _duplicate_groups(complete_signatures)
    return {
        "patient_only_duplicate_group_count": len(patient_only),
        "trajectory_only_duplicate_group_count": len(trajectory_only),
        "complete_duplicate_groups": complete,
    }


def _sorted_counts(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _quantiles(values: list[float]) -> dict[str, float] | None:
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
        key: round(percentile(fraction), 3)
        for key, fraction in (
            ("min", 0.0),
            ("p25", 0.25),
            ("median", 0.5),
            ("p75", 0.75),
            ("max", 1.0),
        )
    }


def build_quality_report(
    baseline_dir: Path,
    baseline: BaselineData,
    combined: CombinedDataset,
    config: ExtensionConfig,
) -> dict[str, Any]:
    patients = combined.patients
    visits = combined.visits
    extension = combined.extension
    baseline_audit = json.loads(json.dumps(baseline.quality))
    outcome_audit = dict(baseline_audit["outcome_assignment_audit"])
    cohort_audit = dict(baseline_audit["cohort_classification_reasons"])
    source_components: dict[str, dict[str, str]] = {}
    for profile in extension.profiles:
        outcome_audit[profile.patient_id] = {
            "final_stage": profile.final_stage,
            "source": profile.outcome_source,
            "source_case_id": None,
        }
        cohort_audit[profile.patient_id] = {
            "cohort_group": profile.cohort_group,
            "reasons": list(profile.classification_reasons),
            "source_case_id": None,
        }
        source_components[profile.patient_id] = dict(profile.source_components)

    by_patient: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in visits:
        by_patient[row["patient_id"]].append(row)
    spans = [
        (
            date.fromisoformat(rows[-1]["visit_date"])
            - date.fromisoformat(rows[0]["visit_date"])
        ).days
        / 30.4375
        for rows in by_patient.values()
    ]
    missing_rates: dict[str, float] = {}
    indicator_quantiles: dict[str, Any] = {}
    for indicator in BASE_GENERATOR.INDICATORS:
        values = [float(row[indicator]) for row in visits if row[indicator] != ""]
        missing_rates[indicator] = round(1.0 - len(values) / len(visits), 4)
        indicator_quantiles[indicator] = _quantiles(values)

    generated_outcome_ids = {
        stage: sorted(
            profile.patient_id
            for profile in extension.profiles
            if profile.final_stage == stage
        )
        for stage in ("fatty_liver", "cirrhosis", "hcc")
    }
    baseline_generated = baseline_audit.get("generated_outcome_ids", {})
    combined_generated_outcomes = {
        stage: sorted(
            list(baseline_generated.get(stage, [])) + generated_outcome_ids[stage]
        )
        for stage in ("fatty_liver", "cirrhosis", "hcc")
    }
    all_paths = dict(
        baseline_audit.get("path_assignments", {})
        or {
            patient_id: "baseline_audited_path"
            for patient_id in (f"P{i:03d}" for i in range(1, 151))
        }
    )
    all_paths.update(extension.paths)
    extension_path_counts = Counter(extension.paths.values())
    total_path_counts = Counter(baseline.quality["path_counts"])
    total_path_counts.update(extension_path_counts)
    return {
        "seed": config.seed,
        "extension_version": EXTENSION_VERSION,
        "base_generator_version": baseline.quality["generator_version"],
        "baseline_directory": Path(baseline_dir).name,
        "baseline_artifact_hashes": baseline_artifact_hashes(baseline_dir),
        "patient_count": len(patients),
        "visit_count": len(visits),
        "baseline_patient_count": len(baseline.patients),
        "baseline_visit_count": len(baseline.visits),
        "extension_patient_count": len(extension.extension_patients),
        "extension_visit_count": len(extension.extension_visits),
        "baseline_patient_ids": [f"P{i:03d}" for i in range(1, 151)],
        "generated_extension_patient_ids": [f"P{i:03d}" for i in range(151, 301)],
        "stage_counts": _sorted_counts([row["final_stage"] for row in patients]),
        "extension_stage_counts": _sorted_counts(
            [row["final_stage"] for row in extension.extension_patients]
        ),
        "cohort_counts": _sorted_counts([row["cohort_group"] for row in patients]),
        "extension_cohort_counts": _sorted_counts(
            [row["cohort_group"] for row in extension.extension_patients]
        ),
        "cohort_stage_cross_counts": {
            f"{cohort}|{stage}": count
            for (cohort, stage), count in sorted(
                Counter(
                    (row["cohort_group"], row["final_stage"]) for row in patients
                ).items()
            )
        },
        "extension_path_counts": dict(sorted(extension_path_counts.items())),
        "path_counts": dict(sorted(total_path_counts.items())),
        "path_assignments": all_paths,
        "outcome_assignment_audit": outcome_audit,
        "cohort_classification_reasons": cohort_audit,
        "extension_source_components": source_components,
        "generated_outcome_ids": combined_generated_outcomes,
        "extension_generated_outcome_ids": generated_outcome_ids,
        "generated_lost_to_followup_ids": sorted(
            list(baseline.quality["generated_lost_to_followup_ids"])
            + extension.generated_lost_to_followup_ids
        ),
        "extension_generated_lost_to_followup_ids": extension.generated_lost_to_followup_ids,
        "lost_to_followup_counts": _sorted_counts(
            [row["lost_to_followup"] for row in patients]
        ),
        "visit_count_distribution": {
            str(count): occurrences
            for count, occurrences in sorted(
                Counter(len(rows) for rows in by_patient.values()).items()
            )
        },
        "followup_months": _quantiles(spans),
        "missing_rates": missing_rates,
        "indicator_quantiles": indicator_quantiles,
        "actual_rule_signal_counts": BASE_GENERATOR._actual_rule_signal_counts(
            patients, visits
        ),
        "cohort_rule_signal_counts": BASE_GENERATOR._cohort_rule_signal_counts(
            all_paths, patients, visits
        ),
        "assigned_path_mismatches": extension.assigned_path_mismatches,
        "duplicate_check": duplicate_signature_report(patients, visits),
        "embedded_rule_paths": ["r1", "r2", "r1_r2"],
        "intended_use": [
            "data_import_pipeline_testing",
            "rule_mining_workflow_mechanism_validation",
            "ui_and_statistical_function_demonstration",
            "stratified_sensitivity_and_regression_testing",
        ],
        "prohibited_uses": [
            "clinical_rule_discovery_claims",
            "real_world_clinical_evidence_claims",
            "diagnostic_or_treatment_decisions",
            "claims_that_extension_patients_came_from_source_documents",
        ],
        "validation": validate_combined_dataset(patients, visits),
    }


def build_extracted_cases(
    baseline: BaselineData, extension: ExtensionResult
) -> list[dict[str, Any]]:
    records = json.loads(json.dumps(baseline.extracted_cases))
    records.extend(
        {
            "patient_id": profile.patient_id,
            "source_case_id": None,
            "record_type": "stratified_recombination_extension",
            "cohort_group": profile.cohort_group,
            "classification_reasons": list(profile.classification_reasons),
            "source_components": dict(profile.source_components),
            "outcome_source": profile.outcome_source,
            "final_stage": profile.final_stage,
        }
        for profile in extension.profiles
    )
    return records


def build_provenance(report: dict[str, Any]) -> str:
    hashes = "\n".join(
        f"- `{name}`: `{value}`"
        for name, value in sorted(report["baseline_artifact_hashes"].items())
    )
    return f"""# 脂肪肝 300 例纵向数据集来源与使用边界

## 数据构成

- P001–P150：逐行继承已审核的 150 例基线，未修改患者或访视字段。
- P151–P300：使用固定种子 `{report['seed']}` 进行分层重组，独立组合人口学、分类理由、指标基线与纵向轨迹来源。
- 扩展版本：`{report['extension_version']}`；基线生成器版本：`{report['base_generator_version']}`。
- 新增队列：118 例 fatty_liver_progression、32 例 mixed。
- 新增结局：75 例 fatty_liver、50 例 cirrhosis、25 例 hcc，均审计为 generated_stage_assignment。

## 基线五项 SHA-256

{hashes}

## 规则路径

R1、R2 与 R1+R2 是有意植入的流程验证信号；stable 与 non_rule_progression 用于对照和非规则进展。它们只能验证数据导入、规则检测、统计和回归流程，不能解释为从病例中独立发现的临床规律。

## 使用边界

本数据集可用于数据导入、接口、UI、统计、性能、规律挖掘流程机制、分层敏感性和算法回归测试。新增病例不对应新的 DOCX 病例原文，不得声称是恢复的真实随访患者，不得作为真实世界临床证据、诊疗依据或未经说明的临床研究原始数据。
"""


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def generate_and_write(
    baseline_dir: Path,
    output_dir: Path,
    config: ExtensionConfig | None = None,
) -> dict[str, Path]:
    config = config or ExtensionConfig()
    baseline_dir = Path(baseline_dir)
    output_dir = Path(output_dir)
    baseline = load_baseline(baseline_dir)
    combined = build_combined_dataset(baseline, config)
    report = build_quality_report(baseline_dir, baseline, combined, config)
    if report["validation"]["errors"]:
        raise ValueError(f"Combined dataset validation failed: {report['validation']['errors']}")
    if report["assigned_path_mismatches"]:
        raise ValueError(
            f"Extension path validation failed: {report['assigned_path_mismatches']}"
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
        (temporary / ARTIFACT_NAMES["provenance"]).write_text(
            provenance, encoding="utf-8"
        )
        (temporary / ARTIFACT_NAMES["extracted_cases"]).write_text(
            json.dumps(extracted, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        for filename in ARTIFACT_NAMES.values():
            (temporary / filename).replace(output_dir / filename)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return {
        name: output_dir / filename for name, filename in ARTIFACT_NAMES.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extend the reviewed fatty-liver longitudinal dataset to 300 patients."
    )
    parser.add_argument("--baseline-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    paths = generate_and_write(args.baseline_dir, args.output_dir)
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
                "outputs": {name: str(path) for name, path in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
