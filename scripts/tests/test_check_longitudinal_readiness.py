import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "check_longitudinal_readiness.py"
)


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location(
        "longitudinal_readiness_checker", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载 readiness 脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exit_code_is_zero_without_blocked_disease(checker):
    assert (
        checker.exit_code_for_report(
            SimpleNamespace(overall_status="degraded")
        )
        == 0
    )


def test_exit_code_is_one_when_any_disease_is_blocked(checker):
    assert (
        checker.exit_code_for_report(SimpleNamespace(overall_status="blocked"))
        == 1
    )


def test_error_payload_contains_no_exception_details(checker):
    payload = checker.build_error_payload("database_unavailable")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["overall_status"] == "error"
    assert "postgresql://" not in serialized
    assert "Traceback" not in serialized


class _FakeTransaction:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class _FakeConnection:
    def __init__(self, transaction):
        self.transaction = transaction
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return self.transaction

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposals = 0

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposals += 1


def test_run_check_rolls_back_and_disposes_engine_on_success(
    checker, monkeypatch, tmp_path
):
    transaction = _FakeTransaction()
    connection = _FakeConnection(transaction)
    engine = _FakeEngine(connection)
    expected = SimpleNamespace(overall_status="blocked")
    monkeypatch.setattr(
        checker, "create_engine", lambda *args, **kwargs: engine
    )
    monkeypatch.setattr(
        checker,
        "collect_longitudinal_readiness",
        lambda *args, **kwargs: expected,
    )
    result = checker.run_check(
        database_url="postgresql://hidden",
        model_dir=tmp_path,
        code_heads={"0010"},
    )
    assert result is expected
    assert connection.begin_calls == 1
    assert transaction.rollbacks == 1
    assert engine.disposals == 1


def test_main_returns_two_and_prints_sanitized_json_on_database_error(
    checker, monkeypatch, capsys
):
    monkeypatch.setattr(
        checker,
        "run_check",
        lambda **kwargs: (_ for _ in ()).throw(
            checker.SQLAlchemyError(
                "postgresql://user:password@localhost/private"
            )
        ),
    )
    assert checker.main() == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["error"]["code"] == "database_unavailable"
    assert "postgresql://" not in output
    assert "password" not in output
    assert "Traceback" not in output


def test_main_prints_one_json_document_for_business_result(
    checker, monkeypatch, capsys
):
    report = SimpleNamespace(
        overall_status="blocked",
        model_dump=lambda mode: {
            "schema_version": "longitudinal_readiness.v1",
            "overall_status": "blocked",
        },
    )
    monkeypatch.setattr(checker, "run_check", lambda **kwargs: report)
    assert checker.main() == 1
    assert json.loads(capsys.readouterr().out)["overall_status"] == "blocked"


def test_checker_source_contains_no_mutating_sql():
    source = SCRIPT_PATH.read_text(encoding="utf-8").upper()
    for forbidden in (
        "DROP ",
        "TRUNCATE ",
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "ALTER ",
    ):
        assert forbidden not in source


def test_checker_uses_shared_model_path_module():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "from app.services.model_paths import MODEL_DIR" in source
    assert "progression_engine" not in source


def test_cli_reconfigures_gbk_stdout_to_utf8(checker, monkeypatch):
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="gbk")
    monkeypatch.setattr(checker.sys, "stdout", stream)
    checker.configure_stdout_utf8()
    checker._print_json({"message": "脂肪肝"})
    stream.flush()
    assert json.loads(raw.getvalue().decode("utf-8"))["message"] == "脂肪肝"
