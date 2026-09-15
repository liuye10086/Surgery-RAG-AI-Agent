"""Deterministic engineering checks for isolated synthetic prediction cases."""

from collections import Counter, defaultdict
import json

from pydantic import ValidationError

from app.schemas.synthetic_prediction_cases import (
    FollowupOutcome, GenerationConfig, PredictionInput, SyntheticObservation,
    SyntheticPatient,
)
from app.services.synthetic_prediction_cases import (
    build_followup_outcomes, build_prediction_inputs, generate_cohort,
)


COLLECTIONS = ("patients", "observations", "prediction_inputs", "followup_outcomes", "generation_audit")


def _check(status, reason, **details):
    return {"status": status, "reason": reason, **details}


def _report(checks):
    statuses = {check["status"] for check in checks.values()}
    status = "failed" if "failed" in statuses else "not_assessable" if "not_assessable" in statuses else "passed"
    return {"status": status, "checks": checks}


def _strip_run_id(value):
    if isinstance(value, dict):
        return {key: _strip_run_id(child) for key, child in value.items() if key != "run_id"}
    if isinstance(value, list):
        return [_strip_run_id(child) for child in value]
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _validate(data):
    models = {"patients": SyntheticPatient, "observations": SyntheticObservation,
              "prediction_inputs": PredictionInput, "followup_outcomes": FollowupOutcome}
    for name, model in models.items():
        for row in data[name]:
            model.model_validate(row)
    patients = {p["subject_id"]: p for p in data["patients"]}
    audit = {a["subject_id"]: a for a in data["generation_audit"]}
    issues = []
    for name, key in (("patients", "subject_id"), ("observations", "observation_id"),
                      ("prediction_inputs", "sample_id"), ("followup_outcomes", "sample_id"),
                      ("generation_audit", "subject_id")):
        ids = [row[key] for row in data[name]]
        if len(ids) != len(set(ids)):
            issues.append(f"duplicate_{name}")
    if set(patients) != set(audit):
        issues.append("audit_subject_mismatch")
    pools = defaultdict(set)
    for patient in data["patients"]:
        subject = patient["subject_id"]
        if subject in audit:
            a = audit[subject]
            if a.get("dependency_group_id") != patient["dependency_group_id"] or a.get("pool") not in {"development_pool", "challenge_pool"}:
                issues.append("invalid_audit_link")
            pools[patient["dependency_group_id"]].add(a.get("pool"))
    if any(len(owners) > 1 for owners in pools.values()):
        issues.append("cross_pool_dependency")
    for row in data["observations"]:
        patient = patients.get(row["subject_id"])
        if patient is None:
            issues.append("foreign_observation")
        elif row["indicator"] != ("mmse" if patient["disease"] == "ad" else "alt") or row["unit"] != ("分" if patient["disease"] == "ad" else "U/L"):
            issues.append("indicator_or_unit")
        if row["indicator"] == "mmse" and row["value"] is not None and not float(row["value"]).is_integer():
            issues.append("noninteger_mmse")
    observation_ids = {r["observation_id"] for r in data["observations"]}
    packets = defaultdict(list)
    outcomes = defaultdict(list)
    for row in data["prediction_inputs"]:
        patient = patients.get(row["subject_id"])
        packets[row["subject_id"]].append(row)
        if patient is None or row["dependency_group_id"] != patient["dependency_group_id"] or row["anchor_date"] != patient["anchor_date"] or row["task_id"] != f'{patient["disease"]}.{("mmse" if patient["disease"] == "ad" else "alt")}.{row["horizon_months"]}m':
            issues.append("invalid_input_link")
        if any(item["observation_id"] not in observation_ids for item in row["input_observations"]):
            issues.append("missing_input_observation")
    for row in data["followup_outcomes"]:
        outcomes[row["subject_id"]].append(row)
        if row["subject_id"] not in patients or row["observation_id"] is not None and row["observation_id"] not in observation_ids:
            issues.append("invalid_outcome_link")
    for subject in patients:
        if {r["horizon_months"] for r in packets[subject]} != {6, 12} or len(packets[subject]) != 2 or {r["horizon_months"] for r in outcomes[subject]} != {6, 12} or len(outcomes[subject]) != 2:
            issues.append("missing_horizon")
        if {r["sample_id"] for r in packets[subject]} != {r["sample_id"] for r in outcomes[subject]}:
            issues.append("sample_mismatch")
    for name in ("patients", "observations", "prediction_inputs"):
        for row in data[name]:
            source = row["source"]
            if source["is_synthetic"] is not True or source["source_kind"] != "synthetic" or source["generator_version"] != "synthetic-prediction.v1":
                issues.append("source_mismatch")
    return sorted(set(issues))


def _diversity(data):
    observations = defaultdict(list)
    patients = {p["subject_id"]: p for p in data["patients"]}
    pools = {a["subject_id"]: a["pool"] for a in data["generation_audit"]}
    for row in data["observations"]:
        if row["observation_kind"] == "actual" and row["observation_status"] == "observed" and row["value"] is not None:
            observations[row["subject_id"]].append(row)
    sequences = defaultdict(list)
    for subject, rows in observations.items():
        if subject not in patients or subject not in pools:
            continue
        rows.sort(key=lambda r: (r["measured_on"], r["observation_id"]))
        values = tuple(r["value"] for r in rows)
        first = rows[0]["measured_on"]
        from datetime import date
        times = tuple((date.fromisoformat(r["measured_on"]) - date.fromisoformat(first)).days for r in rows)
        spread = max(max(values) - min(values), 1)
        shape = tuple(round((v - values[0]) / spread, 2) for v in values) if len(values) >= 3 else None
        sequences[(patients[subject]["disease"], pools[subject])].append((subject, values, times, shape))
    details = {}
    for (disease, pool), entries in sorted(sequences.items()):
        value_counts = Counter(e[1] for e in entries)
        relative_counts = Counter((e[2], e[1]) for e in entries)
        shape_counts = Counter((len(e[1]), e[3]) for e in entries if e[3] is not None)
        collisions = []
        for fingerprint, count in sorted(shape_counts.items()):
            if count > 1:
                members = [{"subject_id": e[0], "relative_days": list(e[2]), "values": list(e[1])}
                           for e in entries if (len(e[1]), e[3]) == fingerprint]
                collisions.append({"shape": list(fingerprint[1]), "members": members})
        details[f"{disease}:{pool}"] = {"patients": len(entries), "unique_values": len(value_counts),
                                      "unique_relative_time_values": len(relative_counts),
                                      "exact_duplicate_patients": sum(n - 1 for n in value_counts.values()),
                                      "near_shape_duplicate_patients": sum(n - 1 for n in shape_counts.values()),
                                      "near_shape_collisions": collisions}
    cross_pool = {}
    for disease in ("ad", "fatty_liver"):
        dev = {e[1] for e in sequences[(disease, "development_pool")]}
        challenge = {e[1] for e in sequences[(disease, "challenge_pool")]}
        cross_pool[disease] = len(dev & challenge)
    return _check("passed", "fingerprints_reported", by_pool=details, exact_cross_pool_sequences=cross_pool)


def _shortcuts(data):
    patients = {p["subject_id"]: p for p in data["patients"]}
    pools = {a["subject_id"]: a["pool"] for a in data["generation_audit"]}
    outcomes = {o["sample_id"]: o for o in data["followup_outcomes"]}
    tasks = {}
    statuses = []
    for task in ("ad.mmse.6m", "ad.mmse.12m", "fatty_liver.alt.6m", "fatty_liver.alt.12m"):
        dev = defaultdict(Counter)
        challenge = []
        scored = Counter()
        for packet in data["prediction_inputs"]:
            if packet["task_id"] != task or packet["subject_id"] not in patients or packet["subject_id"] not in pools:
                continue
            outcome = outcomes.get(packet["sample_id"])
            pool = pools[packet["subject_id"]]
            if packet["input_status"] != "available" or not outcome or outcome["status"] != "fixture_observed_at_nominal":
                scored[f"{pool}_skipped"] += 1
                continue
            anchor = next((o["value"] for o in packet["input_observations"] if o["observation_id"] == packet["anchor_observation_id"]), None)
            if anchor is None:
                scored[f"{pool}_unknown"] += 1
                continue
            value = outcome["value"] - anchor
            sign = -1 if value < 0 else 1 if value > 0 else 0
            key = (patients[packet["subject_id"]]["disease"], packet["horizon_months"], patients[packet["subject_id"]]["baseline_stage"], len(packet["input_observations"]) - 1)
            scored[f"{pool}_scored"] += 1
            if pool == "development_pool":
                dev[key][sign] += 1
            else:
                challenge.append((key, sign))
        supported = {key: counts for key, counts in dev.items() if sum(counts.values()) >= 4}
        ambiguous = {key: counts for key, counts in supported.items() if len(counts) >= 2}
        comparable = [(key, sign) for key, sign in challenge if key in dev]
        supported_comparable = [(key, sign) for key, sign in comparable if key in ambiguous]
        correct = sum(sign == sorted(dev[key], key=lambda s: (-dev[key][s], s))[0] for key, sign in comparable)
        if ambiguous and comparable:
            status = "failed" if correct == len(comparable) else "passed"
        elif supported and not ambiguous:
            status = "failed"
        else:
            status = "not_assessable"
        statuses.append(status)
        tasks[task] = {"status": status, **dict(scored), "development_keys": len(dev),
                       "supported_keys": len(supported), "ambiguous_keys": len(ambiguous),
                       "known_challenge": sum(key in dev for key, _ in challenge),
                       "unseen_challenge": sum(key not in dev for key, _ in challenge),
                       "ambiguous_challenge": len(supported_comparable),
                       "comparable_challenge": len(comparable), "correct_challenge": correct,
                       "distributions": {str(key): {str(sign): count for sign, count in sorted(counts.items())} for key, counts in sorted(dev.items())}}
    status = "failed" if "failed" in statuses else "not_assessable" if "not_assessable" in statuses else "passed"
    return _check(status, "lookup_diagnostic", tasks=tasks)


def assess_cohort(cohort: dict) -> dict:
    try:
        if not isinstance(cohort, dict) or any(not isinstance(cohort.get(name), list) for name in COLLECTIONS):
            return _report({"structure": _check("failed", "missing_or_invalid_collections")})
        issues = _validate(cohort)
        checks = {"structure": _check("failed" if issues else "passed", "invalid_structure" if issues else "valid_structure",
                                      patients=len(cohort["patients"]), observations=len(cohort["observations"]), issues=issues)}
        expected_inputs = build_prediction_inputs(cohort["patients"], cohort["observations"])
        expected_outcomes = build_followup_outcomes(cohort["patients"], cohort["observations"])
        mismatch = []
        for name, expected in (("prediction_inputs", expected_inputs), ("followup_outcomes", expected_outcomes)):
            if _canonical(_strip_run_id(cohort[name])) != _canonical(_strip_run_id(expected)):
                mismatch.append(name)
        checks["projection"] = _check("failed" if mismatch else "passed", "projection_mismatch" if mismatch else "recomputed_equal", mismatched=mismatch)
        checks["diversity"] = _diversity(cohort)
        checks["label_shortcut"] = _shortcuts(cohort)
        return _report(checks)
    except (KeyError, TypeError, ValueError, ValidationError, IndexError, AttributeError):
        return _report({"structure": _check("failed", "malformed_records")})


def assess_sequence_variation(base_rows: list[dict], changed_seed_rows: list[dict], expanded_rows: list[dict]) -> dict:
    """Compare measurement content alone; useful for legacy diagnostic rows too."""
    def unique(rows, disease):
        by_subject = defaultdict(list)
        for row in rows:
            if row["disease"] == disease and row["value"] is not None:
                by_subject[row["subject_id"]].append((row["measured_on"], row["value"]))
        return {tuple(value for _, value in sorted(items)) for items in by_subject.values()}

    def measurements(rows):
        return sorted((row["disease"], row["measured_on"] or "", row["value"] if row["value"] is not None else -1)
                      for row in rows)

    counts = {disease: {"base": len(unique(base_rows, disease)), "expanded": len(unique(expanded_rows, disease))}
              for disease in ("ad", "fatty_liver")}
    changed = measurements(base_rows) != measurements(changed_seed_rows)
    growth = {disease: counts[disease]["expanded"] > counts[disease]["base"] for disease in counts}
    return {"status": "passed" if changed and all(growth.values()) else "failed",
            "changed_seed_values_or_dates": changed, "expanded_unique_values": growth,
            "unique_value_sequences": counts}


def assess_generation(config: GenerationConfig, cohort: dict) -> dict:
    report = assess_cohort(cohort)
    try:
        base = generate_cohort(config)
        same = generate_cohort(config)
        exact = _canonical(base) == _canonical(same)
        exported_equal = _canonical(_strip_run_id(base)) == _canonical(_strip_run_id({name: cohort[name] for name in COLLECTIONS}))
        changed = generate_cohort(config.model_copy(update={"seed": config.seed + 1}))
        expanded = generate_cohort(config.model_copy(update={"patients_per_disease": config.patients_per_disease * 2,
                                                       "challenge_per_disease": config.challenge_per_disease * 2}))
        stable = all({row[key]: _strip_run_id(row) for row in expanded[name]} .items() >= {row[key]: _strip_run_id(row) for row in base[name]}.items()
                     for name, key in (("patients", "subject_id"), ("observations", "observation_id"),
                                       ("prediction_inputs", "sample_id"), ("followup_outcomes", "sample_id"),
                                       ("generation_audit", "subject_id")))
        def project(data):
            diseases = {p["subject_id"]: p["disease"] for p in data["patients"]}
            return [{"disease": diseases[row["subject_id"]], "subject_id": row["subject_id"],
                     "measured_on": row["measured_on"], "value": row["value"]}
                    for row in data["observations"] if row["observation_kind"] == "actual" and row["observation_status"] == "observed"]
        variation = assess_sequence_variation(project(base), project(changed), project(expanded))
        passed = exact and exported_equal and stable and variation["status"] == "passed"
        report["checks"]["generation"] = _check("passed" if passed else "failed", "regeneration_checks",
                                                  same_seed_exact=exact, supplied_matches_regeneration=exported_equal,
                                                  changed_seed_values_or_dates=variation["changed_seed_values_or_dates"], expansion_stable=stable,
                                                  expanded_unique_values=variation["expanded_unique_values"],
                                                  unique_value_sequences=variation["unique_value_sequences"])
    except (KeyError, TypeError, ValueError, AttributeError):
        report["checks"]["generation"] = _check("failed", "invalid_generation_inputs")
    return _report(report["checks"])


def assess_fixed_fixtures(fixtures: list[dict], expected_results: list[dict]) -> dict:
    """Exercise current pure validation and the already implemented offline projections."""
    from datetime import date
    from app.schemas.longitudinal_case import OperatorCaseCreate
    from app.services.operator_case_validation import (
        OperatorCaseValidationError, normalize_operator_timeline,
        validate_operator_case_profile,
    )

    try:
        oracle = {row["fixture_id"]: row for row in expected_results}
        offline_issues, api_issues, api_checked, offline_checked = [], [], 0, 0
        if len(oracle) != len(expected_results) or len({f["fixture_id"] for f in fixtures}) != len(fixtures):
            offline_issues.append("duplicate_fixture_id")
            api_issues.append("duplicate_fixture_id")
        by_id = {f["fixture_id"]: f for f in fixtures}
        if set(by_id) != set(oracle):
            offline_issues.append("fixture_oracle_mismatch")
            api_issues.append("fixture_oracle_mismatch")
        required = {f"S{scenario:02d}-{disease}" for scenario in range(1, 21)
                    for disease in ("ad", "fatty_liver")}
        covered = {f"{fixture['scenario_id']}-{fixture['disease']}" for fixture in fixtures}
        variants = {f"S12-{disease}-{variant}" for disease in ("ad", "fatty_liver")
                    for variant in ("base", "future_changed")}
        variants |= {f"S18-{disease}-{variant}" for disease in ("ad", "fatty_liver")
                     for variant in ("base", "source_copy", "related")}
        if not required <= covered or not variants <= set(by_id):
            offline_issues.append("missing_required_fixtures")
            api_issues.append("missing_required_fixtures")
        for fixture in fixtures:
            fid = fixture["fixture_id"]
            if fid not in oracle:
                continue
            expected = oracle[fid]
            request = fixture.get("api_request")
            if request is not None:
                api_checked += 1
                try:
                    parsed = OperatorCaseCreate.model_validate({**request, "disease_id": 1})
                    validate_operator_case_profile(fixture["disease"], parsed.age, parsed.sex, parsed.baseline_stage)
                    normalized = normalize_operator_timeline(fixture["disease"], parsed.visits)
                    actual_status, actual_reason = "accept", None
                    if fid.startswith("S09-") and [v.visit_date for v in normalized] != sorted(v.visit_date for v in normalized):
                        api_issues.append(fid + ":normalization")
                except ValidationError:
                    actual_status, actual_reason = "reject", "schema"
                except OperatorCaseValidationError as exc:
                    actual_status, actual_reason = "reject", exc.code
                target = expected["current_api"]
                if actual_status != target["status"] or (actual_reason == "schema" and not str(target["reason"]).startswith("schema_")) or (actual_reason not in (None, "schema") and actual_reason != target["reason"]):
                    api_issues.append(fid + ":api")
            patient = fixture["patients"][0]
            inputs = build_prediction_inputs([patient], fixture["observations"])
            outcomes = build_followup_outcomes([patient], fixture["observations"])
            offline_checked += 1
            offline = expected["offline"]
            values = expected.get("expected_values", {})
            for horizon in (6, 12):
                h = f"{horizon}m"
                actual = next(row for row in outcomes if row["horizon_months"] == horizon)
                wanted = offline.get(h)
                if wanted == "ineligible_anchor":
                    if next(row for row in inputs if row["horizon_months"] == horizon)["input_status"] != "unavailable":
                        offline_issues.append(fid + ":" + h)
                elif wanted and wanted != actual["status"]:
                    offline_issues.append(fid + ":" + h)
            if "d03_history_count" in offline:
                state = inputs[0]["history_state"]
                count = len(inputs[0]["input_observations"]) - (1 if inputs[0]["anchor_observation_id"] else 0)
                actual_count = None if state == "unknown" else count
                if actual_count != offline["d03_history_count"]:
                    offline_issues.append(fid + ":history_count")
            if "conflict" in offline and offline["conflict"] == "preserve_no_averaging":
                if fixture["variant"] == "duplicate_day" and inputs[0]["input_status"] != "unavailable":
                    offline_issues.append(fid + ":conflict")
            if offline.get("unit") == "normalized_to_canonical":
                if inputs[0]["input_status"] != "available" or next(o for o in inputs[0]["input_observations"] if o["observation_id"] == inputs[0]["anchor_observation_id"])["unit"] != values.get("canonical_unit", "分" if fixture["disease"] == "ad" else "U/L"):
                    offline_issues.append(fid + ":canonical_unit")
            if "baseline_absolute_errors" in values:
                anchor = next(r["value"] for r in fixture["observations"] if r["role"] == "anchor")
                targets = [next(o for o in outcomes if o["horizon_months"] == h) for h in (6, 12)]
                if [abs(o["value"] - anchor) for o in targets] != values["baseline_absolute_errors"]:
                    offline_issues.append(fid + ":baseline_errors")
                if [o["value"] for o in targets] != values["targets"] or [o["nominal_date"] for o in targets] != values["target_dates"]:
                    offline_issues.append(fid + ":literal_targets")
            for h in (6, 12):
                if f"{h}m_target_date" in values and next(o for o in outcomes if o["horizon_months"] == h)["nominal_date"] != values[f"{h}m_target_date"]:
                    offline_issues.append(fid + ":calendar")
                if f"{h}m_offset_days" in values:
                    o = next(o for o in outcomes if o["horizon_months"] == h)
                    if (date.fromisoformat(o["actual_date"]) - date.fromisoformat(o["nominal_date"])).days != values[f"{h}m_offset_days"]:
                        offline_issues.append(fid + ":offset")
            if "accepted_anchor" in values and next(r["value"] for r in fixture["observations"] if r["role"] == "anchor") != values["accepted_anchor"]:
                offline_issues.append(fid + ":boundary")
            if "input_equivalent_to" in offline:
                peer = by_id.get(offline["input_equivalent_to"])
                if peer:
                    left = _strip_run_id(build_prediction_inputs([patient], fixture["observations"]))
                    right = _strip_run_id(build_prediction_inputs([peer["patients"][0]], peer["observations"]))
                    if left != right:
                        offline_issues.append(fid + ":future_isolation")
            if "deduplicated_measurement_count" in offline:
                dedup = {_canonical(r) for r in fixture["observations"]}
                if len(dedup) != offline["deduplicated_measurement_count"]:
                    offline_issues.append(fid + ":dedup")
                if build_prediction_inputs([patient], fixture["observations"] + [fixture["observations"][0]]) != inputs:
                    offline_issues.append(fid + ":duplicate_input")
            counts = expected.get("expected_counts", {})
            if "patients" in counts and len(fixture["patients"]) != counts["patients"]:
                offline_issues.append(fid + ":patient_count")
            if "dependency_groups" in counts and len({p["dependency_group_id"] for p in fixture["patients"]}) != counts["dependency_groups"]:
                offline_issues.append(fid + ":group_count")
        return _report({"fixture_offline": _check("failed" if offline_issues else "passed", "fixture_checks", checked=offline_checked, issues=sorted(set(offline_issues)),
                                                  future_consumers_not_run=["new_task_scorer", "old_report_route", "database_integration"]),
                        "fixture_current_api": _check("failed" if api_issues else "passed", "pure_api_validation", checked=api_checked, issues=sorted(set(api_issues))),
                        })
    except (KeyError, TypeError, ValueError, ValidationError, IndexError, AttributeError):
        return _report({"fixture_offline": _check("failed", "malformed_fixture_or_oracle")})
