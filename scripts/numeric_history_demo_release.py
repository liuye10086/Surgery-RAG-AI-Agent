"""Pure contracts and static gates for the local numeric-history demo release."""

from datetime import datetime
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePath
import re
import subprocess
import tempfile
import traceback

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.schemas.numeric_demo_release import (
    NumericDemoReleaseMetrics,
    NumericDemoReleaseRecord,
    NumericDemoSessionChecks,
    SafeCodeLocation,
    SafeReleaseDiagnostic,
    SESSION_CHECKS_FILENAME,
)
from app.services.prediction_case_source import seed_prediction_cases
from app.services.report_integrity import compute_input_snapshot_sha256
from scripts.numeric_report_acceptance_browser import convert_source_package


SOURCE_SHA = "3b333b090186e6c09fe938106bf2a176328e1d591b1bf6d56cf5ecbd7cd38296"
SOURCE_DATA_SHA = "2a18dee7fe1dcb89b583c5c7091f44b45607f7d4c2e9a93112dae26303bab426"
LEGACY_SHA = "32b8069f92dab3e104f3668c3639cdc6e5461f5bedf61a4f7590ce2cef478215"
HISTORY_SHA = "a6816ed1a30d9a65ae089f67746e98473f0514732883d98a2843d3bc90db2464"
RENDERER_SHA = "38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558"
ACCEPTANCE_SHA = "3dd8473c6df25aeb84c7e5c2782caef6e420e60227578062108a9edf30332c37"
MAX_ACCEPTANCE_BYTES = 1024 * 1024
DEMO_DATABASE = "surgery_rag_test"
DEMO_ALEMBIC_VERSION = "0031"
EXECUTION_PHASES = (
    "model_loading",
    "prediction",
    "standard_evidence",
    "rendering",
    "persistence",
)
JOB_STATES = ("queued", "running", "completed", "failed", "cancelled")
ARCHIVE_STATES = ("queued", "rendering", "ready", "failed", "missing", "corrupt")
SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*$")
MAX_DIAGNOSTIC_FRAMES = 8
REPO_ROOT = Path(__file__).resolve().parents[1]

# The demo operator identities. The email domain must be one the API's response
# schema accepts: ``EmailStr`` rejects reserved domains such as ``.invalid``, and
# a rejected address makes ``/auth/me`` answer 500, which drops the browser back
# to the login page and never shows the operator workspace.
DEMO_IDENTITIES = (
    ("numeric-history-demo-primary", "numeric-history-demo-primary@example.com", "ai_operator"),
    ("numeric-history-demo-secondary", "numeric-history-demo-secondary@example.com", "ai_operator"),
    ("numeric-history-demo-doctor", "numeric-history-demo-doctor@example.com", "doctor"),
)

ALLOWED_DIRTY_DOCUMENTS = frozenset(
    {
        "docs/superpowers/plans/2026-09-16-prediction-model-refactor-phase-4-history-integration.md",
        "docs/superpowers/specs/2026-09-09-prediction-model-refactor-master-design.md",
        "docs/superpowers/specs/2026-09-20-prediction-model-refactor-phase-5-local-demo-release-design.md",
        "docs/superpowers/plans/2026-09-20-prediction-model-refactor-phase-5-local-demo-release.md",
    }
)


def _nested(value, *keys):
    for key in keys:
        value = value[key]
    return value


def validate_acceptance_result(path: Path, identities: dict) -> dict:
    """Bind the frozen phase-four success to the current static identities."""
    try:
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise ValueError
        if path.stat().st_size > MAX_ACCEPTANCE_BYTES:
            raise ValueError
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != ACCEPTANCE_SHA:
            raise ValueError
        result = json.loads(raw)
        expected_identity_pairs = (
            (("identities", "source", "source_manifest_sha256"), SOURCE_SHA),
            (("identities", "source", "data_content_sha256"), SOURCE_DATA_SHA),
            (("identities", "legacy", "bundle_sha256"), LEGACY_SHA),
            (("identities", "history", "bundle_sha256"), HISTORY_SHA),
            (("identities", "renderer", "manifest_sha256"), RENDERER_SHA),
            (("external_llm", "planned_reports"), 5),
            (("external_llm", "worker_invocations"), 5),
            (("external_llm", "completed_reports"), 5),
            (("external_llm", "audited_invocations"), 5),
        )
        if any(_nested(result, *keys) != expected for keys, expected in expected_identity_pairs):
            raise ValueError
        current_pairs = (
            (("source", "source_manifest_sha256"), SOURCE_SHA),
            (("source", "data_content_sha256"), SOURCE_DATA_SHA),
            (("legacy", "bundle_sha256"), LEGACY_SHA),
            (("history", "bundle_sha256"), HISTORY_SHA),
            (("renderer", "manifest_sha256"), RENDERER_SHA),
        )
        if any(_nested(identities, *keys) != expected for keys, expected in current_pairs):
            raise ValueError
        if (
            result["status"] != "passed"
            or result["is_synthetic"] is not True
            or result["clinical_validity_claim"] is not False
            or result["checks"]["page_errors"] != []
            or len(result["reports"]) != 5
            or result["identities"]["source"]["source_run_id"]
            != identities["source"]["source_run_id"]
        ):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ValueError("frozen_acceptance_mismatch") from None
    return {
        "acceptance_result_sha256": ACCEPTANCE_SHA,
        "status": "passed",
        "planned_reports": 5,
        "worker_invocations": 5,
        "completed_reports": 5,
        "audited_invocations": 5,
        "page_errors": [],
    }


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
    ).stdout


def _status_path(line: str) -> str:
    if len(line) < 4 or line[2] != " ":
        raise ValueError("uncommitted_release_code")
    status, path = line[:2], line[3:]
    if status not in {" M", "M ", "MM", "??", "A ", "AM"}:
        raise ValueError("uncommitted_release_code")
    if not path or path.startswith('"') or " -> " in path or "\\" in path:
        raise ValueError("uncommitted_release_code")
    return path


def validate_git_release_state(root: Path, *, apply: bool) -> str:
    """Return the exact release commit when only approved documents are dirty."""
    root = Path(root).resolve()
    try:
        head = _git(root, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.SubprocessError):
        raise ValueError("git_identity_required") from None
    if re.fullmatch(r"[0-9a-f]{40}", head) is None:
        raise ValueError("git_identity_required")
    try:
        status = _git(root, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError):
        raise ValueError("git_identity_required") from None
    for line in status.splitlines():
        if _status_path(line) not in ALLOWED_DIRTY_DOCUMENTS:
            raise ValueError("uncommitted_release_code")
    return head


def inspect_demo_database(connection) -> dict:
    """Verify the connected database itself before any release output or seed write."""
    connection.execute(text("SET TRANSACTION READ ONLY"))
    database = connection.execute(text("SELECT current_database()")).scalar_one()
    if database != DEMO_DATABASE:
        raise ValueError("isolated_test_database_required")
    version = connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    if version != DEMO_ALEMBIC_VERSION:
        raise ValueError("test_database_migration_required")
    counts = {
        table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("users", "operator_cases", "ai_reports")
    }
    if any(type(value) is not int or value != 0 for value in counts.values()):
        raise ValueError("clean_test_database_required")
    return {"database": database, "alembic_version": version, "counts": counts}


def seed_demo_database(connection, source_dir: Path, identities: dict) -> dict:
    """Seed all demo identities and frozen cases inside the caller's transaction."""
    if not connection.in_transaction():
        raise ValueError("demo_seed_transaction_required")
    users = (
        connection.execute(
            text(
                "INSERT INTO users (username,email,hashed_password,role) VALUES "
                "(:primary_name,:primary_email,'x','ai_operator'),"
                "(:secondary_name,:secondary_email,'x','ai_operator'),"
                "(:doctor_name,:doctor_email,'x','doctor') RETURNING id"
            ),
            {
                "primary_name": DEMO_IDENTITIES[0][0],
                "primary_email": DEMO_IDENTITIES[0][1],
                "secondary_name": DEMO_IDENTITIES[1][0],
                "secondary_email": DEMO_IDENTITIES[1][1],
                "doctor_name": DEMO_IDENTITIES[2][0],
                "doctor_email": DEMO_IDENTITIES[2][1],
            },
        )
        .scalars()
        .all()
    )
    if len(users) != 3 or any(type(user_id) is not int for user_id in users):
        raise ValueError("demo_seed_users_failed")
    for code, name in (("ad", "阿尔茨海默病"), ("fatty_liver", "脂肪肝")):
        connection.execute(
            text(
                "INSERT INTO diseases (code,name,operator_enabled) "
                "VALUES (:code,:name,true) "
                "ON CONFLICT (code) DO UPDATE SET operator_enabled=true"
            ),
            {"code": code, "name": name},
        )
    # seed_prediction_cases accepts either an Engine or a connection-bound
    # Session and validates the bind through its URL. SQLAlchemy Connection
    # exposes that URL through .engine, so make the same read-only identity
    # available while keeping every ORM write on this outer transaction.
    if not hasattr(connection, "url") and hasattr(connection, "engine"):
        connection.url = connection.engine.url
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="rollback_only",
    )
    with tempfile.TemporaryDirectory(prefix="numeric-history-demo-") as temporary:
        package = convert_source_package(
            Path(source_dir),
            deepcopy(identities["source"]),
            Path(temporary) / "source-package",
        )
        case_ids = seed_prediction_cases(factory, package, users[0])
    if not case_ids or any(type(case_id) is not int for case_id in case_ids):
        raise ValueError("demo_seed_cases_failed")
    subjects = (
        connection.execute(
            text(
                "SELECT id, anonymous_case_code, prediction_source->>'subject_id' AS subject_id "
                "FROM operator_cases WHERE id = ANY(:case_ids) ORDER BY id"
            ),
            {"case_ids": case_ids},
        )
        .mappings()
        .all()
    )
    if len(subjects) != len(case_ids):
        raise ValueError("demo_seed_cases_failed")
    safe_subjects = [
        {
            "case_id": row["id"],
            "anonymous_case_code": row["anonymous_case_code"],
            "subject_id": row["subject_id"],
        }
        for row in subjects
    ]
    return {
        "user_ids": {
            "primary_operator": users[0],
            "secondary_operator": users[1],
            "doctor": users[2],
        },
        "case_ids": list(case_ids),
        "subjects": safe_subjects,
    }


def identity_matches(identities: dict | None, git_commit: str | None) -> dict:
    """Compare recorded identities with the frozen constants; never assume a match."""
    identities = identities or {}
    source = identities.get("source") or {}
    return {
        "source_matches": source.get("source_manifest_sha256") == SOURCE_SHA
        and source.get("data_content_sha256") == SOURCE_DATA_SHA,
        "legacy_bundle_matches": (identities.get("legacy") or {}).get("bundle_sha256")
        == LEGACY_SHA,
        "history_bundle_matches": (identities.get("history") or {}).get("bundle_sha256")
        == HISTORY_SHA,
        "renderer_matches": (identities.get("renderer") or {}).get("manifest_sha256")
        == RENDERER_SHA,
        "acceptance_matches": (identities.get("acceptance") or {}).get(
            "acceptance_result_sha256"
        )
        == ACCEPTANCE_SHA,
        "git_commit_matches": git_commit == identities.get("git_commit")
        and isinstance(git_commit, str),
    }


def _zero_metrics(identities: dict | None = None, git_commit: str | None = None) -> dict:
    def timing():
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
            "model_loading": timing(),
            "prediction": timing(),
            "standard_evidence": timing(),
            "rendering": timing(),
            "persistence": timing(),
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
        "identity": identity_matches(identities, git_commit),
    }


def build_release_record(
    run_id: str,
    identities: dict,
    git_commit: str,
    runtime: dict,
    started_at: datetime,
) -> NumericDemoReleaseRecord:
    return NumericDemoReleaseRecord.model_validate(
        {
            "schema_version": "numeric_history_demo_release.v1",
            "run_id": run_id,
            "status": "starting",
            "is_synthetic": True,
            "clinical_validity_claim": False,
            "clinical_status": "not_assessable",
            "production_enabled": False,
            "started_at": started_at,
            "stopped_at": None,
            "identities": {
                "source_manifest_sha256": identities["source"]["source_manifest_sha256"],
                "source_data_content_sha256": identities["source"]["data_content_sha256"],
                "legacy_bundle_sha256": identities["legacy"]["bundle_sha256"],
                "history_bundle_sha256": identities["history"]["bundle_sha256"],
                "renderer_manifest_sha256": identities["renderer"]["manifest_sha256"],
                "acceptance_result_sha256": identities["acceptance"]["acceptance_result_sha256"],
                "git_commit": git_commit,
            },
            "runtime": runtime,
            "metrics": _zero_metrics(identities, git_commit),
            "diagnostics": [],
            "cleanup_errors": [],
        }
    )


def transition_release(
    record: NumericDemoReleaseRecord,
    status: str,
    *,
    at: datetime,
    metrics: dict | NumericDemoReleaseMetrics | None = None,
    diagnostics: list[dict] | None = None,
) -> NumericDemoReleaseRecord:
    allowed = {
        "starting": {"running", "failed"},
        "running": {"stopped", "failed"},
        "stopped": set(),
        "failed": set(),
    }
    if status not in allowed[record.status]:
        raise ValueError("invalid_release_transition")
    raw = record.model_dump(mode="python")
    raw["status"] = status
    raw["stopped_at"] = at if status in {"stopped", "failed"} else None
    if metrics is not None:
        raw["metrics"] = (
            metrics.model_dump(mode="python")
            if isinstance(metrics, NumericDemoReleaseMetrics)
            else metrics
        )
    if diagnostics is not None:
        raw["diagnostics"] = diagnostics
    return NumericDemoReleaseRecord.model_validate(raw)


def atomic_write_release(path: Path, record: NumericDemoReleaseRecord) -> None:
    """Validate and atomically replace the release record in its final directory."""
    path = Path(path)
    validated = NumericDemoReleaseRecord.model_validate(
        record.model_dump(mode="python")
    )
    payload = validated.model_dump_json(indent=2).encode("utf-8") + b"\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def safe_diagnostic(stage: str, error: BaseException) -> SafeReleaseDiagnostic:
    """Project any failure to a closed code location; never keep its text."""
    def token(value: str, fallback: str) -> str:
        return value if isinstance(value, str) and SAFE_NAME.fullmatch(value) else fallback

    locations = []
    frames = traceback.extract_tb(error.__traceback__) if error.__traceback__ else []
    for frame in frames[-MAX_DIAGNOSTIC_FRAMES:]:
        name = PurePath(frame.filename).name
        if not SAFE_NAME.fullmatch(frame.name or "") or not SAFE_NAME.fullmatch(name):
            continue
        locations.append(
            SafeCodeLocation(file=name, line=max(1, frame.lineno), function=frame.name)
        )
    return SafeReleaseDiagnostic(
        stage=token(stage, "unknown"),
        error_type=token(type(error).__name__, "Exception"),
        error_location=locations,
    )


def read_session_checks(output: Path) -> dict | None:
    """Return the outcomes the browser session recorded, or None when it recorded none.

    A missing record is reported as absent, never as a passing result: callers
    turn ``None`` into zero counts instead of inferring success from silence.
    """
    path = Path(output) / SESSION_CHECKS_FILENAME
    if not path.exists():
        return None
    try:
        checks = NumericDemoSessionChecks.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except Exception:
        raise ValueError("demo_session_checks_invalid") from None
    return checks.admission.model_dump(mode="python")


def inspect_release_record(path: Path) -> dict:
    """Read-only view of an existing record; a leftover run is never called stopped."""
    try:
        record = NumericDemoReleaseRecord.model_validate_json(
            Path(path).read_text(encoding="utf-8")
        )
    except Exception:
        raise ValueError("demo_release_record_unreadable") from None
    return {
        "run_id": record.run_id,
        "status": record.status,
        "unconfirmed_stop": record.status in {"starting", "running"},
        "clinical_status": record.clinical_status,
    }


def _canonical_sha256(value) -> str:
    """The same canonical JSON form the publication path stores its digests with."""
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _empty_phase_samples() -> dict:
    return {phase: [] for phase in EXECUTION_PHASES}


def _jobs_metrics(jobs: list[dict]) -> dict:
    counts = {state: 0 for state in JOB_STATES}
    timeouts = 0
    timed_out_phases = set()
    for job in jobs:
        status = job["status"]
        if status not in counts:
            raise ValueError("demo_job_state_invalid")
        counts[status] += 1
        if job.get("error_code") == "phase_timeout":
            timeouts += 1
            timed_out_phases.add(job.get("failure_phase") or "unknown")
    return {
        **counts,
        "unsettled": counts["queued"] + counts["running"],
        "phase_timeouts": timeouts,
        "phase_timeout_phases": sorted(timed_out_phases),
    }


def _timing_metrics(jobs: list[dict], audit: list[dict]) -> dict:
    """Attribute each phase's duration from its own audit order; no wall-clock guess.

    A re-queued report interleaves the attempts' checkpoints, so the intervals
    are taken within one batch; only a single-attempt report is closed by the
    job's own finish time, and a multi-attempt report simply leaves its last
    phase unsampled rather than reporting a span that never happened.
    """
    finished = {job["report_id"]: job.get("finished_at") for job in jobs}
    samples = _empty_phase_samples()
    for report_id in sorted({event["report_id"] for event in audit}):
        events = sorted(
            (
                event
                for event in audit
                if event["report_id"] == report_id
                and event["event_kind"] == "phase_entered"
            ),
            key=lambda event: event["event_seq"],
        )
        batches = {event["batch_id"] for event in events}
        for index, event in enumerate(events):
            ends_batch = (
                index + 1 >= len(events)
                or events[index + 1]["batch_id"] != event["batch_id"]
            )
            if ends_batch:
                end = finished.get(report_id) if len(batches) == 1 else None
            else:
                end = events[index + 1]["created_at"]
            if end is None:
                continue
            elapsed_ms = int((end - event["created_at"]).total_seconds() * 1000)
            if elapsed_ms < 0:
                raise ValueError("demo_audit_integrity_failed")
            # 'queued', 'terminal' and 'unknown' are not execution phases.
            if event["phase"] in samples:
                samples[event["phase"]].append(elapsed_ms)
    return {
        phase: {
            "samples": len(values),
            "total_ms": sum(values),
            "max_ms": max(values, default=0),
        }
        for phase, values in samples.items()
    }


def _llm_audit_metrics(audit: list[dict]) -> dict:
    """Close every invocation against its own task and batch, without payloads.

    A report records a ``task_finished`` for each model task as well as for the
    narrative, but an ``invocation_started`` only for the narrative. A finish
    with no matching start is therefore normal; a start whose matching finish
    never arrives, or arrives out of order, is not closed.
    """
    started = finished = closed = unclosed = 0
    for report_id in sorted({event["report_id"] for event in audit}):
        events = sorted(
            (
                event
                for event in audit
                if event["report_id"] == report_id
                and event["event_kind"] in ("invocation_started", "task_finished")
            ),
            key=lambda event: event["event_seq"],
        )
        if len({event["batch_id"] for event in events}) > 1:
            raise ValueError("demo_audit_integrity_failed")
        starts = [event for event in events if event["event_kind"] == "invocation_started"]
        finished += len([e for e in events if e["event_kind"] == "task_finished"])
        started += len(starts)
        pending = {}
        unmatched = 0
        for event in events:
            task = event["task"]
            if event["event_kind"] == "invocation_started":
                if task in pending:
                    unmatched += 1
                pending[task] = event
            elif task in pending:
                start = pending.pop(task)
                if (
                    event["event_seq"] < start["event_seq"]
                    or event["created_at"] < start["created_at"]
                ):
                    raise ValueError("demo_audit_integrity_failed")
        unmatched += len(pending)
        if unmatched:
            unclosed += 1
        elif starts:
            closed += 1
    return {
        "invocation_started": started,
        "task_finished": finished,
        "closed_reports": closed,
        "unclosed_reports": unclosed,
    }


def _history_metrics(reports: list[dict]) -> dict:
    """Verify saved identities only; the current model is never loaded or rerun."""
    published = [report for report in reports if report.get("published")]
    verified = sum(
        1
        for report in published
        if report["context_ok"]
        and report["snapshot_ok"]
        and report["evidence_ok"]
        and report["document_ok"]
    )
    return {"verified_reports": verified, "mismatches": len(published) - verified}


def _pdf_metrics(pdf: list[dict], downloads: int) -> dict:
    counts = {state: 0 for state in ARCHIVE_STATES}
    verified = mismatched = 0
    for archive in pdf:
        state = archive["state"]
        if state not in counts:
            raise ValueError("demo_archive_state_invalid")
        counts[state] += 1
        if state != "ready":
            continue
        if archive["verified"]:
            verified += 1
        else:
            mismatched += 1
    return {
        "ready": counts["ready"],
        "failed": counts["failed"],
        "missing": counts["missing"],
        "corrupt": counts["corrupt"],
        "downloads": downloads,
        "bytes_verified": verified,
        "sha_mismatches": mismatched,
    }


def _admission_metrics(session: dict | None) -> tuple[dict, dict]:
    """Only what the browser session actually recorded; silence is zero, not a pass."""
    session = session or {}
    rejected = (
        session.get("admission_disabled", 0)
        + session.get("permission_denied", 0)
        + session.get("invalid_input", 0)
        + session.get("conflict", 0)
    )
    return (
        {
            "requests": session.get("submissions", 0),
            "idempotency_replays": session.get("idempotency_replays", 0),
            "rejected": rejected,
            "admission_disabled": session.get("admission_disabled", 0),
            "permission_denied": session.get("permission_denied", 0),
            "invalid_input": session.get("invalid_input", 0),
            "conflict": session.get("conflict", 0),
        },
        {
            "non_owner_404": session.get("non_owner_404", 0),
            "wrong_role_403": session.get("wrong_role_403", 0),
            "disease_permission_denied": session.get("disease_permission_denied", 0),
        },
    )


def build_release_metrics(facts: dict) -> NumericDemoReleaseMetrics:
    """Recompute the engineering summary from recorded facts alone."""
    if facts.get("external_records", 0):
        raise ValueError("demo_external_records_present")
    admission, authorization = _admission_metrics(facts.get("session"))
    return NumericDemoReleaseMetrics.model_validate(
        {
            "admission": admission,
            "jobs": _jobs_metrics(facts.get("jobs", [])),
            "timings": _timing_metrics(facts.get("jobs", []), facts.get("audit", [])),
            "llm_audit": _llm_audit_metrics(facts.get("audit", [])),
            "authorization": authorization,
            "history": _history_metrics(facts.get("reports", [])),
            "pdf": _pdf_metrics(facts.get("pdf", []), facts.get("downloads", 0)),
            "identity": {
                key: bool(value)
                for key, value in (
                    facts.get("identity") or identity_matches(None, None)
                ).items()
            },
        }
    )


def _scoped_ids(connection, seeded: dict) -> tuple[list[int], list[int]]:
    user_ids = sorted(set(seeded["user_ids"].values()))
    if not user_ids or any(type(value) is not int for value in user_ids):
        raise ValueError("demo_seed_users_failed")
    return user_ids, sorted(set(seeded["case_ids"]))


def _reject_external_records(connection, user_ids: list[int], report_ids: list[int]) -> int:
    """Any row the seed did not create would quietly change every denominator."""
    external = connection.execute(
        text("SELECT count(*) FROM users WHERE id <> ALL(:user_ids)"),
        {"user_ids": user_ids},
    ).scalar_one()
    external += connection.execute(
        text("SELECT count(*) FROM operator_cases WHERE user_id <> ALL(:user_ids)"),
        {"user_ids": user_ids},
    ).scalar_one()
    scoped = report_ids or [0]
    external += connection.execute(
        text("SELECT count(*) FROM report_generation_jobs WHERE report_id <> ALL(:ids)"),
        {"ids": scoped},
    ).scalar_one()
    external += connection.execute(
        text(
            "SELECT count(*) FROM report_generation_audit_events "
            "WHERE report_id <> ALL(:ids)"
        ),
        {"ids": scoped},
    ).scalar_one()
    external += connection.execute(
        text("SELECT count(*) FROM report_pdf_archives WHERE report_id <> ALL(:ids)"),
        {"ids": scoped},
    ).scalar_one()
    external += connection.execute(
        text("SELECT count(*) FROM report_pdf_deliveries WHERE report_id <> ALL(:ids)"),
        {"ids": scoped},
    ).scalar_one()
    return external


def collect_demo_facts(session, archive_root: Path, seeded: dict) -> dict:
    """Read the isolated demo's own facts; nothing here writes or reloads a model."""
    connection = session
    user_ids, case_ids = _scoped_ids(connection, seeded)
    reports = (
        connection.execute(
            text(
                "SELECT id,status,input_snapshot,input_snapshot_sha256,"
                "evidence_snapshot,evidence_snapshot_sha256,report_document,"
                "report_document_sha256 FROM ai_reports "
                "WHERE user_id = ANY(:user_ids) ORDER BY id"
            ),
            {"user_ids": user_ids},
        )
        .mappings()
        .all()
    )
    report_ids = [row["id"] for row in reports]
    jobs = (
        connection.execute(
            text(
                "SELECT report_id,status,error_code,last_execution_phase,failure_phase,"
                "finished_at,generation_context,context_sha256 FROM report_generation_jobs "
                "ORDER BY report_id"
            )
        )
        .mappings()
        .all()
    )
    audit = (
        connection.execute(
            text(
                "SELECT report_id,event_seq,event_kind,phase,task,generation_batch_id,"
                "created_at FROM report_generation_audit_events ORDER BY report_id,event_seq"
            )
        )
        .mappings()
        .all()
    )
    archives = (
        connection.execute(
            text(
                "SELECT a.report_id,a.state,a.pdf_sha256,a.size_bytes,a.renderer_sha256,"
                "p.object_key FROM report_pdf_archives a LEFT JOIN report_pdf_attempts p "
                "ON p.id = a.published_attempt_id ORDER BY a.report_id"
            )
        )
        .mappings()
        .all()
    )
    downloads = connection.execute(
        text("SELECT count(*) FROM report_pdf_deliveries WHERE report_id = ANY(:ids)"),
        {"ids": report_ids or [0]},
    ).scalar_one()
    jobs_by_report = {job["report_id"]: job for job in jobs}

    def readable(value, recorded) -> bool:
        return value is not None and recorded is not None and _canonical_sha256(value) == recorded

    report_facts = []
    for row in reports:
        job = jobs_by_report.get(row["id"])
        context = job["generation_context"] if job else None
        report_facts.append(
            {
                "report_id": row["id"],
                "status": row["status"],
                "published": row["status"] == "completed" and row["report_document"] is not None,
                "context_ok": bool(job)
                and readable(context, job["context_sha256"])
                and (context.get("algorithm") or {}).get("bundle_sha256") == HISTORY_SHA,
                "snapshot_ok": row["input_snapshot"] is not None
                and compute_input_snapshot_sha256(row["input_snapshot"])
                == row["input_snapshot_sha256"],
                "evidence_ok": readable(
                    row["evidence_snapshot"], row["evidence_snapshot_sha256"]
                ),
                "document_ok": readable(
                    row["report_document"], row["report_document_sha256"]
                ),
            }
        )

    pdf_facts = []
    storage = None
    if any(row["object_key"] for row in archives):
        from app.services.report_archive_storage import ArchiveStorage
        from app.services.report_pdf_errors import PdfError

        storage = ArchiveStorage(Path(archive_root), create=False)
    for row in archives:
        if row["state"] == "ready" and row["renderer_sha256"] != RENDERER_SHA:
            # An original produced by any other renderer is not this release's.
            raise ValueError("demo_renderer_identity_mismatch")
        verified = False
        if storage is not None and row["object_key"] and row["state"] == "ready":
            try:
                with storage.open_verified(
                    row["object_key"], row["pdf_sha256"], row["size_bytes"]
                ):
                    verified = True
            except PdfError:
                verified = False
        pdf_facts.append(
            {"report_id": row["report_id"], "state": row["state"], "verified": verified}
        )

    return {
        "external_records": _reject_external_records(connection, user_ids, report_ids),
        "reports": report_facts,
        "jobs": [dict(job) for job in jobs],
        "audit": [
            {
                "report_id": row["report_id"],
                "event_seq": row["event_seq"],
                "event_kind": row["event_kind"],
                "phase": row["phase"],
                "task": row["task"],
                "batch_id": str(row["generation_batch_id"]),
                "created_at": row["created_at"],
            }
            for row in audit
        ],
        "pdf": pdf_facts,
        "downloads": downloads,
        "session": None,
        # Re-read HEAD rather than compare the record with itself: a commit that
        # moved during the session would otherwise still read as a match.
        "identity": identity_matches(seeded.get("identities"), _current_commit()),
    }


def _current_commit() -> str | None:
    try:
        head = _git(REPO_ROOT, "rev-parse", "HEAD").strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return head if re.fullmatch(r"[0-9a-f]{40}", head) else None


def summarize_demo_release(
    session_factory, archive_root: Path, seeded: dict
) -> NumericDemoReleaseMetrics:
    """Build the session's engineering summary from database, audit and file facts."""
    with session_factory() as session:
        facts = collect_demo_facts(session, archive_root, seeded)
    facts["session"] = read_session_checks(Path(archive_root).parent)
    return build_release_metrics(facts)
