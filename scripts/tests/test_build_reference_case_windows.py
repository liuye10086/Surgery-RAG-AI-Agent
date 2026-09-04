import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_reference_case_windows", ROOT / "scripts/build_reference_case_windows.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


def test_cli_defaults_to_dry_run_and_prints_statistics_only(capsys):
    result = SimpleNamespace(model_dump=lambda mode="json": {"total_windows": 3, "eligible_windows": 2, "inserted": 0, "unchanged": 0, "dataset_release_id": "r", "data_content_sha256": "a" * 64, "eligibility_config_hash": "b" * 64, "logical_dataset": "ad", "exclusion_counts": {}})
    with patch.object(module, "SessionLocal") as session, patch.object(module, "synchronize_reference_case_windows", return_value=result) as sync:
        session.return_value.__enter__.return_value = MagicMock()
        assert module.main(["--dataset", "ad"]) == 0
    sync.assert_called_once()
    assert sync.call_args.kwargs["apply"] is False
    payload = json.loads(capsys.readouterr().out)
    assert payload["total_windows"] == 3
    assert "feature_summary" not in payload


def test_cli_reports_blocked_without_details(capsys):
    from app.services.reference_case_windows import ReferenceIndexError

    with patch.object(module, "SessionLocal") as session, patch.object(module, "synchronize_reference_case_windows", side_effect=ReferenceIndexError("active_release_missing")):
        session.return_value.__enter__.return_value = MagicMock()
        assert module.main(["--dataset", "fatty_liver"]) == 1
    assert capsys.readouterr().out.strip() == "status=BLOCKED error_code=active_release_missing"
