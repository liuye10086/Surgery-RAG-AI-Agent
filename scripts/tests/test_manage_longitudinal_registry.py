import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _cli():
    path = ROOT / "scripts" / "manage_longitudinal_registry.py"
    spec = importlib.util.spec_from_file_location("registry_cli", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cli_requires_explicit_registry_directory(capsys):
    cli = _cli()
    assert cli.main(["review", "--bundle-dir", "candidate"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "registry_dir_required"


def test_cli_sanitizes_service_errors(monkeypatch, capsys, tmp_path):
    cli = _cli()

    def fail(*args, **kwargs):
        raise cli.ModelReleaseError(
            "candidate_invalid", "C:\\private\\P001 password postgresql://secret"
        )

    monkeypatch.setattr(cli, "review_candidate", fail)
    code = cli.main(
        [
            "review",
            "--bundle-dir",
            str(tmp_path / "candidate"),
            "--registry-dir",
            str(tmp_path / "registry"),
            "--reviewer",
            "owner",
            "--note",
            "review",
            "--reviewed-at",
            "2026-08-26T00:00:00Z",
        ]
    )
    assert code == 2
    output = capsys.readouterr().out
    assert all(value not in output for value in ("P001", "password", "postgresql://", "C:\\private"))
    assert json.loads(output)["error"]["code"] == "candidate_invalid"


def test_review_cli_returns_relative_record_for_relative_registry(monkeypatch, capsys, tmp_path):
    from types import SimpleNamespace

    cli = _cli()
    monkeypatch.chdir(tmp_path)
    review_path = (tmp_path / "registry" / "reviews" / "review-1.json").resolve()
    monkeypatch.setattr(
        cli,
        "review_candidate",
        lambda *args, **kwargs: SimpleNamespace(
            path=review_path,
            record=SimpleNamespace(task="ad.pre_dementia_to_dementia", model_id="model-1"),
        ),
    )
    code = cli.main(
        [
            "review",
            "--bundle-dir",
            "candidate",
            "--registry-dir",
            "registry",
            "--reviewer",
            "owner",
            "--note",
            "review",
            "--reviewed-at",
            "2026-08-26T00:00:00Z",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["review_file"] == "reviews/review-1.json"
