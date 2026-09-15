"""Literal, offline checks for the versioned synthetic counterexamples."""

import json

import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_case import OperatorCaseCreate
from app.services.operator_case_validation import (
    OperatorCaseValidationError,
    normalize_operator_timeline,
    validate_operator_case_profile,
)
from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
from app.services.synthetic_prediction_cases import build_prediction_inputs, build_followup_outcomes, canonical_json
from app.services.longitudinal_task_routing import route_outcome_task


@pytest.fixture(scope="module")
def cases():
    fixtures, results = build_fixed_fixtures()
    return {(f["scenario_id"], f["disease"], f["variant"]): (f, next(r for r in results if r["fixture_id"] == f["fixture_id"])) for f in fixtures}


@pytest.mark.parametrize("disease,anchor,targets,errors", [
    ("ad", 22, (21, 19), (1, 3)),
    ("fatty_liver", 60, (55, 70), (5, 10)),
])
def test_s01_literal_baseline(cases, disease, anchor, targets, errors):
    fixture, expected = cases["S01", disease, "base"]
    assert [o["value"] for o in fixture["observations"]] == ([25, 24, 22, *targets] if disease == "ad" else [58, 63, 60, *targets])
    assert expected["expected_values"]["anchor"] == anchor
    assert expected["expected_values"]["targets"] == list(targets)
    assert expected["expected_values"]["baseline_absolute_errors"] == list(errors)


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s02_s03_zero_versus_unknown(cases, disease):
    zero = cases["S02", disease, "base"][1]["offline"]
    unknown = cases["S03", disease, "base"][1]["offline"]
    assert zero["d03_history_count"] == zero["d03_history_span_days"] == 0
    assert unknown["d03_history_count"] is None
    assert unknown["d03_history_span_days"] is None


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s12_future_mutation_does_not_touch_request(cases, disease):
    base = cases["S12", disease, "base"][0]
    changed = cases["S12", disease, "future_changed"][0]
    assert json.dumps(base["api_request"], sort_keys=True) == json.dumps(changed["api_request"], sort_keys=True)
    assert base["patients"] == changed["patients"]
    assert base["observations"] != changed["observations"]


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s18_related_patients_share_group_but_not_identity(cases, disease):
    fixture, expected = cases["S18", disease, "related"]
    assert len({p["subject_id"] for p in fixture["patients"]}) == 2
    assert len({p["dependency_group_id"] for p in fixture["patients"]}) == 1
    assert expected["expected_counts"]["patients"] == 2


def test_every_scenario_has_both_diseases_and_explicit_sources(cases):
    assert {scenario for scenario, _, _ in cases} == {f"S{i:02d}" for i in range(1, 21)}
    for scenario in {f"S{i:02d}" for i in range(1, 21)}:
        assert {disease for key, disease, _ in cases if key == scenario} == {"ad", "fatty_liver"}
    for (fixture, result) in cases.values():
        assert fixture["patients"] and fixture["observations"]
        assert all(p["source"]["is_synthetic"] and p["source"]["source_kind"] == "synthetic" for p in fixture["patients"])
        assert all(o["source"]["is_synthetic"] and o["source"]["source_kind"] == "synthetic" for o in fixture["observations"])
        assert result["offline"]
        assert "disease_id" not in (fixture["api_request"] or {})
        assert all(v["visit_date"] <= fixture["patients"][0]["anchor_date"] for v in fixture["api_request"]["visits"])


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_current_api_accepts_or_rejects_literal_examples(cases, disease):
    for (scenario, code, variant), (fixture, expected) in cases.items():
        if code != disease or fixture["api_request"] is None:
            continue
        request = {**fixture["api_request"], "disease_id": 1}
        status = expected["current_api"]["status"]
        reason = expected["current_api"]["reason"]
        try:
            parsed = OperatorCaseCreate.model_validate(request)
            validate_operator_case_profile(code, parsed.age, parsed.sex, parsed.baseline_stage)
            normalized = normalize_operator_timeline(code, parsed.visits)
        except ValidationError:
            assert status == "reject" and reason.startswith("schema_"), (scenario, variant)
        except OperatorCaseValidationError as exc:
            assert status == "reject" and reason == exc.code, (scenario, variant, exc.code)
        else:
            assert status == "accept", (scenario, variant)
            assert normalized


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s09_reorders_context_and_indicator_together(cases, disease):
    fixture = cases["S09", disease, "base"][0]
    parsed = OperatorCaseCreate.model_validate({**fixture["api_request"], "disease_id": 1})
    normalized = normalize_operator_timeline(disease, parsed.visits)
    assert [v.visit_date.isoformat() for v in normalized] == ["2023-01-31", "2024-01-31"]
    assert [v.visit_context["method"] for v in normalized] == ["synthetic_fixture_earlier", "synthetic_fixture_anchor"]
    assert [v.indicators[0]["value"] for v in normalized] == ([24.0, 22.0] if disease == "ad" else [63.0, 60.0])


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s18_copies_and_related_observations_are_real(cases, disease):
    base = cases["S18", disease, "base"][0]
    duplicate = cases["S18", disease, "source_copy"][0]
    related = cases["S18", disease, "related"][0]
    assert len(duplicate["observations"]) > len(base["observations"])
    assert len({o["observation_id"] for o in duplicate["observations"]}) < len(duplicate["observations"])
    assert {o["subject_id"] for o in related["observations"]} == {p["subject_id"] for p in related["patients"]}


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_future_statuses_and_calendar_literals(cases, disease):
    assert cases["S06", disease, "base"][1]["offline"]["6m"] == "confirmed_unobserved"
    assert cases["S07", disease, "base"][1]["offline"]["6m"] == "pending_observation"
    assert cases["S08", disease, "early"][1]["expected_values"]["6m_offset_days"] == -7
    assert cases["S08", disease, "late"][1]["expected_values"]["6m_offset_days"] == 21
    leap = cases["S08", disease, "leap_day"][0]
    assert leap["patients"][0]["anchor_date"] == "2024-02-29"
    assert [o["measured_on"] for o in leap["observations"] if o["role"] == "followup"] == ["2024-08-29", "2025-02-28"]


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_unknown_and_incompatible_methods_remain_distinct(cases, disease):
    assert cases["S17", disease, "method_unknown"][1]["offline"]["6m"] == "pending_comparability"
    assert cases["S17", disease, "method_incompatible"][1]["offline"]["6m"] == "incomparable"
    assert cases["S20", disease, "diagnosis_unknown"][1]["offline"]["population"] == "pending"
    assert cases["S20", disease, "diagnosis_excluded"][1]["offline"]["population"] == "excluded"


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s02_s03_real_input_history_state(cases, disease):
    zero = cases["S02", disease, "base"][0]
    unknown = cases["S03", disease, "base"][0]
    zero_inputs = build_prediction_inputs(zero["patients"], zero["observations"])
    unknown_inputs = build_prediction_inputs(unknown["patients"], unknown["observations"])
    assert {item["history_state"] for item in zero_inputs} == {"confirmed_none"}
    assert {item["history_state"] for item in unknown_inputs} == {"unknown"}
    assert all(item["input_status"] == "available" for item in zero_inputs + unknown_inputs)


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s12_real_prediction_packets_identical(cases, disease):
    base = cases["S12", disease, "base"][0]
    changed = cases["S12", disease, "future_changed"][0]
    assert canonical_json(build_prediction_inputs(base["patients"], base["observations"])) == canonical_json(build_prediction_inputs(changed["patients"], changed["observations"]))


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s17_real_outcome_comparability(cases, disease):
    for variant, status in (("method_unknown", "pending_comparability"), ("method_incompatible", "incomparable")):
        fixture = cases["S17", disease, variant][0]
        outcome = build_followup_outcomes(fixture["patients"], fixture["observations"])
        assert {item["horizon_months"]: item["status"] for item in outcome} == {6: status, 12: "fixture_observed_at_nominal"}


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s11_current_request_respects_known_at_anchor(cases, disease):
    for variant in ("late_known", "unknown_known"):
        fixture = cases["S11", disease, variant][0]
        assert [visit["visit_date"] for visit in fixture["api_request"]["visits"]] == ["2024-01-31"]
        assert build_prediction_inputs(fixture["patients"], fixture["observations"])[0]["history_state"] == "unknown"


@pytest.mark.parametrize("disease", ["ad", "fatty_liver"])
def test_s19_existing_route_literal(cases, disease):
    fixture, expected = cases["S19", disease, "base"]
    route = route_outcome_task(disease, fixture["patients"][0]["baseline_stage"])
    if disease == "ad":
        assert route.reason_code == expected["offline"]["old_route"] == "task_not_applicable_terminal_stage"
    else:
        assert route.routing_status == "selected"
        assert route.normalized_stage == "cirrhosis"
