import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("checker", ROOT / "scripts/check_database_readonly.py")
checker = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(checker)


def test_checker_declares_evidence_storage_contract():
    assert checker.REQUIRED_COLUMNS["reference_case_windows"] >= {
        "anonymous_case_code", "dataset_release_id", "feature_summary", "eligibility_status", "timeline_sha256"
    }
    assert checker.REQUIRED_COLUMNS["ai_reports"] >= {"evidence_snapshot", "evidence_snapshot_sha256", "evidence_status"}

