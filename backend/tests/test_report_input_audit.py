from app.services.disease_progression import AD_ADAPTER
from app.services.report_input_audit import run_audited_prediction
from backend.tests.test_longitudinal_prediction_contract import (
    _complete_ad_suite,
    _ad_visits,
)


def test_audit_records_every_selected_task_and_actual_model_calls():
    result = run_audited_prediction(
        {"age": 62, "sex": "female", "baseline_stage": "mci"},
        AD_ADAPTER,
        _complete_ad_suite(bad_mmse=True),
        visits=_ad_visits(),
    )
    assert len(result.model_runs) == 4
    mmse = next(r for r in result.model_runs if r.task.endswith(".mmse"))
    assert mmse.input_audit.model_invoked is True
    assert mmse.runtime.status != "available"
    assert mmse.input_audit.frame_sha256 is not None


import pytest
from unittest.mock import Mock
from app.services.report_input_audit import fingerprint_input_row


def test_allowed_missing_matches_actual_frame_and_does_not_store_notes():
    suite = _complete_ad_suite()
    entry = next(iter(suite.outcomes.values()))
    spy = Mock(wraps=entry.model.predict_proba)
    entry.model.predict_proba = spy
    result = run_audited_prediction(
        {"baseline_stage": "mci", "notes": "PRIVATE"},
        AD_ADAPTER,
        suite,
        visits=_ad_visits(),
    )
    frame = spy.call_args.args[0]
    audit = result.model_runs[0].input_audit
    assert list(frame.columns) == [field.name for field in audit.fields]
    assert audit.frame_sha256 == fingerprint_input_row(
        list(frame.columns), frame.iloc[0].to_dict()
    )
    assert [field.state for field in audit.fields] == [
        "allowed_missing",
        "present",
        "allowed_missing",
    ]
    assert audit.numeric_imputation == "median_add_indicator"
    assert "PRIVATE" not in str(audit.model_dump())


def test_required_missing_prevents_model_invocation():
    suite = _complete_ad_suite()
    entry = next(iter(suite.outcomes.values()))
    entry.metadata.feature_contract.required_features = ["visit_count", "age"]
    entry.metadata.feature_contract.allowed_missing_features = ["sex"]
    spy = Mock(wraps=entry.model.predict_proba)
    entry.model.predict_proba = spy
    result = run_audited_prediction(
        {"baseline_stage": "mci"}, AD_ADAPTER, suite, visits=_ad_visits()
    )
    run = result.model_runs[0]
    assert spy.call_count == 0
    assert run.runtime.reason_code == "required_feature_missing"
    assert run.input_audit.fields[0].state == "required_missing"
    assert run.input_audit.model_invoked is False


@pytest.mark.parametrize("age", [True, float("nan"), float("inf"), "invalid"])
def test_invalid_numeric_never_invokes_model(age):
    suite = _complete_ad_suite()
    result = run_audited_prediction(
        {"baseline_stage": "mci", "age": age}, AD_ADAPTER, suite, visits=_ad_visits()
    )
    for run in result.model_runs:
        assert run.input_audit.model_invoked is False
        assert run.input_audit.fields[0].state == "invalid"
        assert run.runtime.reason_code == "non_finite_feature"


def test_explicit_visits_must_match_snapshot():
    with pytest.raises(ValueError, match="audit_visits_mismatch"):
        run_audited_prediction(
            {"visits": []}, AD_ADAPTER, _complete_ad_suite(), visits=_ad_visits()
        )


def test_events_finish_each_task_before_next_task_starts_without_values():
    events = []
    run_audited_prediction({"age": 62, "sex": "female", "baseline_stage": "mci", "notes": "PRIVATE"},
                          AD_ADAPTER, _complete_ad_suite(bad_mmse=True), visits=_ad_visits(), on_event=events.append)
    finished = [event for event in events if event["kind"] == "task_finished"]
    assert len(finished) == 4
    assert finished[2]["result_state"] == "unavailable"
    for left, right in zip(finished, finished[1:]):
        next_start = next(event for event in events if event["task"] == right["task"] and event["kind"] == "input_prepared")
        assert events.index(left) < events.index(next_start)
    assert "PRIVATE" not in str(events)
    assert all(set(field) == {"name", "state"} for event in events for field in event["input_audit"]["fields"])
