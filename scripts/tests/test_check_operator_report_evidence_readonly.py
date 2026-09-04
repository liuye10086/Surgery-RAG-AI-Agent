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


def test_phase_is_explicit_for_deployment_safety():
    action = next(
        item for item in checker._argument_parser()._actions
        if item.dest == "phase"
    )
    assert action.required is True


def test_postflight_runtime_and_storage_checks_fail_closed():
    assert checker._evidence_runtime_matches({"available": False}, "postflight") is False
    assert checker._evidence_storage_matches({"available": False}, "postflight") is False


def test_runtime_query_failure_is_explicit_and_not_a_pass():
    class BrokenConnection:
        def execute(self, *_args, **_kwargs):
            raise RuntimeError("database details must not escape")

    result = checker._collect_evidence_runtime_checks(BrokenConnection(), "postflight")

    assert result == {"available": False, "reason_code": "evidence_runtime_query_failed"}
    assert checker._evidence_runtime_matches(result, "postflight") is False
