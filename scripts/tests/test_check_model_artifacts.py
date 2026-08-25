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
