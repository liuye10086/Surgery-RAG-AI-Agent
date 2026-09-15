from copy import deepcopy
import hashlib

import pytest

from app.services.prediction_stability import aggregate_runs, build_partitions, evaluate_role


def samples_for_partition(n=8):
    rows = []
    for disease, task in (("ad", "ad.mmse"), ("fatty_liver", "fatty_liver.alt")):
        for pool in ("development_pool", "challenge_pool"):
            for index in range(n):
                subject = f"{disease}-{pool}-{index}"
                for horizon in (6, 12):
                    rows.append({"sample_id": f"{subject}:{horizon}m", "subject_id": subject,
                                 "dependency_group_id": f"group-{subject}", "task_id": f"{task}.{horizon}m",
                                 "pool": pool, "actual": index, "label_status": "valid"})
    return rows


def test_partition_is_nested_grouped_and_invariant_to_targets_and_row_order():
    rows = samples_for_partition()
    parts = build_partitions(rows, 20260914, train_group_sizes=(2, 4), validation_fraction=.25)
    val, challenge = set(parts["validation_groups"]), set(parts["challenge_groups"])
    small, large = (set(parts["training_groups"][str(size)]) for size in (2, 4))
    assert len(val) == 4 and len(challenge) == 16
    assert len(small) == 4 and len(large) == 8
    assert small < large and not val & large and not challenge & (val | large)
    changed = deepcopy(rows)
    for row in changed:
        row["actual"] = -9999
        row["label_status"] = "pending"
    assert build_partitions(changed[::-1], 20260914, train_group_sizes=(2, 4), validation_fraction=.25) == parts
    for group in val | large | challenge:
        assert {row["task_id"].rsplit(".", 1)[-1] for row in rows if row["dependency_group_id"] == group} == {"6m", "12m"}


def test_hash_ties_sort_by_group_id(monkeypatch):
    from app.services import prediction_stability

    class SameHash:
        def hexdigest(self):
            return "same"

    monkeypatch.setattr(prediction_stability.hashlib, "sha256", lambda _: SameHash())
    rows = samples_for_partition(5)
    result = build_partitions(rows, 1, train_group_sizes=(2,), validation_fraction=.2)
    for disease in ("ad", "fatty_liver"):
        assert f"group-{disease}-development_pool-0" in result["validation_groups"]
        assert [g for g in result["training_groups"]["2"] if g.startswith(f"group-{disease}-")] == [
            f"group-{disease}-development_pool-1", f"group-{disease}-development_pool-2"]


def test_hash_domain_and_related_subjects_remain_one_group():
    rows = samples_for_partition(8)
    sibling = deepcopy(rows[0])
    sibling["sample_id"] = "related-subject:6m"
    sibling["subject_id"] = "related-subject"
    rows.append(sibling)
    result = build_partitions(rows, 20260914, train_group_sizes=(2,), validation_fraction=.25)
    disease = "ad"
    ordered = sorted((f"group-ad-development_pool-{i}" for i in range(8)), key=lambda group: (
        hashlib.sha256(f"stability.v1:20260914:{disease}:{group}".encode("utf-8")).hexdigest(), group))
    assert [group for group in result["validation_groups"] if group.startswith("group-ad-")] == ordered[:2]
    assert [group for group in result["training_groups"]["2"] if group.startswith("group-ad-")] == ordered[2:4]
    assert sum(row["dependency_group_id"] == sibling["dependency_group_id"] for row in rows) == 3


@pytest.mark.parametrize("mutation", ["cross_disease", "cross_pool", "subject_group", "duplicate_task", "short_pool"])
def test_partition_rejects_broken_identity_or_budget(mutation):
    rows = samples_for_partition()
    if mutation == "cross_disease":
        rows[-1]["dependency_group_id"] = rows[0]["dependency_group_id"]
    elif mutation == "cross_pool":
        rows[16]["dependency_group_id"] = rows[0]["dependency_group_id"]
    elif mutation == "subject_group":
        rows[1]["dependency_group_id"] = "other"
    elif mutation == "duplicate_task":
        rows.append(deepcopy(rows[0]))
    elif mutation == "short_pool":
        rows = [r for r in rows if r["pool"] != "development_pool" or r["subject_id"].endswith("-0")]
    with pytest.raises(ValueError):
        build_partitions(rows, 20260914, train_group_sizes=(2, 4), validation_fraction=.25)


def role_data(pool):
    samples, predictions, baselines = [], [], []
    for i, actual in enumerate((10., 20.)):
        sid = f"subject-{pool}-{i}:6m"
        samples.append(dict(sample_id=sid, subject_id=f"subject-{pool}-{i}",
                            dependency_group_id=f"group-{pool}-{i}", task_id="ad.mmse.6m", pool=pool,
                            anchor_status="eligible", label_status="valid", actual=actual,
                            n_pre=i, span_pre_days=i * 30, anchor_value=8.))
        for family in ("ridge", "random_forest"):
            for branch in ("main_anchor", "d03_anchor", "d03_augmented"):
                predictions.append(dict(sample_id=sid, task_id="ad.mmse.6m", model_id=f"{family}:{branch}",
                                        status="valid", value=actual - (0 if branch == "d03_augmented" else 1)))
        baselines.append(dict(sample_id=sid, model_id="last_value", status="valid", value=actual - 2))
    return samples, predictions, baselines


@pytest.mark.parametrize("role,pool", [("training", "development_pool"),
                                       ("internal_validation", "development_pool"),
                                       ("challenge", "challenge_pool")])
def test_role_scoring_keeps_real_pool_denominators_and_paired_identity(role, pool):
    source = role_data(pool)
    snapshot = deepcopy(source)
    result = evaluate_role(*source, role)
    assert source == snapshot
    comparisons = result["evaluation"]["comparisons"]
    assert len(comparisons) == 32
    assert {c["pool"] for c in comparisons} == {pool}
    assert {c["source_pool"] for c in comparisons} == {pool}
    assert {c["evaluation_role"] for c in comparisons} == {role}
    assert all(c["uncertainty_scope"] == "descriptive_seed_stability_only" and not c["intervals"] for c in comparisons)
    assert result["bootstrap_plans"] == {}
    main = next(c for c in comparisons if c["task_id"] == "ad.mmse.6m" and c["family"] == "ridge"
                and c["branch"] == "main_anchor")
    flow = next(c for c in comparisons if c["task_id"] == "ad.mmse.6m" and c["family"] == "ridge"
                and c["comparison_kind"] == "d03_flow")
    assert main["counts"]["N_pair_valid"] == main["counts"]["N_label_valid"] == 2
    assert main["statistics"]["mae_gain_vs_last"] == 1.
    assert flow["statistics"]["flow_mae_gain"] == 1.
    assert all(row["comparison_id"] in {c["comparison_id"] for c in comparisons}
               for row in result["paired_rows"])


def test_role_scoring_rejects_mismatched_pool():
    with pytest.raises(ValueError):
        evaluate_role(*role_data("challenge_pool"), "internal_validation")
    with pytest.raises(ValueError):
        evaluate_role(*role_data("development_pool"), "other")


def fake_role(value, *, complete=True):
    return {"evaluation": {"comparisons": [{"task_id": "ad.mmse.6m", "family": "ridge",
              "branch": "main_anchor", "comparison_kind": "vs_last", "evaluation_role": "internal_validation",
              "complete_output": complete, "statistics": {"mae": value,
                  "rmse": value + 1 if value is not None else None,
                  "bias": -value if value is not None else None,
                  "mae_gain_vs_last": 2 - value if value is not None else None},
              "counts": {"N_pair_valid": 5, "N_label_valid": 6}}]}}


def test_aggregate_equal_seed_weights_null_metrics_and_missing_seed():
    runs = [{"seed": 20260914, "scale": 120, "roles": {"internal_validation": fake_role(1)}},
            {"seed": 20260915, "scale": 120, "roles": {"internal_validation": fake_role(None)}}]
    result = aggregate_runs(runs)
    assert len(result) == 1
    row = result[0]
    assert row["seeds"] == [20260914, 20260915]
    assert row["expected_seeds"] == [20260914, 20260915, 20260916]
    assert not row["complete"]
    assert row["metrics"]["mae"] == {"mean": 1., "min": 1., "max": 1., "n_valid": 1}
    assert row["counts"]["N_pair_valid"] == {"mean": 5., "min": 5, "max": 5, "n_valid": 2}


def test_aggregate_complete_requires_all_three_unique_complete_outputs():
    runs = [{"seed": seed, "scale": 600, "roles": {"internal_validation": fake_role(value)}}
            for seed, value in ((20260916, 3), (20260914, 1), (20260915, 2))]
    row = aggregate_runs(runs)[0]
    assert row["complete"] and row["seeds"] == [20260914, 20260915, 20260916]
    assert row["metrics"]["mae"] == {"mean": 2., "min": 1, "max": 3, "n_valid": 3}
    runs[1]["roles"]["internal_validation"]["evaluation"]["comparisons"][0]["complete_output"] = False
    assert not aggregate_runs(runs)[0]["complete"]
    with pytest.raises(ValueError):
        aggregate_runs([runs[0], deepcopy(runs[0])])
