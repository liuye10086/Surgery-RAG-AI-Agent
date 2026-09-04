import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.standard_source_binding import (
    SourceBindingPlan,
    StandardSourceBindingError,
    apply_current_standard_bindings,
    plan_current_standard_bindings,
    resolve_manifest_source_segment,
)
from app.schemas.standard_manifest import SourceLocator


def load_script():
    spec = importlib.util.spec_from_file_location(
        "bind_standard_rule_sources", ROOT / "scripts/bind_standard_rule_sources.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def fake_session():
    transaction = type("Transaction", (), {"rollbacks": 0, "commits": 0})()
    transaction.rollback = lambda: setattr(transaction, "rollbacks", transaction.rollbacks + 1)
    transaction.commit = lambda: setattr(transaction, "commits", transaction.commits + 1)
    transaction.close = lambda: None
    return transaction


def test_cli_defaults_to_dry_run(monkeypatch, capsys):
    module = load_script()
    transaction = fake_session()
    plan = SourceBindingPlan(
        dataset="ad", version_id=4, total_rules=8, to_bind=((30, 213),), consistent=7
    )
    monkeypatch.setattr(module, "SessionLocal", lambda: transaction)
    monkeypatch.setattr(module, "build_plan", lambda *_: plan)

    assert module.main(["--standard", "ad"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "consistent": 7,
        "dataset": "ad",
        "status": "dry_run",
        "to_bind": 1,
        "total_rules": 8,
        "version_id": 4,
    }
    assert transaction.commits == 0
    assert transaction.rollbacks == 1


def test_apply_rolls_back_on_existing_source_conflict(monkeypatch, capsys):
    module = load_script()
    transaction = fake_session()
    monkeypatch.setattr(module, "SessionLocal", lambda: transaction)
    monkeypatch.setattr(
        module,
        "build_plan",
        lambda *_: (_ for _ in ()).throw(
            StandardSourceBindingError("source_binding_conflict")
        ),
    )

    assert module.main(["--standard", "fatty_liver", "--apply"]) == 1

    assert transaction.rollbacks == 1
    assert transaction.commits == 0
    assert json.loads(capsys.readouterr().out) == {
        "error": "source_binding_conflict",
        "status": "blocked",
    }


def test_apply_updates_locked_empty_rules_without_committing():
    first_rule = type("Rule", (), {"id": 30, "version_id": 4, "source_segment_id": None})()
    second_rule = type("Rule", (), {"id": 31, "version_id": 4, "source_segment_id": None})()
    rules = {30: first_rule, 31: second_rule}

    class Query:
        def filter(self, *criteria):
            self.rule_id = criteria[0].right.value
            return self

        def with_for_update(self):
            return self

        def first(self):
            return rules[self.rule_id]

    class Session:
        commits = 0

        def query(self, _model):
            return Query()

        def commit(self):
            self.commits += 1

    plan = SourceBindingPlan(
        dataset="ad", version_id=4, total_rules=2,
        to_bind=((30, 213), (31, 214)), consistent=0,
    )

    db = Session()
    applied = apply_current_standard_bindings(db, plan)

    assert first_rule.source_segment_id == 213
    assert second_rule.source_segment_id == 214
    assert applied.to_bind == ()
    assert applied.consistent == 2
    assert db.commits == 0


def test_resolver_rejects_same_text_at_a_different_manifest_location():
    source = SourceLocator(table_index=3, row_index=3, raw_text="source text")
    correct = type("Segment", (), {
        "id": 213, "version_id": 4, "paragraph_index": None,
        "table_index": 3, "row_index": 3, "column_index": None,
        "raw_text": "source text",
    })()
    wrong_column = type("Segment", (), {
        "id": 214, "version_id": 4, "paragraph_index": None,
        "table_index": 3, "row_index": 3, "column_index": 2,
        "raw_text": "source text",
    })()

    class Query:
        def filter(self, *_criteria):
            return self

        def all(self):
            return [correct, wrong_column]

    class Session:
        def query(self, _model):
            return Query()

    resolved = resolve_manifest_source_segment(Session(), version_id=4, source=source)

    assert resolved.id == 213


def test_repair_plan_rejects_document_file_hash_drift(monkeypatch, tmp_path):
    document_path = tmp_path / "standard.txt"
    document_path.write_bytes(b"changed content")
    manifest_hash = "a" * 64
    source = SourceLocator(table_index=3, row_index=3, raw_text="source text")
    manifest = type("Manifest", (), {
        "dataset": "ad",
        "review_state": "approved",
        "target_version_label": "2026.1",
        "source_document_sha256": manifest_hash,
        "entries": [type("Entry", (), {
            "entry_id": "ad-rule",
            "entry_kind": "rule",
            "review_status": "approved",
            "source": source,
        })()],
    })()
    version = type("Version", (), {
        "id": 4,
        "status": "approved",
        "version_label": "2026.1",
        "content_hash": manifest_hash,
        "standard_document": type("Document", (), {
            "content_hash": manifest_hash,
            "file_path": str(document_path),
        })(),
        "rules": [],
    })()
    monkeypatch.setattr(
        "app.services.standard_source_binding.load_standard_manifest", lambda _path: manifest
    )
    monkeypatch.setattr(
        "app.services.standard_source_binding._current_approved_version", lambda _db, _dataset: version
    )

    with pytest.raises(StandardSourceBindingError) as caught:
        plan_current_standard_bindings(object(), "ad")

    assert caught.value.code == "manifest_document_hash_mismatch"


@pytest.mark.parametrize(
    "source",
    [
        SourceLocator(document_absence_terms=["missing source"]),
        SourceLocator(table_index=3, row_index=3, raw_text=" \t\n"),
    ],
)
def test_resolver_rejects_missing_or_whitespace_source_text_before_any_query_or_write(source):
    empty_segment = type("Segment", (), {
        "id": 213, "version_id": 4, "paragraph_index": None,
        "table_index": None, "row_index": None, "column_index": None,
        "raw_text": "",
    })()

    class Query:
        def filter(self, *_criteria):
            return self

        def all(self):
            return [empty_segment]

    class Session:
        commits = 0
        queries = 0

        def query(self, _model):
            self.queries += 1
            return Query()

        def commit(self):
            self.commits += 1

    db = Session()
    with pytest.raises(StandardSourceBindingError) as caught:
        resolve_manifest_source_segment(db, version_id=4, source=source)

    assert caught.value.code == "source_segment_missing"
    assert db.queries == 0
    assert db.commits == 0


def test_apply_commits_once_and_a_repeat_reports_zero_writes(monkeypatch, capsys):
    module = load_script()
    first_transaction = fake_session()
    repeated_transaction = fake_session()
    transactions = iter((first_transaction, repeated_transaction))
    initial = SourceBindingPlan(
        dataset="ad", version_id=4, total_rules=2, to_bind=((30, 213),), consistent=1
    )
    repeated = SourceBindingPlan(
        dataset="ad", version_id=4, total_rules=2, to_bind=(), consistent=2
    )
    plans = iter((initial, repeated))
    writes = []
    monkeypatch.setattr(module, "SessionLocal", lambda: next(transactions))
    monkeypatch.setattr(module, "build_plan", lambda *_: next(plans))
    monkeypatch.setattr(
        module,
        "apply_current_standard_bindings",
        lambda _db, plan: writes.extend(plan.to_bind) or SourceBindingPlan(
            dataset=plan.dataset, version_id=plan.version_id, total_rules=plan.total_rules,
            to_bind=(), consistent=plan.total_rules,
        ),
    )

    assert module.main(["--standard", "ad", "--apply"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert module.main(["--standard", "ad", "--apply"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first_transaction.commits == 1
    assert repeated_transaction.commits == 1
    assert writes == [(30, 213)]
    assert first["bound"] == 1
    assert second["bound"] == 0
    assert second["to_bind"] == 0


def test_apply_conflict_rolls_back_every_staged_binding(monkeypatch, capsys):
    module = load_script()
    first_rule = type("Rule", (), {"id": 30, "version_id": 4, "source_segment_id": None})()
    second_rule = type("Rule", (), {"id": 31, "version_id": 4, "source_segment_id": 999})()
    rules = {30: first_rule, 31: second_rule}

    class Query:
        def filter(self, *criteria):
            self.rule_id = criteria[0].right.value
            return self

        def with_for_update(self):
            return self

        def first(self):
            return rules[self.rule_id]

    class Transaction:
        commits = 0
        rollbacks = 0

        def query(self, _model):
            return Query()

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1
            first_rule.source_segment_id = None

        def close(self):
            return None

    transaction = Transaction()
    plan = SourceBindingPlan(
        dataset="ad", version_id=4, total_rules=2,
        to_bind=((30, 213), (31, 214)), consistent=0,
    )
    monkeypatch.setattr(module, "SessionLocal", lambda: transaction)
    monkeypatch.setattr(module, "build_plan", lambda *_: plan)

    assert module.main(["--standard", "ad", "--apply"]) == 1

    assert transaction.commits == 0
    assert transaction.rollbacks == 1
    assert first_rule.source_segment_id is None
    assert json.loads(capsys.readouterr().out) == {
        "error": "source_binding_conflict",
        "status": "blocked",
    }
