from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import AIReport, OperatorCase, ReportGenerationJob
from app.services.report_generation_service import submit_report_job, ReportJobError
from app.services.model_paths import MODEL_DIR

REQUEST = {"report_kind": "numeric_prediction"}


@pytest.fixture
def environment(db, integration_engine, monkeypatch):
    from app.core.config import settings
    from app.services.synthetic_case_source import seed_synthetic_cases

    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    for flag in ("REPORT_JOBS_ENABLED", "REPORT_JOBS_ACCEPTING", "NUMERIC_REPORTS_ENABLED"):
        monkeypatch.setattr(settings, flag, True)
    package = Path(__file__).resolve().parents[3] / "outputs/synthetic-prediction-cases/2026-09-14-v1"
    patients = [json.loads(line) for line in (package / "patients.jsonl").read_text(encoding="utf-8").splitlines()]
    subjects = [next(p["subject_id"] for p in patients if p["disease"] == disease) for disease in ("ad", "fatty_liver")]
    ids = seed_synthetic_cases(factory, package, 1, subjects)
    return factory, ids


def submit(environment, case_index=0, key=None, user=1, payload=None):
    factory, ids = environment
    return submit_report_job(user, ids[case_index], key or str(uuid4()), REQUEST if payload is None else payload, factory, MODEL_DIR)


def test_real_admission_snapshots_both_diseases(environment):
    from app.services.report_job_repository import context_hash
    from app.services.report_integrity import compute_input_snapshot_sha256

    for i in (0, 1):
        accepted = submit(environment, i)
        with environment[0]() as db:
            report, job = db.get(AIReport, accepted.report_id), db.get(ReportGenerationJob, accepted.report_id)
            assert report.analysis_type == "numeric_prediction"
            assert job.status == "queued"
            assert job.generation_context["schema_version"] == "numeric_generation_context.v1"
            assert job.context_sha256 == context_hash(job.generation_context)
            assert report.input_snapshot_sha256 == compute_input_snapshot_sha256(report.input_snapshot)
            assert len(report.input_snapshot["numeric_input"]["packets"]) == 2
            assert report.input_snapshot["numeric_input"]["source"]["is_synthetic"] is True
            assert "followup_outcomes" not in report.input_snapshot


def test_same_key_concurrent_admission_and_closed_gate_replay(environment, monkeypatch):
    from app.core.config import settings

    barrier, key = Barrier(2), str(uuid4())
    def run():
        barrier.wait(10)
        return submit(environment, key=key).report_id
    with ThreadPoolExecutor(2) as executor:
        a, b = executor.submit(run), executor.submit(run)
        assert a.result() == b.result()
    monkeypatch.setattr(settings, "NUMERIC_REPORTS_ENABLED", False)
    assert submit(environment, key=key).report_id == a.result()
    with environment[0]() as db:
        assert db.query(ReportGenerationJob).count() == 1
    with pytest.raises(ReportJobError) as error:
        submit(environment, key=key, payload={})
    assert error.value.code == "idempotency_conflict"


@pytest.mark.parametrize("action,expected", [
    ("other_user", "case_not_found"), ("role", "auth_expired"),
    ("disabled", "disease_disabled"), ("archived", "case_archived"),
    ("ordinary", "prediction_source_required"), ("old_route", "synthetic_report_kind_required"),
    ("tampered", "prediction_source_invalid"), ("closed", "numeric_reports_unavailable"),
])
def test_admission_rejects_without_persisting(environment, monkeypatch, action, expected):
    from app.core.config import settings

    factory, ids = environment
    with factory() as db:
        if action == "role": db.execute(text("UPDATE users SET role='patient' WHERE id=1"))
        if action == "disabled": db.execute(text("UPDATE diseases SET operator_enabled=false"))
        if action == "archived": db.get(OperatorCase, ids[0]).status = "archived"
        if action == "ordinary": db.get(OperatorCase, ids[0]).engineering_source = None
        if action == "tampered": db.get(OperatorCase, ids[0]).age += 1
        db.commit()
    if action == "closed": monkeypatch.setattr(settings, "NUMERIC_REPORTS_ENABLED", False)
    with pytest.raises(ReportJobError) as error:
        submit(environment, user=2 if action == "other_user" else 1, payload={} if action == "old_route" else None)
    assert error.value.code == expected
    with factory() as db:
        assert db.query(AIReport).count() == db.query(ReportGenerationJob).count() == 0


def test_http_permission_legacy_and_readonly_inputs(environment, client):
    case_id = environment[1][0]
    base = f"/api/v1/operator/longitudinal-cases/{case_id}"
    own, other = client(1), client(2)
    assert own.get(base + "/report-readiness").json()["ready"] is False
    assert own.get(base + "/report-readiness?report_kind=numeric_prediction").json()["ready"] is True
    assert other.post(base + "/report-jobs", json=REQUEST, headers={"Idempotency-Key": str(uuid4())}).status_code == 404
    legacy = own.post(base + "/reports", json={}, headers={"Idempotency-Key": str(uuid4())})
    assert legacy.status_code == 409
    assert legacy.json()["detail"]["code"] == "synthetic_report_kind_required"
    detail = own.get(base).json()
    payload = {k: detail[k] for k in ("age", "sex", "baseline_stage", "notes")}
    payload["visits"] = [{k: v[k] for k in ("visit_date", "indicators", "notes", "visit_context")} for v in detail["visits"]]
    payload.update(age=50, change_reason="test change")
    assert own.put(base, json=payload).status_code == 409
    accepted = own.post(base + "/report-jobs", json=REQUEST, headers={"Idempotency-Key": str(uuid4())})
    assert accepted.status_code == 202, accepted.text
    status = own.get(f'/api/v1/operator/reports/{accepted.json()["report_id"]}/generation-status')
    assert status.json()["status"] == "queued"


def test_seed_duplicate_and_mid_transaction_failure_leave_no_partial_cases(environment, monkeypatch):
    from app.services import synthetic_case_source as source

    factory, ids = environment
    package = Path(__file__).resolve().parents[3] / "outputs/synthetic-prediction-cases/2026-09-14-v1"
    with factory() as db:
        subject = db.get(OperatorCase, ids[0]).engineering_source["subject_id"]
    with pytest.raises(source.SyntheticCaseSourceError, match="synthetic_subject_already_imported"):
        source.seed_synthetic_cases(factory, package, 1, [subject])
    original = source.build_engineering_binding
    calls = []
    def fail_second(case, numeric):
        calls.append(case.id)
        if len(calls) == 2: raise ValueError("simulated_binding_failure")
        return original(case, numeric)
    monkeypatch.setattr(source, "build_engineering_binding", fail_second)
    patients = [json.loads(line) for line in (package / "patients.jsonl").read_text(encoding="utf-8").splitlines()]
    with pytest.raises(ValueError, match="simulated_binding_failure"):
        source.seed_synthetic_cases(factory, package, 2, [p["subject_id"] for p in patients[:2]])
    with factory() as db:
        assert db.query(OperatorCase).count() == 2
        assert db.execute(text("SELECT count(*) FROM operator_case_change_logs WHERE actor_id=2")).scalar_one() == 0


@pytest.mark.parametrize("value", [{}, {"source_kind": "synthetic", "is_synthetic": True},
    {"schema_version": "synthetic_case_source.v1", "source_kind": "synthetic", "is_synthetic": 1},
    {"schema_version": "synthetic_case_source.v1", "source_kind": "real", "is_synthetic": True}])
def test_database_rejects_unmarked_source_objects(environment, value):
    from sqlalchemy.exc import IntegrityError

    with environment[0]() as db:
        db.get(OperatorCase, environment[1][0]).engineering_source = value
        with pytest.raises(IntegrityError): db.commit()
        db.rollback()


def test_all_service_edit_paths_reject_bound_case(environment):
    from app.services import longitudinal_case_service as cases

    with environment[0]() as db:
        case = db.get(OperatorCase, environment[1][0])
        visit_id = case.visits[0].id
        for change in (
            lambda: cases.update_operator_case(db, 1, case.id, None),
            lambda: cases.add_visit(db, 1, case.id, None),
            lambda: cases.update_visit(db, 1, case.id, visit_id, None),
            lambda: cases.delete_visit(db, 1, case.id, visit_id),
            lambda: cases.replace_visits(db, 1, case.id, []),
            lambda: cases.replace_case_visits_in_session(db, case, []),
        ):
            with pytest.raises(cases.ArchivedCaseError): change()
        assert len(case.visits) > 0


def test_http_wrong_role_cannot_replay_or_submit(environment, client):
    accepted = submit(environment, key="10000000-0000-4000-8000-000000000001")
    with environment[0]() as db:
        db.execute(text("UPDATE users SET role='patient' WHERE id=1")); db.commit()
    response = client(1).post(f"/api/v1/operator/longitudinal-cases/{environment[1][0]}/report-jobs",
        json=REQUEST, headers={"Idempotency-Key": "10000000-0000-4000-8000-000000000001"})
    assert response.status_code == 403
    with environment[0]() as db:
        assert db.query(AIReport).count() == 1
        assert db.get(AIReport, accepted.report_id).status == "generating"


def test_disease_disabled_after_case_load_is_rechecked_under_lock(environment, monkeypatch):
    from app.services import disease_catalog

    original = disease_catalog.require_operator_disease
    def disable_before_lock(db, disease_id, *, for_update=False):
        with environment[0]() as other:
            other.execute(text("UPDATE diseases SET operator_enabled=false WHERE id=:id"), {"id": disease_id})
            other.commit()
        return original(db, disease_id, for_update=for_update)
    monkeypatch.setattr(disease_catalog, "require_operator_disease", disable_before_lock)
    with pytest.raises(ReportJobError) as error:
        submit(environment)
    assert error.value.code == "disease_disabled"
    with environment[0]() as db:
        assert db.query(AIReport).count() == 0


def test_migration_refuses_to_remove_existing_provenance(environment, monkeypatch):
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[2] / "alembic/versions/0027_synthetic_case_source.py"
    spec = importlib.util.spec_from_file_location("synthetic_source_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with environment[0]() as db:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(db.connection())))
        with pytest.raises(RuntimeError, match="discard_provenance"):
            migration.downgrade()
        assert db.get(OperatorCase, environment[1][0]).engineering_source is not None


def test_seed_rechecks_disease_disabled_after_initial_lookup(environment, monkeypatch):
    from app.services import disease_catalog
    from app.services.synthetic_case_source import seed_synthetic_cases

    package = Path(__file__).resolve().parents[3] / "outputs/synthetic-prediction-cases/2026-09-14-v1"
    with environment[0]() as db:
        subject = db.get(OperatorCase, environment[1][0]).engineering_source["subject_id"]
    original = disease_catalog.require_operator_disease
    def disable_before_lock(db, disease_id, *, for_update=False):
        with environment[0]() as other:
            other.execute(text("UPDATE diseases SET operator_enabled=false WHERE id=:id"), {"id": disease_id})
            other.commit()
        return original(db, disease_id, for_update=for_update)
    monkeypatch.setattr(disease_catalog, "require_operator_disease", disable_before_lock)
    with pytest.raises(disease_catalog.DiseaseDisabledError):
        seed_synthetic_cases(environment[0], package, 2, [subject])
    with environment[0]() as db:
        assert db.query(OperatorCase).filter_by(user_id=2).count() == 0


def test_capacity_cancel_and_source_snapshot_are_persistent(environment):
    from app.services.report_generation_service import cancel_report_job

    accepted = submit(environment)
    with pytest.raises(ReportJobError) as conflict: submit(environment)
    assert conflict.value.code == "active_report_exists"
    with environment[0]() as db:
        snapshot = deepcopy(db.get(AIReport, accepted.report_id).input_snapshot)
        cancel_report_job(db, 1, accepted.report_id)
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        assert report.status == "cancelled" and report.input_snapshot == snapshot
        assert db.get(ReportGenerationJob, accepted.report_id).status == "cancelled"


def test_synthetic_queue_timeout_preserves_fixed_input(environment):
    from app.services.report_job_repository import reap_expired

    accepted = submit(environment)
    with environment[0]() as db:
        snapshot = deepcopy(db.get(AIReport, accepted.report_id).input_snapshot)
        db.execute(text("UPDATE report_generation_jobs SET queue_deadline=clock_timestamp()-interval '1 second' WHERE report_id=:id"), {"id": accepted.report_id})
        db.commit()
        assert reap_expired(db) == 1
    with environment[0]() as db:
        report = db.get(AIReport, accepted.report_id)
        job = db.get(ReportGenerationJob, accepted.report_id)
        assert report.status == job.status == "failed"
        assert job.error_code == "queue_timeout"
        assert report.input_snapshot == snapshot


def test_recheck_rejects_change_between_preflight_and_insert(environment, monkeypatch):
    from app.services import numeric_report_admission as admission

    original = admission.capture_numeric_context
    def changed(snapshot):
        context = original(snapshot)
        with environment[0]() as db:
            db.get(OperatorCase, environment[1][0]).age += 1
            db.commit()
        return context
    monkeypatch.setattr(admission, "capture_numeric_context", changed)
    with pytest.raises(ReportJobError): submit(environment)
    with environment[0]() as db:
        assert db.query(AIReport).count() == 0
