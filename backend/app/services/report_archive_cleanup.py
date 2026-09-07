"""Durable deletion compensation, independent of report and user lifetime."""

from dataclasses import dataclass
from datetime import timedelta
import multiprocessing
from uuid import uuid4
from sqlalchemy import or_, text
from app.db.models import ReportFileCleanupTask, ReportPdfArchive, ReportPdfAttempt
from app.services.report_job_repository import bounded_transaction, db_now
from app.services.report_archive_storage import ArchiveStorage
from app.services.report_pdf_errors import PdfError


def next_cleanup_delay(failure_count):
    return min(3600, 5 * (2 ** min(failure_count, 10)))


def _delete_child(root, key, connection):
    try:
        connection.send(ArchiveStorage(root).delete_attempt(key))
    except Exception:
        connection.send(False)
    finally:
        connection.close()


def bounded_delete(root, key):
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_delete_child, args=(str(root), key, send))
    try:
        process.start()
        send.close()
        result = receive.recv() if receive.poll(10) else False
        return result is True
    except (OSError, EOFError):
        return False
    finally:
        from app.workers.report_process_control import stop_child

        if process.pid is not None:
            stop_child(process)
        process.close()
        receive.close()
        send.close()


def run_cleanup_once(db, root, *, task_id=None, delete_io=bounded_delete):
    try:
        bounded_transaction(db)
        now = db_now(db)
        query = db.query(ReportFileCleanupTask).filter(
            ReportFileCleanupTask.state != "done",
            ReportFileCleanupTask.next_attempt_at <= now,
            or_(
                ReportFileCleanupTask.lease_expires_at.is_(None),
                ReportFileCleanupTask.lease_expires_at <= now,
            ),
        )
        if task_id is not None:
            query = query.filter_by(id=task_id)
        task = (
            query.order_by(
                ReportFileCleanupTask.next_attempt_at, ReportFileCleanupTask.id
            )
            .with_for_update(skip_locked=True)
            .first()
        )
        if task is None:
            db.rollback()
            return None
        # A referenced original is never an orphan, even if an erroneous cleanup
        # row exists. Do not take archive locks in the cleanup lock order.
        referenced = (
            db.query(ReportPdfArchive.report_id)
            .join(
                ReportPdfAttempt,
                ReportPdfArchive.published_attempt_id == ReportPdfAttempt.id,
            )
            .filter(ReportPdfAttempt.object_key == task.object_key)
            .first()
        )
        task_id = task.id
        key = task.object_key
        token = uuid4()
        task.state = "running"
        task.lease_token = token
        task.lease_expires_at = now + timedelta(seconds=45)
        db.commit()
        success = False if referenced else delete_io(root, key)
        bounded_transaction(db)
        task = (
            db.query(ReportFileCleanupTask)
            .filter_by(id=task_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        now = db_now(db)
        if not task or task.lease_token != token or task.lease_expires_at <= now:
            db.rollback()
            return False
        task.lease_token = None
        task.lease_expires_at = None
        if success:
            task.error_code = None
            if now >= task.not_before_final_check:
                task.state = "done"
                task.completed_at = now
            else:
                task.state = "settling"
                task.next_attempt_at = task.not_before_final_check
        else:
            task.state = "pending"
            task.failure_count += 1
            task.error_code = "pdf_storage_unavailable"
            task.next_attempt_at = now + timedelta(
                seconds=next_cleanup_delay(task.failure_count)
            )
        db.commit()
        return success
    except Exception:
        db.rollback()
        raise


@dataclass(frozen=True)
class DeleteReportResult:
    deleted: bool
    cleanup_state: str


def delete_owned_report(db, user_id, report_id, root):
    from app.services.report_generation_service import delete_report_job

    delete_report_job(db, user_id, report_id)
    return cleanup_deleted_report(db, report_id, root)


def cleanup_deleted_report(db, report_id, root):
    # One bounded I/O attempt per API call; the durable worker handles the rest.
    try:
        tasks = (
            db.query(ReportFileCleanupTask.id)
            .filter_by(report_id_snapshot=report_id)
            .filter(ReportFileCleanupTask.state != "done")
            .limit(2)
            .all()
        )
    except Exception:
        # The deletion and durable outbox have already committed. A transient
        # cleanup outage must not report that the report itself still exists.
        db.rollback()
        return DeleteReportResult(True, "pending")
    db.rollback()
    complete = True
    for (task_id,) in tasks[:1]:
        try:
            complete = bool(run_cleanup_once(db, root, task_id=task_id)) and complete
        except Exception:
            db.rollback()
            complete = False
    if len(tasks) > 1:
        complete = False
    return DeleteReportResult(True, "complete" if complete else "pending")
