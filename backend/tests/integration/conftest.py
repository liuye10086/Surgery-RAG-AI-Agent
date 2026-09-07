"""Real PostgreSQL fixtures for the operator workspace contract."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
if TEST_DATABASE_URL and not TEST_DATABASE_URL.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("TEST_DATABASE_URL must target a database ending in _test")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def integration_engine():
    if not TEST_DATABASE_URL:
        pytest.skip(
            "TEST_DATABASE_URL is not set; real PostgreSQL integration is opt-in"
        )
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    repo_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=repo_root,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
        check=True,
    )
    yield engine
    engine.dispose()


@pytest.fixture()
def db(integration_engine):
    Session = sessionmaker(bind=integration_engine, future=True)
    session = Session()
    tables = (
        "report_generation_jobs",
        "operator_idempotency_keys",
        "operator_case_change_logs",
        "ai_reports",
        "operator_case_visits",
        "operator_cases",
        "diseases",
        "users",
    )
    try:
        session.execute(
            text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
        )
        session.execute(
            text(
                "INSERT INTO users (username, email, hashed_password, role) "
                "VALUES ('operator-a', 'operator-a@test.invalid', 'x', 'ai_operator'), "
                "('operator-b', 'operator-b@test.invalid', 'x', 'ai_operator')"
            )
        )
        session.execute(
            text(
                "INSERT INTO diseases (code, name, operator_enabled) VALUES "
                "('fatty_liver', '脂肪肝', true), ('ad', '阿尔茨海默病', true)"
            )
        )
        session.commit()
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from app.api.deps import get_db
    from app.core.config import settings
    from app.core.security import create_access_token
    from app.db.models import User
    from app.main import app

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    def for_user(user_id: int):
        token = create_access_token(
            {"sub": str(user_id)}, settings.JWT_SECRET, settings.JWT_ALGORITHM
        )
        return TestClient(app, headers={"Authorization": f"Bearer {token}"})

    yield for_user
    app.dependency_overrides.clear()


@pytest.fixture()
def queued_report(db):
    from uuid import uuid4
    from datetime import timedelta
    from app.db.models import AIReport, ReportGenerationJob
    from app.services.report_job_repository import db_now, context_hash
    from app.services.report_integrity import compute_input_snapshot_sha256
    from backend.tests.report_document_fixtures import context_payload, snapshot_payload

    snapshot = snapshot_payload()
    snapshot["generation_batch_id"] = str(uuid4())
    context = context_payload()
    from app.schemas.report_document import ReportGenerationContext

    context = ReportGenerationContext.model_validate(context).model_dump(mode="json")
    report = AIReport(
        user_id=1,
        disease_id=1,
        query="匿名测试报告",
        status="generating",
        analysis_type="predictive",
        input_snapshot=snapshot,
        input_snapshot_sha256=compute_input_snapshot_sha256(snapshot),
        generation_batch_id=snapshot["generation_batch_id"],
    )
    db.add(report)
    db.flush()
    db.add(
        ReportGenerationJob(
            report_id=report.id,
            user_id=1,
            source_case_id=1,
            generation_context=context,
            context_sha256=context_hash(context),
            queue_deadline=db_now(db) + timedelta(seconds=600),
        )
    )
    report_id = report.id
    db.commit()
    return report_id
