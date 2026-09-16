"""Paired evaluation for the fixed synthetic history-feature experiment."""

from collections import Counter, defaultdict
import hashlib
import math
from numbers import Real

from app.services.prediction_calculation import TASKS
from app.services.prediction_calculation_metrics import paired_bootstrap, paired_statistics
from app.services.prediction_history_training import BRANCH_FEATURES, FAMILIES, history_model_id
from app.services.synthetic_prediction_cases import canonical_json


ROLES = {
    "training": "development_pool",
    "internal_validation": "development_pool",
    "challenge": "challenge_pool",
}
EXPECTED_SEEDS = (20260914, 20260915, 20260916)
STATES = ("valid", "abstain", "error")
JOINT_STATES = (
    "both_valid",
    "candidate_unavailable",
    "reference_unavailable",
    "both_unavailable",
)
SCOPES = ("original", "common_complete")
MISSING = {"status": "error", "value": None, "reason": "prediction_record_missing"}


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _comparison_specs(family):
    specs = [
        (f"{branch}_vs_last_value", history_model_id(family, branch), "last_value", branch)
        for branch in BRANCH_FEATURES
    ]
    specs.extend((
        ("history_trend_vs_last_value", "history_trend", "last_value", "history"),
        ("schedule_history_vs_anchor_history", history_model_id(family, "schedule_history"),
         history_model_id(family, "anchor_history"), "history"),
        ("value_history_vs_anchor_history", history_model_id(family, "value_history"),
         history_model_id(family, "anchor_history"), "history"),
        ("value_schedule_history_vs_value_history", history_model_id(family, "value_schedule_history"),
         history_model_id(family, "value_history"), "history"),
        ("value_schedule_history_vs_schedule_history", history_model_id(family, "value_schedule_history"),
         history_model_id(family, "schedule_history"), "history"),
    ))
    return tuple(specs)


def _catalog():
    return tuple(
        (role, task, family, name, scope)
        for role in ROLES for task in TASKS for family in FAMILIES
        for name, _, _, _ in _comparison_specs(family) for scope in SCOPES
    )


def _samples_index(samples, role):
    if role not in ROLES:
        raise ValueError("unsupported_evaluation_role")
    indexed, subjects, groups, analysis = {}, {}, {}, set()
    for row in samples:
        required = ("sample_id", "subject_id", "dependency_group_id", "task_id", "pool",
                    "evaluation_role", "anchor_status", "label_status", "history_status",
                    "history_reason")
        if any(key not in row for key in required):
            raise ValueError("missing_analysis_metadata")
        sid, subject, group, task = (row[key] for key in required[:4])
        row_role = row["evaluation_role"]
        if (sid in indexed or (subject, task) in analysis or task not in TASKS
                or row_role not in ROLES or row["pool"] != ROLES[row_role]
                or row["anchor_status"] not in {"eligible", "ineligible", "pending"}
                or row["label_status"] not in {"valid", "absent", "pending", "not_applicable"}
                or row["history_status"] not in {"available", "abstain", "error"}):
            raise ValueError("invalid_analysis_identity")
        partition = (group, row["pool"], row_role)
        if ((subject in subjects and subjects[subject] != partition)
                or (group in groups and groups[group] != (row["pool"], row_role))):
            raise ValueError("dependency_crosses_partitions")
        if row["label_status"] == "valid" and not _finite(row.get("actual")):
            raise ValueError("invalid_analysis_target")
        analysis.add((subject, task))
        subjects[subject] = partition
        groups[group] = (row["pool"], row_role)
        indexed[sid] = row
    return indexed


def _prediction_index(rows, samples, allowed, *, require_task):
    indexed = {}
    for raw in rows:
        row = dict(raw)
        sid, model_id = row.get("sample_id"), row.get("model_id")
        key = (sid, model_id)
        if (key in indexed or sid not in samples or model_id not in allowed
                or (require_task and row.get("task_id") != samples[sid]["task_id"])
                or (not require_task and "task_id" in row
                    and row["task_id"] != samples[sid]["task_id"])):
            raise ValueError("invalid_prediction_identity")
        if row.get("status") not in STATES:
            raise ValueError("invalid_prediction_status")
        if row["status"] == "valid" and not _finite(row.get("value")):
            row.update(status="error", value=None, reason="nonfinite_prediction")
        indexed[key] = row
    return indexed


def _joint(candidate, reference):
    candidate_valid = candidate["status"] == "valid"
    reference_valid = reference["status"] == "valid"
    if candidate_valid and reference_valid:
        return "both_valid"
    if reference_valid:
        return "candidate_unavailable"
    if candidate_valid:
        return "reference_unavailable"
    return "both_unavailable"


def _ratio(numerator, denominator):
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "reason": None if denominator else "zero_denominator"}


def _renamed(values):
    names = {"baseline_mae": "reference_mae", "mae_gain": "mae_gain_reference_minus_candidate"}
    result = {names.get(key, key): value for key, value in values.items()}
    if "unavailable" in result:
        result["unavailable"] = [
            names.get(item.split(":", 1)[0], item.split(":", 1)[0])
            + ((":" + item.split(":", 1)[1]) if ":" in item else "")
            for item in result["unavailable"]
        ]
    return result


def _out_of_range(task, value):
    return value < 0 or (task.startswith("ad.") and value > 30)


def _plan_id(task, role, rows):
    identity = canonical_json([
        {key: row[key] for key in ("sample_id", "subject_id", "dependency_group_id")}
        for row in rows
    ])
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{task}:{role}:{digest}"


def evaluate_history_role(samples: list[dict], predictions: list[dict],
                          baseline_predictions: list[dict], *, role: str) -> dict:
    """Evaluate every fixed comparison without converting engineering results to clinical gates."""
    smap = _samples_index(samples, role)
    model_ids = {history_model_id(family, branch)
                 for family in FAMILIES for branch in BRANCH_FEATURES}
    pmap = _prediction_index(predictions, smap, model_ids, require_task=True)
    bmap = _prediction_index(baseline_predictions, smap, {"last_value", "history_trend"},
                             require_task=False)
    all_outputs = {**bmap, **pmap}
    comparisons, paired_rows, plans, plan_cache = [], [], {}, {}

    for task in TASKS:
        selected = sorted((row for row in samples
                           if row["task_id"] == task and row["evaluation_role"] == role),
                          key=lambda row: row["sample_id"])
        eligible = [row for row in selected if row["anchor_status"] == "eligible"]
        history = [row for row in eligible if row["history_status"] in {"available", "error"}]
        common_model_ids = sorted(model_ids | {"last_value", "history_trend"})
        common = [row for row in history if row["label_status"] == "valid" and all(
            all_outputs.get((row["sample_id"], model_id), MISSING)["status"] == "valid"
            for model_id in common_model_ids
        )]

        for family in FAMILIES:
            for name, candidate_id, reference_id, branch in _comparison_specs(family):
                for scope in SCOPES:
                    original_rows = eligible if branch == "anchor_all" else history
                    branch_rows = original_rows if scope == "original" else common
                    labelled = [row for row in branch_rows if row["label_status"] == "valid"]
                    candidate_source = bmap if candidate_id in {"last_value", "history_trend"} else pmap
                    reference_source = bmap if reference_id in {"last_value", "history_trend"} else pmap
                    candidate = lambda row: candidate_source.get((row["sample_id"], candidate_id), MISSING)
                    reference = lambda row: reference_source.get((row["sample_id"], reference_id), MISSING)
                    all_candidate = Counter(candidate(row)["status"] for row in branch_rows)
                    all_reference = Counter(reference(row)["status"] for row in branch_rows)
                    original_candidate = Counter(candidate(row)["status"] for row in original_rows)
                    original_reference = Counter(reference(row)["status"] for row in original_rows)
                    selected_candidate = Counter(candidate(row)["status"] for row in selected)
                    selected_reference = Counter(reference(row)["status"] for row in selected)
                    joint, pairs = Counter(), []
                    for row in labelled:
                        c_row, r_row = candidate(row), reference(row)
                        state = _joint(c_row, r_row)
                        joint[state] += 1
                        if state == "both_valid":
                            pair = {
                                "sample_id": row["sample_id"], "subject_id": row["subject_id"],
                                "dependency_group_id": row["dependency_group_id"], "actual": row["actual"],
                                "prediction": c_row["value"], "baseline": r_row["value"],
                            }
                            pairs.append(pair)
                    comparison_id = f"{task}:{role}:{family}:{name}:{scope}"
                    stats = _renamed(paired_statistics(pairs))
                    intervals, plan_id = {}, None
                    if role == "challenge":
                        cache_key = (task, role, tuple(
                            (row["sample_id"], row["subject_id"], row["dependency_group_id"])
                            for row in pairs
                        ))
                        if cache_key not in plan_cache:
                            first = paired_bootstrap(pairs, seed=20260910, iterations=2000)
                            plan_id = _plan_id(task, role, pairs)
                            plan_cache[cache_key] = (plan_id, first)
                            plans[plan_id] = {
                                key: first[key] for key in (
                                    "seed", "iterations", "attempted", "ordered_groups", "draw_indices"
                                )
                            }
                        else:
                            plan_id, first = plan_cache[cache_key]
                        if first["ordered_groups"] and len(first["ordered_groups"]) >= 2:
                            bootstrap = paired_bootstrap(
                                pairs, seed=20260910, iterations=2000,
                                draw_indices=first["draw_indices"],
                            )
                        else:
                            bootstrap = first
                        intervals = _renamed(bootstrap["intervals"])
                    records_complete = all(
                        (row["sample_id"], candidate_id) in candidate_source
                        and (row["sample_id"], reference_id) in reference_source
                        for row in selected
                    )
                    common_excluded_due_to_output = len([
                        row for row in history if row["label_status"] == "valid"
                    ]) - len(common)
                    complete = (records_complete and original_candidate["error"] == 0
                                and original_reference["error"] == 0
                                and selected_candidate["error"] == 0
                                and selected_reference["error"] == 0
                                and original_candidate["abstain"] == 0
                                and original_reference["abstain"] == 0
                                and (scope != "common_complete" or common_excluded_due_to_output == 0))
                    counts = {
                        "N_patient": len(selected), "N_anchor_eligible": len(eligible),
                        "N_anchor_ineligible": sum(row["anchor_status"] == "ineligible" for row in selected),
                        "N_anchor_pending": sum(row["anchor_status"] == "pending" for row in selected),
                        "N_history_eligible": len(history),
                        "N_history_unavailable": len(eligible) - len(history),
                        "N_branch_eligible": len(branch_rows),
                        "N_original_eligible": len(original_rows),
                        "N_common_complete": len(common),
                        "N_common_excluded": len(original_rows) - len(common),
                        "N_common_excluded_due_to_output": common_excluded_due_to_output,
                        "N_label_valid": len(labelled),
                        "N_label_absent": sum(row["label_status"] == "absent" for row in branch_rows),
                        "N_label_pending": sum(row["label_status"] == "pending" for row in branch_rows),
                        "N_label_not_applicable": sum(row["label_status"] == "not_applicable" for row in branch_rows),
                        "N_pair_valid": len(pairs),
                        "N_dependency_groups": len({row["dependency_group_id"] for row in branch_rows}),
                        "N_candidate_out_of_range": sum(_out_of_range(task, pair["prediction"]) for pair in pairs),
                        "N_reference_out_of_range": sum(_out_of_range(task, pair["baseline"]) for pair in pairs),
                        "N_all_candidate_out_of_range": sum(
                            candidate(row)["status"] == "valid"
                            and _out_of_range(task, candidate(row)["value"]) for row in selected
                        ),
                        "N_all_reference_out_of_range": sum(
                            reference(row)["status"] == "valid"
                            and _out_of_range(task, reference(row)["value"]) for row in selected
                        ),
                    }
                    for state in STATES:
                        counts[f"N_pred_{state}"] = all_candidate[state]
                        counts[f"N_reference_{state}"] = all_reference[state]
                        counts[f"N_original_pred_{state}"] = original_candidate[state]
                        counts[f"N_original_reference_{state}"] = original_reference[state]
                        counts[f"N_all_pred_{state}"] = selected_candidate[state]
                        counts[f"N_all_reference_{state}"] = selected_reference[state]
                    comparison = {
                        "comparison_id": comparison_id, "task_id": task, "pool": ROLES[role],
                        "evaluation_role": role, "family": family, "comparison_name": name,
                        "scope": scope, "candidate_model_id": candidate_id,
                        "reference_model_id": reference_id,
                        "gain_name": "mae_gain_reference_minus_candidate",
                        "unit": "分" if task.startswith("ad.") else "U/L",
                        "counts": counts, "joint_states": {state: joint[state] for state in JOINT_STATES},
                        "coverage": {"label_support": _ratio(len(labelled), len(branch_rows)),
                                     "paired": _ratio(len(pairs), len(labelled)),
                                     "end_to_end": _ratio(len(pairs), len(branch_rows))},
                        "complete_output": complete, "statistics": stats, "intervals": intervals,
                        "common_scope_limited": (scope == "common_complete"
                                                 and common_excluded_due_to_output > 0),
                        "bootstrap_plan_id": plan_id,
                        "uncertainty_scope": ("synthetic_fixed_challenge_group_bootstrap"
                                              if role == "challenge" else "descriptive_only"),
                        "clinical_status": "not_assessable",
                    }
                    comparisons.append(comparison)
                    for pair in pairs:
                        paired_rows.append({
                            **{key: value for key, value in pair.items() if key not in {"prediction", "baseline"}},
                            "comparison_id": comparison_id, "candidate": pair["prediction"],
                            "reference": pair["baseline"], "candidate_model_id": candidate_id,
                            "reference_model_id": reference_id,
                        })
    return {
        "evaluation": {
            "schema_version": "synthetic_prediction_history_evaluation.v1",
            "source_kind": "synthetic", "clinical_validity_claim": False,
            "clinical_status": "not_assessable", "evaluation_role": role,
            "comparisons": comparisons,
        },
        "paired_rows": paired_rows,
        "bootstrap_plans": plans,
    }


def _summary(values):
    valid = [value for value in values if _finite(value)]
    try:
        mean = math.fsum(value / len(valid) for value in valid) if valid else None
    except OverflowError:
        mean = None
    if mean is not None and not math.isfinite(mean):
        mean = None
    return {"mean": mean,
            "min": min(valid) if valid else None, "max": max(valid) if valid else None,
            "n_valid": len(valid),
            "n_invalid": len(values) - len(valid)}


def aggregate_history_runs(runs: list[dict]) -> list[dict]:
    """Equally summarize fixed seed rows while exposing every missing catalog member."""
    grouped, seen_seeds = defaultdict(dict), set()
    catalog = set(_catalog())
    for run in runs:
        seed = run.get("seed")
        if isinstance(seed, bool) or seed not in EXPECTED_SEEDS or seed in seen_seeds:
            raise ValueError("invalid_or_duplicate_history_seed")
        seen_seeds.add(seed)
        evaluations = run.get("evaluations")
        if not isinstance(evaluations, list):
            raise ValueError("invalid_history_evaluations")
        seen_roles, seen_comparisons = set(), set()
        for scored in evaluations:
            evaluation = scored.get("evaluation", scored)
            role = evaluation.get("evaluation_role")
            if role not in ROLES or role in seen_roles:
                raise ValueError("invalid_or_duplicate_evaluation_role")
            seen_roles.add(role)
            for comparison in evaluation.get("comparisons", []):
                key = (role, comparison.get("task_id"), comparison.get("family"),
                       comparison.get("comparison_name"), comparison.get("scope"))
                expected_spec = next((spec for spec in _comparison_specs(key[2])
                                      if spec[0] == key[3]), None) if key in catalog else None
                expected_id = f"{key[1]}:{role}:{key[2]}:{key[3]}:{key[4]}"
                if (key not in catalog or comparison.get("evaluation_role") != role
                        or key in seen_comparisons or expected_spec is None
                        or comparison.get("candidate_model_id") != expected_spec[1]
                        or comparison.get("reference_model_id") != expected_spec[2]
                        or comparison.get("comparison_id") != expected_id):
                    raise ValueError("unknown_or_duplicate_history_comparison")
                seen_comparisons.add(key)
                grouped[key][seed] = comparison

    summaries = []
    for key in _catalog():
        role, task, family, name, scope = key
        members = grouped.get(key, {})
        ordered = [members[seed] for seed in EXPECTED_SEEDS if seed in members]
        missing_seeds = [seed for seed in EXPECTED_SEEDS if seed not in members]
        metric_names = ("mae", "rmse", "bias", "reference_mae",
                        "mae_gain_reference_minus_candidate")
        gain_values = [row["statistics"].get("mae_gain_reference_minus_candidate") for row in ordered]
        valid_gains = [value for value in gain_values if _finite(value)]
        direction = ("positive" if valid_gains and all(value > 0 for value in valid_gains)
                     else "negative" if valid_gains and all(value < 0 for value in valid_gains)
                     else "zero" if valid_gains and all(value == 0 for value in valid_gains)
                     else "mixed" if valid_gains else "unavailable")
        effective_seeds = [seed for seed in EXPECTED_SEEDS if seed in members and all(
            _finite(members[seed].get("statistics", {}).get(metric)) for metric in metric_names
        )]
        summaries.append({
            "evaluation_role": role, "task_id": task, "family": family,
            "comparison_name": name, "scope": scope,
            "candidate_model_id": next(spec[1] for spec in _comparison_specs(family)
                                       if spec[0] == name),
            "reference_model_id": next(spec[2] for spec in _comparison_specs(family)
                                       if spec[0] == name),
            "gain_name": "mae_gain_reference_minus_candidate",
            "unit": "分" if task.startswith("ad.") else "U/L",
            "expected_seeds": list(EXPECTED_SEEDS), "seeds": sorted(members),
            "missing_seeds": missing_seeds, "n_present_seeds": len(members),
            "effective_seeds": effective_seeds, "n_effective_seeds": len(effective_seeds),
            "complete": (not missing_seeds and len(effective_seeds) == len(EXPECTED_SEEDS)
                         and all(row.get("complete_output") for row in ordered)),
            "incomplete": (bool(missing_seeds) or len(effective_seeds) != len(EXPECTED_SEEDS)
                           or any(not row.get("complete_output") for row in ordered)),
            "gain_direction": direction,
            "metrics": {metric: _summary([row["statistics"].get(metric) for row in ordered]) | {
                "missing_seeds": [seed for seed in EXPECTED_SEEDS if seed not in members
                                  or not _finite(members[seed].get("statistics", {}).get(metric))]
            } for metric in metric_names},
            "counts": {metric: _summary([row["counts"].get(metric) for row in ordered])
                       for metric in ("N_pair_valid", "N_label_valid")},
            "source_kind": "synthetic", "clinical_validity_claim": False,
            "clinical_status": "not_assessable",
        })
    return summaries
