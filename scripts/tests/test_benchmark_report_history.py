import pytest
from scripts.benchmark_report_history import main


def test_benchmark_never_falls_back_to_production_database(monkeypatch, tmp_path):
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://production/real")
    with pytest.raises(ValueError, match="explicit_local_test_database_required"):
        main(["--output", str(tmp_path / "result.json")])
