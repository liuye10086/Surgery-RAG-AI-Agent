"""Supervise a frozen local numeric-history demo release."""

import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import stat
import subprocess
import sys
import threading
import time
import urllib.request

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
sys.dont_write_bytecode = True

from scripts.numeric_history_demo_release import (
    ACCEPTANCE_SHA,
    HISTORY_SHA,
    LEGACY_SHA,
    RENDERER_SHA,
    SOURCE_DATA_SHA,
    SOURCE_SHA,
    atomic_write_release,
    build_release_record,
    inspect_demo_database,
    inspect_release_record,
    safe_diagnostic,
    seed_demo_database,
    summarize_demo_release,
    transition_release,
    validate_acceptance_result,
    validate_git_release_state,
)
from scripts.run_numeric_history_acceptance import (
    preflight as phase_four_preflight,
    require_free_ports,
    validate_database_url,
)


DEMO_PORTS = (18060, 15173)
PROCESS_NAMES = frozenset({"api", "frontend", "report_worker", "pdf_worker"})
OWNED_PROCESS_NAMES = PROCESS_NAMES | {"browser"}
PROCESS_EVENTS = frozenset({"started", "ready", "stopped", "exited"})
RELEASE_ERROR_CODES = frozenset(
    {
        "invalid_arguments",
        "test_database_url_required",
        "isolated_test_database_required",
        "external_llm_authorization_required",
        "input_path_invalid",
        "output_already_exists",
        "port_in_use",
        "frozen_source_mismatch",
        "frozen_source_scenarios_missing",
        "frozen_model_mismatch",
        "frozen_renderer_mismatch",
        "renderer_static_runtime_unsupported",
        "frozen_acceptance_mismatch",
        "git_identity_required",
        "uncommitted_release_code",
        "preflight_identity_changed",
        "phase4_migration_required",
        "clean_test_database_required",
        "demo_seed_transaction_required",
        "demo_seed_users_failed",
        "demo_seed_cases_failed",
        "demo_release_record_unreadable",
        "demo_release_record_write_failed",
        "demo_external_records_present",
        "demo_audit_integrity_failed",
        "demo_session_checks_invalid",
        "demo_shutdown_failed",
        "demo_evaluation_failed",
        "demo_renderer_identity_mismatch",
        "demo_archive_integrity_failed",
        "demo_history_integrity_failed",
        "demo_jobs_unsettled",
        "demo_identity_drift",
        "owned_service_exited",
        "owned_service_start_timeout",
        "owned_service_missing",
        "owned_process_name_invalid",
        "owned_process_resume_failed",
        "demo_browser_child_failed",
        "demo_browser_start_timeout",
        "demo_browser_stop_timeout",
        "demo_browser_protocol_closed",
        "demo_browser_protocol_invalid",
        "demo_browser_subjects_invalid",
        "demo_browser_token_required",
        "demo_session_check_failed",
        "inflight_not_settled",
        "audit_limit_exceeded",
    }
)
POSIX_SIGKILL = getattr(signal, "SIGKILL", 9)
UNIQUE_OPTIONS = frozenset(
    {
        "--source-dir",
        "--legacy-bundle",
        "--history-bundle",
        "--renderer",
        "--acceptance-result",
        "--output",
        "--apply",
        "--allow-external-llm",
    }
)


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")

    def parse_args(self, args=None, namespace=None):
        values = list(sys.argv[1:] if args is None else args)
        options = [
            value.split("=", 1)[0]
            for value in values
            if isinstance(value, str) and value.startswith("--")
        ]
        if any(options.count(option) > 1 for option in UNIQUE_OPTIONS):
            raise ValueError("invalid_arguments")
        return super().parse_args(values, namespace)


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _reject_symlink_components(path: Path) -> None:
    candidate = _absolute(path)
    for component in (candidate, *candidate.parents):
        try:
            mode = component.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError("input_path_invalid")
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("input_path_invalid") from None


def _strict_input(path: Path, *, directory: bool) -> Path:
    try:
        _reject_symlink_components(path)
        resolved = _absolute(path).resolve(strict=True)
        if resolved.is_symlink():
            raise ValueError
        if directory != resolved.is_dir():
            raise ValueError
        if not directory and not resolved.is_file():
            raise ValueError
        return resolved
    except (OSError, RuntimeError, ValueError):
        raise ValueError("input_path_invalid") from None


def _validate_paths(args) -> None:
    output = _absolute(args.output)
    _reject_symlink_components(output.parent)
    if output.exists() or output.is_symlink():
        raise ValueError("output_already_exists")
    args.output = output.resolve(strict=False)
    args.source_dir = _strict_input(args.source_dir, directory=True)
    for name in ("legacy_bundle", "history_bundle", "renderer", "acceptance_result"):
        setattr(args, name, _strict_input(getattr(args, name), directory=False))


def preflight(args) -> dict:
    validate_database_url()
    if args.apply and not args.allow_external_llm:
        raise ValueError("external_llm_authorization_required")
    _validate_paths(args)
    require_free_ports(DEMO_PORTS)
    identities = phase_four_preflight(args)
    acceptance = validate_acceptance_result(args.acceptance_result, identities)
    git_commit = validate_git_release_state(ROOT, apply=args.apply)
    return {**identities, "acceptance": acceptance, "git_commit": git_commit}


def runtime_identity(args) -> dict:
    renderer = json.loads(args.renderer.read_text(encoding="utf-8"))
    node = subprocess.run(
        ["node", "--version"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        shell=False,
    ).stdout.strip()
    return {
        "python_version": platform.python_version(),
        "node_version": node.removeprefix("v"),
        "playwright_version": importlib.metadata.version("playwright"),
        "fonttools_version": importlib.metadata.version("fonttools"),
        "chromium_version": renderer["chromium_version"],
    }


def build_child_environment(
    args,
    database_url: str,
    output: Path,
    *,
    base_environment: dict | None = None,
) -> dict:
    """Build an isolated child environment without changing the parent process."""
    env = dict(os.environ if base_environment is None else base_environment)
    env.update(
        {
            "DATABASE_URL": database_url,
            "VECTOR_STORE_CONNECTION_STRING": database_url,
            "PYTHONPATH": os.pathsep.join((str(ROOT), str(ROOT / "backend"))),
            "PYTHONUTF8": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "MODELSCOPE_OFFLINE": "1",
            "REPORT_HISTORY_CURSOR_SECRET": secrets.token_urlsafe(32),
            "REPORT_PDF_ENABLED": "true",
            "REPORT_PDF_ACCEPTING": "true",
            "REPORT_PDF_RENDERER_MANIFEST": str(args.renderer.resolve()),
            "REPORT_ARCHIVE_ROOT": str((Path(output) / "archive").resolve()),
            "REPORT_JOBS_ENABLED": "true",
            "REPORT_JOBS_ACCEPTING": "true",
            "NUMERIC_REPORTS_ENABLED": "true",
            "NUMERIC_MODEL_BUNDLE": str(args.history_bundle.resolve()),
            "E2E_API_PROXY": "http://127.0.0.1:18060",
        }
    )
    return env


class SafeOwnedProcesses:
    """Own complete process trees while retaining only closed lifecycle events."""

    def __init__(self, output: Path, env: dict, *, platform_name: str | None = None):
        self.output = Path(output)
        self.env = dict(env)
        self.platform_name = os.name if platform_name is None else platform_name
        self.processes = {}
        self.jobs = {}
        self.cleanup_errors = []
        self.event_path = self.output / "process-events.jsonl"

    def _event(self, name: str, event: str, exit_code: int | None = None) -> None:
        if name not in OWNED_PROCESS_NAMES or event not in PROCESS_EVENTS:
            raise ValueError("invalid_process_event")
        value = {
            "process": name,
            "event": event,
            "time": datetime.now(timezone.utc).isoformat(),
            "exit_code": exit_code,
        }
        with self.event_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def start(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        *,
        protocol: bool = False,
    ):
        if name not in OWNED_PROCESS_NAMES or name in self.processes:
            raise ValueError("owned_process_name_invalid")
        job = None
        job_assigned = False
        process = None
        try:
            if self.platform_name == "nt":
                from app.workers.report_process_control import _WindowsJob

                job = _WindowsJob()
            popen_options = {
                "cwd": cwd,
                "env": self.env,
                "stdin": subprocess.PIPE if protocol else subprocess.DEVNULL,
                "stdout": subprocess.PIPE if protocol else subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "shell": False,
                "creationflags": (subprocess.CREATE_NO_WINDOW | 0x00000004)
                if self.platform_name == "nt"
                else 0,
                "start_new_session": self.platform_name != "nt",
            }
            if protocol:
                popen_options.update(
                    {"text": True, "encoding": "utf-8", "errors": "strict", "bufsize": 1}
                )
            process = subprocess.Popen(command, **popen_options)
            if job is not None:
                import ctypes
                from ctypes import wintypes
                from types import SimpleNamespace

                job.assign(SimpleNamespace(sentinel=int(process._handle)))
                job_assigned = True
                api = ctypes.WinDLL("ntdll", use_last_error=True)
                api.NtResumeProcess.argtypes = [wintypes.HANDLE]
                api.NtResumeProcess.restype = wintypes.LONG
                if api.NtResumeProcess(int(process._handle)) < 0:
                    raise RuntimeError("owned_process_resume_failed")
                self.jobs[name] = job
            self.processes[name] = process
            self._event(name, "started")
            return process
        except BaseException:
            if process is not None:
                self.processes.setdefault(name, process)
            if job is not None and job_assigned:
                self.jobs.setdefault(name, job)
            elif job is not None:
                try:
                    job.close()
                except BaseException as cleanup_error:
                    self.cleanup_errors.append(cleanup_error)
            if process is not None:
                try:
                    self.stop(name)
                except BaseException as cleanup_error:
                    self.cleanup_errors.append(cleanup_error)
            raise

    @staticmethod
    def _stop_posix_group(process) -> int:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            exit_code = None
        finally:
            # The root may exit before descendants that ignore SIGTERM. The
            # original PID is also the fixed process-group id because start()
            # used start_new_session=True, so always close the full group.
            try:
                os.killpg(process.pid, POSIX_SIGKILL)
            except ProcessLookupError:
                pass
            exit_code = process.wait(timeout=5)
        return exit_code

    @staticmethod
    def _stop_windows_process(process) -> int:
        if process.poll() is None:
            process.kill()
        return process.wait(timeout=5)

    def _check_exits(self, names=None) -> None:
        selected = set(self.processes) if names is None else set(names)
        for name, process in tuple(self.processes.items()):
            if name not in selected:
                continue
            exit_code = process.poll()
            if exit_code is not None:
                self._event(name, "exited", exit_code)
                raise RuntimeError("owned_service_exited")

    def ready(self, name: str, endpoint: str) -> None:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._check_exits()
            try:
                with urllib.request.urlopen(endpoint, timeout=2) as response:
                    if response.status == 200:
                        self._event(name, "ready")
                        return
            except OSError:
                pass
            time.sleep(0.25)
        raise RuntimeError("owned_service_start_timeout")

    def assert_alive(self, *names: str) -> None:
        self._check_exits(names)
        if any(name not in self.processes for name in names):
            raise RuntimeError("owned_service_missing")

    def observe_workers(self) -> None:
        self.assert_alive("report_worker", "pdf_worker")
        engine = create_engine(self.env["DATABASE_URL"])
        try:
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                connection.execute(
                    text("SELECT count(*) FROM report_generation_jobs")
                ).scalar_one()
                connection.execute(
                    text("SELECT count(*) FROM report_pdf_attempts")
                ).scalar_one()
        finally:
            engine.dispose()
        self.assert_alive("report_worker", "pdf_worker")
        self._event("report_worker", "ready")
        self._event("pdf_worker", "ready")

    def stop(self, name: str) -> None:
        process = self.processes.get(name)
        if process is None:
            return
        job = self.jobs.get(name)
        exit_code = process.poll()
        if job is not None:
            job.close()
            exit_code = process.wait(timeout=5)
        elif self.platform_name == "nt":
            exit_code = self._stop_windows_process(process)
        else:
            exit_code = self._stop_posix_group(process)
        self._event(name, "stopped", exit_code)
        self.processes.pop(name, None)
        self.jobs.pop(name, None)

    def close(self) -> list[BaseException]:
        errors = list(self.cleanup_errors)
        self.cleanup_errors.clear()
        for name in list(self.processes)[::-1]:
            try:
                self.stop(name)
            except BaseException as exc:
                errors.append(exc)
        return errors


def start_services(args, owned: SafeOwnedProcesses, env: dict) -> None:
    del args, env
    owned.start(
        "api",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.tests.e2e.report_test_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18060",
        ],
        ROOT,
    )
    owned.ready("api", "http://127.0.0.1:18060/health")
    owned.start(
        "frontend",
        [
            "node",
            str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
            "--host",
            "127.0.0.1",
            "--port",
            "15173",
            "--strictPort",
        ],
        # Vite serves its working directory; from the repository root there is
        # no index.html and every request answers 404, so readiness never fires.
        ROOT / "frontend",
    )
    owned.ready("frontend", "http://127.0.0.1:15173")
    owned.start(
        "report_worker",
        [sys.executable, "-m", "app.workers.report_worker"],
        ROOT / "backend",
    )
    owned.start(
        "pdf_worker",
        [sys.executable, "-m", "app.workers.report_pdf_worker"],
        ROOT / "backend",
    )
    owned.assert_alive("report_worker", "pdf_worker")
    owned.observe_workers()


def create_demo_token(user_id: int) -> str:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("demo_browser_user_required")
    from app.core.config import settings
    from app.core.security import create_access_token

    return create_access_token(
        {"sub": str(user_id)},
        settings.JWT_SECRET,
        settings.JWT_ALGORITHM,
    )


class BrowserSession:
    """Supervise a browser child whose main thread owns all Playwright objects."""

    def __init__(
        self,
        *,
        output: Path,
        user_ids: dict,
        subjects: list[dict],
        owned,
        token_factory=create_demo_token,
    ):
        self.output = Path(output)
        self.user_ids = user_ids
        self.subjects = subjects
        self.owned = owned
        self.token_factory = token_factory
        self.stop_event = threading.Event()
        self.session_ready = threading.Event()
        self.error = None
        self.result = None
        self.process = None
        self.started = False
        self.thread = threading.Thread(
            target=self._read_protocol,
            name="numeric-history-demo-browser-protocol",
            daemon=True,
        )

    def _read_protocol(self) -> None:
        terminal = False
        try:
            for line in self.process.stdout:
                value = json.loads(line)
                if value == {"event": "ready"}:
                    self.session_ready.set()
                elif value.get("event") == "stopped" and set(value) <= {
                    "event",
                    "cleanup_failed",
                }:
                    self.result = {
                        "cleanup_error_types": ["browser_child_cleanup_failed"]
                        if value.get("cleanup_failed") is True
                        else []
                    }
                    terminal = True
                    self.stop_event.set()
                elif value.get("event") == "error" and set(value) == {
                    "event",
                    "error_type",
                } and type(value["error_type"]) is str:
                    self.error = RuntimeError("demo_browser_child_failed")
                    terminal = True
                    self.stop_event.set()
                else:
                    raise ValueError("demo_browser_protocol_invalid")
            if not terminal:
                raise RuntimeError("demo_browser_protocol_closed")
        except BaseException as exc:
            self.error = exc
        finally:
            self.stop_event.set()

    def start(self) -> None:
        tokens = {
            name: self.token_factory(self.user_ids[key])
            for name, key in (
                ("primary", "primary_operator"),
                ("secondary", "secondary_operator"),
                ("doctor", "doctor"),
            )
        }
        payload = None
        try:
            self.process = self.owned.start(
                "browser",
                [sys.executable, "-m", "scripts.numeric_history_demo_browser", "--child"],
                ROOT,
                protocol=True,
            )
            payload = json.dumps(
                {
                    "output": str(self.output),
                    "tokens": tokens,
                    "subjects": self.subjects,
                },
                separators=(",", ":"),
            )
            self.process.stdin.write(payload + "\n")
            self.process.stdin.flush()
            self.thread.start()
            self.started = True
        except BaseException:
            if self.process is not None:
                try:
                    self.owned.stop("browser")
                except BaseException:
                    pass
            raise
        finally:
            tokens = None
            payload = None

    def wait_ready(self, *, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while not self.session_ready.wait(0.05):
            if self.error is not None:
                raise self.error
            if not self.thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("demo_browser_start_timeout")
        if self.error is not None:
            raise self.error

    def stop(self, *, timeout_seconds: float = 15) -> BaseException | None:
        self.stop_event.set()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.stdin.write('{"command":"stop"}\n')
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
        if self.started:
            self.thread.join(timeout_seconds)
        self.owned.stop("browser")
        if self.started and self.thread.is_alive():
            self.thread.join(1)
        if self.started and self.thread.is_alive():
            return RuntimeError("demo_browser_stop_timeout")
        if self.result and self.result.get("cleanup_error_types"):
            return RuntimeError("demo_browser_cleanup_failed")
        return self.error


def _inflight_timeout_seconds() -> int:
    from app.core.config import settings

    return sum(
        (
            settings.REPORT_JOB_QUEUE_SECONDS,
            settings.REPORT_JOB_RUN_SECONDS,
            settings.REPORT_JOB_LEASE_SECONDS,
            settings.REPORT_JOB_SWEEP_SECONDS,
            settings.REPORT_PDF_QUEUE_SECONDS,
            settings.REPORT_PDF_RUN_SECONDS,
            settings.REPORT_PDF_LEASE_SECONDS,
            settings.REPORT_PDF_SWEEP_SECONDS,
        )
    )


def wait_for_inflight(
    engine,
    owned,
    *,
    timeout_seconds: float | None = None,
    poll_seconds: float = 1,
    clock=time.monotonic,
    sleeper=time.sleep,
) -> dict:
    """Observe existing report/PDF work without changing a database row."""
    if timeout_seconds is None:
        timeout_seconds = _inflight_timeout_seconds()
    deadline = clock() + timeout_seconds
    polls = 0
    while True:
        owned.assert_alive("report_worker", "pdf_worker")
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            report_jobs = connection.execute(
                text(
                    "SELECT count(*) FROM report_generation_jobs "
                    "WHERE status IN ('queued','running')"
                )
            ).scalar_one()
            pdf_attempts = connection.execute(
                text(
                    "SELECT count(*) FROM report_pdf_attempts "
                    "WHERE status IN ('queued','running')"
                )
            ).scalar_one()
        polls += 1
        result = {
            "settled": report_jobs == 0 and pdf_attempts == 0,
            "report_jobs": report_jobs,
            "pdf_attempts": pdf_attempts,
            "polls": polls,
        }
        if result["settled"] or clock() >= deadline:
            return result
        sleeper(poll_seconds)


def restore_parent_environment(parent: dict) -> None:
    if dict(os.environ) != parent:
        os.environ.clear()
        os.environ.update(parent)


def supervise_demo_session(owned, browser: BrowserSession, *, poll_seconds: float = 0.25) -> str:
    """Wait for browser close or Ctrl+C while detecting owned-process failure."""
    try:
        while not browser.stop_event.wait(poll_seconds):
            if browser.error is not None:
                raise browser.error
            owned.assert_alive(*PROCESS_NAMES)
    except KeyboardInterrupt:
        return "keyboard_interrupt"
    if browser.error is not None:
        raise browser.error
    return "browser_closed"


def shutdown_demo_session(
    engine,
    session_factory,
    archive_root,
    owned,
    browser,
    seeded: dict,
    parent_environment: dict,
    *,
    wait_for=wait_for_inflight,
    summarize=None,
    restore=restore_parent_environment,
    port_check=require_free_ports,
) -> dict:
    """Close admission first, then converge work and release every resource."""
    if summarize is None:

        def summarize():
            return summarize_demo_release(session_factory, archive_root, seeded)

    errors = []
    inflight = None
    summary = None

    def attempt(stage, function):
        try:
            return function()
        except BaseException as exc:
            errors.append((stage, exc))
            return None

    attempt("stop_api", lambda: owned.stop("api"))
    browser_error = attempt("stop_browser", lambda: browser.stop(timeout_seconds=15))
    if isinstance(browser_error, BaseException):
        errors.append(("browser_session", browser_error))
    attempt("stop_frontend", lambda: owned.stop("frontend"))
    inflight = attempt("wait_inflight", lambda: wait_for(engine, owned))
    if inflight is not None and not inflight["settled"]:
        errors.append(("wait_inflight", RuntimeError("inflight_not_settled")))
    attempt("stop_report_worker", lambda: owned.stop("report_worker"))
    attempt("stop_pdf_worker", lambda: owned.stop("pdf_worker"))
    remaining = attempt("retry_owned_processes", owned.close)
    if remaining:
        errors.extend(("retry_owned_processes", error) for error in remaining)
    summary = attempt("summarize", summarize)
    attempt("dispose_engine", engine.dispose)
    attempt("restore_environment", lambda: restore(parent_environment))
    attempt("release_ports", lambda: port_check(DEMO_PORTS))
    return {"inflight": inflight, "summary": summary, "errors": errors}


def _diagnostic(stage: str, exc: BaseException) -> dict:
    return safe_diagnostic(stage, exc).model_dump(mode="python")


def _with_cleanup_errors(record, errors: list[dict]):
    raw = record.model_dump(mode="python")
    raw["cleanup_errors"] = errors
    return type(record).model_validate(raw)


def relative_artifact(output: Path) -> str:
    """The only path the console may print: relative to the repository root."""
    resolved = Path(output).resolve()
    try:
        return resolved.relative_to(ROOT).as_posix() + "/release.json"
    except ValueError:
        return resolved.name + "/release.json"


def evaluation_blockers(metrics) -> list[str]:
    """Integrity facts that must never be reported as a clean stop."""
    blockers = []
    if metrics.pdf.sha_mismatches:
        blockers.append("demo_archive_integrity_failed")
    if metrics.history.mismatches:
        blockers.append("demo_history_integrity_failed")
    if metrics.jobs.unsettled:
        blockers.append("demo_jobs_unsettled")
    if not all(metrics.identity.model_dump().values()):
        blockers.append("demo_identity_drift")
    return blockers


def _report_failure(output: Path, primary: BaseException) -> None:
    code = str(primary) if str(primary) in RELEASE_ERROR_CODES else "demo_release_failed"
    print(json.dumps({"status": "failed", "release": relative_artifact(output), "error": code}))


def execute(args, identities: dict) -> int:
    if not args.apply or not args.allow_external_llm:
        raise ValueError("external_llm_authorization_required")
    current = preflight(args)
    if current != identities:
        raise ValueError("preflight_identity_changed")
    url = validate_database_url()
    output = args.output.resolve()
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    archive_root = output / "archive"
    parent_environment = dict(os.environ)
    owned = None
    browser = None
    seeded = None
    record = None
    primary = None
    summary = None
    cleanup_errors = []
    try:
        with engine.connect() as connection:
            inspect_demo_database(connection)
        started_at = datetime.now(timezone.utc)
        prepared_record = build_release_record(
            started_at.strftime("%Y%m%dT%H%M%SZ"),
            identities,
            identities["git_commit"],
            runtime_identity(args),
            started_at,
        )
        output.mkdir(parents=True, exist_ok=False)
        record = prepared_record
        atomic_write_release(output / "release.json", record)
        with engine.begin() as connection:
            seeded = {
                **seed_demo_database(connection, args.source_dir, identities),
                # The shutdown evaluation compares these against the frozen
                # constants and the commit still checked out at that moment.
                "identities": identities,
            }
        env = build_child_environment(args, url, output)
        owned = SafeOwnedProcesses(output, env)
        start_services(args, owned, env)
        browser = BrowserSession(
            output=output,
            user_ids=seeded["user_ids"],
            subjects=seeded["subjects"],
            owned=owned,
        )
        browser.start()
        browser.wait_ready(timeout_seconds=95)
        record = transition_release(record, "running", at=datetime.now(timezone.utc))
        atomic_write_release(output / "release.json", record)
        supervise_demo_session(owned, browser)
    except BaseException as exc:
        primary = exc
    finally:
        if owned is not None and browser is not None and seeded is not None:
            shutdown = shutdown_demo_session(
                engine,
                factory,
                archive_root,
                owned,
                browser,
                seeded,
                parent_environment,
            )
            cleanup_errors.extend(
                _diagnostic(stage, exc) for stage, exc in shutdown["errors"]
            )
            summary = shutdown["summary"]
        else:
            if owned is not None:
                try:
                    for exc in owned.close() or []:
                        cleanup_errors.append(_diagnostic("process_cleanup", exc))
                except BaseException as exc:
                    cleanup_errors.append(_diagnostic("process_cleanup", exc))
            for stage, function in (
                ("database_cleanup", engine.dispose),
                (
                    "restore_environment",
                    lambda: restore_parent_environment(parent_environment),
                ),
                ("release_ports", lambda: require_free_ports(DEMO_PORTS)),
            ):
                try:
                    function()
                except BaseException as exc:
                    cleanup_errors.append(_diagnostic(stage, exc))

    if record is None:
        raise primary
    blockers = evaluation_blockers(summary) if summary is not None else []
    clean = (
        primary is None and not cleanup_errors and summary is not None and not blockers
    )
    if clean:
        try:
            stopped = transition_release(
                record, "stopped", at=datetime.now(timezone.utc), metrics=summary
            )
            atomic_write_release(output / "release.json", stopped)
        except BaseException:
            # The console may not continue as if the session had closed cleanly.
            print(
                json.dumps(
                    {"status": "error", "error": "demo_release_record_write_failed"}
                )
            )
            return 1
        print(
            json.dumps(
                {"status": "stopped", "release": relative_artifact(output)}
            )
        )
        return 0
    if primary is None:
        # Name the first thing that actually went wrong, not the last stage run.
        if blockers:
            primary = ValueError(blockers[0])
        elif cleanup_errors and cleanup_errors[0]["stage"] == "summarize":
            primary = ValueError("demo_evaluation_failed")
        else:
            primary = ValueError("demo_shutdown_failed")
    diagnostics = [_diagnostic("execution", primary)]
    failed = transition_release(
        record,
        "failed",
        at=datetime.now(timezone.utc),
        metrics=summary,
        diagnostics=diagnostics,
    )
    failed = _with_cleanup_errors(failed, cleanup_errors)
    try:
        atomic_write_release(output / "release.json", failed)
    except BaseException:
        print(json.dumps({"status": "error", "error": "demo_release_record_write_failed"}))
        if isinstance(primary, (KeyboardInterrupt, SystemExit)):
            raise primary
        return 1
    _report_failure(output, primary)
    if isinstance(primary, (KeyboardInterrupt, SystemExit)):
        raise primary
    return 1


def _parser() -> SafeParser:
    parser = SafeParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--legacy-bundle", type=Path, required=True)
    parser.add_argument("--history-bundle", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--acceptance-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-external-llm", action="store_true")
    return parser


def inspect_release_command(values: list[str]) -> int:
    """Read-only view of a leftover run; never opens a database or starts a process."""
    if len(values) != 1:
        raise ValueError("invalid_arguments")
    print(json.dumps(inspect_release_record(Path(values[0])), ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    try:
        if values[:1] == ["--inspect-release"]:
            return inspect_release_command(values[1:])
        args = _parser().parse_args(values)
        identities = preflight(args)
        if args.apply:
            return execute(args, identities)
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "database_connected": False,
                    "services_started": False,
                    "identities": identities,
                },
                ensure_ascii=False,
            )
        )
        return 0
    except Exception as exc:
        code = str(exc) if str(exc) in RELEASE_ERROR_CODES else "demo_release_preflight_failed"
        print(json.dumps({"status": "error", "error": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
