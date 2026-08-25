from types import SimpleNamespace

import pytest

from app.schemas.standard import RulePatch
from app.services.standard_lifecycle import ImmutableVersionError, update_draft_rule
from app.services.standard_lifecycle import publish_approved_version, materialize_candidate_rule, seed_standard_draft


def test_approved_rule_cannot_be_edited():
    db = SimpleNamespace()
    rule = SimpleNamespace(
        id=1,
        version=SimpleNamespace(status="approved"),
    )
    db.query = lambda model: SimpleNamespace(get=lambda _id: rule)
    with pytest.raises(ImmutableVersionError):
        update_draft_rule(db, 10, 1, RulePatch(upper=2), "校正边界")


def test_rule_edit_writes_before_after_and_reason():
    rule = SimpleNamespace(
        id=1,
        version_id=2,
        version=SimpleNamespace(status="draft"),
        upper=1.0,
        indicator_id=None,
        rule_type="threshold",
        machine_actionability="calculable",
    )
    logs = []

    class Query:
        def get(self, _id):
            return rule

    class Session:
        def query(self, _model):
            return Query()

        def add(self, value):
            logs.append(value)

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    result = update_draft_rule(Session(), 10, 1, RulePatch(upper=2.0), "修正原文边界")
    assert result.upper == 2.0
    assert logs[0].before_json["upper"] == 1.0
    assert logs[0].after_json["upper"] == 2.0
    assert logs[0].reason == "修正原文边界"


def test_publish_retires_previous_version_and_projects_only_calculable_rules():
    old = SimpleNamespace(id=1, status="approved")
    rule = SimpleNamespace(
        id=7,
        machine_actionability="calculable",
        rule_type="numeric_range",
        unit="U/L",
        lower=9.0,
        upper=50.0,
        lower_inclusive=True,
        upper_inclusive=True,
        sex="male",
        category=None,
        applicability={"lab": "A"},
        indicator=SimpleNamespace(canonical_key="alt", name_en="ALT", name_cn="谷丙转氨酶"),
    )
    evidence = SimpleNamespace(
        id=8,
        machine_actionability="evidence-only",
        rule_type="qualitative_direction",
        unit=None,
        lower=None,
        upper=None,
        lower_inclusive=True,
        upper_inclusive=True,
        sex=None,
        category=None,
        applicability={},
        indicator=SimpleNamespace(canonical_key="alt", name_en="ALT", name_cn="谷丙转氨酶"),
    )
    version = SimpleNamespace(
        id=2,
        status="review",
        standard_id=3,
        standard=SimpleNamespace(current_version=old),
        rules=[rule, evidence],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )
    added = []

    class Query:
        def __init__(self, value):
            self.value = value
        def filter(self, *args, **kwargs):
            return self
        def first(self):
            return self.value

    class Session:
        def query(self, model):
            name = getattr(model, "__name__", "")
            return Query(version if name == "ReferenceStandardVersion" else None)
        def add(self, value):
            added.append(value)
        def commit(self):
            return None
        def refresh(self, value):
            return None

    result = publish_approved_version(Session(), 10, 2)
    assert result.version.status == "approved"
    assert old.status == "retired"
    assert len(result.projections) == 1
    assert result.projections[0].standard_rule_id == 7


def test_materialize_candidate_creates_rule_from_reviewed_candidate():
    candidate = SimpleNamespace(
        id=5,
        version_id=2,
        segment_id=8,
        status="accepted",
        candidate_json={
            "indicator_name": "ALT",
            "rule_type": "numeric_range",
            "target_state_type": "reference",
            "machine_actionability": "calculable",
            "evidence_type": "standard_table",
            "numeric": {"lower": 7, "upper": 40, "lower_inclusive": True, "upper_inclusive": True, "unit": "U/L"},
            "applicability": {},
        },
    )
    added = []
    class Query:
        def filter(self, *args, **kwargs): return self
        def first(self): return None
    class Session:
        def query(self, model): return Query()
        def add(self, value): added.append(value)
        def commit(self): pass
        def refresh(self, value): pass
    result = materialize_candidate_rule(Session(), candidate, admin_id=10, reason="审核通过")
    assert result.rule_type == "numeric_range"
    assert result.upper == 40
    assert result.machine_actionability == "calculable"
    assert added


class _SeedQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *conditions):
        return self

    def first(self):
        return self.value


class _SeedDb:
    def __init__(self, values):
        self.values = {name: list(items) for name, items in values.items()}
        self.added = []
        self.commits = 0

    def query(self, model):
        values = self.values.get(model.__name__, [])
        return _SeedQuery(values.pop(0) if values else None)

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = len(self.added) + 20
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def refresh(self, value):
        return None


def test_seed_standard_draft_uses_standard_document_id_and_stored_hash(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"different bytes")
    disease = SimpleNamespace(id=2, name="阿尔茨海默病")
    standard = SimpleNamespace(id=4, disease_id=2, current_version_id=3, versions=[])
    document = SimpleNamespace(
        id=9,
        file_path=str(source),
        file_type=".DOCX",
        content_hash="c" * 64,
        version=None,
    )
    db = _SeedDb({
        "Disease": [disease],
        "StandardDocument": [document],
        "ReferenceStandard": [standard],
    })

    version = seed_standard_draft(db, 2, 9, "AD-2026-08", admin_id=7)

    assert version.standard_id == 4
    assert version.standard_document_id == 9
    assert version.content_hash == "c" * 64
    assert version.created_by == 7
    assert version.supersedes_version_id == 3
    assert version.status == "draft"


def test_seed_standard_draft_returns_same_disease_association(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    associated = SimpleNamespace(
        id=5,
        standard=SimpleNamespace(id=4, disease_id=2),
    )
    document = SimpleNamespace(
        id=9,
        file_path=str(source),
        file_type="docx",
        content_hash="a" * 64,
        version=associated,
    )
    db = _SeedDb({
        "Disease": [SimpleNamespace(id=2, name="阿尔茨海默病")],
        "StandardDocument": [document],
    })

    assert seed_standard_draft(db, 2, 9, "AD-2026-08") is associated
    assert db.added == []


def test_seed_standard_draft_rejects_other_version_association(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    associated = SimpleNamespace(
        id=5,
        standard=SimpleNamespace(id=8, disease_id=3),
    )
    document = SimpleNamespace(
        id=9,
        file_path=str(source),
        file_type="docx",
        content_hash="a" * 64,
        version=associated,
    )
    db = _SeedDb({
        "Disease": [SimpleNamespace(id=2, name="阿尔茨海默病")],
        "StandardDocument": [document],
    })

    with pytest.raises(ValueError, match="标准文档已关联其他版本"):
        seed_standard_draft(db, 2, 9, "AD-2026-08")
