import importlib.util
import json
from pathlib import Path


def _load():
    path = Path(__file__).parents[1] / "check_standard_manifests.py"
    spec = importlib.util.spec_from_file_location("check_standard_manifests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_cli_defaults_to_dry_run(monkeypatch, capsys, tmp_path):
    script = _load()
    monkeypatch.setattr(script, "build_plan", lambda *args, **kwargs: {"status": "dry_run"})
    assert script.main(["--manifest", str(tmp_path / "x.json"), "--source", str(tmp_path / "x.docx"), "--review-output", str(tmp_path / "review.md")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"


def test_check_mode_reports_drift(monkeypatch, capsys, tmp_path):
    script = _load()
    monkeypatch.setattr(script, "build_plan", lambda *args, **kwargs: {"status": "drift"})
    assert script.main(["--manifest", str(tmp_path / "x.json"), "--source", str(tmp_path / "x.docx"), "--review-output", str(tmp_path / "review.md"), "--check"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "drift"


def test_source_hash_mismatch_is_a_business_blocker(monkeypatch, capsys, tmp_path):
    script = _load()
    monkeypatch.setattr(script, "build_plan", lambda *args, **kwargs: {"status": "blocked", "error": "source_hash_mismatch"})
    assert script.main(["--manifest", str(tmp_path / "x.json"), "--source", str(tmp_path / "x.docx"), "--review-output", str(tmp_path / "review.md"), "--check"]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "source_hash_mismatch"
