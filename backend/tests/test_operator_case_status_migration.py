from pathlib import Path
import importlib.util


ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    path = ROOT / "backend" / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_status_migrations_are_two_phase_and_chain_from_0014():
    first = _load("0015_operator_case_status_constraint.py")
    second = _load("0016_validate_operator_case_status.py")
    assert first.down_revision == "0014"
    assert second.down_revision == "0015"
    assert "NOT VALID" in Path(first.__file__).read_text(encoding="utf-8")
    assert "VALIDATE CONSTRAINT ck_operator_cases_status" in Path(second.__file__).read_text(encoding="utf-8")


def test_status_migration_source_never_rewrites_case_values():
    first = Path(ROOT / "backend/alembic/versions/0015_operator_case_status_constraint.py").read_text(encoding="utf-8").upper()
    second = Path(ROOT / "backend/alembic/versions/0016_validate_operator_case_status.py").read_text(encoding="utf-8").upper()
    for source in (first, second):
        assert "UPDATE OPERATOR_CASES" not in source
        assert "DELETE FROM OPERATOR_CASES" not in source

