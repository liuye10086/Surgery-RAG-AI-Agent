"""End-to-end filesystem checks, isolated from business data."""

import hashlib
import json
from pathlib import Path

import pytest

from app.schemas.synthetic_prediction_cases import GenerationConfig


def exporter():
    from app.services import synthetic_prediction_case_export
    return synthetic_prediction_case_export


def small_config():
    return GenerationConfig(patients_per_disease=3, challenge_per_disease=1)


def test_export_is_reproducible_and_verifier_retains_unsupported_status(tmp_path):
    module = exporter()
    first = module.export_synthetic_cases(small_config(), tmp_path / "first")
    second = module.export_synthetic_cases(small_config(), tmp_path / "second")
    assert first["status"] == second["status"] == "not_assessable"
    for name in module.DATA_FILES:
        assert (tmp_path / "first" / name).read_bytes() == (tmp_path / "second" / name).read_bytes()
    manifest = json.loads((tmp_path / "first/manifest.json").read_text(encoding="utf-8"))
    assert manifest["clinical_validity_claim"] is False
    assert manifest["counts"]["patients"] == 6
    assert manifest["counts"]["prediction_inputs"] == 12
    for line in (tmp_path / "first/patients.jsonl").read_text(encoding="utf-8").splitlines():
        assert json.loads(line)["source"]["run_id"] == manifest["run_id"]
    assert module.verify_synthetic_case_export(tmp_path / "first")["status"] == "not_assessable"


def test_existing_directory_is_never_overwritten(tmp_path):
    module = exporter()
    destination = tmp_path / "exists"
    destination.mkdir()
    sentinel = destination / "keep.txt"
    sentinel.write_bytes(b"unchanged")
    with pytest.raises(FileExistsError):
        module.export_synthetic_cases(small_config(), destination)
    assert sentinel.read_bytes() == b"unchanged"
    assert list(tmp_path.iterdir()) == [destination]


def test_concurrent_destination_creation_is_preserved(tmp_path, monkeypatch):
    module = exporter()
    destination = tmp_path / "raced"
    rename = module.os.rename

    def competing_writer(source, target):
        destination.mkdir()
        (destination / "keep").write_bytes(b"other writer")
        return rename(source, target)

    monkeypatch.setattr(module.os, "rename", competing_writer)
    with pytest.raises(FileExistsError):
        module.export_synthetic_cases(small_config(), destination)
    assert (destination / "keep").read_bytes() == b"other writer"
    assert list(tmp_path.iterdir()) == [destination]


def test_corrupted_data_is_detected(tmp_path):
    module = exporter()
    module.export_synthetic_cases(small_config(), tmp_path / "data")
    with (tmp_path / "data/prediction_inputs.jsonl").open("ab") as handle:
        handle.write(b"{}\n")
    assert module.verify_synthetic_case_export(tmp_path / "data")["status"] == "failed"


def test_forged_passed_report_is_recomputed_even_with_updated_hashes(tmp_path):
    module = exporter()
    destination = tmp_path / "data"
    module.export_synthetic_cases(small_config(), destination)
    quality_path = destination / "quality_report.json"
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    quality["status"] = "passed"
    quality_path.write_text(json.dumps(quality), encoding="utf-8")
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["quality_status"] = "passed"
    manifest["files"]["quality_report.json"] = {
        "sha256": hashlib.sha256(quality_path.read_bytes()).hexdigest(),
        "bytes": quality_path.stat().st_size,
    }
    manifest["data_content_sha256"] = module.content_hash(manifest["files"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = module.verify_synthetic_case_export(destination)
    assert result["status"] == "failed"
    assert result["reason"] == "quality_report_mismatch"


def test_file_failure_cleans_only_owned_temporary_directory(tmp_path, monkeypatch):
    module = exporter()
    keep = tmp_path / "unrelated"
    keep.mkdir()
    (keep / "keep").write_bytes(b"untouched")
    original = Path.write_bytes

    def fail_quality(path, value):
        if path.name == "quality_report.json":
            raise OSError("synthetic IO failure must not print this detail")
        return original(path, value)

    monkeypatch.setattr(Path, "write_bytes", fail_quality)
    with pytest.raises(OSError):
        module.export_synthetic_cases(small_config(), tmp_path / "data")
    assert list(tmp_path.iterdir()) == [keep]
    assert (keep / "keep").read_bytes() == b"untouched"
