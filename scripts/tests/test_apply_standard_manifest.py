import importlib.util
import json
from pathlib import Path


def _load():
    path = Path(__file__).parents[1] / "apply_standard_manifest.py"
    spec = importlib.util.spec_from_file_location("apply_standard_manifest", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def test_cli_defaults_to_dry_run(monkeypatch, capsys, tmp_path):
    script = _load()
    monkeypatch.setattr(script, "build_plan", lambda *args, **kwargs: {"status": "dry_run"})
    assert script.main(["--manifest", str(tmp_path / "x.json"), "--source", str(tmp_path / "x.docx"), "--version-id", "4", "--admin-id", "7"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"


def test_execute_path_rolls_back_on_failure(monkeypatch, capsys, tmp_path):
    script = _load()
    transaction = type("Tx", (), {"rollbacks": 0, "commits": 0})()
    transaction.rollback = lambda: setattr(transaction, "rollbacks", transaction.rollbacks + 1)
    transaction.commit = lambda: setattr(transaction, "commits", transaction.commits + 1)
    monkeypatch.setattr(script, "open_transaction", lambda: transaction)
    monkeypatch.setattr(script, "execute_changes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")))
    assert script.main(["--manifest", str(tmp_path / "x.json"), "--source", str(tmp_path / "x.docx"), "--version-id", "4", "--admin-id", "7", "--execute"]) == 2
    assert transaction.rollbacks == 1
    assert transaction.commits == 0


def test_execute_publish_submits_draft_for_review_before_publication(monkeypatch):
    script = _load()
    args = type("Args", (), {
        "manifest": Path("approved.json"),
        "version_id": 4,
        "admin_id": 7,
        "import_rules": True,
        "publish": True,
    })()
    events = []
    manifest = object()

    monkeypatch.setattr(script, "load_standard_manifest", lambda path: manifest)
    monkeypatch.setattr(
        script,
        "import_manifest_rules",
        lambda db, **kwargs: events.append("import") or object(),
    )
    monkeypatch.setattr(
        script,
        "submit_review_version",
        lambda db, **kwargs: events.append("review") or object(),
    )
    monkeypatch.setattr(
        script,
        "publish_review_version",
        lambda db, **kwargs: events.append("publish") or object(),
    )

    script.execute_changes(object(), args)

    assert events == ["import", "review", "publish"]
