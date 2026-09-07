"""Run with python -m app.workers.report_worker; no HTTP or RAG bootstrap."""

import argparse
import logging
import os
import signal
import socket
import time
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.db.models import AIReport, ReportGenerationJob
from app.services.report_job_repository import (
    claim_next,
    heartbeat,
    update_phase,
    publish_completed,
    finish_job,
    reap_expired,
    db_now,
)
from app.services.report_generation_errors import safe_code
from app.workers.report_execution import execute_report
from app.workers.report_process_control import supervise_execution

logger = logging.getLogger(__name__)


def run_worker_once(
    session_factory, registry_root, owner, *, execution_target=execute_report
):
    if not settings.REPORT_JOBS_ENABLED:
        return False
    with session_factory() as db:
        reap_expired(db)
        claim = claim_next(db, owner)
    if claim is None:
        return False
    try:
        with session_factory() as db:
            report = db.get(AIReport, claim.report_id)
            job = db.get(ReportGenerationJob, claim.report_id)
            if report is None or job is None:
                return True
            remaining_seconds = (claim.run_deadline - db_now(db)).total_seconds()
            budget_started = time.monotonic()
            payload = {
                "report_id": report.id,
                "created_at": report.created_at.isoformat(),
                "snapshot": report.input_snapshot,
                "snapshot_sha256": report.input_snapshot_sha256,
                "context": job.generation_context,
                "context_sha256": job.context_sha256,
                "registry_root": str(Path(registry_root).resolve()),
            }

        def renew():
            with session_factory() as db:
                return heartbeat(db, claim)

        phase_started = time.monotonic()
        current_phase = "model_loading"

        def phase(value):
            nonlocal phase_started, current_phase
            now = time.monotonic()
            logger.info(
                "report_job_phase report_id=%s batch_id=%s phase=%s elapsed_ms=%d",
                claim.report_id,
                claim.batch_id,
                current_phase,
                int((now - phase_started) * 1000),
            )
            phase_started = now
            current_phase = value
            with session_factory() as db:
                return update_phase(db, claim, value)

        def audit(event):
            from app.services.report_generation_audit import append_generation_audit
            with session_factory() as db:
                return append_generation_audit(db, claim, event)

        result = supervise_execution(
            execution_target,
            payload,
            maximum_seconds=max(
                0, remaining_seconds - (time.monotonic() - budget_started)
            ),
            lease_check=renew,
            on_phase=phase,
            on_audit=audit,
            phase_limits={
                "model_loading": settings.REPORT_JOB_LOAD_SECONDS,
                "prediction": settings.REPORT_JOB_PREDICTION_SECONDS,
                "standard_evidence": settings.REPORT_JOB_EVIDENCE_SECONDS,
                "rendering": settings.REPORT_JOB_RENDER_SECONDS,
                "persistence": settings.REPORT_JOB_PERSIST_SECONDS,
            },
        )
        with session_factory() as db:
            if result.publication is not None:
                published = publish_completed(db, claim, result.publication)
                logger.info(
                    "report_job_publish report_id=%s accepted=%s",
                    claim.report_id,
                    published,
                )
            elif result.code != "lease_lost":
                finished = finish_job(db, claim, "failed", safe_code(result.code))
                logger.info(
                    "report_job_finish report_id=%s batch_id=%s reason=%s accepted=%s",
                    claim.report_id,
                    claim.batch_id,
                    safe_code(result.code),
                    finished,
                )
    except (KeyboardInterrupt, SystemExit):
        try:
            with session_factory() as db:
                finish_job(db, claim, "failed", "worker_interrupted")
        finally:
            raise
    except Exception:
        # Commit may have succeeded before the connection failed. Never blindly
        # overwrite or resubmit: inspect through a fresh session, then let leases
        # converge any unresolved running state.
        try:
            with session_factory() as db:
                job = db.get(ReportGenerationJob, claim.report_id)
                logger.error(
                    "report_job_uncertain report_id=%s status=%s",
                    claim.report_id,
                    job.status if job else "missing",
                )
        except Exception:
            logger.error(
                "report_job_database_unavailable report_id=%s", claim.report_id
            )
    return True


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--once", action="store_true")
    group.add_argument("--sweep-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from app.workers.report_database import SessionLocal
    from app.services.model_paths import MODEL_DIR

    if args.sweep_only:
        with SessionLocal() as db:
            logger.info("report_jobs_reaped count=%s", reap_expired(db))
        return
    if not settings.REPORT_JOBS_ENABLED:
        parser.error("REPORT_JOBS_ENABLED must be true to run the worker")
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            worked = run_worker_once(SessionLocal, MODEL_DIR, owner)
            if args.once:
                return
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("report_worker_stopped")


if __name__ == "__main__":
    main()
