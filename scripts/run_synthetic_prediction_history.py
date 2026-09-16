"""Run and independently verify the frozen synthetic history experiment."""

import argparse
from datetime import datetime, timezone
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.synthetic_prediction_cases import GenerationConfig
from app.services.synthetic_prediction_cases import canonical_json, generate_cohort
from app.services.synthetic_prediction_quality import assess_cohort
from app.services.prediction_calculation import build_engineering_samples, predict_baselines
from app.services.prediction_stability import build_partitions
from app.services.prediction_candidate_export import _runtime
from app.services.prediction_history_features import project_history_features
from app.services.prediction_history_training import fit_history_models, predict_history_models
from app.services.prediction_history_evaluation import evaluate_history_role, aggregate_history_runs


PROTOCOL = {
    "version": "synthetic_prediction_history.v1",
    "seeds": [20260914, 20260915, 20260916],
    "patients_per_disease": 1200,
    "challenge_per_disease": 400,
    "training_groups_per_disease": 640,
    "validation_fraction": 0.2,
    "roles": ["training", "internal_validation", "challenge"],
    "model_families": ["ridge", "random_forest"],
    "branches": ["anchor_all", "anchor_history", "schedule_history", "value_history", "value_schedule_history"],
    "branch_features": {
        "anchor_all": ["anchor_value"],
        "anchor_history": ["anchor_value"],
        "schedule_history": ["anchor_value", "n_pre", "span_pre_days"],
        "value_history": ["anchor_value", "prior_value", "slope_per_day"],
        "value_schedule_history": ["anchor_value", "prior_value", "slope_per_day", "n_pre", "span_pre_days"],
    },
    "standardization": "training_population_mean_std_ddof0_constant_scale_one",
    "ridge_parameters": {"alpha": 1.0, "fit_intercept": True, "solver": "svd", "positive": False, "copy_X": True},
    "random_forest_parameters": {
        "n_estimators": 200, "criterion": "squared_error", "max_depth": 4,
        "min_samples_split": 2, "min_samples_leaf": 3, "max_features": 1.0,
        "bootstrap": True, "oob_score": False, "random_state": 20260914,
        "n_jobs": 1, "warm_start": False,
    },
    "model_attempts_per_seed": 40,
    "comparisons_per_role_per_seed": 160,
    "bootstrap_iterations": 2000,
    "bootstrap_seed": 20260910,
    "bootstrap_confidence_level": 0.95,
    "automatic_retries": 0,
    "failure_verification": "rebuild_inputs_do_not_retry_fit_errors",
    "clinical_status": "not_assessable",
    "clinical_validity_claim": False,
    "model_publication": False,
    "is_test_fixture": False,
    "test_fixture_purpose": None,
}

CODE_FILES = (
    "backend/app/schemas/synthetic_prediction_cases.py",
    "backend/app/services/synthetic_prediction_cases.py",
    "backend/app/services/synthetic_prediction_fixtures.py",
    "backend/app/services/synthetic_prediction_quality.py",
    "backend/app/services/indicator_validation.py",
    "backend/app/services/prediction_calculation.py",
    "backend/app/services/prediction_calculation_metrics.py",
    "backend/app/services/prediction_stability.py",
    "backend/app/services/prediction_candidate_export.py",
    "backend/app/services/prediction_history_features.py",
    "backend/app/services/prediction_history_training.py",
    "backend/app/services/prediction_history_evaluation.py",
    "scripts/run_synthetic_prediction_history.py",
)


def _hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _envelope():
    return {
        "protocol": copy.deepcopy(PROTOCOL),
        "runtime": _runtime(),
        "code_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES},
    }


def _is_reparse(path):
    try:
        return bool(getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError:
        return False


def _validate_new_output(path):
    path = Path(path).absolute()
    if path.exists():
        raise FileExistsError("output_exists")
    existing = path.parent
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    for ancestor in (existing, *existing.parents):
        if ancestor.is_symlink() or _is_reparse(ancestor):
            raise ValueError("unsafe_output_path")
        if (ancestor / "manifest.json").exists() or (ancestor / "protocol.json").exists():
            raise ValueError("output_inside_artifact")
    resolved = path.resolve(strict=False)
    root = ROOT.resolve()
    if resolved.is_relative_to(root):
        allowed = (root / "outputs" / "synthetic-prediction-history").resolve()
        if resolved == allowed or not resolved.is_relative_to(allowed):
            raise ValueError("output_outside_allowed_tree")
    return path


def _write(directory, name, value, *, text=False):
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value if text else canonical_json(value) + "\n")


def _read(path):
    value = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite_json")))
    def validate(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("nonfinite_json")
        if isinstance(item, dict):
            for key, nested in item.items():
                if not isinstance(key, str):
                    raise ValueError("invalid_json_key")
                validate(nested)
        elif isinstance(item, list):
            for nested in item:
                validate(nested)
    validate(value)
    return value


def _same(left, right):
    return canonical_json(left) == canonical_json(right)


def _file_records(directory):
    records = {}
    for current, dirs, files in os.walk(directory, followlinks=False):
        base = Path(current)
        for name in dirs:
            child = base / name
            if child.is_symlink() or _is_reparse(child):
                raise ValueError("unsafe_artifact")
        for name in files:
            path = base / name
            if path.is_symlink() or _is_reparse(path):
                raise ValueError("unsafe_artifact")
            if path != directory / "manifest.json":
                raw = path.read_bytes()
                records[path.relative_to(directory).as_posix()] = {
                    "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)
                }
    return dict(sorted(records.items()))


def _source(seed):
    config = GenerationConfig(
        seed=seed,
        patients_per_disease=PROTOCOL["patients_per_disease"],
        challenge_per_disease=PROTOCOL["challenge_per_disease"],
    )
    cohort = generate_cohort(config)
    quality = assess_cohort(cohort)
    return cohort, quality


def _prepared(seed, cohort):
    raw_samples = build_engineering_samples(
        cohort["patients"], cohort["prediction_inputs"], cohort["followup_outcomes"], cohort["generation_audit"]
    )
    raw_features = project_history_features(cohort["prediction_inputs"])
    feature_ids = {row["sample_id"] for row in raw_features}
    sample_ids = {row["sample_id"] for row in raw_samples}
    if len(feature_ids) != len(raw_features) or feature_ids != sample_ids:
        raise ValueError("source_identity_mismatch")
    partitions = build_partitions(
        raw_samples, seed,
        train_group_sizes=(PROTOCOL["training_groups_per_disease"],),
        validation_fraction=PROTOCOL["validation_fraction"],
    )
    group_roles = {}
    selections = {
        "training": partitions["training_groups"][str(PROTOCOL["training_groups_per_disease"])],
        "internal_validation": partitions["validation_groups"],
        "challenge": partitions["challenge_groups"],
    }
    for role, groups in selections.items():
        for group in groups:
            if group in group_roles:
                raise ValueError("overlapping_partitions")
            group_roles[group] = role
    if {row["dependency_group_id"] for row in raw_samples} != set(group_roles):
        raise ValueError("incomplete_partitions")
    sample_by_id = {row["sample_id"]: row for row in raw_samples}
    features, samples = [], []
    for feature in raw_features:
        sample = sample_by_id[feature["sample_id"]]
        identity = ("subject_id", "dependency_group_id", "task_id", "horizon_months", "anchor_date", "source")
        if any(feature.get(key) != sample.get(key) for key in identity):
            raise ValueError("source_identity_mismatch")
        role = group_roles[feature["dependency_group_id"]]
        pool = "challenge_pool" if role == "challenge" else "development_pool"
        if sample.get("pool") != pool:
            raise ValueError("partition_pool_mismatch")
        features.append({**feature, "pool": pool, "evaluation_role": role})
        samples.append({
            **sample, "pool": pool, "evaluation_role": role,
            "history_status": feature["history_status"], "history_reason": feature["history_reason"],
        })
    return partitions, features, samples


def _calculate(features, samples, *, recorded_fit_errors=()):
    begin = perf_counter()
    training_samples = [row for row in samples if row["evaluation_role"] == "training"]
    fitted = fit_history_models(features, training_samples, recorded_fit_errors=tuple(recorded_fit_errors))
    trained = perf_counter()
    predictions = predict_history_models(features, fitted["models"], fitted["estimators"])
    baselines = predict_baselines(features)
    predicted = perf_counter()
    evaluations = [
        evaluate_history_role(samples, predictions, baselines, role=role)
        for role in PROTOCOL["roles"]
    ]
    finished = perf_counter()
    timings = {
        "fit_seconds": trained - begin,
        "prediction_seconds": predicted - trained,
        "evaluation_seconds": finished - predicted,
        "total_seconds": finished - begin,
    }
    return {
        "models": fitted["models"], "predictions": predictions,
        "baseline_predictions": baselines, "evaluations": evaluations,
    }, timings


def _counts(units, aggregate):
    return {
        "seeds": len(units),
        "model_attempts": sum(len(unit["models"]) for unit in units),
        "fitted_models": sum(model["status"] == "fitted" for unit in units for model in unit["models"]),
        "predictions": sum(len(unit["predictions"]) for unit in units),
        "baseline_predictions": sum(len(unit["baseline_predictions"]) for unit in units),
        "comparisons": sum(len(scored["evaluation"]["comparisons"]) for unit in units for scored in unit["evaluations"]),
        "aggregate_rows": len(aggregate),
    }


def _engineering_status(units, aggregate):
    expected_seeds = len(PROTOCOL["seeds"])
    models_ok = len(units) == expected_seeds and all(
        len(unit["models"]) == PROTOCOL["model_attempts_per_seed"]
        and all(model["status"] == "fitted" for model in unit["models"])
        for unit in units
    )
    evaluations_ok = all(
        len(unit["predictions"]) == len({row["sample_id"] for row in unit["predictions"]}) * 10
        and len(unit["baseline_predictions"]) == len({row["sample_id"] for row in unit["baseline_predictions"]}) * 2
        and len(unit["evaluations"]) == 3
        and all(len(scored["evaluation"]["comparisons"]) == 160
                and all(row.get("complete_output") is True
                        for row in scored["evaluation"]["comparisons"])
                for scored in unit["evaluations"])
        for unit in units
    )
    aggregate_ok = len(aggregate) == 480 and all(
        row["n_present_seeds"] == expected_seeds and row["n_effective_seeds"] == expected_seeds
        and row.get("complete") is True
        for row in aggregate
    )
    return "passed" if models_ok and evaluations_ok and aggregate_ok else "incomplete"


def _number(value):
    return "NA" if value is None else format(value, ".6g")


def _summary(manifest, aggregate):
    counts = manifest["counts"]
    return (
        "# Synthetic prediction history experiment\n\n"
        f"- Engineering status: {manifest['status']}\n"
        "- Source kind: synthetic\n"
        "- Clinical status: not_assessable\n"
        "- Clinical validity claim: false\n"
        f"- Seeds: {counts['seeds']}\n"
        f"- Model attempts: {counts['model_attempts']}\n"
        f"- Comparisons: {counts['comparisons']}\n"
        "- Negative gains are retained. This is a synthetic engineering result, not a clinical conclusion.\n\n"
        "## Challenge summary\n\n"
        "| Task | Family | Comparison | Scope | Reference | Valid seeds | MAE mean | Gain mean | Direction | Complete |\n"
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | --- | --- |\n"
        + "".join(
            f"| {row['task_id']} | {row['family']} | {row['comparison_name']} | {row['scope']} | "
            f"{row['reference_model_id']} | {row['n_effective_seeds']} | {_number(row['metrics']['mae']['mean'])} | "
            f"{_number(row['metrics']['mae_gain_reference_minus_candidate']['mean'])} | {row['gain_direction']} | "
            f"{'yes' if row['complete'] else 'no'} |\n"
            for row in aggregate if row["evaluation_role"] == "challenge"
        )
    )


def _receipt(directory, envelope, units, aggregate, status, error=None):
    records = _file_records(directory)
    return {
        "run_id": "hist-" + _hash(envelope)[:16],
        "protocol_identity_sha256": _hash(envelope),
        "status": status,
        "error": error,
        "source_kind": "synthetic",
        "clinical_status": "not_assessable",
        "clinical_validity_claim": False,
        "is_test_fixture": bool(PROTOCOL["is_test_fixture"]),
        "counts": _counts(units, aggregate),
        "files": records,
        "data_content_sha256": _hash(records),
        "fit_error_verification": (
            "inputs_checked_not_retried" if any(
                model.get("reason") == "model_fit_error" for unit in units for model in unit["models"]
            ) else "not_applicable"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _public(manifest):
    return {key: manifest[key] for key in (
        "status", "run_id", "data_content_sha256", "counts", "clinical_status", "is_test_fixture"
    )}


def run(output_dir: Path) -> dict:
    directory = _validate_new_output(output_dir)
    directory.mkdir(parents=True, exist_ok=False)
    units, runs, aggregate = [], [], []
    try:
        envelope = _envelope()
        _write(directory, "protocol.json", envelope)
        for seed in PROTOCOL["seeds"]:
            cohort, quality = _source(seed)
            _write(directory, f"seed-{seed}/cohort.json", cohort)
            _write(directory, f"seed-{seed}/quality.json", quality)
            if quality.get("status") != "passed":
                manifest = _receipt(directory, envelope, units, aggregate, "failed", "source_quality_failed")
                _write(directory, "manifest.json", manifest)
                return _public(manifest)
            partitions, features, samples = _prepared(seed, cohort)
            _write(directory, f"seed-{seed}/partitions.json", partitions)
            _write(directory, f"seed-{seed}/features.json", features)
            _write(directory, f"seed-{seed}/samples.json", samples)
            unit, timings = _calculate(features, samples)
            _write(directory, f"seed-{seed}/models.json", unit["models"])
            _write(directory, f"seed-{seed}/predictions.json", unit["predictions"])
            _write(directory, f"seed-{seed}/baseline_predictions.json", unit["baseline_predictions"])
            _write(directory, f"seed-{seed}/timings.json", timings)
            for role, scored in zip(PROTOCOL["roles"], unit["evaluations"]):
                _write(directory, f"seed-{seed}/{role}/evaluation.json", scored["evaluation"])
                _write(directory, f"seed-{seed}/{role}/paired_rows.json", scored["paired_rows"])
                _write(directory, f"seed-{seed}/{role}/bootstrap_plans.json", scored["bootstrap_plans"])
            units.append(unit)
            runs.append({"seed": seed, "evaluations": unit["evaluations"]})
        aggregate = aggregate_history_runs(runs)
        _write(directory, "aggregate.json", aggregate)
        if _envelope() != envelope:
            raise ValueError("source_identity_changed")
        status = _engineering_status(units, aggregate)
        draft = _receipt(directory, envelope, units, aggregate, status)
        _write(directory, "summary.md", _summary(draft, aggregate), text=True)
        manifest = _receipt(directory, envelope, units, aggregate, status)
        _write(directory, "manifest.json", manifest)
        return _public(manifest)
    except Exception:
        if not (directory / "manifest.json").exists():
            if "envelope" not in locals():
                envelope = {
                    "protocol": copy.deepcopy(PROTOCOL), "runtime": None,
                    "code_sha256": None, "envelope_status": "failed",
                }
            if not (directory / "protocol.json").exists():
                try:
                    _write(directory, "protocol.json", envelope)
                except OSError:
                    pass
            manifest = _receipt(directory, envelope, units, aggregate, "failed", "experiment_runtime_error")
            _write(directory, "manifest.json", manifest)
        raise


def _expected_names():
    names = {"protocol.json", "aggregate.json", "summary.md"}
    for seed in PROTOCOL["seeds"]:
        prefix = f"seed-{seed}"
        names.update(f"{prefix}/{name}.json" for name in (
            "cohort", "quality", "partitions", "features", "samples", "models",
            "predictions", "baseline_predictions", "timings",
        ))
        for role in PROTOCOL["roles"]:
            names.update(f"{prefix}/{role}/{name}.json" for name in ("evaluation", "paired_rows", "bootstrap_plans"))
    return names


def verify(output_dir: Path) -> dict:
    directory = Path(output_dir).absolute()
    rejected = lambda reason: {"status": "failed", "reason": reason}
    try:
        if (not directory.is_dir() or directory.is_symlink() or _is_reparse(directory)
                or any(parent.is_symlink() or _is_reparse(parent) for parent in directory.parents)):
            return rejected("unreadable_or_unsafe_artifact")
        actual = _file_records(directory)
        manifest = _read(directory / "manifest.json")
        if set(actual) != _expected_names() or manifest.get("files") != actual or manifest.get("data_content_sha256") != _hash(actual):
            return rejected("file_integrity_mismatch")
        envelope = _envelope()
        if (not _same(_read(directory / "protocol.json"), envelope)
                or manifest.get("protocol_identity_sha256") != _hash(envelope)
                or manifest.get("run_id") != "hist-" + _hash(envelope)[:16]
                or manifest.get("status") not in {"passed", "incomplete"}):
            return rejected("protocol_runtime_or_code_mismatch")
        units, runs = [], []
        for seed in PROTOCOL["seeds"]:
            cohort, quality = _source(seed)
            if quality.get("status") != "passed":
                return rejected("source_quality_failed")
            partitions, features, samples = _prepared(seed, cohort)
            trusted = {"cohort": cohort, "quality": quality, "partitions": partitions, "features": features, "samples": samples}
            for name, value in trusted.items():
                if not _same(_read(directory / f"seed-{seed}/{name}.json"), value):
                    return rejected("source_recalculation_mismatch")
            recorded = _read(directory / f"seed-{seed}/models.json")
            errors = tuple(
                f"{model['task_id']}:{model['model_id']}" for model in recorded
                if model.get("status") == "error" and model.get("reason") == "model_fit_error"
            )
            unit, _ = _calculate(features, samples, recorded_fit_errors=errors)
            comparisons = {
                "models": unit["models"], "predictions": unit["predictions"],
                "baseline_predictions": unit["baseline_predictions"],
            }
            for name, value in comparisons.items():
                if not _same(_read(directory / f"seed-{seed}/{name}.json"), value):
                    return rejected("model_or_prediction_recalculation_mismatch")
            for role, scored in zip(PROTOCOL["roles"], unit["evaluations"]):
                for name in ("evaluation", "paired_rows", "bootstrap_plans"):
                    if not _same(_read(directory / f"seed-{seed}/{role}/{name}.json"), scored[name]):
                        return rejected("evaluation_recalculation_mismatch")
            timing = _read(directory / f"seed-{seed}/timings.json")
            if set(timing) != {"fit_seconds", "prediction_seconds", "evaluation_seconds", "total_seconds"} or any(
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                for value in timing.values()
            ):
                return rejected("invalid_timing")
            units.append(unit)
            runs.append({"seed": seed, "evaluations": unit["evaluations"]})
        aggregate = aggregate_history_runs(runs)
        status = _engineering_status(units, aggregate)
        if not _same(_read(directory / "aggregate.json"), aggregate) or status != manifest["status"]:
            return rejected("aggregate_recalculation_mismatch")
        expected = _receipt(directory, envelope, units, aggregate, status)
        if (directory / "summary.md").read_text(encoding="utf-8") != _summary(expected, aggregate):
            return rejected("summary_recalculation_mismatch")
        if any(not _same(manifest.get(key), value)
               for key, value in expected.items() if key != "created_at"):
            return rejected("manifest_recalculation_mismatch")
        if _envelope() != envelope:
            return rejected("source_identity_changed")
        return {**_public(manifest), "status": "passed", "engineering_status": status,
                "fit_error_verification": manifest["fit_error_verification"]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        return rejected("unreadable_or_invalid_artifact")


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def _print(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), flush=True)


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--output-dir", type=Path)
    group.add_argument("--verify-dir", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    except ValueError:
        _print({"status": "error", "reason": "invalid_arguments"})
        return 2
    try:
        if args.output_dir:
            _validate_new_output(args.output_dir)
    except (FileExistsError, ValueError):
        _print({"status": "error", "reason": "invalid_output_target"})
        return 2
    except Exception:
        _print({"status": "error", "reason": "experiment_runtime_error"})
        return 4
    try:
        if args.output_dir:
            result = run(args.output_dir)
            if result.get("status") == "passed":
                result = verify(args.output_dir)
        else:
            result = verify(args.verify_dir)
    except ValueError:
        _print({"status": "error", "reason": "experiment_incomplete"})
        return 3
    except Exception:
        _print({"status": "error", "reason": "experiment_runtime_error"})
        return 4
    _print(result)
    return 0 if result.get("status") == "passed" and result.get("engineering_status", "passed") == "passed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
