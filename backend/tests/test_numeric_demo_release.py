from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


SHA = "1" * 64
GIT_SHA = "2" * 40
STARTED = datetime(2026, 9, 20, 8, 0, tzinfo=timezone.utc)
STOPPED = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)


def zero_metrics():
    def phase():
        return {"samples": 0, "total_ms": 0, "max_ms": 0}

    return {
        "admission": {
            "requests": 0,
            "idempotency_replays": 0,
            "rejected": 0,
            "admission_disabled": 0,
            "permission_denied": 0,
            "invalid_input": 0,
            "conflict": 0,
        },
        "jobs": {
            "queued": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "unsettled": 0,
            "phase_timeouts": 0,
            "phase_timeout_phases": [],
        },
        "timings": {
            "model_loading": phase(),
            "prediction": phase(),
            "standard_evidence": phase(),
            "rendering": phase(),
            "persistence": phase(),
        },
        "llm_audit": {
            "invocation_started": 0,
            "task_finished": 0,
            "closed_reports": 0,
            "unclosed_reports": 0,
        },
        "authorization": {
            "non_owner_404": 0,
            "wrong_role_403": 0,
            "disease_permission_denied": 0,
        },
        "history": {"verified_reports": 0, "mismatches": 0},
        "pdf": {
            "ready": 0,
            "failed": 0,
            "missing": 0,
            "corrupt": 0,
            "downloads": 0,
            "bytes_verified": 0,
            "sha_mismatches": 0,
        },
        "identity": {
            "source_matches": True,
            "legacy_bundle_matches": True,
            "history_bundle_matches": True,
            "renderer_matches": True,
            "acceptance_matches": True,
            "git_commit_matches": True,
        },
    }


def record(status="starting"):
    return {
        "schema_version": "numeric_history_demo_release.v1",
        "run_id": "2026-09-20-v1",
        "status": status,
        "is_synthetic": True,
        "clinical_validity_claim": False,
        "clinical_status": "not_assessable",
        "production_enabled": False,
        "started_at": STARTED,
        "stopped_at": STOPPED if status in {"stopped", "failed"} else None,
        "identities": {
            "source_manifest_sha256": SHA,
            "source_data_content_sha256": SHA,
            "legacy_bundle_sha256": SHA,
            "history_bundle_sha256": SHA,
            "renderer_manifest_sha256": SHA,
            "acceptance_result_sha256": SHA,
            "git_commit": GIT_SHA,
        },
        "runtime": {
            "python_version": "3.11.4",
            "node_version": "22.15.0",
            "playwright_version": "1.55.0",
            "fonttools_version": "4.59.1",
            "chromium_version": "140.0.7339.16",
        },
        "metrics": zero_metrics(),
        "diagnostics": [],
        "cleanup_errors": [],
    }


@pytest.mark.parametrize("status", ["starting", "running", "stopped", "failed"])
def test_release_record_accepts_only_explicit_lifecycle_states(status):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    parsed = NumericDemoReleaseRecord.model_validate(record(status))
    assert parsed.status == status
    assert parsed.clinical_status == "not_assessable"


@pytest.mark.parametrize(
    ("status", "stopped_at"),
    [("starting", STOPPED), ("running", STOPPED), ("stopped", None), ("failed", None)],
)
def test_release_record_rejects_inconsistent_stop_time(status, stopped_at):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record(status)
    raw["stopped_at"] = stopped_at
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


def test_release_record_requires_timezone_aware_ordered_timestamps():
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record("stopped")
    raw["started_at"] = STARTED.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)
    raw = record("stopped")
    raw["stopped_at"] = STARTED.replace(hour=7)
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("is_synthetic", False),
        ("is_synthetic", 1),
        ("clinical_validity_claim", True),
        ("clinical_validity_claim", 0),
        ("clinical_status", "passed"),
        ("production_enabled", True),
        ("production_enabled", 0),
    ],
)
def test_release_record_rejects_non_engineering_release_flags(field, value):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record()
    raw[field] = value
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


def test_release_record_rejects_unknown_fields_and_bad_hashes():
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record()
    raw["database_url"] = "postgresql://secret@host/db"
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)
    raw = record()
    raw["identities"]["history_bundle_sha256"] = "A" * 64
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)
    raw = record()
    raw["identities"]["git_commit"] = "2" * 39
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_release_metrics_require_strict_non_negative_integers(value):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record()
    raw["metrics"]["jobs"]["completed"] = value
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


@pytest.mark.parametrize(
    "extra",
    [
        {"url": "http://secret"},
        {"token": "secret"},
        {"password": "secret"},
        {"patient": "raw-content"},
        {"prompt": "full request"},
        {"response": "full response"},
    ],
)
def test_release_diagnostics_reject_sensitive_or_freeform_fields(extra):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record("failed")
    raw["diagnostics"] = [
        {
            "stage": "preflight",
            "error_type": "ValueError",
            "error_location": [{"file": "runner.py", "line": 10, "function": "main"}],
            **extra,
        }
    ]
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


@pytest.mark.parametrize("file", ["C:/private/runner.py", "../runner.py", "folder/runner.py"])
def test_release_diagnostics_accept_only_basename_locations(file):
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record("failed")
    raw["diagnostics"] = [
        {
            "stage": "preflight",
            "error_type": "ValueError",
            "error_location": [{"file": file, "line": 10, "function": "main"}],
        }
    ]
    with pytest.raises(ValidationError):
        NumericDemoReleaseRecord.model_validate(raw)


def test_release_record_json_round_trip_preserves_closed_contract():
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    parsed = NumericDemoReleaseRecord.model_validate(record("stopped"))
    encoded = parsed.model_dump_json()
    restored = NumericDemoReleaseRecord.model_validate_json(encoded)
    assert restored == parsed
    assert restored.started_at.tzinfo is not None
    assert "database_url" not in restored.model_dump(mode="json")


def test_phase_metric_objects_are_independent():
    from app.schemas.numeric_demo_release import NumericDemoReleaseRecord

    raw = record()
    raw["metrics"] = deepcopy(raw["metrics"])
    raw["metrics"]["timings"]["prediction"]["samples"] = 1
    parsed = NumericDemoReleaseRecord.model_validate(raw)
    assert parsed.metrics.timings.prediction.samples == 1
    assert parsed.metrics.timings.rendering.samples == 0


def session_checks():
    from app.schemas.numeric_demo_release import DEMO_SESSION_CHECKS

    return {
        "schema_version": "numeric_demo_session_checks.v1",
        "performed": list(DEMO_SESSION_CHECKS),
        "admission": {
            "submissions": 2,
            "accepted": 1,
            "idempotency_replays": 1,
            "admission_disabled": 0,
            "permission_denied": 0,
            "invalid_input": 0,
            "conflict": 0,
            "non_owner_404": 1,
            "wrong_role_403": 1,
            "disease_permission_denied": 0,
        },
    }


def test_session_checks_accept_only_the_closed_performed_set():
    from app.schemas.numeric_demo_release import (
        DEMO_SESSION_CHECKS,
        NumericDemoSessionChecks,
    )

    parsed = NumericDemoSessionChecks.model_validate(session_checks())
    assert sorted(parsed.performed) == sorted(DEMO_SESSION_CHECKS)
    assert parsed.admission.idempotency_replays == 1


@pytest.mark.parametrize(
    "performed",
    [
        [],
        ["non_owner_404"],
        ["non_owner_404", "wrong_role_403", "idempotency_replay", "unknown_check"],
        ["non_owner_404", "non_owner_404", "wrong_role_403", "idempotency_replay"],
    ],
)
def test_session_checks_require_every_named_check_exactly_once(performed):
    from app.schemas.numeric_demo_release import NumericDemoSessionChecks

    raw = session_checks()
    raw["performed"] = performed
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)


def test_session_checks_require_every_check_to_be_observed_at_least_once():
    """A named check that observed nothing is a missing result, not a pass."""
    from app.schemas.numeric_demo_release import NumericDemoSessionChecks

    raw = session_checks()
    raw["admission"]["idempotency_replays"] = 0
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
    raw = session_checks()
    raw["admission"]["non_owner_404"] = 0
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)


def test_session_checks_require_outcomes_to_sum_to_submissions():
    from app.schemas.numeric_demo_release import NumericDemoSessionChecks

    raw = session_checks()
    raw["admission"]["submissions"] = 1
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
    raw = session_checks()
    raw["admission"]["conflict"] = 1
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
    raw = session_checks()
    raw["admission"]["accepted"] = 0
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_session_checks_require_strict_non_negative_integers(value):
    from app.schemas.numeric_demo_release import NumericDemoSessionChecks

    raw = session_checks()
    raw["admission"]["accepted"] = value
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)


@pytest.mark.parametrize(
    "extra",
    [
        {"url": "postgresql://secret@host/db"},
        {"token": "secret"},
        {"password": "secret"},
        {"patient": "raw-content"},
    ],
)
def test_session_checks_reject_sensitive_or_freeform_fields(extra):
    from app.schemas.numeric_demo_release import NumericDemoSessionChecks

    raw = session_checks()
    raw["admission"].update(extra)
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
    raw = session_checks()
    raw.update(extra)
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
    raw = session_checks()
    raw["admission"]["reason_codes"] = {}
    with pytest.raises(ValidationError):
        NumericDemoSessionChecks.model_validate(raw)
