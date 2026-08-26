from types import SimpleNamespace

import pytest

from app.schemas.standard_manifest import StandardManifest
from app.services.standard_manifest_import import import_manifest_rules, plan_manifest_import


def _entry(entry_id, key, *, kind="rule", status="approved", actionability="calculable"):
    entry = {
        "entry_id": entry_id,
        "entry_kind": kind,
        "review_status": status,
        "review_note": "已审核",
        "source": {"table_index": 1, "row_index": 1, "raw_text": f"{key} 7-40 U/L"},
        "indicator": {
            "canonical_key": key,
            "name_en": key.upper(),
            "name_cn": key,
            "aliases": [],
            "domain": "laboratory",
            "specimen_or_modality": "serum",
            "data_type": "numeric",
            "scale_or_method": None,
            "default_unit": "U/L",
            "clinical_dimension": "liver_injury",
            "allows_numeric_comparison": True,
            "abnormal_direction": "high",
        },
        "rule": None,
    }
    if kind == "rule":
        entry["rule"] = {
            "rule_type": "numeric_range",
            "comparator": None,
            "lower": 7,
            "upper": 40,
            "lower_inclusive": True,
            "upper_inclusive": True,
            "unit": "U/L",
            "sex": None,
            "category": "reference",
            "applicability": {},
            "target_state_type": "control",
            "target_state_value": "reference",
            "clinical_dimension": "liver_injury",
            "evidence_type": "standard_table",
            "machine_actionability": actionability,
            "actionability_reason": "逐条审核",
            "interpretation": f"{key} reference",
            "priority": 0,
            "conflict_group": None,
            "framework": None,
            "biomarker_axis": None,
            "biomarker_state": None,
            "stage": None,
            "clinical_function": None,
            "conditions": {},
        }
    return entry


def _manifest(*entries):
    return StandardManifest.model_validate({
        "schema_version": "standard_manifest.v1",
        "dataset": "fatty_liver",
        "disease_name": "脂肪肝",
        "source_document_sha256": "a" * 64,
        "target_version_label": "fatty-v1",
        "review_state": "approved",
        "reviewed_at": "2026-08-25T12:00:00Z",
        "entries": list(entries),
    })


class ImportSession:
    def __init__(self, *, existing_entry_ids=None):
        self.existing_entry_ids = set(existing_entry_ids or ())
        self.added = []
        self.flushes = 0
        self.commits = 0
        self.version = SimpleNamespace(
            id=4,
            status="review",
            standard_id=2,
            rules=[SimpleNamespace(applicability={"_manifest_entry_id": entry_id}) for entry_id in self.existing_entry_ids],
        )

    def query(self, model):
        session = self
        name = model.__name__

        class Query:
            def filter(self, *args, **kwargs):
                return self

            def with_for_update(self):
                return self

            def first(self):
                if name == "ReferenceStandardVersion":
                    return session.version
                return None

            def all(self):
                return []

        return Query()

    def add(self, value):
        self.added.append(value)

    def flush(self):
        self.flushes += 1


@pytest.fixture
def approved_manifest():
    return _manifest(
        _entry("fatty-alt", "alt"),
        _entry("fatty-ast", "ast"),
        _entry("fatty-afp-no-safe-rule", "afp", kind="no_safe_rule"),
        _entry("fatty-plt-rejected", "plt", status="rejected"),
    )


def test_pending_manifest_is_rejected_before_database_mutation(approved_manifest):
    pending = approved_manifest.model_copy(update={"review_state": "pending", "reviewed_at": None})
    db = ImportSession()
    with pytest.raises(ValueError, match="approved"):
        import_manifest_rules(db, manifest=pending, version_id=4, admin_id=7)
    assert db.added == []
    assert db.flushes == 0


def test_import_plan_counts_only_approved_rule_entries(approved_manifest):
    plan = plan_manifest_import(ImportSession(), manifest=approved_manifest, version_id=4)
    assert plan.indicator_keys == ["alt", "ast"]
    assert plan.rule_entry_ids == ["fatty-alt", "fatty-ast"]
    assert plan.skipped_entry_ids == ["fatty-afp-no-safe-rule", "fatty-plt-rejected"]


def test_import_is_idempotent_by_version_and_manifest_entry_id(approved_manifest):
    db = ImportSession(existing_entry_ids={"fatty-alt"})
    result = import_manifest_rules(db, manifest=approved_manifest, version_id=4, admin_id=7)
    assert result.created_rule_entry_ids == ["fatty-ast"]
    assert result.existing_rule_entry_ids == ["fatty-alt"]
    assert db.commits == 0


def test_import_persists_manifest_review_time_for_reviewed_override():
    manifest = _manifest(_entry("fatty-ast", "ast"))
    db = ImportSession()

    import_manifest_rules(db, manifest=manifest, version_id=4, admin_id=7)

    rule = next(item for item in db.added if item.__class__.__name__ == "StandardRule")
    assert rule.applicability["_manifest_entry_id"] == "fatty-ast"
    assert rule.applicability["_manifest_sha256"] == "a" * 64
    assert rule.applicability["_manifest_reviewed_at"] == "2026-08-25T12:00:00+00:00"
