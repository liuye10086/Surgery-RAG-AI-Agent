import json
import io
from pathlib import Path
import threading

import pytest


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://127.0.0.1:15173", "http://127.0.0.1:15173"),
        (
            "http://user:password@127.0.0.1:15173/operator?token=secret#part",
            "http://127.0.0.1:15173/operator",
        ),
        ("https://127.0.0.1:15173/operator", "invalid_browser_url"),
        ("http://example.com:15173/operator", "invalid_browser_url"),
        ("http://127.0.0.1:bad/operator?token=secret", "invalid_browser_url"),
        ("user:password@host?token=secret", "invalid_browser_url"),
    ],
)
def test_safe_demo_page_url_is_loopback_and_never_returns_credentials(value, expected):
    from scripts.numeric_history_demo_browser import safe_demo_page_url

    result = safe_demo_page_url(value)
    assert result == expected
    assert "user" not in result and "password" not in result and "secret" not in result


class Locator:
    def __init__(self, events, label):
        self.events = events
        self.label = label

    def wait_for(self, **kwargs):
        self.events.append(("wait", self.label, kwargs))

    def click(self):
        self.events.append(("click", self.label))

    def inner_text(self):
        return self.label


class Response:
    def __init__(self, events, status, body):
        self.events = events
        self.status = status
        self.body = body

    def json(self):
        return self.body


class Request:
    """Records every probe the session makes and answers from a closed plan."""

    def __init__(self, events, plan):
        self.events = events
        self.plan = plan
        self.calls = []

    def _answer(self, method, url, headers, data=None):
        self.calls.append((method, url, dict(headers), data))
        self.events.append((method, url))
        status, body = self.plan.pop(0)
        return Response(self.events, status, body)

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs.get("headers") or {})

    def post(self, url, **kwargs):
        return self._answer(
            "POST", url, kwargs.get("headers") or {}, kwargs.get("data")
        )


def default_plan(report_id=41):
    return [
        (202, {"report_id": report_id}),
        (202, {"report_id": report_id}),
        (200, {"status": "cancelled"}),
        (404, {"detail": {"code": "case_not_found"}}),
        (403, {"detail": "AI operator or admin required"}),
    ]


class Page:
    def __init__(
        self,
        events,
        *,
        url="http://127.0.0.1:15173/operator",
        fail_goto=False,
        body="body",
        plan=None,
    ):
        self.events = events
        self.url = url
        self.fail_goto = fail_goto
        self.body = body
        self.request = Request(events, default_plan() if plan is None else list(plan))

    def on(self, name, callback):
        self.events.append(("on", name))

    def goto(self, url):
        self.events.append(("goto", url))
        if self.fail_goto:
            raise RuntimeError("secret browser failure")

    def evaluate(self, expression, value):
        self.events.append(("evaluate", expression, value))

    def get_by_role(self, role, **kwargs):
        return Locator(self.events, kwargs["name"])

    def get_by_text(self, value, **kwargs):
        return Locator(self.events, value)

    def locator(self, value):
        assert value == "body"
        return Locator(self.events, self.body)

    def screenshot(self, **kwargs):
        self.events.append(("screenshot", Path(kwargs["path"]).name, kwargs["full_page"]))


class Context:
    def __init__(self, events, page):
        self.events = events
        self.page = page

    def new_page(self):
        self.events.append(("new_page",))
        return self.page

    def close(self):
        self.events.append(("context_close",))


class Browser:
    def __init__(self, events, context, *, connected=True):
        self.events = events
        self.context = context
        self.connected = connected

    def new_context(self, **kwargs):
        self.events.append(("context", kwargs))
        return self.context

    def is_connected(self):
        return self.connected

    def close(self):
        self.events.append(("browser_close",))


class Playwright:
    def __init__(self, events, browser):
        self.events = events
        self.chromium = self
        self.browser = browser

    def launch(self, **kwargs):
        self.events.append(("launch", kwargs))
        return self.browser

    def __enter__(self):
        self.events.append(("driver_open", threading.get_ident()))
        return self

    def __exit__(self, *args):
        self.events.append(("driver_close", threading.get_ident()))


class Owned:
    def __init__(self):
        self.checks = []

    def assert_alive(self, *names):
        self.checks.append(names)


def _factory(events, *, page=None, connected=True):
    page = page or Page(events)
    context = Context(events, page)
    browser = Browser(events, context, connected=connected)
    return lambda: Playwright(events, browser)


def _subjects():
    return [
        {"case_id": 11, "anonymous_case_code": "CASE-AAA"},
        {"case_id": 12, "anonymous_case_code": "CASE-BBB"},
        {"case_id": 13, "anonymous_case_code": "CASE-CCC"},
    ]


def _tokens():
    return {
        "primary": "primary.secret-token.signature",
        "secondary": "secondary.secret-token.signature",
        "doctor": "doctor.secret-token.signature",
    }


def _expected_checks():
    return {
        "schema_version": "numeric_demo_session_checks.v1",
        "performed": ["non_owner_404", "wrong_role_403", "idempotency_replay"],
        "admission": {
            "submissions": 2,
            "accepted": 1,
            "idempotency_replays": 1,
            "admission_disabled": 0,
            "permission_denied": 0,
            "invalid_input": 0,
            "conflict": 0,
            "non_owner_404": 1,
            "wrong_role_403": 1,
            "disease_permission_denied": 0,
        },
    }


def test_authenticated_demo_uses_headed_loopback_and_process_memory_token(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    ready = threading.Event()
    stop = threading.Event()
    stop.set()
    tokens = _tokens()
    result = run_authenticated_demo(
        output=tmp_path,
        tokens=tokens,
        subjects=_subjects(),
        owned=Owned(),
        stop_event=stop,
        session_ready=ready,
        playwright_factory=_factory(events),
        poll_seconds=0,
    )
    assert ready.is_set()
    assert result["page_error_types"] == []
    assert result["cleanup_error_types"] == []
    assert result["admission"] == _expected_checks()["admission"]
    assert ("launch", {"headless": False}) in events
    assert ("context", {"base_url": "http://127.0.0.1:15173"}) in events
    assert [event for event in events if event[0] == "goto"] == [
        ("goto", "http://127.0.0.1:15173"),
        ("goto", "http://127.0.0.1:15173"),
    ]
    for subject in _subjects():
        assert any(event[:2] == ("wait", subject["anonymous_case_code"]) for event in events)
    writes = [event for event in events if event[0] == "evaluate"]
    assert writes == [
        (
            "evaluate",
            "value => window.localStorage.setItem('token', value)",
            tokens["primary"],
        )
    ]
    assert json.loads(
        (tmp_path / "session-checks.json").read_text(encoding="utf-8")
    ) == _expected_checks()


def test_token_is_not_registered_for_reinjection_after_external_navigation(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    stop = threading.Event()
    stop.set()
    page = Page(events)
    run_authenticated_demo(
        output=tmp_path,
        tokens=_tokens(),
        subjects=_subjects(),
        owned=Owned(),
        stop_event=stop,
        session_ready=threading.Event(),
        playwright_factory=_factory(events, page=page),
        poll_seconds=0,
    )
    page.goto("https://example.invalid/")
    assert len([event for event in events if event[0] == "evaluate"]) == 1
    assert not any(event[0] == "init" for event in events)


def test_redirected_initial_navigation_never_receives_the_token(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    tokens = _tokens()
    page = Page(events, url="https://example.invalid/login")
    with pytest.raises(RuntimeError, match="^demo_browser_origin_changed$"):
        run_authenticated_demo(
            output=tmp_path,
            tokens=tokens,
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events, page=page),
            poll_seconds=0,
        )
    assert not any(event[0] == "evaluate" for event in events)
    diagnostic = (tmp_path / "browser-failure.json").read_text(encoding="utf-8")
    assert json.loads(diagnostic)["page_url"] == "invalid_browser_url"
    for token in tokens.values():
        assert token not in diagnostic
    assert "example.invalid" not in diagnostic


def test_browser_close_sets_the_shared_stop_event_without_restart(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    ready = threading.Event()
    stop = threading.Event()
    owned = Owned()
    run_authenticated_demo(
        output=tmp_path,
        tokens=_tokens(),
        subjects=_subjects(),
        owned=owned,
        stop_event=stop,
        session_ready=ready,
        playwright_factory=_factory(events, connected=False),
        poll_seconds=0,
    )
    assert stop.is_set() and ready.is_set()
    assert len([event for event in events if event[0] == "launch"]) == 1
    assert owned.checks == []


def test_browser_failure_diagnostic_is_bounded_redacted_and_relative(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    tokens = _tokens()
    events = []
    page = Page(
        events,
        url="http://user:password@127.0.0.1:15173/operator?token=secret#part",
        fail_goto=True,
        body=tokens["primary"] + "x" * 5000,
    )
    with pytest.raises(RuntimeError, match="secret browser failure"):
        run_authenticated_demo(
            output=tmp_path,
            tokens=tokens,
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events, page=page),
            poll_seconds=0,
        )
    raw = (tmp_path / "browser-failure.json").read_text(encoding="utf-8")
    diagnostic = json.loads(raw)
    assert diagnostic["page_url"] == "http://127.0.0.1:15173/operator"
    assert diagnostic["screenshot"] == "browser-failure.png"
    assert len(diagnostic["body_text"]) <= 4000
    for token in tokens.values():
        assert token not in raw
    assert "password" not in raw and "?token" not in raw
    assert ("screenshot", "browser-failure.png", True) in events
    assert events[-3][0] == "context_close"
    assert events[-2][0] == "browser_close"
    assert events[-1][0] == "driver_close"


def test_stop_during_shell_readiness_interrupts_the_bounded_wait():
    from scripts.numeric_history_demo_browser import _wait_visible

    stop = threading.Event()
    timeouts = []

    class SlowLocator:
        def wait_for(self, **kwargs):
            timeouts.append(kwargs["timeout"])
            stop.set()
            raise TimeoutError

    with pytest.raises(RuntimeError, match="^demo_browser_stop_requested$"):
        _wait_visible(SlowLocator(), stop)
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 500


def test_child_protocol_reports_only_closed_events_and_never_echoes_token(
    tmp_path, monkeypatch
):
    from scripts import numeric_history_demo_browser as module

    tokens = _tokens()
    request = json.dumps(
        {"output": str(tmp_path), "tokens": tokens, "subjects": _subjects()}
    )
    stdout = io.StringIO()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(request + "\n"))
    monkeypatch.setattr(module.sys, "stdout", stdout)

    def run(**kwargs):
        assert kwargs["tokens"] == tokens
        kwargs["session_ready"].set()
        return {"cleanup_error_types": []}

    monkeypatch.setattr(module, "run_authenticated_demo", run)
    assert module.child_main() == 0
    values = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert values == [
        {"event": "ready"},
        {"event": "stopped", "cleanup_failed": False},
    ]
    for token in tokens.values():
        assert token not in stdout.getvalue()


def test_child_protocol_projects_failure_to_type_only(tmp_path, monkeypatch):
    from scripts import numeric_history_demo_browser as module

    tokens = _tokens()
    request = json.dumps(
        {"output": str(tmp_path), "tokens": tokens, "subjects": _subjects()}
    )
    stdout = io.StringIO()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(request + "\n"))
    monkeypatch.setattr(module.sys, "stdout", stdout)
    monkeypatch.setattr(
        module,
        "run_authenticated_demo",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("secret failure detail")),
    )
    assert module.child_main() == 1
    assert json.loads(stdout.getvalue()) == {
        "event": "error",
        "error_type": "RuntimeError",
    }
    for token in tokens.values():
        assert token not in stdout.getvalue()
    assert "secret failure detail" not in stdout.getvalue()


def test_session_checks_probe_fixed_endpoints_with_each_seeded_identity(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    stop = threading.Event()
    stop.set()
    page = Page(events)
    run_authenticated_demo(
        output=tmp_path,
        tokens=_tokens(),
        subjects=_subjects(),
        owned=Owned(),
        stop_event=stop,
        session_ready=threading.Event(),
        playwright_factory=_factory(events, page=page),
        poll_seconds=0,
    )
    calls = [(method, url) for method, url, _, _ in page.request.calls]
    job_path = "/api/v1/operator/longitudinal-cases/11/report-jobs"
    assert calls == [
        ("POST", job_path),
        ("POST", job_path),
        ("POST", "/api/v1/operator/reports/41/cancel"),
        ("POST", job_path),
        ("POST", job_path),
    ]
    authentication = [headers["Authorization"] for _, _, headers, _ in page.request.calls]
    assert authentication == [
        "Bearer " + _tokens()["primary"],
        "Bearer " + _tokens()["primary"],
        "Bearer " + _tokens()["primary"],
        "Bearer " + _tokens()["secondary"],
        "Bearer " + _tokens()["doctor"],
    ]
    keys = [headers.get("Idempotency-Key") for _, _, headers, _ in page.request.calls]
    assert keys[0] == keys[1] and keys[0] is not None
    assert keys[2] is None
    assert len({key for key in keys if key is not None}) == 3
    assert page.request.calls[0][3] == {
        "model_options": {},
        "report_kind": "numeric_prediction",
    }


@pytest.mark.parametrize(
    ("index", "status"),
    [(0, 200), (1, 409), (2, 500), (3, 200), (4, 404)],
)
def test_session_checks_fail_closed_when_an_expectation_does_not_hold(
    tmp_path, index, status
):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    ready = threading.Event()
    plan = default_plan()
    plan[index] = (status, {"report_id": 41, "status": "queued"})
    page = Page(events, plan=plan)
    with pytest.raises(RuntimeError, match="^demo_session_check_failed$"):
        run_authenticated_demo(
            output=tmp_path,
            tokens=_tokens(),
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=ready,
            playwright_factory=_factory(events, page=page),
            poll_seconds=0,
        )
    assert not ready.is_set()
    assert not (tmp_path / "session-checks.json").exists()


def test_session_checks_reject_a_replay_that_returns_a_different_report(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    plan = default_plan()
    plan[1] = (202, {"report_id": 42})
    with pytest.raises(RuntimeError, match="^demo_session_check_failed$"):
        run_authenticated_demo(
            output=tmp_path,
            tokens=_tokens(),
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events, page=Page(events, plan=plan)),
            poll_seconds=0,
        )


def test_session_checks_require_three_distinct_seeded_cases():
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    with pytest.raises(ValueError, match="^demo_browser_subjects_invalid$"):
        run_authenticated_demo(
            output=Path("."),
            tokens=_tokens(),
            subjects=[{"case_id": 11, "anonymous_case_code": "A"}],
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events),
            poll_seconds=0,
        )


def test_session_checks_require_all_three_identities():
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    with pytest.raises(ValueError, match="^demo_browser_token_required$"):
        run_authenticated_demo(
            output=Path("."),
            tokens={"primary": "only-primary"},
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events),
            poll_seconds=0,
        )
    with pytest.raises(ValueError, match="^demo_browser_token_required$"):
        run_authenticated_demo(
            output=Path("."),
            tokens={"primary": "", "secondary": "b", "doctor": "c"},
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events),
            poll_seconds=0,
        )


def test_session_checks_failure_diagnostic_never_keeps_a_token(tmp_path):
    from scripts.numeric_history_demo_browser import run_authenticated_demo

    events = []
    plan = default_plan()
    plan[3] = (200, {"detail": "leaked"})
    with pytest.raises(RuntimeError, match="^demo_session_check_failed$"):
        run_authenticated_demo(
            output=tmp_path,
            tokens=_tokens(),
            subjects=_subjects(),
            owned=Owned(),
            stop_event=threading.Event(),
            session_ready=threading.Event(),
            playwright_factory=_factory(events, page=Page(events, plan=plan)),
            poll_seconds=0,
        )
    raw = (tmp_path / "browser-failure.json").read_text(encoding="utf-8")
    for token in _tokens().values():
        assert token not in raw
    assert "leaked" not in raw
