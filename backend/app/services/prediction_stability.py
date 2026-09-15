"""Fixed synthetic learning-curve partitions and descriptive seed summaries."""

from collections import defaultdict
import hashlib
import math

from app.services.prediction_calculation import POOLS, TASKS
from app.services.prediction_candidate_evaluation import evaluate_candidates


EXPECTED_SEEDS = (20260914, 20260915, 20260916)
SCALES = (120, 600, 1200)
ROLES = {"training": "development_pool", "internal_validation": "development_pool",
         "challenge": "challenge_pool"}
DISEASES = tuple(dict.fromkeys(task.split(".", 1)[0] for task in TASKS))


def build_partitions(samples, seed, *, train_group_sizes=(64, 320, 640), validation_fraction=.2):
    """Select whole development groups by a seed/disease/group-only SHA-256 key."""
    if (isinstance(seed, bool) or not isinstance(seed, int)
            or isinstance(validation_fraction, bool) or not isinstance(validation_fraction, (int, float))
            or not math.isfinite(validation_fraction) or not 0 < validation_fraction < 1):
        raise ValueError("invalid_partition_parameters")
    sizes = tuple(train_group_sizes)
    if (not sizes or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in sizes)
            or len(set(sizes)) != len(sizes)):
        raise ValueError("invalid_train_group_sizes")
    identities, subjects, groups, by_pool = set(), {}, {}, defaultdict(set)
    for row in samples:
        sid, subject, group, task, pool = (row[key] for key in
                                            ("sample_id", "subject_id", "dependency_group_id", "task_id", "pool"))
        if (not all(isinstance(value, str) and value for value in (sid, subject, group))
                or task not in TASKS or pool not in POOLS
                or sid in identities or (subject, task) in identities):
            raise ValueError("invalid_partition_identity")
        identities.update((sid, (subject, task)))
        disease = task.split(".", 1)[0]
        identity = (disease, pool, group)
        if ((subject in subjects and subjects[subject] != identity)
                or (group in groups and groups[group] != (disease, pool))):
            raise ValueError("dependency_partition_mismatch")
        subjects[subject], groups[group] = identity, (disease, pool)
        by_pool[(disease, pool)].add(group)

    result = {"validation_groups": [], "challenge_groups": [],
              "training_groups": {str(n): [] for n in sizes}}
    for disease in DISEASES:
        development = sorted(by_pool[(disease, "development_pool")], key=lambda group: (
            hashlib.sha256(f"stability.v1:{seed}:{disease}:{group}".encode("utf-8")).hexdigest(), group))
        challenge = sorted(by_pool[(disease, "challenge_pool")])
        validation_count = math.floor(len(development) * validation_fraction)
        if not challenge or validation_count == 0 or len(development) - validation_count < max(sizes):
            raise ValueError("insufficient_partition_groups")
        result["validation_groups"].extend(development[:validation_count])
        result["challenge_groups"].extend(challenge)
        for size in sizes:
            result["training_groups"][str(size)].extend(development[validation_count:validation_count + size])
    return result


def evaluate_role(samples, predictions, baselines, role):
    """Reuse paired evaluation on a temporary development projection without bootstrap."""
    if role not in ROLES:
        raise ValueError("unsupported_evaluation_role")
    source_pool = ROLES[role]
    if any(sample["pool"] != source_pool for sample in samples):
        raise ValueError("evaluation_role_pool_mismatch")
    projected = [{**sample, "pool": "development_pool"} for sample in samples]
    result = evaluate_candidates(projected, predictions, baselines)

    def rename(comparison_id):
        return comparison_id.replace(":development_pool:", f":{role}:")

    result["evaluation"]["comparisons"] = [
        {**comparison, "comparison_id": rename(comparison["comparison_id"]),
         "pool": source_pool, "source_pool": source_pool, "evaluation_role": role,
         "uncertainty_scope": "descriptive_seed_stability_only"}
        for comparison in result["evaluation"]["comparisons"]
        if comparison["pool"] == "development_pool"
    ]
    result["paired_rows"] = [{**row, "comparison_id": rename(row["comparison_id"])}
                             for row in result["paired_rows"]]
    result["bootstrap_plans"] = {}
    return result


def _summary(values):
    valid = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)]
    return {"mean": math.fsum(valid) / len(valid) if valid else None,
            "min": min(valid) if valid else None, "max": max(valid) if valid else None,
            "n_valid": len(valid)}


def aggregate_runs(runs):
    """Equally weight seed point estimates; never pool subjects or create confidence intervals."""
    seen_runs, grouped = set(), defaultdict(dict)
    for run in runs:
        seed, scale = run["seed"], run["scale"]
        if (isinstance(seed, bool) or seed not in EXPECTED_SEEDS or isinstance(scale, bool)
                or scale not in SCALES or (seed, scale) in seen_runs):
            raise ValueError("invalid_or_duplicate_stability_run")
        seen_runs.add((seed, scale))
        seen_comparisons = set()
        for role, scored in run["roles"].items():
            if role not in ROLES:
                raise ValueError("unsupported_evaluation_role")
            for comparison in scored["evaluation"]["comparisons"]:
                if comparison["evaluation_role"] != role:
                    raise ValueError("evaluation_role_mismatch")
                key = (scale, role, comparison["task_id"], comparison["family"],
                       comparison["branch"], comparison["comparison_kind"])
                if key in seen_comparisons:
                    raise ValueError("duplicate_stability_comparison")
                seen_comparisons.add(key)
                grouped[key][seed] = comparison

    summaries = []
    for (scale, role, task, family, branch, kind), members in sorted(grouped.items()):
        metric_names = ("mae", "rmse", "bias", "flow_mae_gain" if kind == "d03_flow" else "mae_gain_vs_last")
        counts = ("N_pair_valid", "N_label_valid")
        ordered = [members[seed] for seed in sorted(members)]
        summaries.append({"scale": scale, "evaluation_role": role, "task_id": task,
                          "family": family, "branch": branch, "comparison_kind": kind,
                          "seeds": sorted(members), "expected_seeds": list(EXPECTED_SEEDS),
                          "complete": set(members) == set(EXPECTED_SEEDS)
                          and all(c["complete_output"] for c in ordered),
                          "metrics": {name: _summary([c["statistics"].get(name) for c in ordered])
                                      for name in metric_names},
                          "counts": {name: _summary([c["counts"].get(name) for c in ordered])
                                     for name in counts}})
    return summaries
