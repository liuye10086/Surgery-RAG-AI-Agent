from copy import deepcopy
import json

from app.schemas.synthetic_prediction_cases import GenerationConfig
from app.services.synthetic_prediction_cases import generate_cohort
from app.services.synthetic_prediction_quality import assess_cohort, assess_generation, assess_fixed_fixtures, assess_sequence_variation
from app.services.synthetic_prediction_fixtures import build_fixed_fixtures


def cohort():
    return generate_cohort(GenerationConfig())


def test_default_passes_and_reports_real_denominators():
    report = assess_generation(GenerationConfig(), cohort())
    assert report["status"] == "passed", report
    assert report["checks"]["structure"]["patients"] == 240
    assert report["checks"]["label_shortcut"]["tasks"]["ad.mmse.6m"]["comparable_challenge"] > 0
    assert json.loads(json.dumps(report, ensure_ascii=False)) == report
    counts = report["checks"]["generation"]["unique_value_sequences"]
    assert all(counts[d]["expanded"] > counts[d]["base"] for d in ("ad", "fatty_liver"))


def test_actual_legacy_demo_has_static_seed_and_nonexpanding_templates():
    from app.services.longitudinal_demonstration_data import build_demonstration_case_rows

    def project(count, seed):
        return [{"disease": row["disease_code"], "subject_id": row["patient_label"],
                 "measured_on": row["metadata"]["visit_date"],
                 "value": next(i["value"] for i in row["indicators"] if i["name"] == ("mmse" if row["disease_code"] == "ad" else "alt"))}
                for row in build_demonstration_case_rows(patients_per_disease=count, seed=seed)]

    base, other_seed, expanded = project(30, 20260827), project(30, 20260828), project(300, 20260827)
    result = assess_sequence_variation(base, other_seed, expanded)
    assert result["status"] == "failed"
    assert result["changed_seed_values_or_dates"] is False
    assert result["unique_value_sequences"] == {"ad": {"base": 5, "expanded": 5},
                                                 "fatty_liver": {"base": 7, "expanded": 7}}


def test_all_known_challenge_lookup_hits_fail_shortcut_gate():
    data = cohort()
    report = assess_cohort(data)
    pools = {a["subject_id"]: a["pool"] for a in data["generation_audit"]}
    stages = {p["subject_id"]: p["baseline_stage"] for p in data["patients"]}
    outcomes = {o["sample_id"]: o for o in data["followup_outcomes"]}
    for packet in data["prediction_inputs"]:
        if pools[packet["subject_id"]] != "challenge_pool":
            continue
        outcome = outcomes[packet["sample_id"]]
        if outcome["status"] != "fixture_observed_at_nominal":
            continue
        key = str((packet["task_id"].split(".")[0], packet["horizon_months"],
                   stages[packet["subject_id"]], len(packet["input_observations"]) - 1))
        distribution = report["checks"]["label_shortcut"]["tasks"][packet["task_id"]]["distributions"].get(key)
        if distribution:
            sign = sorted(distribution, key=lambda s: (-distribution[s], int(s)))[0]
            anchor = next(o["value"] for o in packet["input_observations"] if o["observation_id"] == packet["anchor_observation_id"])
            outcome["value"] = anchor + int(sign)
    shortcut = assess_cohort(data)["checks"]["label_shortcut"]
    assert shortcut["status"] == "failed"
    assert all(task["correct_challenge"] == task["comparable_challenge"] for task in shortcut["tasks"].values())


def test_shortcut_support_need_not_share_the_challenge_key():
    from app.services.synthetic_prediction_quality import _shortcuts
    data = cohort()
    original = _shortcuts(data)["tasks"]["ad.mmse.6m"]
    ambiguous = {key for key, counts in original["distributions"].items()
                 if sum(counts.values()) >= 4 and len(counts) >= 2}
    other = {key for key in original["distributions"] if key not in ambiguous}
    pools = {a["subject_id"]: a["pool"] for a in data["generation_audit"]}
    stages = {p["subject_id"]: p["baseline_stage"] for p in data["patients"]}
    outcomes = {o["sample_id"]: o for o in data["followup_outcomes"]}
    chosen = next(p for p in data["prediction_inputs"]
                  if p["task_id"] == "ad.mmse.6m" and pools[p["subject_id"]] == "challenge_pool"
                  and outcomes[p["sample_id"]]["status"] == "fixture_observed_at_nominal"
                  and str(("ad", 6, stages[p["subject_id"]], len(p["input_observations"]) - 1)) in other)
    for outcome in data["followup_outcomes"]:
        if outcome["sample_id"] != chosen["sample_id"] and pools[outcome["subject_id"]] == "challenge_pool":
            outcome["status"] = "pending_observation"
            outcome["value"] = None
    result = _shortcuts(data)["tasks"]["ad.mmse.6m"]
    assert result["ambiguous_keys"] > 0
    assert result["comparable_challenge"] == 1
    assert result["ambiguous_challenge"] == 0
    assert result["status"] in {"passed", "failed"}


def test_tampered_input_and_future_input_fail():
    data = cohort()
    data["prediction_inputs"][0]["input_observations"][0]["value"] = 999
    assert assess_cohort(data)["checks"]["projection"]["status"] == "failed"
    data = cohort()
    data["prediction_inputs"][0]["input_observations"][0]["known_on"] = "2099-01-01"
    assert assess_cohort(data)["status"] == "failed"


def test_missing_and_foreign_links_fail():
    data = cohort()
    data["observations"].pop()
    assert assess_cohort(data)["status"] == "failed"
    data = cohort()
    data["followup_outcomes"][0]["subject_id"] = "foreign"
    assert assess_cohort(data)["checks"]["structure"]["status"] == "failed"


def test_shared_dependency_cannot_cross_pools():
    data = cohort()
    dev = next(a for a in data["generation_audit"] if a["pool"] == "development_pool")
    challenge = next(a for a in data["generation_audit"] if a["pool"] == "challenge_pool")
    challenge["dependency_group_id"] = dev["dependency_group_id"]
    patient = next(p for p in data["patients"] if p["subject_id"] == challenge["subject_id"])
    patient["dependency_group_id"] = dev["dependency_group_id"]
    for packet in data["prediction_inputs"]:
        if packet["subject_id"] == patient["subject_id"]:
            packet["dependency_group_id"] = dev["dependency_group_id"]
    assert assess_cohort(data)["checks"]["structure"]["status"] == "failed"


def test_small_cohort_has_unknown_support_without_fabricated_pass():
    data = generate_cohort(GenerationConfig(patients_per_disease=3, challenge_per_disease=1))
    report = assess_cohort(data)
    assert report["status"] == "not_assessable"
    assert report["checks"]["label_shortcut"]["status"] == "not_assessable"


def test_repeated_tiny_templates_are_visible_without_deleting_patients():
    data = cohort()
    ad = [p for p in data["patients"] if p["disease"] == "ad"]
    template = [24.0, 22.0, 21.0]
    for patient in ad:
        rows = sorted((r for r in data["observations"] if r["subject_id"] == patient["subject_id"] and r["value"] is not None),
                      key=lambda r: (r["measured_on"], r["observation_id"]))
        for index, row in enumerate(rows):
            row["value"] = template[index % 3]
    from app.services.synthetic_prediction_cases import build_prediction_inputs, build_followup_outcomes
    data["prediction_inputs"] = build_prediction_inputs(data["patients"], data["observations"])
    data["followup_outcomes"] = build_followup_outcomes(data["patients"], data["observations"])
    report = assess_cohort(data)
    pools = report["checks"]["diversity"]["by_pool"]
    assert pools["ad:development_pool"]["exact_duplicate_patients"] > 0
    assert pools["ad:challenge_pool"]["exact_duplicate_patients"] > 0
    assert pools["ad:development_pool"]["near_shape_collisions"]
    assert "relative_days" in pools["ad:development_pool"]["near_shape_collisions"][0]["members"][0]
    assert report["checks"]["structure"]["patients"] == 240


def test_malformed_input_is_diagnosed():
    report = assess_cohort({"patients": []})
    assert report["status"] == "failed"


def test_exported_run_id_does_not_break_generation_comparison():
    data = cohort()
    def fill(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "source":
                    child["run_id"] = "syn-test"
                else:
                    fill(child)
        elif isinstance(value, list):
            for child in value:
                fill(child)
    fill(data)
    assert assess_generation(GenerationConfig(), data)["status"] == "passed"


def test_fixed_fixtures_check_literal_answers_and_future_isolation():
    fixtures, expected = build_fixed_fixtures()
    report = assess_fixed_fixtures(fixtures, expected)
    assert report["status"] == "passed", report
    assert report["checks"]["fixture_offline"]["checked"] == len(fixtures)
    changed = deepcopy(expected)
    next(row for row in changed if row["fixture_id"] == "S01-ad-base")["expected_values"]["baseline_absolute_errors"] = [9, 9]
    assert assess_fixed_fixtures(fixtures, changed)["checks"]["fixture_offline"]["status"] == "failed"
    assert assess_fixed_fixtures(fixtures, changed)["checks"]["fixture_current_api"]["status"] == "passed"


def test_fixture_history_and_alias_oracles_are_exercised():
    fixtures, expected = build_fixed_fixtures()
    changed = deepcopy(expected)
    next(r for r in changed if r["fixture_id"] == "S02-ad-base")["offline"]["d03_history_count"] = 1
    assert assess_fixed_fixtures(fixtures, changed)["checks"]["fixture_offline"]["status"] == "failed"
    changed = deepcopy(fixtures)
    alias = next(r for r in changed if r["fixture_id"] == "S14-ad-approved_alias")
    next(r for r in alias["observations"] if r["role"] == "anchor")["unit"] = "mg/dL"
    assert assess_fixed_fixtures(changed, expected)["checks"]["fixture_offline"]["status"] == "failed"


def test_empty_and_jointly_deleted_fixed_scenarios_cannot_pass():
    assert assess_fixed_fixtures([], [])["status"] != "passed"
    fixtures, expected = build_fixed_fixtures()
    fixtures = [row for row in fixtures if row["scenario_id"] != "S18"]
    expected = [row for row in expected if not row["fixture_id"].startswith("S18-")]
    report = assess_fixed_fixtures(fixtures, expected)
    assert report["status"] != "passed"
    assert "missing_required_fixtures" in report["checks"]["fixture_offline"]["issues"]
