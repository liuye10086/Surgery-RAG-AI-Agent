from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import queue
import socket
import stat
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/run_numeric_history_demo_release.py"


def runner():
    assert SCRIPT.is_file(), "phase-five demo runner is not implemented"
    spec = importlib.util.spec_from_file_location("history_demo_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def argv(tmp_path, *extra):
    return [
        "--source-dir",
        str(ROOT / "outputs/synthetic-prediction-cases/2026-09-15-switch-v2"),
        "--legacy-bundle",
        str(ROOT / "outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json"),
        "--history-bundle",
        str(ROOT / "outputs/numeric-history-integration/2026-09-16-v1/bundle.json"),
        "--renderer",
        str(
            ROOT
            / "outputs/numeric-history-renderers/2026-09-20-v1"
            / "38f18749e2ceed29eb12273c66f2a056e701f01db01b3ada7a5582e433357558"
            / "manifest.json"
        ),
        "--acceptance-result",
        str(ROOT / "outputs/numeric-history-acceptance/2026-09-20-v2/result.json"),
        "--output",
        str(tmp_path / "output"),
        *extra,
    ]


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql://test:secret@127.0.0.1/surgery_rag_phase4_test",
    )
    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"):
        monkeypatch.delenv(key, raising=False)


def test_actual_frozen_dry_run_has_no_database_process_network_or_writes(
    tmp_path, monkeypatch, capsys, isolated
):
    module = runner()
    import sqlalchemy

    def forbidden(*args, **kwargs):
        pytest.fail("dry-run must not connect, spawn, or write")

    monkeypatch.setattr(module, "validate_git_release_state", lambda *a, **k: "2" * 40)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(module, "execute", forbidden)
    assert module.main(argv(tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "dry_run"
    assert result["database_connected"] is False
    assert result["services_started"] is False
    assert result["identities"]["history"]["bundle_sha256"] == module.HISTORY_SHA
    assert result["identities"]["acceptance"]["acceptance_result_sha256"] == module.ACCEPTANCE_SHA
    assert result["identities"]["git_commit"] == "2" * 40
    assert str(ROOT) not in json.dumps(result)
    assert not (tmp_path / "output").exists()


def test_single_external_authorization_without_apply_is_still_dry_run(
    tmp_path, monkeypatch, capsys, isolated
):
    module = runner()
    monkeypatch.setattr(module, "validate_git_release_state", lambda *a, **k: "2" * 40)
    assert module.main(argv(tmp_path, "--allow-external-llm")) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    assert not (tmp_path / "output").exists()


def test_apply_requires_external_authorization_before_reading_assets(
    tmp_path, capsys, isolated
):
    module = runner()
    arguments = argv(tmp_path, "--apply")
    arguments[1] = str(tmp_path / "missing-source")
    assert module.main(arguments) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error": "external_llm_authorization_required",
    }
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--source-dir", "duplicate"],
        ["--output=duplicate"],
        ["--apply", "--apply", "--allow-external-llm"],
        ["--allow-external-llm", "--allow-external-llm"],
        ["--source", "abbreviated"],
        ["--database-url", "postgresql://secret:password@host/db"],
        ["--unknown", "secret"],
    ],
)
def test_argument_errors_are_closed_and_redacted(tmp_path, capsys, isolated, extra):
    module = runner()
    assert module.main(argv(tmp_path, *extra)) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {"status": "error", "error": "invalid_arguments"}
    assert "secret" not in output and "password" not in output


@pytest.mark.parametrize(
    "url",
    [
        "",
        "postgresql://localhost/surgery_rag_test",
        "postgresql://localhost/business",
        "postgresql://remote/surgery_rag_phase4_test",
        "postgresql://localhost/surgery_rag_phase4_test?host=remote",
        "postgresql://localhost/surgery_rag_phase4_test#secret",
    ],
)
def test_rejects_unsafe_database_without_writing(
    tmp_path, monkeypatch, capsys, isolated, url
):
    module = runner()
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    assert module.main(argv(tmp_path)) == 2
    output = capsys.readouterr().out
    assert json.loads(output)["error"] in {
        "test_database_url_required",
        "isolated_test_database_required",
    }
    assert "secret" not in output
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"])
def test_rejects_libpq_redirects(tmp_path, monkeypatch, capsys, isolated, key):
    module = runner()
    monkeypatch.setenv(key, "secret-override")
    assert module.main(argv(tmp_path)) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "status": "error",
        "error": "isolated_test_database_required",
    }
    assert "secret" not in output


def test_existing_output_is_preserved(tmp_path, isolated):
    module = runner()
    output = tmp_path / "output"
    output.mkdir()
    marker = output / "original"
    marker.write_text("preserve", encoding="utf-8")
    assert module.main(argv(tmp_path)) == 2
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_input_symlink_is_rejected_before_static_preflight(
    tmp_path, monkeypatch, capsys, isolated
):
    module = runner()
    source = ROOT / "outputs/synthetic-prediction-cases/2026-09-15-switch-v2"
    original = Path.is_symlink
    monkeypatch.setattr(
        module.Path,
        "is_symlink",
        lambda self: True if self == source else original(self),
    )
    assert module.main(argv(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "input_path_invalid"


def test_broken_symlink_parent_is_rejected_by_lstat(tmp_path, monkeypatch):
    module = runner()
    broken = tmp_path / "broken-parent"
    target = broken / "input.json"
    original = module.Path.lstat

    def fake_lstat(path):
        if path == broken:
            return SimpleNamespace(st_mode=stat.S_IFLNK)
        return original(path)

    monkeypatch.setattr(module.Path, "lstat", fake_lstat)
    with pytest.raises(ValueError, match="^input_path_invalid$"):
        module._reject_symlink_components(target)


def test_busy_port_is_rejected_without_killing_listener(tmp_path, monkeypatch, isolated):
    module = runner()
    monkeypatch.setattr(module, "validate_git_release_state", lambda *a, **k: "2" * 40)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        monkeypatch.setattr(module, "DEMO_PORTS", (listener.getsockname()[1],))
        assert module.main(argv(tmp_path)) == 2
        assert listener.fileno() >= 0


def test_apply_invokes_execute_only_with_both_flags(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    identities = {"verified": True}
    seen = []
    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "execute", lambda args, value: seen.append(value) or 7)
    assert module.main(argv(tmp_path, "--apply", "--allow-external-llm")) == 7
    assert seen == [identities]


def test_dry_run_rejects_actual_uncommitted_release_code(tmp_path, capsys, isolated):
    module = runner()
    assert module.main(argv(tmp_path)) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error": "uncommitted_release_code",
    }
    assert not (tmp_path / "output").exists()


def test_environment_is_unchanged_by_dry_run(tmp_path, monkeypatch, isolated, capsys):
    module = runner()
    before = dict(os.environ)
    monkeypatch.setattr(module, "validate_git_release_state", lambda *a, **k: "2" * 40)
    assert module.main(argv(tmp_path)) == 0
    capsys.readouterr()
    assert dict(os.environ) == before


def _release_identities(module):
    return {
        "source": {
            "source_run_id": "syn-0aa14c3fe543c3b5",
            "source_manifest_sha256": module.SOURCE_SHA,
            "data_content_sha256": module.SOURCE_DATA_SHA,
            "subjects": ["subject-a", "subject-b", "subject-c"],
        },
        "legacy": {"bundle_sha256": module.LEGACY_SHA},
        "history": {"bundle_sha256": module.HISTORY_SHA},
        "renderer": {"manifest_sha256": module.RENDERER_SHA},
        "acceptance": {"acceptance_result_sha256": module.ACCEPTANCE_SHA},
        "git_commit": "2" * 40,
    }


def _runtime():
    return {
        "python_version": "3.11.4",
        "node_version": "22.15.0",
        "playwright_version": "1.55.0",
        "fonttools_version": "4.59.1",
        "chromium_version": "140.0.7339.16",
    }


def test_child_environment_is_explicit_offline_and_does_not_mutate_parent(tmp_path):
    module = runner()
    base = {"EXISTING": "kept", "DATABASE_URL": "parent"}
    args = SimpleNamespace(
        history_bundle=tmp_path / "bundle-c.json",
        renderer=tmp_path / "renderer.json",
    )
    child = module.build_child_environment(
        args,
        "postgresql://local/isolated",
        tmp_path / "output",
        base_environment=base,
    )
    assert base == {"EXISTING": "kept", "DATABASE_URL": "parent"}
    assert child["DATABASE_URL"] == "postgresql://local/isolated"
    assert child["VECTOR_STORE_CONNECTION_STRING"] == child["DATABASE_URL"]
    assert child["NUMERIC_MODEL_BUNDLE"] == str(args.history_bundle.resolve())
    assert child["REPORT_ARCHIVE_ROOT"] == str((tmp_path / "output/archive").resolve())
    assert child["REPORT_JOBS_ENABLED"] == child["REPORT_JOBS_ACCEPTING"] == "true"
    assert child["REPORT_PDF_ENABLED"] == child["REPORT_PDF_ACCEPTING"] == "true"
    assert child["NUMERIC_REPORTS_ENABLED"] == "true"
    assert child["HF_HUB_OFFLINE"] == "1"
    assert child["TRANSFORMERS_OFFLINE"] == "1"
    assert child["MODELSCOPE_OFFLINE"] == "1"
    assert len(child["REPORT_HISTORY_CURSOR_SECRET"]) >= 32


def test_start_services_uses_fixed_commands_and_readiness_order(tmp_path):
    module = runner()
    events = []

    class Owned:
        def start(self, name, command, cwd):
            events.append(("start", name, command, cwd))

        def ready(self, name, endpoint):
            events.append(("ready", name, endpoint))

        def assert_alive(self, *names):
            events.append(("alive", *names))

        def observe_workers(self):
            events.append(("observe_workers",))

    module.start_services(SimpleNamespace(), Owned(), {"SAFE": "value"})
    assert [(event[0], event[1]) for event in events if event[0] in {"start", "ready"}] == [
        ("start", "api"),
        ("ready", "api"),
        ("start", "frontend"),
        ("ready", "frontend"),
        ("start", "report_worker"),
        ("start", "pdf_worker"),
    ]
    # Vite serves its working directory, so it must not be started at the root.
    assert {event[1]: event[3] for event in events if event[0] == "start"} == {
        "api": ROOT,
        "frontend": ROOT / "frontend",
        "report_worker": ROOT / "backend",
        "pdf_worker": ROOT / "backend",
    }
    starts = {event[1]: event[2] for event in events if event[0] == "start"}
    assert starts == {
        "api": [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.tests.e2e.report_test_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18060",
        ],
        "frontend": [
            "node",
            str(ROOT / "frontend/node_modules/vite/bin/vite.js"),
            "--host",
            "127.0.0.1",
            "--port",
            "15173",
            "--strictPort",
        ],
        "report_worker": [sys.executable, "-m", "app.workers.report_worker"],
        "pdf_worker": [sys.executable, "-m", "app.workers.report_pdf_worker"],
    }
    assert events[-2:] == [
        ("alive", "report_worker", "pdf_worker"),
        ("observe_workers",),
    ]


def test_owned_processes_discard_raw_output_and_write_closed_events(
    tmp_path, monkeypatch
):
    module = runner()
    popen_calls = []
    kill_calls = []

    class Process:
        pid = 9191

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        module.os,
        "killpg",
        lambda pid, sig: kill_calls.append((pid, sig)),
        raising=False,
    )
    owned = module.SafeOwnedProcesses(
        tmp_path,
        {"TOKEN": "secret-token"},
        platform_name="posix",
    )
    owned.start("api", ["fake", "postgresql://user:secret@host/db"], ROOT)
    owned.stop("api")
    events = (tmp_path / "process-events.jsonl").read_text(encoding="utf-8")
    assert "secret-token" not in events
    assert "postgresql://" not in events
    assert set(json.loads(line)["event"] for line in events.splitlines()) == {
        "started",
        "stopped",
    }
    assert popen_calls[0][1]["stdout"] is subprocess.DEVNULL
    assert popen_calls[0][1]["stderr"] is subprocess.DEVNULL
    assert popen_calls[0][1]["shell"] is False
    assert kill_calls == [
        (9191, module.signal.SIGTERM),
        (9191, module.POSIX_SIGKILL),
    ]


def test_owned_browser_protocol_uses_anonymous_pipes_and_owned_process_group(
    tmp_path, monkeypatch
):
    module = runner()
    popen_calls = []
    kill_calls = []

    class Process:
        pid = 9192

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    def popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return Process()

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(
        module.os,
        "killpg",
        lambda pid, sig: kill_calls.append((pid, sig)),
        raising=False,
    )
    owned = module.SafeOwnedProcesses(tmp_path, {}, platform_name="posix")
    command = [sys.executable, "-m", "scripts.numeric_history_demo_browser", "--child"]
    owned.start("browser", command, ROOT, protocol=True)
    owned.stop("browser")
    assert popen_calls[0][0] == command
    options = popen_calls[0][1]
    assert options["stdin"] is subprocess.PIPE
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.DEVNULL
    assert options["text"] is True and options["encoding"] == "utf-8"
    assert options["start_new_session"] is True
    assert kill_calls == [
        (9192, module.signal.SIGTERM),
        (9192, module.POSIX_SIGKILL),
    ]


def test_owned_process_event_failure_still_closes_full_posix_group(
    tmp_path, monkeypatch
):
    module = runner()
    kill_calls = []

    class Process:
        pid = 9292

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        module.os,
        "killpg",
        lambda pid, sig: kill_calls.append((pid, sig)),
        raising=False,
    )
    owned = module.SafeOwnedProcesses(tmp_path, {}, platform_name="posix")
    event_calls = []

    def fail_first_event(*args):
        event_calls.append(args)
        if len(event_calls) == 1:
            raise OSError("event write failed")

    monkeypatch.setattr(owned, "_event", fail_first_event)
    with pytest.raises(OSError, match="event write failed"):
        owned.start("api", ["fake"], ROOT)
    assert owned.processes == {} and owned.jobs == {}
    assert kill_calls == [
        (9292, module.signal.SIGTERM),
        (9292, module.POSIX_SIGKILL),
    ]


def test_owned_start_cleanup_error_does_not_replace_primary_failure(
    tmp_path, monkeypatch
):
    module = runner()

    class Process:
        pid = 9393

        def poll(self):
            return None

    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: Process())
    owned = module.SafeOwnedProcesses(tmp_path, {}, platform_name="posix")
    event_calls = []
    cleanup_calls = []

    def fail_first_event(*args):
        event_calls.append(args)
        if len(event_calls) == 1:
            raise OSError("primary event failure")

    def fail_first_cleanup(process):
        cleanup_calls.append(process)
        if len(cleanup_calls) == 1:
            raise TimeoutError("cleanup failure")
        return 0

    monkeypatch.setattr(owned, "_event", fail_first_event)
    monkeypatch.setattr(owned, "_stop_posix_group", fail_first_cleanup)
    with pytest.raises(OSError, match="^primary event failure$"):
        owned.start("api", ["fake"], ROOT)
    assert "api" in owned.processes
    errors = owned.close()
    assert len(errors) == 1 and isinstance(errors[0], TimeoutError)
    assert owned.processes == {} and len(cleanup_calls) == 2


def test_execute_rechecks_database_before_creating_output(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(argv(tmp_path, "--apply", "--allow-external-llm"))
    identities = _release_identities(module)

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Context()

        def dispose(self):
            pass

    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: Engine(), raising=False)
    monkeypatch.setattr(
        module,
        "inspect_demo_database",
        lambda connection: (_ for _ in ()).throw(ValueError("clean_test_database_required")),
    )
    monkeypatch.setattr(
        module,
        "seed_demo_database",
        lambda *args: pytest.fail("database gate must precede seed"),
    )
    with pytest.raises(ValueError, match="^clean_test_database_required$"):
        module.execute(arguments, identities)
    assert not arguments.output.exists()


def test_execute_collects_runtime_before_creating_output(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(argv(tmp_path, "--apply", "--allow-external-llm"))
    identities = _release_identities(module)
    disposed = []

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Context()

        def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: Engine())
    monkeypatch.setattr(module, "inspect_demo_database", lambda connection: {"ok": True})
    monkeypatch.setattr(
        module,
        "runtime_identity",
        lambda args: (_ for _ in ()).throw(RuntimeError("runtime failed")),
    )
    with pytest.raises(RuntimeError, match="^runtime failed$"):
        module.execute(arguments, identities)
    assert disposed == [True]
    assert not arguments.output.exists()


@pytest.mark.parametrize("failure_name", ["api", "frontend", "report_worker", "pdf_worker"])
def test_execute_start_failure_closes_owned_processes_and_writes_failed_record(
    tmp_path, monkeypatch, isolated, failure_name
):
    module = runner()
    arguments = module._parser().parse_args(argv(tmp_path, "--apply", "--allow-external-llm"))
    identities = _release_identities(module)
    lifecycle = []

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Context()

        def begin(self):
            return Context()

        def dispose(self):
            lifecycle.append("dispose")

    class Owned:
        def __init__(self, output, env):
            self.started = []
            lifecycle.append("owned")

        def start(self, name, command, cwd):
            lifecycle.append(f"start:{name}")
            if name == failure_name:
                raise RuntimeError("injected startup output with secret")
            self.started.append(name)

        def ready(self, name, endpoint):
            lifecycle.append(f"ready:{name}")

        def assert_alive(self, *names):
            lifecycle.append("alive")

        def observe_workers(self):
            lifecycle.append("observe")

        def close(self):
            for name in reversed(self.started):
                lifecycle.append(f"stop:{name}")

    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: Engine(), raising=False)
    monkeypatch.setattr(module, "inspect_demo_database", lambda connection: {"ok": True})
    monkeypatch.setattr(module, "seed_demo_database", lambda *args: {"case_ids": [1, 2, 3]})
    monkeypatch.setattr(module, "runtime_identity", lambda args: _runtime(), raising=False)
    monkeypatch.setattr(module, "SafeOwnedProcesses", Owned, raising=False)
    before = dict(os.environ)

    assert module.execute(arguments, identities) == 1
    assert dict(os.environ) == before
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert "secret" not in json.dumps(record)
    names = ["api", "frontend", "report_worker", "pdf_worker"]
    successful = names[: names.index(failure_name)]
    assert [item for item in lifecycle if item.startswith("stop:")] == [
        f"stop:{name}" for name in reversed(successful)
    ]
    assert lifecycle[-1] == "dispose"


def test_execute_marks_running_only_after_all_services_are_ready(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(argv(tmp_path, "--apply", "--allow-external-llm"))
    identities = _release_identities(module)
    statuses = []
    original_write = module.atomic_write_release

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Context()

        def begin(self):
            return Context()

        def dispose(self):
            pass

    class Owned:
        def __init__(self, output, env):
            self.started = []

        def start(self, name, command, cwd):
            self.started.append(name)

        def ready(self, name, endpoint):
            pass

        def assert_alive(self, *names):
            pass

        def observe_workers(self):
            pass

        def close(self):
            self.started.clear()
            return []

    class Browser:
        def __init__(self, **kwargs):
            self.stop_event = threading.Event()
            self.error = None

        def start(self):
            statuses.append("browser_started")

        def wait_ready(self, **kwargs):
            statuses.append("browser_ready")

    def write(path, record):
        statuses.append(record.status)
        original_write(path, record)

    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: Engine())
    monkeypatch.setattr(module, "inspect_demo_database", lambda connection: {"ok": True})
    seeded = {
        "case_ids": [1, 2, 3],
        "user_ids": {"primary_operator": 1, "secondary_operator": 2, "doctor": 3},
        "subjects": [{"anonymous_case_code": code} for code in ("A", "B", "C")],
    }
    monkeypatch.setattr(module, "seed_demo_database", lambda *args: seeded)
    monkeypatch.setattr(module, "runtime_identity", lambda args: _runtime())
    monkeypatch.setattr(module, "SafeOwnedProcesses", Owned)
    monkeypatch.setattr(module, "BrowserSession", Browser)
    monkeypatch.setattr(module, "supervise_demo_session", lambda *args: "browser_closed")
    monkeypatch.setattr(
        module,
        "shutdown_demo_session",
        lambda *args: {
            "inflight": {"settled": True},
            "summary": _metrics(),
            "errors": [],
        },
    )
    monkeypatch.setattr(module, "atomic_write_release", write)

    assert module.execute(arguments, identities) == 0
    assert statuses == [
        "starting",
        "browser_started",
        "browser_ready",
        "running",
        "stopped",
    ]


def test_cleanup_errors_are_appended_without_replacing_primary_failure(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(argv(tmp_path, "--apply", "--allow-external-llm"))
    identities = _release_identities(module)

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, *args):
            return False

    class Engine:
        def connect(self):
            return Context()

        def begin(self):
            return Context()

        def dispose(self):
            raise OSError("secret database url")

    class Owned:
        def __init__(self, output, env):
            pass

        def start(self, name, command, cwd):
            if name == "frontend":
                raise RuntimeError("primary secret")

        def ready(self, name, endpoint):
            pass

        def close(self):
            return [TimeoutError("cleanup secret")]

    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: Engine())
    monkeypatch.setattr(module, "inspect_demo_database", lambda connection: {"ok": True})
    monkeypatch.setattr(module, "seed_demo_database", lambda *args: {"case_ids": [1, 2, 3]})
    monkeypatch.setattr(module, "runtime_identity", lambda args: _runtime())
    monkeypatch.setattr(module, "SafeOwnedProcesses", Owned)

    assert module.execute(arguments, identities) == 1
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert [(item["stage"], item["error_type"]) for item in record["diagnostics"]] == [
        ("execution", "RuntimeError")
    ]
    assert [
        (item["stage"], item["error_type"]) for item in record["cleanup_errors"]
    ] == [("process_cleanup", "TimeoutError"), ("database_cleanup", "OSError")]
    for item in record["diagnostics"] + record["cleanup_errors"]:
        assert all(
            "/" not in frame["file"] and "\\" not in frame["file"]
            for frame in item["error_location"]
        )
    assert "secret" not in json.dumps(record)


class _ProtocolInput:
    def __init__(self):
        self.writes = []

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        pass


class _BlockingProtocolOutput:
    def __init__(self):
        self.values = queue.Queue()

    def __iter__(self):
        return self

    def __next__(self):
        value = self.values.get(timeout=2)
        if value is None:
            raise StopIteration
        return value

    def send(self, value):
        self.values.put(json.dumps(value) + "\n")

    def close(self):
        self.values.put(None)


def test_browser_session_sends_token_only_over_pipe_and_uses_daemon_protocol_thread(
    tmp_path,
):
    module = runner()
    events = []

    class Process:
        def __init__(self):
            self.stdin = _ProtocolInput()
            self.stdout = iter(
                [
                    '{"event":"ready"}\n',
                    '{"event":"stopped","cleanup_failed":false}\n',
                ]
            )

        def poll(self):
            return 0

    process = Process()

    class Owned:
        def start(self, name, command, cwd, **kwargs):
            events.append(("start", name, command, cwd, kwargs))
            return process

        def stop(self, name):
            events.append(("stop", name))

    browser = module.BrowserSession(
        output=tmp_path,
        user_ids={"primary_operator": 17, "secondary_operator": 18, "doctor": 19},
        subjects=[{"anonymous_case_code": code} for code in ("A", "B", "C")],
        owned=Owned(),
        token_factory=lambda user_id: f"temporary-token-{user_id}",
    )
    browser.start()
    browser.wait_ready(timeout_seconds=1)
    assert browser.stop(timeout_seconds=1) is None
    assert browser.thread.daemon is True
    assert not browser.thread.is_alive()
    command = events[0][2]
    assert command == [
        sys.executable,
        "-m",
        "scripts.numeric_history_demo_browser",
        "--child",
    ]
    assert events[0][4] == {"protocol": True}
    assert "temporary-token-17" not in str(events)
    payload = json.loads(process.stdin.writes[0])
    assert payload["tokens"] == {
        "primary": "temporary-token-17",
        "secondary": "temporary-token-18",
        "doctor": "temporary-token-19",
    }
    assert payload["subjects"] == [
        {"anonymous_case_code": "A"},
        {"anonymous_case_code": "B"},
        {"anonymous_case_code": "C"},
    ]
    assert events[-1] == ("stop", "browser")


def test_browser_session_force_stops_owned_process_when_protocol_reader_hangs(tmp_path):
    module = runner()
    output = _BlockingProtocolOutput()

    class Process:
        def __init__(self):
            self.stdin = _ProtocolInput()
            self.stdout = output
            self.running = True

        def poll(self):
            return None if self.running else 0

    process = Process()

    class Owned:
        def start(self, *args, **kwargs):
            return process

        def stop(self, name):
            assert name == "browser"
            process.running = False
            output.close()

    browser = module.BrowserSession(
        output=tmp_path,
        user_ids={"primary_operator": 17, "secondary_operator": 18, "doctor": 19},
        subjects=[{"anonymous_case_code": code} for code in ("A", "B", "C")],
        owned=Owned(),
        token_factory=lambda user_id: "temporary-token",
    )
    browser.start()
    output.send({"event": "ready"})
    browser.wait_ready(timeout_seconds=1)
    assert isinstance(browser.stop(timeout_seconds=0.01), RuntimeError)
    assert not browser.thread.is_alive()


class _CountResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


def test_wait_for_inflight_is_read_only_and_settles_only_at_zero():
    module = runner()
    counts = iter([(2, 1), (0, 0)])
    statements = []

    class Connection:
        def __enter__(self):
            self.current = next(counts)
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            sql = str(statement)
            statements.append(sql)
            if "report_generation_jobs" in sql:
                return _CountResult(self.current[0])
            if "report_pdf_attempts" in sql:
                return _CountResult(self.current[1])
            return _CountResult(None)

    class Engine:
        def connect(self):
            return Connection()

    class Processes:
        def __init__(self):
            self.checks = 0

        def assert_alive(self, *names):
            assert names == ("report_worker", "pdf_worker")
            self.checks += 1

    owned = Processes()
    clock_values = iter([0.0, 0.0, 0.1])
    result = module.wait_for_inflight(
        Engine(),
        owned,
        timeout_seconds=1,
        poll_seconds=0,
        clock=lambda: next(clock_values),
        sleeper=lambda seconds: None,
    )
    assert result == {
        "settled": True,
        "report_jobs": 0,
        "pdf_attempts": 0,
        "polls": 2,
    }
    assert owned.checks == 2
    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SELECT count(*) FROM report_generation_jobs WHERE status IN ('queued','running')",
        "SELECT count(*) FROM report_pdf_attempts WHERE status IN ('queued','running')",
    ] * 2
    assert not any("UPDATE" in statement or "DELETE" in statement for statement in statements)


def test_wait_for_inflight_times_out_without_changing_job_states():
    module = runner()

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            return _CountResult(1 if "SET TRANSACTION" not in str(statement) else None)

    engine = SimpleNamespace(connect=lambda: Connection())
    owned = SimpleNamespace(assert_alive=lambda *names: None)
    result = module.wait_for_inflight(
        engine,
        owned,
        timeout_seconds=0,
        poll_seconds=0,
        clock=lambda: 0,
        sleeper=lambda seconds: pytest.fail("timeout must not sleep"),
    )
    assert result == {
        "settled": False,
        "report_jobs": 1,
        "pdf_attempts": 1,
        "polls": 1,
    }


def test_shutdown_order_closes_admission_before_waiting_for_inflight():
    module = runner()
    events = []

    class Owned:
        def stop(self, name):
            events.append(f"stop:{name}")

        def close(self):
            events.append("retry_owned")
            return []

    browser = SimpleNamespace(stop=lambda **kwargs: events.append("stop:browser"))
    engine = SimpleNamespace(dispose=lambda: events.append("dispose"))

    def wait_for(engine_value, owned_value):
        events.append("wait_inflight")
        return {"settled": True, "report_jobs": 0, "pdf_attempts": 0, "polls": 1}

    summary = _metrics()

    def summarize():
        events.append("summarize")
        return summary

    result = module.shutdown_demo_session(
        engine,
        None,
        "/archive",
        Owned(),
        browser,
        {"case_ids": [1, 2, 3]},
        {"PARENT": "value"},
        wait_for=wait_for,
        summarize=summarize,
        restore=lambda parent: events.append("restore"),
        port_check=lambda ports: events.append("ports"),
    )
    assert events == [
        "stop:api",
        "stop:browser",
        "stop:frontend",
        "wait_inflight",
        "stop:report_worker",
        "stop:pdf_worker",
        "retry_owned",
        "summarize",
        "dispose",
        "restore",
        "ports",
    ]
    assert result["inflight"]["settled"] is True
    assert result["summary"] == summary
    assert result["errors"] == []


def test_shutdown_attempts_every_step_and_keeps_closed_error_values():
    module = runner()
    events = []

    def fail(stage):
        events.append(stage)
        raise RuntimeError("secret cleanup detail")

    owned = SimpleNamespace(
        stop=lambda name: fail(f"stop:{name}"),
        close=lambda: fail("retry_owned"),
    )
    browser = SimpleNamespace(stop=lambda **kwargs: fail("stop:browser"))
    engine = SimpleNamespace(dispose=lambda: fail("dispose"))
    result = module.shutdown_demo_session(
        engine,
        None,
        "/archive",
        owned,
        browser,
        {"case_ids": []},
        {},
        wait_for=lambda *args: fail("wait_inflight"),
        summarize=lambda: fail("summarize"),
        restore=lambda parent: fail("restore"),
        port_check=lambda ports: fail("ports"),
    )
    assert events == [
        "stop:api",
        "stop:browser",
        "stop:frontend",
        "wait_inflight",
        "stop:report_worker",
        "stop:pdf_worker",
        "retry_owned",
        "summarize",
        "dispose",
        "restore",
        "ports",
    ]
    assert [stage for stage, _ in result["errors"]] == [
        "stop_api",
        "stop_browser",
        "stop_frontend",
        "wait_inflight",
        "stop_report_worker",
        "stop_pdf_worker",
        "retry_owned_processes",
        "summarize",
        "dispose_engine",
        "restore_environment",
        "release_ports",
    ]
    assert "secret" not in json.dumps(
        [module._diagnostic(stage, error) for stage, error in result["errors"]]
    )


def test_supervisor_treats_ctrl_c_as_a_stop_request_before_browser_signal():
    module = runner()

    class StopEvent:
        def wait(self, timeout):
            raise KeyboardInterrupt

    browser = SimpleNamespace(stop_event=StopEvent(), error=None)
    owned = SimpleNamespace(
        assert_alive=lambda *names: pytest.fail("Ctrl+C must leave process checks")
    )
    assert module.supervise_demo_session(owned, browser, poll_seconds=0) == "keyboard_interrupt"


def test_supervisor_propagates_browser_thread_failure():
    module = runner()
    failure = RuntimeError("browser failed")
    browser = SimpleNamespace(
        stop_event=SimpleNamespace(wait=lambda timeout: True),
        error=failure,
    )
    with pytest.raises(RuntimeError, match="^browser failed$"):
        module.supervise_demo_session(SimpleNamespace(), browser, poll_seconds=0)


def _metrics(identities=None):
    from app.schemas.numeric_demo_release import NumericDemoReleaseMetrics

    from scripts import numeric_history_demo_release as release

    identities = identities or _release_identities(release)
    return NumericDemoReleaseMetrics.model_validate(
        release._zero_metrics(identities, identities["git_commit"])
    )


class _LoopbackEngine:
    def __init__(self, lifecycle=None, *, dispose_error=None):
        self.lifecycle = lifecycle if lifecycle is not None else []
        self.dispose_error = dispose_error

    def connect(self):
        return _LoopbackContext()

    def begin(self):
        return _LoopbackContext()

    def dispose(self):
        if self.dispose_error is not None:
            raise self.dispose_error
        self.lifecycle.append("dispose")


class _LoopbackContext:
    def __enter__(self):
        return object()

    def __exit__(self, *args):
        return False


class _LoopbackOwned:
    def __init__(self, output, env):
        self.started = []

    def start(self, name, command, cwd):
        self.started.append(name)

    def ready(self, name, endpoint):
        pass

    def assert_alive(self, *names):
        pass

    def observe_workers(self):
        pass

    def close(self):
        self.started.clear()
        return []


class _LoopbackBrowser:
    def __init__(self, **kwargs):
        self.stop_event = threading.Event()
        self.error = None

    def start(self):
        pass

    def wait_ready(self, **kwargs):
        pass


def _prepare_execute(monkeypatch, module, arguments, identities, seeded, **overrides):
    monkeypatch.setattr(module, "preflight", lambda args: identities)
    monkeypatch.setattr(module, "create_engine", lambda url: _LoopbackEngine())
    monkeypatch.setattr(module, "inspect_demo_database", lambda connection: {"ok": True})
    monkeypatch.setattr(module, "seed_demo_database", lambda *args: seeded)
    monkeypatch.setattr(module, "runtime_identity", lambda args: _runtime())
    monkeypatch.setattr(module, "SafeOwnedProcesses", _LoopbackOwned)
    monkeypatch.setattr(module, "BrowserSession", _LoopbackBrowser)
    monkeypatch.setattr(
        module, "supervise_demo_session", lambda *args, **kwargs: "browser_closed"
    )
    for name, value in overrides.items():
        monkeypatch.setattr(module, name, value)


def _seeded():
    return {
        "case_ids": [1, 2, 3],
        "user_ids": {"primary_operator": 1, "secondary_operator": 2, "doctor": 3},
        "subjects": [{"anonymous_case_code": code} for code in ("A", "B", "C")],
    }


def test_execute_writes_stopped_with_recomputed_metrics_after_a_clean_stop(
    tmp_path, monkeypatch, isolated, capsys
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    summary = _metrics()
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": summary,
            "errors": [],
        },
    )
    assert module.execute(arguments, identities) == 0
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "stopped"
    assert record["stopped_at"] is not None
    assert record["metrics"] == summary.model_dump(mode="json")
    assert record["cleanup_errors"] == []
    assert record["diagnostics"] == []
    console = json.loads(capsys.readouterr().out)
    assert console["status"] == "stopped"
    assert console["release"].endswith("/release.json")
    assert str(tmp_path) not in json.dumps(console)


def test_execute_marks_failed_when_a_teardown_step_fails_after_a_clean_stop(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    summary = _metrics()
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": summary,
            "errors": [("release_ports", OSError("secret port detail"))],
        },
    )
    assert module.execute(arguments, identities) == 1
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["cleanup_errors"] == [
        {"stage": "release_ports", "error_type": "OSError", "error_location": []}
    ]
    assert record["diagnostics"][0]["error_type"] == "ValueError"
    assert "secret" not in json.dumps(record)


def test_execute_marks_failed_when_the_evaluation_itself_fails(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": None,
            "errors": [("summarize", ValueError("demo_external_records_present"))],
        },
    )
    assert module.execute(arguments, identities) == 1
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["cleanup_errors"][0]["stage"] == "summarize"


def test_execute_reports_a_closed_code_and_never_the_primary_exception_text(
    tmp_path, monkeypatch, isolated, capsys
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)

    def fail(*args, **kwargs):
        raise RuntimeError("postgresql://secret:password@host/db token=abc")

    _prepare_execute(
        monkeypatch, module, arguments, identities, _seeded(),
        supervise_demo_session=fail,
    )
    assert module.execute(arguments, identities) == 1
    console = capsys.readouterr().out
    assert json.loads(console)["error"] == "demo_release_failed"
    assert "secret" not in console and "password" not in console


def test_execute_records_interrupts_as_failed_and_still_raises(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    _prepare_execute(
        monkeypatch, module, arguments, identities, _seeded(),
        supervise_demo_session=interrupt,
    )
    with pytest.raises(KeyboardInterrupt):
        module.execute(arguments, identities)
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["diagnostics"][0]["error_type"] == "KeyboardInterrupt"


def test_execute_returns_nonzero_when_the_final_record_cannot_be_written(
    tmp_path, monkeypatch, isolated, capsys
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    original = module.atomic_write_release
    calls = []

    def write(path, record):
        calls.append(record.status)
        if record.status in {"stopped", "failed"}:
            raise OSError("secret write detail")
        return original(path, record)

    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        atomic_write_release=write,
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": _metrics(),
            "errors": [],
        },
    )
    assert module.execute(arguments, identities) == 1
    assert calls == ["starting", "running", "stopped"]
    console = capsys.readouterr().out
    assert json.loads(console) == {
        "status": "error",
        "error": "demo_release_record_write_failed",
    }
    assert "secret" not in console


def test_execute_never_serializes_injected_secrets_anywhere_in_the_record(
    tmp_path, monkeypatch, isolated
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    secrets = [
        "postgresql://demo:pa55word@127.0.0.1/surgery_rag_phase4_test",
        "temporary-bearer-token",
        "SELECT * FROM users",
        "Authorization: Bearer temporary-bearer-token",
        "llm request body",
    ]

    def fail(*args, **kwargs):
        raise RuntimeError(" ".join(secrets))

    _prepare_execute(
        monkeypatch, module, arguments, identities, _seeded(),
        supervise_demo_session=fail,
    )
    assert module.execute(arguments, identities) == 1
    raw = (arguments.output / "release.json").read_text(encoding="utf-8")
    for secret in secrets:
        assert secret not in raw
    assert "pa55word" not in raw


def test_inspect_release_cli_mode_is_read_only_and_reports_unconfirmed_stop(
    tmp_path, monkeypatch, capsys
):
    module = runner()
    now = datetime.now(timezone.utc)
    record = module.build_release_record(
        "2026-09-20-v1",
        _release_identities(module),
        "2" * 40,
        _runtime(),
        now,
    )
    path = tmp_path / "release.json"
    path.write_text(json.dumps(record.model_dump(mode="json")), encoding="utf-8")
    before = path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("read-only inspection must not touch the database or spawn work")

    import sqlalchemy

    monkeypatch.setattr(sqlalchemy, "create_engine", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    result = module.main(["--inspect-release", str(path)])
    assert result == 0
    console = json.loads(capsys.readouterr().out)
    assert console == {
        "run_id": "2026-09-20-v1",
        "status": "starting",
        "unconfirmed_stop": True,
        "clinical_status": "not_assessable",
    }
    assert path.read_bytes() == before


def test_inspect_release_cli_mode_requires_exactly_one_path(tmp_path, capsys):
    module = runner()
    assert module.main(["--inspect-release"]) == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "error",
        "error": "invalid_arguments",
    }


def test_evaluation_blockers_name_every_integrity_fact_that_contradicts_a_clean_stop():
    from scripts.run_numeric_history_demo_release import evaluation_blockers

    assert evaluation_blockers(_metrics()) == []
    assert evaluation_blockers(_metrics_with(pdf={"sha_mismatches": 1})) == [
        "demo_archive_integrity_failed"]
    assert evaluation_blockers(_metrics_with(history={"mismatches": 2})) == [
        "demo_history_integrity_failed"]
    assert evaluation_blockers(_metrics_with(jobs={"unsettled": 1})) == [
        "demo_jobs_unsettled"]
    assert evaluation_blockers(
        _metrics_with(identity={"renderer_matches": False})
    ) == ["demo_identity_drift"]


def _metrics_with(**blocks):
    from app.schemas.numeric_demo_release import NumericDemoReleaseMetrics

    raw = _metrics().model_dump(mode="python")
    for name, override in blocks.items():
        raw[name].update(override)
    return NumericDemoReleaseMetrics.model_validate(raw)


@pytest.mark.parametrize(
    ("block", "code"),
    [
        ({"pdf": {"sha_mismatches": 1}}, "demo_archive_integrity_failed"),
        ({"history": {"mismatches": 1}}, "demo_history_integrity_failed"),
        ({"jobs": {"unsettled": 1}}, "demo_jobs_unsettled"),
        ({"identity": {"git_commit_matches": False}}, "demo_identity_drift"),
    ],
)
def test_execute_never_reports_stopped_when_the_evaluation_found_a_contradiction(
    tmp_path, monkeypatch, isolated, capsys, block, code
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    summary = _metrics_with(**block)
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": summary,
            "errors": [],
        },
    )
    assert module.execute(arguments, identities) == 1
    record = json.loads((arguments.output / "release.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"
    assert record["metrics"] == summary.model_dump(mode="json")
    assert json.loads(capsys.readouterr().out)["error"] == code


def test_execute_names_an_evaluation_failure_apart_from_a_shutdown_failure(
    tmp_path, monkeypatch, isolated, capsys
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": None,
            "errors": [("summarize", ValueError("demo_audit_integrity_failed"))],
        },
    )
    assert module.execute(arguments, identities) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "demo_evaluation_failed"


def test_execute_names_a_teardown_failure_apart_from_an_evaluation_failure(
    tmp_path, monkeypatch, isolated, capsys
):
    module = runner()
    arguments = module._parser().parse_args(
        argv(tmp_path, "--apply", "--allow-external-llm")
    )
    identities = _release_identities(module)
    _prepare_execute(
        monkeypatch,
        module,
        arguments,
        identities,
        _seeded(),
        shutdown_demo_session=lambda *args, **kwargs: {
            "inflight": {"settled": True},
            "summary": _metrics(),
            "errors": [("stop_api", OSError("secret teardown detail"))],
        },
    )
    assert module.execute(arguments, identities) == 1
    console = capsys.readouterr().out
    assert json.loads(console)["error"] == "demo_shutdown_failed"
    assert "secret" not in console
