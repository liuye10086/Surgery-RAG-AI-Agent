import pytest
from app.services.report_generation_idempotency import hash_report_request


def test_retry_hash_is_case_bound_and_normalizes_empty_options():
    assert hash_report_request(1, {}) == hash_report_request(1, {"model_options": {}})
    assert hash_report_request(1, {}) != hash_report_request(2, {})


@pytest.mark.parametrize(
    "body",
    [{"model_options": {"model": "other"}}, {"model_options": None}, {"unknown": True}],
)
def test_unsupported_options_rejected(body):
    with pytest.raises(ValueError, match="unsupported_report_options"):
        hash_report_request(1, body)


def test_readiness_failure_precedes_snapshot_and_context(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import Mock
    from uuid import uuid4
    from app.services import report_generation_service as service

    monkeypatch.setattr(service.settings, "REPORT_JOBS_ENABLED", True)
    monkeypatch.setattr(service.settings, "REPORT_JOBS_ACCEPTING", True)
    monkeypatch.setattr(service, "_replay", lambda *a: None)
    monkeypatch.setattr(service, "get_operator_case", lambda *a: SimpleNamespace())
    monkeypatch.setattr(
        service,
        "evaluate_operator_case_readiness",
        lambda *a, **k: SimpleNamespace(ready=False),
    )
    snapshot = Mock()
    context = Mock()
    monkeypatch.setattr(service, "build_input_snapshot", snapshot)
    monkeypatch.setattr(service, "capture_generation_context", context)

    @contextmanager
    def factory():
        yield Mock()

    with pytest.raises(service.ReportJobError, match="report_not_ready"):
        service.submit_report_job(1, 1, str(uuid4()), {}, factory, ".")
    snapshot.assert_not_called()
    context.assert_not_called()


def test_preflight_failure_creates_no_write_transaction(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from unittest.mock import Mock
    from uuid import uuid4
    from app.services import report_generation_service as service
    from app.services.evidence_bundle import EvidenceBuildError

    monkeypatch.setattr(service.settings, "REPORT_JOBS_ENABLED", True)
    monkeypatch.setattr(service.settings, "REPORT_JOBS_ACCEPTING", True)
    monkeypatch.setattr(service, "_replay", lambda *a: None)
    monkeypatch.setattr(
        service, "get_operator_case", lambda *a: SimpleNamespace(visits=[])
    )
    monkeypatch.setattr(
        service,
        "evaluate_operator_case_readiness",
        lambda *a, **k: SimpleNamespace(ready=True),
    )
    monkeypatch.setattr(service, "build_input_snapshot", lambda *a: {})
    monkeypatch.setattr(
        service,
        "capture_generation_context",
        Mock(side_effect=EvidenceBuildError("standard_integrity_failed")),
    )
    sessions = []

    @contextmanager
    def factory():
        db = Mock()
        sessions.append(db)
        yield db

    with pytest.raises(service.ReportJobError, match="standard_integrity_failed"):
        service.submit_report_job(1, 1, str(uuid4()), {}, factory, ".")
    assert len(sessions) == 2
    for db in sessions:
        db.add.assert_not_called()
        db.commit.assert_not_called()
