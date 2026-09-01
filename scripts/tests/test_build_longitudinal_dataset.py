"""Read-only CLI contracts for the P0-03 dataset builder."""

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_longitudinal_dataset.py"
for import_path in (ROOT, ROOT / "backend"):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))


@pytest.fixture
def cli():
    spec = importlib.util.spec_from_file_location(
        "build_longitudinal_dataset_cli",
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载数据集脚本: {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeMappings:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return FakeMappings(self.rows)


class LoaderConnection:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))
        if len(self.statements) == 1:
            return FakeResult([])
        return FakeResult(self.rows)


def test_load_case_rows_sets_read_only_before_scoped_select():
    from app.services.longitudinal_dataset import load_case_rows

    row = {
        "record_id": 1,
        "disease_code": "fatty_liver",
        "disease_name": "脂肪肝",
        "patient_label": "P001",
        "indicators": [],
        "metadata": {},
    }
    connection = LoaderConnection([row])

    rows = load_case_rows(connection)

    first_sql = connection.statements[0][0].strip().upper()
    select_sql = connection.statements[1][0]
    assert first_sql == "SET TRANSACTION READ ONLY"
    assert "FROM case_records" in select_sql
    assert "confirmed" not in select_sql.lower()
    assert "dataset_active" in select_sql
    assert "NOT EXISTS" in select_sql.upper()
    assert set(rows[0]) == {
        "record_id",
        "disease_code",
        "disease_name",
        "patient_label",
        "indicators",
        "metadata",
    }
    assert connection.statements[1][1] is None
    assert "d.code AS disease_code" in select_sql
    assert "d.code IN ('fatty_liver', 'ad')" in select_sql


class FakeTransaction:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class FakeConnection:
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


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposals = 0

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposals += 1


def _summary_payload():
    return {
        "schema_version": "longitudinal_fixed_window_dataset.v1",
        "minimum_visits": 3,
        "horizon_days": 365,
        "diseases": {
            "fatty_liver": {"real": {"patient_count": 1}},
            "ad": {"real": {"patient_count": 1}},
        },
    }


def test_run_build_rolls_back_and_disposes_without_export(cli, monkeypatch):
    transaction = FakeTransaction()
    connection = FakeConnection(transaction)
    engine = FakeEngine(connection)
    result = SimpleNamespace(
        summary=SimpleNamespace(model_dump=lambda **kwargs: _summary_payload())
    )
    monkeypatch.setattr(cli, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli, "load_case_rows", lambda connection: [])
    monkeypatch.setattr(cli, "build_fixed_window_dataset", lambda rows: result)

    payload = cli.run_build(
        database_url="postgresql://hidden",
        output_dir=None,
        generated_at=cli.datetime(2026, 8, 26, tzinfo=cli.timezone.utc),
    )

    assert payload["mode"] == "audit_only"
    assert "output_dir" not in payload
    assert transaction.rollbacks == 1
    assert connection.begin_calls == 1
    assert engine.disposals == 1


def test_run_build_explicit_export_returns_hash(cli, monkeypatch, tmp_path):
    transaction = FakeTransaction()
    engine = FakeEngine(FakeConnection(transaction))
    result = SimpleNamespace(
        summary=SimpleNamespace(model_dump=lambda **kwargs: _summary_payload())
    )
    target = tmp_path / "fresh"
    calls = []
    monkeypatch.setattr(cli, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(cli, "load_case_rows", lambda connection: [])
    monkeypatch.setattr(cli, "build_fixed_window_dataset", lambda rows: result)
    monkeypatch.setattr(cli, "get_code_version", lambda: "abc123")
    monkeypatch.setattr(
        cli,
        "export_fixed_window_dataset",
        lambda built, output_dir, **kwargs: (
            calls.append((built, output_dir, kwargs))
            or {"data_content_sha256": "f" * 64}
        ),
    )

    payload = cli.run_build(
        database_url="postgresql://hidden",
        output_dir=target,
        generated_at=cli.datetime(2026, 8, 26, tzinfo=cli.timezone.utc),
    )

    assert payload["mode"] == "exported"
    assert payload["data_content_sha256"] == "f" * 64
    assert payload["output_dir"] == str(target.resolve())
    assert calls[0][1] == target


def test_main_default_prints_one_anonymous_json_document(cli, monkeypatch, capsys):
    payload = {
        "schema_version": "longitudinal_fixed_window_dataset.v1",
        "mode": "audit_only",
        "summary": _summary_payload(),
    }
    calls = []
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda **kwargs: calls.append(kwargs) or payload,
    )

    assert cli.main([]) == 0

    output = capsys.readouterr().out
    assert json.loads(output) == payload
    assert calls[0]["output_dir"] is None
    for forbidden in ("patient_label", "group_id", "P001", "source_document"):
        assert forbidden not in output


def test_main_passes_explicit_output_directory(cli, monkeypatch, tmp_path, capsys):
    target = tmp_path / "dataset"
    calls = []
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda **kwargs: calls.append(kwargs)
        or {
            "schema_version": "longitudinal_fixed_window_dataset.v1",
            "mode": "exported",
            "summary": _summary_payload(),
        },
    )

    assert cli.main(["--output-dir", str(target)]) == 0

    json.loads(capsys.readouterr().out)
    assert calls[0]["output_dir"] == target


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (SQLAlchemyError("postgresql://user:password@host/private"), "database_unavailable"),
        (FileExistsError("P001"), "output_exists"),
        (OSError("P001"), "output_error"),
    ],
)
def test_main_sanitizes_runtime_errors(cli, monkeypatch, capsys, error, expected_code):
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )

    assert cli.main([]) == 2

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["error"]["code"] == expected_code
    for secret in ("postgresql://", "password", "P001", "Traceback"):
        assert secret not in output


def test_main_uses_stable_validation_code_without_patient_details(cli, monkeypatch, capsys):
    error = cli.DatasetValidationError(
        "duplicate_patient_visit_date",
        {"patient_label": "P001", "conflict_count": 2},
    )
    monkeypatch.setattr(
        cli,
        "run_build",
        lambda **kwargs: (_ for _ in ()).throw(error),
    )

    assert cli.main([]) == 2

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["error"]["code"] == "duplicate_patient_visit_date"
    assert payload["error"]["details"] == {"conflict_count": 2}
    assert "P001" not in output


def test_cli_source_has_no_training_or_mutating_operations():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    upper = source.upper()
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "TRUNCATE ", "ALTER "):
        assert forbidden not in upper
    for forbidden in ("joblib", ".fit(", "ml_models"):
        assert forbidden not in source
