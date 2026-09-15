import hashlib
import json
from pathlib import Path
import shutil

import pytest


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    from app.schemas.synthetic_prediction_cases import GenerationConfig
    from app.services.synthetic_prediction_case_export import export_synthetic_cases
    path = tmp_path_factory.mktemp("calculation-source") / "verified"
    export_synthetic_cases(GenerationConfig(), path)
    return path


def exporter():
    from app.services import prediction_calculation_export
    return prediction_calculation_export


def test_real_source_export_is_reproducible_and_preserves_source(tmp_path, source):
    m = exporter()
    before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    a, b = tmp_path / "one", tmp_path / "two"
    first, second = m.evaluate_synthetic_package(source, a), m.evaluate_synthetic_package(source, b)
    assert first["status"] == second["status"] == "passed"
    assert first["counts"]["samples"] == 480
    assert first["counts"]["predictions"] == 960
    for name in m.DATA_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes()
    assert m.verify_calculation_export(a)["status"] == "passed"
    assert all(c["performance"]["status"] == "not_assessable"
               for c in json.loads((a / "evaluation.json").read_text(encoding="utf-8"))["comparisons"])
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()} == before


def test_output_and_source_failures_never_overwrite(tmp_path, source):
    m = exporter()
    exists = tmp_path / "exists"
    exists.mkdir()
    (exists / "keep").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        m.evaluate_synthetic_package(source, exists)
    assert (exists / "keep").read_bytes() == b"keep"
    copied = tmp_path / "invalid-source"
    shutil.copytree(source, copied)
    (copied / "prediction_inputs.jsonl").write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="source_not_verified"):
        m.evaluate_synthetic_package(copied, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_forged_calculation_even_with_rehashed_files_is_rejected(tmp_path, source):
    m = exporter()
    out = tmp_path / "data"
    m.evaluate_synthetic_package(source, out)
    path = out / "evaluation.json"
    evaluation = json.loads(path.read_text(encoding="utf-8"))
    evaluation["comparisons"][0]["statistics"]["mae"] = 999
    path.write_text(json.dumps(evaluation), encoding="utf-8")
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"]["evaluation.json"] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    manifest["data_content_sha256"] = m.content_hash(manifest["files"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    assert m.verify_calculation_export(out)["reason"] == "calculation_mismatch"


def test_io_failure_only_cleans_its_own_directory(tmp_path, source, monkeypatch):
    m = exporter()
    keep = tmp_path / "keep"
    keep.write_bytes(b"keep")
    write = Path.write_bytes

    def fail(path, value):
        if path.name == "evaluation.json":
            raise OSError("synthetic IO error")
        return write(path, value)

    monkeypatch.setattr(Path, "write_bytes", fail)
    with pytest.raises(OSError):
        m.evaluate_synthetic_package(source, tmp_path / "result")
    assert list(tmp_path.iterdir()) == [keep]
    assert keep.read_bytes() == b"keep"


def test_destination_appearing_at_rename_is_not_overwritten(tmp_path, source, monkeypatch):
    m = exporter()
    destination = tmp_path / "result"
    rename = m.os.rename

    def competing_writer(temporary, target):
        destination.mkdir()
        (destination / "keep").write_bytes(b"other writer")
        return rename(temporary, target)

    monkeypatch.setattr(m.os, "rename", competing_writer)
    with pytest.raises(FileExistsError):
        m.evaluate_synthetic_package(source, destination)
    assert list(tmp_path.iterdir()) == [destination]
    assert (destination / "keep").read_bytes() == b"other writer"


def test_nested_output_is_rejected_without_changing_verified_source(tmp_path, source):
    m = exporter()
    copied = tmp_path / "source"
    shutil.copytree(source, copied)
    before = {p.name: p.read_bytes() for p in copied.iterdir()}
    with pytest.raises(ValueError, match="output_inside_source"):
        m.evaluate_synthetic_package(copied, copied / "new-parent/calculation")
    assert {p.name: p.read_bytes() for p in copied.iterdir()} == before
