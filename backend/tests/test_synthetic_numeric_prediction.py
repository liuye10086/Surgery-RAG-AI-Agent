from copy import deepcopy

import pytest


def service():
    from app.services import synthetic_numeric_prediction
    return synthetic_numeric_prediction


def literal_input(disease="ad", anchor="2023-08-31"):
    indicator, unit, value = ("mmse", "分", 22.0) if disease == "ad" else ("alt", "U/L", 47.5)
    source = {"source_kind": "synthetic", "is_synthetic": True,
              "generator_version": "synthetic-prediction.v1", "run_id": "syn-literal"}
    packets = []
    for horizon in (6, 12):
        packets.append({
            "sample_id": f"subject:{horizon}m", "subject_id": "subject", "dependency_group_id": "group",
            "task_id": f"{disease}.{indicator}.{horizon}m", "horizon_months": horizon,
            "anchor_date": anchor, "anchor_observation_id": "anchor",
            "input_observations": [
                {"observation_id": "previous", "indicator": indicator, "measured_on": "2023-01-01",
                 "known_on": "2023-01-02", "value": 24.0, "unit": unit, "method": "fixture"},
                {"observation_id": "anchor", "indicator": indicator, "measured_on": anchor,
                 "known_on": anchor, "value": value, "unit": unit, "method": "fixture"}],
            "input_status": "available", "input_reason": None,
            "history_coverage": "complete", "history_state": "observed", "source": deepcopy(source),
        })
    return {"schema_version": "synthetic_numeric_input.v1", "disease_code": disease,
            "subject_id": "subject", "dependency_group_id": "group", "anchor_date": anchor,
            "source": {**source, "manifest_sha256": "a" * 64, "input_file_sha256": "b" * 64},
            "packets": packets}


@pytest.mark.parametrize("disease,value,unit", [("ad", 22.0, "分"), ("fatty_liver", 47.5, "U/L")])
def test_calendar_and_constant_values(disease, value, unit):
    m = service()
    raw = literal_input(disease)
    before = deepcopy(raw)
    result = m.predict_synthetic_numeric(raw)
    assert [(r.horizon_months, r.target_date.isoformat(), r.value, r.unit) for r in result.predictions] == [
        (6, "2024-02-29", value, unit), (12, "2024-08-31", value, unit)]
    assert [r.task_id for r in result.predictions] == [p["task_id"] for p in raw["packets"]]
    assert all(r.status == "available" and r.reason is None for r in result.predictions)
    assert result.algorithm.model_id == "last_value"
    assert result.algorithm.clinical_validity_claim is False
    assert result.algorithm.production_enabled is False
    assert result.input_sha256 == m.numeric_input_sha256(raw)
    assert m.validate_numeric_prediction(result, raw, result.algorithm) == result
    assert raw == before


@pytest.mark.parametrize("anchor,expected", [
    ("2024-02-29", ["2024-08-29", "2025-02-28"]),
    ("2024-08-31", ["2025-02-28", "2025-08-31"]),
])
def test_calendar_month_end_and_leap_year(anchor, expected):
    result = service().predict_synthetic_numeric(literal_input(anchor=anchor))
    assert [r.target_date.isoformat() for r in result.predictions] == expected


@pytest.mark.parametrize("state,coverage", [("confirmed_none", "complete"), ("unknown", "unknown")])
def test_absent_or_unknown_history_does_not_block_baseline(state, coverage):
    raw = literal_input()
    for p in raw["packets"]:
        p["input_observations"] = p["input_observations"][1:]
        p["history_state"], p["history_coverage"] = state, coverage
    result = service().predict_synthetic_numeric(raw)
    assert [r.value for r in result.predictions] == [22.0, 22.0]
    assert raw["packets"][0]["history_state"] == state


@pytest.mark.parametrize("reason", ["anchor_unavailable", "population_not_confirmed",
                                   "population_not_known_at_anchor", "conflicting_history"])
def test_unavailable_keeps_specific_reason(reason):
    raw = literal_input()
    for p in raw["packets"]:
        p["input_status"], p["input_reason"] = "unavailable", reason
        if reason == "anchor_unavailable":
            p["anchor_observation_id"], p["input_observations"] = None, []
            p["history_state"] = "unknown"
        elif reason == "conflicting_history":
            p["input_observations"] = p["input_observations"][1:]
            p["history_state"] = "unknown"
    result = service().predict_synthetic_numeric(raw)
    assert [(r.status, r.value, r.reason) for r in result.predictions] == [("unavailable", None, reason)] * 2


@pytest.mark.parametrize("path,value", [
    (("disease_code",), "fatty_liver"), (("subject_id",), "other"),
    (("dependency_group_id",), "other"), (("anchor_date",), "2023-09-01"),
    (("source", "run_id"), "other"), (("source", "run_id"), None),
    (("source", "manifest_sha256"), "bad"), (("source", "input_file_sha256"), "b" * 63),
    (("source", "source_kind"), "real"), (("source", "is_synthetic"), False),
    (("source", "is_synthetic"), 1), (("source", "generator_version"), "unknown"),
    (("packets", 0, "task_id"), "ad.mmse.12m"),
    (("packets", 0, "horizon_months"), 12), (("packets", 0, "horizon_months"), 6.0),
    (("packets", 0, "sample_id"), "subject:12m"),
    (("packets", 0, "source", "run_id"), "other"),
    (("packets", 0, "source", "is_synthetic"), 1),
    (("packets", 0, "input_observations", 1, "value"), 23.0),
    (("packets", 0, "anchor_observation_id"), "missing"),
    (("packets", 0, "input_reason"), "unexpected"),
    (("packets", 0, "history_state"), "confirmed_none"),
    (("packets", 0, "input_status"), "unavailable"),
    (("followup_outcomes",), []), (("packets", 0, "actual"), 24),
])
def test_rejects_inconsistent_or_untrusted_envelope(path, value):
    raw = literal_input()
    target = raw
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        service().predict_synthetic_numeric(raw)


@pytest.mark.parametrize("field,value", [
    ("known_on", "2023-09-01"), ("measured_on", "2023-09-01"),
    ("known_on", "2023-08-30"), ("measured_on", "2023-08-30"),
    ("measured_on", 1693440000), ("indicator", "alt"), ("unit", "points"),
    ("method", "different"), ("method", ""), ("value", float("nan")),
    ("value", float("inf")), ("value", True), ("value", "22"),
    ("value", -1), ("value", 31), ("value", None),
])
def test_rejects_invalid_observation_even_when_both_packets_match(field, value):
    raw = literal_input()
    for p in raw["packets"]:
        p["input_observations"][1][field] = value
    with pytest.raises(ValueError):
        service().predict_synthetic_numeric(raw)


@pytest.mark.parametrize("mutation", ["missing_packet", "duplicate_packet", "duplicate_id", "duplicate_date",
                                     "missing_anchor", "false_zero_history", "false_observed_history", "unknown_reason"])
def test_rejects_structurally_invalid_inputs(mutation):
    raw = literal_input()
    if mutation == "missing_packet":
        raw["packets"].pop()
    elif mutation == "duplicate_packet":
        raw["packets"][1] = deepcopy(raw["packets"][0])
    else:
        for p in raw["packets"]:
            if mutation == "duplicate_id":
                p["input_observations"].append(deepcopy(p["input_observations"][0]))
            elif mutation == "duplicate_date":
                duplicate = deepcopy(p["input_observations"][0])
                duplicate["observation_id"] = "duplicate"
                p["input_observations"].append(duplicate)
            elif mutation == "missing_anchor":
                p["anchor_observation_id"] = None
            elif mutation == "false_zero_history":
                p["history_state"] = "confirmed_none"
            elif mutation == "false_observed_history":
                p["input_observations"] = p["input_observations"][1:]
            elif mutation == "unknown_reason":
                p["input_status"], p["input_reason"] = "unavailable", "anything"
    with pytest.raises(ValueError):
        service().predict_synthetic_numeric(raw)


def test_order_does_not_change_identity_or_predictions_but_input_change_does():
    m = service()
    raw = literal_input()
    reordered = deepcopy(raw)
    reordered["packets"].reverse()
    for p in reordered["packets"]:
        p["input_observations"].reverse()
    assert m.numeric_input_sha256(raw) == m.numeric_input_sha256(reordered)
    assert m.predict_synthetic_numeric(raw) == m.predict_synthetic_numeric(reordered)
    changed = deepcopy(raw)
    for p in changed["packets"]:
        p["input_observations"][0]["value"] = 25.0
    assert m.numeric_input_sha256(raw) != m.numeric_input_sha256(changed)
    assert [p.value for p in m.predict_synthetic_numeric(changed).predictions] == [22.0, 22.0]


@pytest.mark.parametrize("path,value", [
    (("predictions", 0, "value"), 21.0), (("predictions", 0, "value"), float("inf")),
    (("predictions", 0, "unit"), "U/L"), (("predictions", 0, "target_date"), "2024-02-28"),
    (("predictions", 0, "horizon_months"), 12), (("predictions", 0, "status"), "unavailable"),
    (("predictions", 0, "reason"), "anchor_unavailable"),
    (("predictions", 0, "prediction_interval"), [20, 24]),
    (("source", "run_id"), "other"), (("subject_id",), "other"),
    (("input_sha256",), "c" * 64), (("algorithm", "implementation_sha256"), "c" * 64),
    (("algorithm", "production_enabled"), True),
])
def test_result_binding_rejects_tampering(path, value):
    m = service()
    raw = literal_input()
    result = m.predict_synthetic_numeric(raw)
    modified = result.model_dump(mode="json")
    target = modified
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        m.validate_numeric_prediction(modified, raw, result.algorithm)


def test_pinned_algorithm_mismatch_fails_before_prediction():
    m = service()
    identity = m.numeric_algorithm_identity()
    assert identity == m.numeric_algorithm_identity()
    assert len(identity.implementation_sha256) == 64
    assert len(identity.parameters_sha256) == 64
    changed = identity.model_dump()
    changed["implementation_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="numeric_algorithm_mismatch"):
        m.predict_synthetic_numeric(literal_input(), expected_algorithm=changed)
    assert m.predict_synthetic_numeric(literal_input(), expected_algorithm=identity).algorithm == identity


def test_mutated_model_instances_are_revalidated():
    from app.schemas.synthetic_numeric_prediction import SyntheticNumericInput
    raw = SyntheticNumericInput.model_validate(literal_input())
    raw.packets[0].input_observations[1].value = float("inf")
    with pytest.raises(ValueError):
        service().predict_synthetic_numeric(raw)


def test_calculation_error_does_not_become_unavailable(monkeypatch):
    m = service()
    monkeypatch.setattr(m, "predict_baselines", lambda _: [
        {"sample_id": "subject:6m", "model_id": "last_value", "status": "error",
         "value": None, "reason": "nonfinite_prediction"}])
    with pytest.raises(ValueError, match="numeric_calculation_failed"):
        m.predict_synthetic_numeric(literal_input())


def test_loaded_algorithm_cannot_claim_changed_disk_implementation(monkeypatch):
    from pathlib import Path

    m = service()
    saved = m.predict_synthetic_numeric(literal_input())
    original_read = Path.read_bytes

    def changed_read(path):
        content = original_read(path)
        return content + b"\n# changed implementation\n" if path.name == "prediction_calculation.py" else content

    monkeypatch.setattr(Path, "read_bytes", changed_read)
    with pytest.raises(ValueError, match="numeric_implementation_changed"):
        m.predict_synthetic_numeric(literal_input())
    # Reading a saved result binds to its saved algorithm, not active files.
    assert m.validate_numeric_prediction(saved, literal_input(), saved.algorithm) == saved


def test_all_fixed_synthetic_packets_reuse_baseline_without_future_targets():
    from app.services.synthetic_prediction_cases import build_prediction_inputs
    from app.services.synthetic_prediction_fixtures import build_fixed_fixtures
    from app.services.prediction_calculation import project_calculation_inputs, predict_baselines

    m = service()
    for fixture in build_fixed_fixtures()[0]:
        packets = build_prediction_inputs(fixture["patients"], fixture["observations"])
        for p in packets:
            p["source"]["run_id"] = "syn-fixed"
        for patient in fixture["patients"]:
            selected = [p for p in packets if p["subject_id"] == patient["subject_id"]]
            raw = {"disease_code": patient["disease"], "subject_id": patient["subject_id"],
                   "dependency_group_id": patient["dependency_group_id"], "anchor_date": patient["anchor_date"],
                   "source": {**selected[0]["source"], "manifest_sha256": "a" * 64, "input_file_sha256": "b" * 64},
                   "packets": selected}
            result = m.predict_synthetic_numeric(raw)
            old = {p["sample_id"]: p for p in predict_baselines(project_calculation_inputs(selected))
                   if p["model_id"] == "last_value"}
            for r, p in zip(result.predictions, sorted(selected, key=lambda p: p["horizon_months"])):
                assert r.value == old[p["sample_id"]]["value"]
                assert r.status == ("available" if old[p["sample_id"]]["status"] == "valid" else "unavailable")
            serialized = result.model_dump(mode="json")
            assert "followup_outcomes" not in serialized
            assert "generation_audit" not in serialized


@pytest.mark.parametrize("state,keep_history", [("observed", True), ("confirmed_none", False), ("unknown", True)])
def test_conflicting_history_requires_unknown_and_discarded_history(state, keep_history):
    raw = literal_input()
    for p in raw["packets"]:
        p["input_status"], p["input_reason"], p["history_state"] = "unavailable", "conflicting_history", state
        if not keep_history:
            p["input_observations"] = p["input_observations"][1:]
    with pytest.raises(ValueError, match="conflicting_history_state_mismatch"):
        service().predict_synthetic_numeric(raw)


def test_dependency_loaded_before_adapter_cannot_claim_new_disk_code():
    import subprocess
    import sys

    script = '''
from pathlib import Path
from app.services import prediction_calculation
original_read = Path.read_bytes
def changed_read(path):
    raw = original_read(path)
    if path.name == "prediction_calculation.py":
        return raw.replace(b'value = row["anchor_value"]', b'value = 0.0')
    return raw
Path.read_bytes = changed_read
from app.services.synthetic_numeric_prediction import numeric_algorithm_identity
try:
    numeric_algorithm_identity()
except ValueError as error:
    assert str(error) == "numeric_loaded_code_mismatch", str(error)
else:
    raise AssertionError("stale dependency accepted as current disk implementation")
'''
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
