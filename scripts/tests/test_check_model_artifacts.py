from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parents[1]))
from check_model_artifacts import sha256_file, sha256_manifest


def test_sha256_manifest_detects_matching_and_tampered_files(tmp_path: Path):
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"stable")
    baseline = sha256_manifest(tmp_path)
    assert sha256_manifest(tmp_path) == baseline
    artifact.write_bytes(b"tampered")
    assert sha256_manifest(tmp_path) != baseline


def test_sha256_file_matches_manifest_value(tmp_path: Path):
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"stable")
    assert sha256_file(artifact) == sha256_manifest(tmp_path)["model.joblib"]


def test_bundle_checker_reuses_registry_status_and_never_predicts(tmp_path):
    import importlib.util

    helper_path = ROOT = Path(__file__).resolve().parents[2] / "backend" / "tests" / "test_longitudinal_model_registry.py"
    spec = importlib.util.spec_from_file_location("registry_helpers_checker", helper_path)
    helpers = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(helpers)
    bundle, _, _, _ = helpers._write_candidate_bundle(tmp_path)

    from check_model_artifacts import check_bundle

    payload = check_bundle(bundle)
    assert payload["status"] == "disabled"
    assert payload["reason_code"] == "lifecycle_not_enabled"
    assert payload["prediction_executed"] is False


def test_registry_checker_reports_tasks_independently(tmp_path):
    import importlib.util

    helper_path = Path(__file__).resolve().parents[2] / "backend" / "tests" / "test_longitudinal_model_registry.py"
    spec = importlib.util.spec_from_file_location("registry_helpers_registry_checker", helper_path)
    helpers = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(helpers)
    helpers._write_enabled_release(
        tmp_path, task="fatty_liver.pre_cirrhosis_to_progression"
    )

    from check_model_artifacts import check_registry

    payload = check_registry(tmp_path)
    fatty = payload["datasets"]["fatty_liver"]["outcomes"]
    assert fatty["fatty_liver.pre_cirrhosis_to_progression"]["status"] == "available"
    assert fatty["fatty_liver.cirrhosis_to_hcc"]["status"] == "missing"
