from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli():
    path = ROOT / "scripts" / "build_longitudinal_demonstration_dataset.py"
    spec = importlib.util.spec_from_file_location("demonstration_dataset_cli", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("demonstration_dataset_cli_missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_builds_fresh_demonstration_release_without_patient_identity(
    cli, tmp_path, capsys
):
    output = tmp_path / "dataset"

    assert cli.main(
        [
            "--output-dir",
            str(output),
            "--patients-per-disease",
            "15",
            "--seed",
            "20260827",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert payload["status"] == "generated"
    assert payload["training_profile"] == "synthetic_demonstration"
    assert payload["patient_count_by_disease"] == {"ad": 15, "fatty_liver": 15}
    assert manifest["generator"]["seed"] == 20260827
    assert "patient_label" not in rendered
    assert "source_document" not in rendered
    assert str(output.resolve()) not in rendered


def test_cli_refuses_existing_output(cli, tmp_path, capsys):
    output = tmp_path / "dataset"
    output.mkdir()
    (output / "keep").write_text("keep", encoding="utf-8")

    assert cli.main(["--output-dir", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "output_exists"
    assert (output / "keep").read_text(encoding="utf-8") == "keep"
