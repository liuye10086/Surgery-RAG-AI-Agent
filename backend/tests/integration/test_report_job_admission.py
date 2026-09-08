from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.services.report_generation_service import submit_report_job, ReportJobError
from app.services.model_paths import MODEL_DIR


@pytest.fixture
def environment(db, integration_engine, monkeypatch):
    from scripts.seed_operator_report_e2e import seed
    from app.core.config import settings

    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    monkeypatch.setattr(settings, "REPORT_JOBS_ENABLED", True)
    monkeypatch.setattr(settings, "REPORT_JOBS_ACCEPTING", True)
    monkeypatch.setenv("DATABASE_URL", integration_engine.url.render_as_string(hide_password=False))
    seed(factory)
    return factory


def test_concurrent_same_key_is_one_report_and_one_job(environment):
    key = str(uuid4())
    barrier = Barrier(2)

    def submit():
        barrier.wait(5)
        return submit_report_job(1, 1, key, {}, environment, MODEL_DIR)

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(submit)
        b = pool.submit(submit)
        assert a.result().report_id == b.result().report_id
    with environment() as db:
        assert (
            db.execute(text("SELECT count(*) FROM report_generation_jobs")).scalar_one()
            == 1
        )
        assert (
            db.execute(
                text(
                    "SELECT count(*) FROM operator_idempotency_keys WHERE scope='create_longitudinal_report'"
                )
            ).scalar_one()
            == 1
        )


def test_limits_conflict_and_deleted_resource_tombstone(environment, monkeypatch):
    from app.core.config import settings
    from app.services.report_generation_service import (
        cancel_report_job,
        delete_report_job,
    )

    key = str(uuid4())
    accepted = submit_report_job(1, 1, key, {}, environment, MODEL_DIR)
    with pytest.raises(ReportJobError) as conflict:
        submit_report_job(1, 1, str(uuid4()), {}, environment, MODEL_DIR)
    assert (
        conflict.value.code == "active_report_exists"
        and conflict.value.report_id == accepted.report_id
    )
    monkeypatch.setattr(settings, "REPORT_JOB_USER_ACTIVE_LIMIT", 1)
    with pytest.raises(ReportJobError) as quota:
        submit_report_job(1, 2, str(uuid4()), {}, environment, MODEL_DIR)
    assert quota.value.status_code == 429
    with environment() as db:
        cancel_report_job(db, 1, accepted.report_id)
        delete_report_job(db, 1, accepted.report_id)
    with pytest.raises(ReportJobError) as deleted:
        submit_report_job(1, 1, key, {}, environment, MODEL_DIR)
    assert deleted.value.code == "idempotency_resource_missing"


def test_real_worker_uses_admitted_case_snapshot(environment):
    from app.workers.report_worker import run_worker_once
    from app.db.models import AIReport

    accepted = submit_report_job(1, 1, str(uuid4()), {}, environment, MODEL_DIR)
    with environment() as db:
        db.execute(text("UPDATE operator_cases SET age=70 WHERE id=1"))
        db.commit()
    assert run_worker_once(environment, MODEL_DIR, "integration-worker")
    with environment() as db:
        report = db.get(AIReport, accepted.report_id)
        assert report.status == "completed", report.error_message
        assert report.report_document["identity"]["age"] == 62
        assert report.input_snapshot["age"] == 62


def test_mutated_pinned_rule_prevents_publication(environment):
    from app.workers.report_worker import run_worker_once
    from app.db.models import AIReport

    accepted = submit_report_job(1, 1, str(uuid4()), {}, environment, MODEL_DIR)
    with environment() as db:
        db.execute(
            text(
                "UPDATE standard_rules SET upper=coalesce(upper,0)+1 WHERE id=(SELECT min(id) FROM standard_rules)"
            )
        )
        db.commit()
    run_worker_once(environment, MODEL_DIR, "integration-worker")
    with environment() as db:
        report = db.get(AIReport, accepted.report_id)
        assert (
            report.status == "failed"
            and report.error_message == "standard_integrity_failed"
        )
        assert report.report_document is None
