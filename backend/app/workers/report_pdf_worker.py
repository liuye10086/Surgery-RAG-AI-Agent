"""Independent PDF worker; no HTTP, model execution or RAG bootstrap."""

import argparse
import logging
import os
import signal
import socket
import time
from uuid import uuid4
from app.core.config import settings
from app.db.models import AIReport, ReportPdfArchive
from app.services.report_pdf_repository import (
    claim_pdf,
    heartbeat_pdf,
    publish_pdf,
    fail_pdf,
    sweep_pdf,
    db_now,
)
from app.services.report_pdf_archive_service import _source
from app.services.report_pdf_errors import safe_pdf_code
from app.services.report_archive_storage import ArchiveStorage
from app.workers.report_pdf_execution import render_pdf_candidate
from app.workers.report_pdf_process_control import supervise_pdf
from app.workers.report_pdf_publication import publish_pdf_candidate

logger = logging.getLogger(__name__)


def run_pdf_worker_once(factory, owner, *, execution_target=render_pdf_candidate):
    if not settings.REPORT_PDF_ENABLED:
        return False
    with factory() as db:
        sweep_pdf(db)
        claim = claim_pdf(db, owner)
    if claim is None:
        return False
    try:
        with factory() as db:
            report = db.get(AIReport, claim.report_id)
            if report is None:
                return True
            source = _source(db, report.user_id, report.id)
            seconds = (claim.run_deadline - db_now(db)).total_seconds()
            started = time.monotonic()
            database_url = db.get_bind().url.render_as_string(hide_password=False)
            payload = dict(
                source=source.model_dump(mode="json"),
                source_sha256=claim.source_sha256,
                renderer_sha256=claim.renderer_sha256,
                object_key=claim.object_key,
                manifest_path=settings.REPORT_PDF_RENDERER_MANIFEST,
                archive_root=settings.REPORT_ARCHIVE_ROOT,
            )

        def heartbeat(phase=None):
            with factory() as db:
                return heartbeat_pdf(db, claim, phase)

        result = supervise_pdf(
            execution_target,
            payload,
            maximum_seconds=max(0, seconds - (time.monotonic() - started)),
            lease_check=heartbeat,
            on_phase=heartbeat,
        )
        if result.candidate:
            publication = supervise_pdf(
                publish_pdf_candidate,
                dict(
                    database_url=database_url,
                    claim=claim.model_dump(mode="json"),
                    candidate=result.candidate.model_dump(mode="json"),
                    archive_root=settings.REPORT_ARCHIVE_ROOT,
                ),
                maximum_seconds=max(0, seconds - (time.monotonic() - started)),
                lease_check=heartbeat,
                on_phase=heartbeat,
            )
            # Resolve the authoritative commit even when the child reply was lost.
            with factory() as db:
                archive = db.get(ReportPdfArchive, claim.report_id)
                accepted = (
                    archive is not None
                    and archive.published_attempt_id == claim.attempt_id
                )
            if not accepted and publication.code != "pdf_lease_lost":
                with factory() as db:
                    fail_pdf(db, claim, publication.code)
            logger.info(
                "pdf_publish report_id=%s attempt_id=%s accepted=%s",
                claim.report_id,
                claim.attempt_id,
                accepted,
            )
        elif result.code != "pdf_lease_lost":
            with factory() as db:
                fail_pdf(db, claim, result.code)
    except (KeyboardInterrupt, SystemExit):
        with factory() as db:
            fail_pdf(db, claim, "pdf_worker_interrupted")
        raise
    except Exception as error:
        # Fresh read resolves a lost commit response without overwriting ready.
        try:
            with factory() as db:
                archive = db.get(ReportPdfArchive, claim.report_id)
                ready = (
                    archive is not None
                    and archive.published_attempt_id == claim.attempt_id
                )
            if not ready:
                with factory() as db:
                    fail_pdf(db, claim, safe_pdf_code(getattr(error, "code", None)))
            logger.warning(
                "pdf_result_checked report_id=%s attempt_id=%s published=%s",
                claim.report_id,
                claim.attempt_id,
                ready,
            )
        except Exception:
            logger.error(
                "pdf_database_unavailable report_id=%s attempt_id=%s",
                claim.report_id,
                claim.attempt_id,
            )
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--sweep", action="store_true")
    args = parser.parse_args()
    from app.workers.report_database import SessionLocal

    logging.basicConfig(level=logging.INFO)
    if args.sweep:
        with SessionLocal() as db:
            logger.info("pdf_sweep count=%s", sweep_pdf(db))
        return
    if not settings.REPORT_PDF_ENABLED:
        parser.error("REPORT_PDF_ENABLED must be true")
    owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while True:
            worked = run_pdf_worker_once(SessionLocal, owner)
            if args.once:
                return
            if not worked:
                time.sleep(1)
    except KeyboardInterrupt:
        logger.info("pdf_worker_stopped")


if __name__ == "__main__":
    main()
