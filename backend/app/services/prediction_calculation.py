"""Synthetic four-task sampling and baseline prediction, outside application routing."""

from collections import Counter, defaultdict
from datetime import date
import math

from app.schemas.synthetic_prediction_cases import FollowupOutcome, PredictionInput, SyntheticPatient
from app.services.synthetic_prediction_cases import add_calendar_months


TASKS = ("ad.mmse.6m", "ad.mmse.12m", "fatty_liver.alt.6m", "fatty_liver.alt.12m")
POOLS = ("development_pool", "challenge_pool")
MODELS = ("last_value", "history_trend")
THRESHOLDS = dict.fromkeys(("max_mae", "min_mae_gain", "max_mae_ci_width", "max_gain_ci_width"))


def _index(rows, key):
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("duplicate_identity")
    return indexed


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def project_calculation_inputs(packets):
    """This entry point cannot receive outcomes, complete observations or audit data."""
    _index(packets, "sample_id")
    features = []
    for raw in sorted(packets, key=lambda p: p["sample_id"]):
        packet = PredictionInput.model_validate(raw).model_dump(mode="json")
        if packet["task_id"] not in TASKS:
            raise ValueError("unsupported_task")
        anchor_date = date.fromisoformat(packet["anchor_date"])
        observations = packet["input_observations"]
        anchor = next((o for o in observations if o["observation_id"] == packet["anchor_observation_id"]), None)
        prior = sorted((o for o in observations if o["measured_on"] < packet["anchor_date"]),
                       key=lambda o: (o["measured_on"], o["observation_id"]))
        indicator = "mmse" if packet["task_id"].startswith("ad.") else "alt"
        if any(o["indicator"] != indicator or o["unit"] != ("分" if indicator == "mmse" else "U/L")
               or o["known_on"] < o["measured_on"] or o["value"] < 0
               or (indicator == "mmse" and o["value"] > 30) for o in observations):
            raise ValueError("invalid_input_observation")
        if packet["input_status"] == "available":
            if anchor is None or anchor["measured_on"] != packet["anchor_date"]:
                raise ValueError("anchor_identity_mismatch")
            if len({o["measured_on"] for o in observations}) != len(observations):
                raise ValueError("conflicting_input_dates")
            if any(o["method"] != anchor["method"] for o in prior):
                raise ValueError("incomparable_input_method")
        history_known = packet["history_state"] != "unknown" and packet["history_coverage"] == "complete"
        span = (anchor_date - date.fromisoformat(prior[0]["measured_on"])).days if prior else 0
        features.append({
            **{key: packet[key] for key in ("sample_id", "subject_id", "dependency_group_id", "task_id",
                                            "horizon_months", "anchor_date", "history_state", "input_status", "input_reason", "source")},
            "horizon_days": (add_calendar_months(anchor_date, packet["horizon_months"]) - anchor_date).days,
            "anchor_value": anchor["value"] if anchor else None,
            "n_pre": len(prior) if history_known else None, "span_pre_days": span if history_known else None,
            "trend_prior_value": prior[-1]["value"] if prior else None,
            "trend_interval_days": (anchor_date - date.fromisoformat(prior[-1]["measured_on"])).days if prior else None,
        })
    return features


def predict_baselines(features):
    predictions = []
    for row in sorted(features, key=lambda f: f["sample_id"]):
        for model in MODELS:
            status, reason, value = "valid", None, None
            if row["input_status"] != "available":
                status, reason = "abstain", "anchor_not_available"
            elif model == "history_trend" and (row["trend_prior_value"] is None or not row["trend_interval_days"]):
                status, reason = "abstain", "comparable_history_required"
            else:
                try:
                    value = row["anchor_value"]
                    if model == "history_trend":
                        value += (row["anchor_value"] - row["trend_prior_value"]) * row["horizon_days"] / row["trend_interval_days"]
                    if not _finite(value):
                        status, reason, value = "error", "nonfinite_prediction", None
                except (ArithmeticError, TypeError, ValueError):
                    status, reason, value = "error", "prediction_calculation_error", None
            predictions.append({"sample_id": row["sample_id"], "model_id": model,
                                "status": status, "value": value, "reason": reason})
    return predictions


def build_engineering_samples(patients, packets, outcomes, audit):
    patients = [SyntheticPatient.model_validate(p).model_dump(mode="json") for p in patients]
    outcomes = [FollowupOutcome.model_validate(o).model_dump(mode="json") for o in outcomes]
    pmap, omap, amap = _index(patients, "subject_id"), _index(outcomes, "sample_id"), _index(audit, "subject_id")
    features = project_calculation_inputs(packets)
    if set(pmap) != set(amap) or {f["sample_id"] for f in features} != set(omap):
        raise ValueError("sample_link_mismatch")
    groups, subject_horizons = defaultdict(set), defaultdict(list)
    for p in patients:
        a = amap[p["subject_id"]]
        if a["pool"] not in POOLS or a["dependency_group_id"] != p["dependency_group_id"]:
            raise ValueError("audit_link_mismatch")
        groups[p["dependency_group_id"]].add(a["pool"])
    if any(len(pools) != 1 for pools in groups.values()):
        raise ValueError("dependency_crosses_pools")
    samples = []
    for f in features:
        if f["subject_id"] not in pmap:
            raise ValueError("foreign_subject")
        p, o = pmap[f["subject_id"]], omap[f["sample_id"]]
        subject_horizons[f["subject_id"]].append(f["horizon_months"])
        expected_task = f'{p["disease"]}.{"mmse" if p["disease"] == "ad" else "alt"}.{f["horizon_months"]}m'
        nominal = add_calendar_months(date.fromisoformat(f["anchor_date"]), f["horizon_months"]).isoformat()
        if (f["dependency_group_id"] != p["dependency_group_id"] or f["anchor_date"] != p["anchor_date"]
                or f["task_id"] != expected_task or f["source"] != p["source"]
                or o["subject_id"] != p["subject_id"] or o["horizon_months"] != f["horizon_months"]
                or o["nominal_date"] != nominal):
            raise ValueError("sample_identity_mismatch")
        if p["diagnosis_status"] == "excluded":
            anchor_status = "ineligible"
        elif p["diagnosis_status"] == "unknown" or not p["diagnosis_known_on"] or p["diagnosis_known_on"] > f["anchor_date"]:
            anchor_status = "pending"
        else:
            anchor_status = "eligible" if f["input_status"] == "available" else "ineligible"
        label_status = "not_applicable"
        if anchor_status == "eligible":
            label_status = ("valid" if o["status"] == "fixture_observed_at_nominal" else
                            "absent" if o["status"] == "confirmed_unobserved" else "pending")
        samples.append({**f, "pool": amap[p["subject_id"]]["pool"], "anchor_status": anchor_status,
                        "label_status": label_status, "label_reason": o["status"],
                        "actual": o["value"] if label_status == "valid" else None,
                        "actual_date": o["actual_date"], "nominal_date": nominal,
                        "label_policy": "synthetic_nominal_date.v1"})
    if any(sorted(subject_horizons[p]) != [6, 12] for p in pmap):
        raise ValueError("two_horizons_required")
    return samples


def _ratio(numerator, denominator):
    return {"value": numerator / denominator if denominator else None,
            "numerator": numerator, "denominator": denominator,
            "reason": None if denominator else "zero_denominator"}


def _prediction_index(predictions, sample_ids):
    result = {}
    for p in predictions:
        key = (p["sample_id"], p["model_id"])
        if key in result or p["sample_id"] not in sample_ids or p["model_id"] not in MODELS:
            raise ValueError("invalid_prediction_identity")
        if p["status"] not in {"valid", "abstain", "error"}:
            raise ValueError("invalid_prediction_status")
        if p["status"] == "valid" and not _finite(p["value"]):
            p = {**p, "status": "error", "value": None, "reason": "nonfinite_prediction"}
        result[key] = p
    return result


def evaluate_baselines(samples, predictions):
    from app.services.prediction_calculation_metrics import paired_bootstrap, paired_statistics, performance_decision

    pmap = _prediction_index(predictions, {s["sample_id"] for s in samples})
    comparisons, all_pairs, plans = [], [], {}
    for task in TASKS:
        for pool in POOLS:
            selected = [s for s in samples if s["task_id"] == task and s["pool"] == pool]
            if len({s["subject_id"] for s in selected}) != len(selected):
                raise ValueError("duplicate_analysis_patient")
            for branch, model in (("main", "last_value"), ("history", "history_trend")):
                key = f"{task}:{pool}:{branch}"
                eligible = [s for s in selected if s["anchor_status"] == "eligible"]
                branch_rows = eligible if branch == "main" else [s for s in eligible if s["trend_prior_value"] is not None
                                                                 and s["trend_interval_days"] is not None and s["trend_interval_days"] > 0]
                valid = [s for s in branch_rows if s["label_status"] == "valid"]
                pairs, output_counts, joint = [], Counter(), Counter()
                missing_prediction = {"status": "error", "value": None, "reason": "prediction_record_missing"}
                complete_output = True
                for s in branch_rows:
                    p = pmap.get((s["sample_id"], model), missing_prediction)
                    baseline = pmap.get((s["sample_id"], "last_value"), missing_prediction)
                    if p["status"] != "valid" or baseline["status"] != "valid":
                        complete_output = False
                for s in valid:
                    p = pmap.get((s["sample_id"], model), missing_prediction)
                    b = pmap.get((s["sample_id"], "last_value"), missing_prediction)
                    output_counts[p["status"]] += 1
                    joint_state = ("both_valid" if p["status"] == b["status"] == "valid" else
                                   "candidate_unavailable" if p["status"] != "valid" and b["status"] == "valid" else
                                   "baseline_unavailable" if p["status"] == "valid" else "both_unavailable")
                    joint[joint_state] += 1
                    if joint_state == "both_valid":
                        pairs.append({"subject_id": s["subject_id"], "dependency_group_id": s["dependency_group_id"],
                                      "actual": s["actual"], "prediction": p["value"], "baseline": b["value"]})
                        all_pairs.append({**pairs[-1], "comparison_id": key, "sample_id": s["sample_id"]})
                summary = paired_statistics(pairs)
                intervals = {}
                if pool == "challenge_pool":
                    boot = paired_bootstrap(pairs)
                    intervals = boot["intervals"]
                    plans[key] = {k: v for k, v in boot.items() if k != "intervals"}
                counts = {"N_patient": len(selected), "N_anchor_eligible": len(eligible),
                          "N_anchor_ineligible": sum(s["anchor_status"] == "ineligible" for s in selected),
                          "N_anchor_pending": sum(s["anchor_status"] == "pending" for s in selected),
                          "N_branch_eligible": len(branch_rows), "N_branch_not_applicable": len(eligible) - len(branch_rows),
                          "N_label_valid": len(valid), "N_label_absent": sum(s["label_status"] == "absent" for s in branch_rows),
                          "N_label_pending": sum(s["label_status"] == "pending" for s in branch_rows),
                          "N_pred_valid": output_counts["valid"], "N_pred_abstain": output_counts["abstain"],
                          "N_pred_error": output_counts["error"], "N_pair_valid": len(pairs),
                          "N_d03_eligible": sum(s["n_pre"] is not None for s in eligible),
                          "N_d03_unknown_history": sum(s["n_pre"] is None for s in eligible),
                          "N_dependency_groups": len({s["dependency_group_id"] for s in selected})}
                comparisons.append({"comparison_id": key, "task_id": task, "pool": pool, "branch": branch,
                    "model_id": model, "counts": counts, "joint_states": {state: joint[state] for state in (
                        "both_valid", "candidate_unavailable", "baseline_unavailable", "both_unavailable")},
                    "coverage": {"label_support": _ratio(len(valid), len(branch_rows)),
                                 "output": _ratio(output_counts["valid"], len(valid)),
                                 "paired": _ratio(len(pairs), len(valid)),
                                 "end_to_end": _ratio(len(pairs), len(branch_rows))},
                    "complete_output": complete_output, "statistics": summary, "intervals": intervals,
                    "uncertainty_scope": "synthetic_fixed_challenge" if pool == "challenge_pool" else "descriptive_only",
                    "thresholds": dict(THRESHOLDS),
                    "performance": performance_decision(summary, intervals, THRESHOLDS,
                                                         prerequisites=False, complete_output=complete_output)})
    return {"evaluation": {"schema_version": "synthetic_prediction_calculation.v1", "clinical_validity_claim": False,
                            "comparisons": comparisons, "d03_model_comparison": "not_run", "candidate_model_training": "not_run"},
            "paired_rows": all_pairs, "bootstrap_plans": plans}
