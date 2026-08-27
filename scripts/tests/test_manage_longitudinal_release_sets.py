from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def cli():
    path = ROOT / "scripts" / "manage_longitudinal_release_sets.py"
    spec = importlib.util.spec_from_file_location("release_set_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_requires_explicit_registry_and_identity(cli, tmp_path, capsys):
    assert cli.main(["review", "--candidate-manifest", str(tmp_path / "x.json")]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "arguments_required"


def test_review_outputs_relative_review_file(cli, monkeypatch, tmp_path, capsys):
    registry = tmp_path / "registry"
    review_file = registry / "reviews" / "review-set-v1.json"
    monkeypatch.setattr(
        cli,
        "review_release_set",
        lambda *args, **kwargs: SimpleNamespace(
            release_set=SimpleNamespace(
                dataset="ad",
                release_set_id="ad-set-v1",
                record_sha256="a" * 64,
            ),
            review_path=review_file,
        ),
    )

    assert (
        cli.main(
            [
                "review",
                "--candidate-manifest",
                str(tmp_path / "candidate.json"),
                "--registry-dir",
                str(registry),
                "--reviewer",
                "owner",
                "--note",
                "approved candidate",
                "--reviewed-at",
                "2026-08-27T00:00:00+00:00",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["review_file"] == "reviews/review-set-v1.json"
    assert str(tmp_path.resolve()) not in output


def test_enable_outputs_safe_release_identity(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "enable_release_set",
        lambda *args, **kwargs: SimpleNamespace(
            dataset="ad",
            release_set_id="ad-set-v1",
            release_set_sha256="a" * 64,
            changed_at=cli.datetime.fromisoformat("2026-08-27T00:00:00+00:00"),
        ),
    )
    assert (
        cli.main(
            [
                "enable",
                "--review-file",
                str(tmp_path / "review.json"),
                "--registry-dir",
                str(tmp_path / "registry"),
                "--enabled-by",
                "owner",
                "--enabled-at",
                "2026-08-27T00:00:00+00:00",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["release_set_id"] == "ad-set-v1"
    assert str(tmp_path.resolve()) not in output
    assert "Traceback" not in output


def test_cli_source_has_no_implicit_enable_after_review():
    source = (ROOT / "scripts" / "manage_longitudinal_release_sets.py").read_text(
        encoding="utf-8"
    )
    assert "review_release_set(" in source
    assert "enable_release_set(" in source
    assert "args.command == \"review\"" in source
    assert "args.command == \"enable\"" in source


def test_deactivate_outputs_safe_identity(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        cli,
        "deactivate_release_set",
        lambda *args, **kwargs: SimpleNamespace(
            dataset="ad",
            previous_release_set_id="ad-set-v1",
            changed_at=cli.datetime.fromisoformat("2026-08-27T00:00:00+00:00"),
        ),
    )

    assert (
        cli.main(
            [
                "deactivate",
                "--dataset",
                "ad",
                "--expected-release-set",
                "ad-set-v1",
                "--registry-dir",
                str(tmp_path / "registry"),
                "--actor",
                "owner",
                "--changed-at",
                "2026-08-27T00:00:00+00:00",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["status"] == "deactivated"
    assert payload["previous_release_set_id"] == "ad-set-v1"
    assert str(tmp_path.resolve()) not in output
    assert "Traceback" not in output
