"""Authenticated, local-only browser session for the numeric-history demo."""

import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from app.schemas.numeric_demo_release import SESSION_CHECKS_FILENAME
from scripts.numeric_history_acceptance_browser import (
    MAX_BODY_TEXT,
    SHELL_TIMEOUT_MS,
    safe_page_url,
    shell_locator,
)


ORIGIN = "http://127.0.0.1:15173"
# The main supervisor watches all four processes. The browser thread omits API
# so Ctrl+C can close admission first without racing this thread's liveness check.
PROCESS_NAMES = ("frontend", "report_worker", "pdf_worker")
VISIBLE_POLL_MS = 500
DEMO_TOKENS = ("primary", "secondary", "doctor")
SUBMIT_PATH = "/api/v1/operator/longitudinal-cases/{case_id}/report-jobs"
CANCEL_PATH = "/api/v1/operator/reports/{report_id}/cancel"
REPORT_REQUEST = {"model_options": {}, "report_kind": "numeric_prediction"}
SESSION_CHECKS_SCHEMA = "numeric_demo_session_checks.v1"


def is_demo_origin(value: str) -> bool:
    """Require the actual page origin before placing credentials in web storage."""
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 15173
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


def safe_demo_page_url(value: str) -> str:
    """Return only an allowed loopback demo URL with query and credentials removed."""
    sanitized = safe_page_url(value)
    try:
        parsed = urlsplit(sanitized)
        if (
            parsed.scheme == "http"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 15173
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        ):
            return sanitized
    except (TypeError, ValueError):
        pass
    return "invalid_browser_url"


def _headers(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


def _blank_admission() -> dict:
    return {
        "submissions": 0,
        "accepted": 0,
        "idempotency_replays": 0,
        "admission_disabled": 0,
        "permission_denied": 0,
        "invalid_input": 0,
        "conflict": 0,
        "non_owner_404": 0,
        "wrong_role_403": 0,
        "disease_permission_denied": 0,
    }


def session_ended_errors() -> tuple:
    """Playwright's public error base: what a gone window surfaces as.

    ``TargetClosedError`` is the concrete class but it lives in the private
    ``playwright._impl`` package, so the supported base is caught instead. While
    the session waits, the only call in the loop is a bounded wait, so the only
    realistic failure is that the operator's window is no longer there.
    """
    try:
        from playwright.sync_api import Error
    except Exception:
        return ()
    return (Error,)


def run_session_checks(page, tokens: dict, subjects: list[dict]) -> dict:
    """Perform the fixed closed checks and keep only the outcomes actually seen.

    Every expectation must hold before the session is announced as ready: a
    permission probe that unexpectedly succeeds is a release-blocking failure,
    never a zero that is quietly reported as a pass.
    """
    case_id = subjects[0]["case_id"]
    submit_path = SUBMIT_PATH.format(case_id=case_id)
    admission = _blank_admission()

    def post(token: str, key: str):
        return page.request.post(
            submit_path,
            headers={**_headers(token), "Idempotency-Key": key},
            data=REPORT_REQUEST,
        )

    # Only the operator's own admissions are counted as requests; the other two
    # identities probe permission outcomes and are reported in that block alone.

    def submit(key: str):
        admission["submissions"] += 1
        return post(tokens["primary"], key)

    key = str(uuid4())
    accepted = submit(key)
    if accepted.status != 202:
        raise RuntimeError("demo_session_check_failed")
    report_id = accepted.json()["report_id"]
    admission["accepted"] = 1

    replay = submit(key)
    if replay.status != 202 or replay.json()["report_id"] != report_id:
        raise RuntimeError("demo_session_check_failed")
    admission["idempotency_replays"] = 1

    cancelled = page.request.post(
        CANCEL_PATH.format(report_id=report_id), headers=_headers(tokens["primary"])
    )
    if cancelled.status != 200 or cancelled.json().get("status") != "cancelled":
        raise RuntimeError("demo_session_check_failed")

    other = post(tokens["secondary"], str(uuid4()))
    if other.status != 404:
        raise RuntimeError("demo_session_check_failed")
    admission["non_owner_404"] = 1

    doctor = post(tokens["doctor"], str(uuid4()))
    if doctor.status != 403:
        raise RuntimeError("demo_session_check_failed")
    admission["wrong_role_403"] = 1
    return admission


def write_session_checks(output: Path, admission: dict) -> None:
    record = {
        "schema_version": SESSION_CHECKS_SCHEMA,
        "performed": ["non_owner_404", "wrong_role_403", "idempotency_replay"],
        "admission": admission,
    }
    target = Path(output) / SESSION_CHECKS_FILENAME
    target.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _redact(value: str, tokens) -> str:
    for token in tokens:
        if token:
            value = value.replace(token, "[redacted]")
    return value


def _safe_browser_failure(
    output: Path, page, page_errors: list[str], exc, tokens
) -> None:
    tokens = list(tokens)
    diagnostic = {
        "page_url": safe_demo_page_url(getattr(page, "url", "") or ""),
        "page_error_types": sorted(set(page_errors)),
        "error_type": type(exc).__name__,
        "screenshot": None,
        "body_text": "",
        "diagnostic_errors": [],
    }
    if page is not None:
        try:
            page.screenshot(
                path=str(Path(output) / "browser-failure.png"),
                full_page=True,
            )
            diagnostic["screenshot"] = "browser-failure.png"
        except BaseException as error:
            diagnostic["diagnostic_errors"].append(
                {"stage": "screenshot", "error_type": type(error).__name__}
            )
        try:
            body = _redact(page.locator("body").inner_text(), tokens)
            diagnostic["body_text"] = body[:MAX_BODY_TEXT]
        except BaseException as error:
            diagnostic["diagnostic_errors"].append(
                {"stage": "body", "error_type": type(error).__name__}
            )
    try:
        (Path(output) / "browser-failure.json").write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except BaseException:
        pass


def _wait_visible(locator, stop_event, *, timeout_ms: int = SHELL_TIMEOUT_MS) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        try:
            locator.wait_for(
                state="visible",
                timeout=min(VISIBLE_POLL_MS, remaining_ms),
            )
            return
        except BaseException as error:
            if type(error).__name__ != "TimeoutError":
                raise
            if stop_event.is_set():
                raise RuntimeError("demo_browser_stop_requested") from None
            if time.monotonic() >= deadline:
                raise RuntimeError("demo_browser_start_timeout") from None


def run_authenticated_demo(
    *,
    output: Path,
    tokens: dict,
    subjects: list[dict],
    owned,
    stop_event,
    session_ready,
    playwright_factory=None,
    poll_seconds: float = 0.25,
) -> dict:
    """Run Playwright entirely in the caller's browser thread until stopped."""
    if (
        not isinstance(tokens, dict)
        or sorted(tokens) != sorted(DEMO_TOKENS)
        or any(type(tokens[name]) is not str or not tokens[name] for name in DEMO_TOKENS)
    ):
        raise ValueError("demo_browser_token_required")
    token = tokens["primary"]
    codes = [subject.get("anonymous_case_code") for subject in subjects]
    if (
        len(codes) != 3
        or len(set(codes)) != 3
        or any(type(code) is not str or not code for code in codes)
        or any(type(subject.get("case_id")) is not int for subject in subjects)
    ):
        raise ValueError("demo_browser_subjects_invalid")
    if playwright_factory is None:
        from playwright.sync_api import sync_playwright

        playwright_factory = sync_playwright

    close_errors = session_ended_errors()
    browser = None
    context = None
    page = None
    page_errors = []
    primary = None
    result = {"page_error_types": [], "cleanup_error_types": [], "admission": None}
    with playwright_factory() as runtime:
        try:
            browser = runtime.chromium.launch(headless=False)
            context = browser.new_context(base_url=ORIGIN)
            page = context.new_page()
            page.on("pageerror", lambda error: page_errors.append(type(error).__name__))
            # Playwright's is_connected() only tracks the driver link, which stays
            # up when the operator closes the window, so the session would never
            # end. These close events are the signal that the operator is finished.
            page.on("close", lambda *_: stop_event.set())
            context.on("close", lambda *_: stop_event.set())
            browser.on("disconnected", lambda *_: stop_event.set())
            page.goto(ORIGIN)
            if not is_demo_origin(page.url):
                raise RuntimeError("demo_browser_origin_changed")
            page.evaluate(
                "value => window.localStorage.setItem('token', value)",
                token,
            )
            page.goto(ORIGIN)
            shell = shell_locator(page)
            _wait_visible(shell, stop_event)
            shell.click()
            for code in codes:
                _wait_visible(page.get_by_text(code, exact=True), stop_event)
            result["admission"] = run_session_checks(page, tokens, subjects)
            write_session_checks(Path(output), result["admission"])
            session_ready.set()
            while not stop_event.is_set():
                # This call is also what dispatches the close events above: the
                # sync API only runs its event loop inside a Playwright call, and
                # is_connected() is a cached flag that never reflects a closed
                # window. When the operator's window goes away, this raises.
                try:
                    page.wait_for_timeout(max(1, int(poll_seconds * 1000)))
                except close_errors:
                    stop_event.set()
                    break
                if stop_event.is_set() or not browser.is_connected():
                    break
                owned.assert_alive(*PROCESS_NAMES)
            if page_errors:
                raise RuntimeError("browser_page_errors")
            return result
        except BaseException as exc:
            primary = exc
            stop_event.set()
            _safe_browser_failure(
                Path(output), page, page_errors, exc, list(tokens.values())
            )
            raise
        finally:
            for resource in (context, browser):
                if resource is None:
                    continue
                try:
                    resource.close()
                except BaseException as error:
                    result["cleanup_error_types"].append(type(error).__name__)
                    if primary is None:
                        stop_event.set()


class _ProtocolReady:
    """Emit readiness without exposing the browser token to stdout."""

    def __init__(self, emit):
        self.emit = emit
        self.sent = False

    def set(self) -> None:
        if not self.sent:
            self.sent = True
            self.emit({"event": "ready"})


class _ParentOwnedProcesses:
    """The parent supervisor owns and observes the service process trees."""

    def assert_alive(self, *names: str) -> None:
        del names


def _emit_protocol(value: dict) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _read_stop_commands(stop_event: threading.Event) -> None:
    for line in sys.stdin:
        try:
            value = json.loads(line)
        except (TypeError, ValueError):
            continue
        if value == {"command": "stop"}:
            stop_event.set()
            return


def child_main() -> int:
    """Run one browser lifecycle behind a strict stdin/stdout control protocol."""
    try:
        line = sys.stdin.readline(65537)
        if not line or len(line) > 65536:
            raise ValueError("demo_browser_protocol_invalid")
        request = json.loads(line)
        if set(request) != {"output", "tokens", "subjects"}:
            raise ValueError("demo_browser_protocol_invalid")
        output = Path(request["output"])
        tokens = request["tokens"]
        subjects = request["subjects"]
        stop_event = threading.Event()
        reader = threading.Thread(
            target=_read_stop_commands,
            args=(stop_event,),
            name="numeric-history-demo-browser-control",
            daemon=True,
        )
        reader.start()
        result = run_authenticated_demo(
            output=output,
            tokens=tokens,
            subjects=subjects,
            owned=_ParentOwnedProcesses(),
            stop_event=stop_event,
            session_ready=_ProtocolReady(_emit_protocol),
        )
        tokens = None
        request = None
        _emit_protocol(
            {
                "event": "stopped",
                "cleanup_failed": bool(result["cleanup_error_types"]),
            }
        )
        return 0
    except BaseException as exc:
        _emit_protocol({"event": "error", "error_type": type(exc).__name__})
        return 1


if __name__ == "__main__":
    if sys.argv[1:] != ["--child"]:
        raise SystemExit(2)
    raise SystemExit(child_main())
