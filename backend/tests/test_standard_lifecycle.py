from types import SimpleNamespace

import pytest

from app.schemas.standard import RulePatch
from app.services.standard_lifecycle import ImmutableVersionError, update_draft_rule
from app.services.standard_lifecycle import (
    materialize_candidate_rule,
    publish_approved_version,
    seed_standard_draft,
    transition_version,
)


def test_approved_rule_cannot_be_edited():
    rule = SimpleNamespace(
        id=1,
        version_id=2,
        version=SimpleNamespace(status="approved"),
    )

    class Query:
        def __init__(self, value):
            self.value = value

        def get(self, _id):
            return self.value

        def filter(self, *_conditions):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return self.value

    db = SimpleNamespace(
        query=lambda model: Query(
            rule if model.__name__ == "StandardRule" else rule.version
        )
    )
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
        def __init__(self, value):
            self.value = value

        def get(self, _id):
            return self.value

        def filter(self, *_conditions):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return self.value

    class Session:
        def query(self, model):
            value = rule if model.__name__ == "StandardRule" else rule.version
            return Query(value)

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


def test_rule_edit_locks_owning_version_before_commit():
    rule = SimpleNamespace(
        id=1,
        version_id=2,
        version=SimpleNamespace(status="review"),
        upper=1.0,
        indicator_id=None,
        rule_type="threshold",
        machine_actionability="calculable",
    )
    version = SimpleNamespace(id=2, status="review")
    events = []

    class Query:
        def __init__(self, value, model_name):
            self.value = value
            self.model_name = model_name

        def get(self, _id):
            events.append(f"{self.model_name}:get")
            return self.value

        def filter(self, *_conditions):
            events.append(f"{self.model_name}:filter")
            return self

        def populate_existing(self):
            events.append(f"{self.model_name}:populate_existing")
            return self

        def with_for_update(self):
            events.append(f"{self.model_name}:with_for_update")
            return self

        def first(self):
            events.append(f"{self.model_name}:first")
            return self.value

    class Session:
        def query(self, model):
            model_name = model.__name__
            value = rule if model_name == "StandardRule" else version
            return Query(value, model_name)

        def add(self, _value):
            return None

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    update_draft_rule(Session(), 10, 1, RulePatch(upper=2.0), "修正原文边界")

    assert events == [
        "StandardRule:get",
        "ReferenceStandardVersion:filter",
        "ReferenceStandardVersion:populate_existing",
        "ReferenceStandardVersion:with_for_update",
        "ReferenceStandardVersion:first",
        "StandardRule:filter",
        "StandardRule:populate_existing",
        "StandardRule:first",
        "commit",
    ]


def test_rule_edit_checks_status_from_locked_owning_version():
    rule = SimpleNamespace(
        id=1,
        version_id=2,
        version=SimpleNamespace(status="draft"),
    )
    locked_version = SimpleNamespace(id=2, status="approved")

    class Query:
        def __init__(self, value):
            self.value = value

        def get(self, _id):
            return self.value

        def filter(self, *_conditions):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return self.value

    class Session:
        def query(self, model):
            value = rule if model.__name__ == "StandardRule" else locked_version
            return Query(value)

        def add(self, _value):
            return None

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    with pytest.raises(ImmutableVersionError, match="已批准或已退役版本不可编辑"):
        update_draft_rule(Session(), 10, 1, RulePatch(upper=2.0), "校正边界")


def test_rule_edit_uses_fresh_rule_after_locking_version():
    stale_probe = SimpleNamespace(
        id=1,
        version_id=2,
        upper=1.0,
        indicator_id=None,
        rule_type="threshold",
        machine_actionability="calculable",
    )
    fresh_rule = SimpleNamespace(
        id=1,
        version_id=2,
        upper=5.0,
        indicator_id=None,
        rule_type="threshold",
        machine_actionability="calculable",
    )
    locked_version = SimpleNamespace(id=2, status="review")
    values = {
        "StandardRule": [stale_probe, fresh_rule],
        "ReferenceStandardVersion": [locked_version],
    }
    events = []
    logs = []

    class Query:
        def __init__(self, value, model_name):
            self.value = value
            self.model_name = model_name

        def get(self, _id):
            events.append(f"{self.model_name}:get")
            return self.value

        def filter(self, *_conditions):
            events.append(f"{self.model_name}:filter")
            return self

        def populate_existing(self):
            events.append(f"{self.model_name}:populate_existing")
            return self

        def with_for_update(self):
            events.append(f"{self.model_name}:with_for_update")
            return self

        def first(self):
            events.append(f"{self.model_name}:first")
            return self.value

    class Session:
        def query(self, model):
            model_name = model.__name__
            return Query(values[model_name].pop(0), model_name)

        def add(self, value):
            logs.append(value)

        def commit(self):
            events.append("commit")

        def refresh(self, _value):
            return None

    result = update_draft_rule(
        Session(),
        10,
        1,
        RulePatch(upper=7.0),
        "修正并发期间更新的边界",
    )

    assert result is fresh_rule
    assert stale_probe.upper == 1.0
    assert fresh_rule.upper == 7.0
    assert logs[0].before_json["upper"] == 5.0
    assert logs[0].after_json["upper"] == 7.0
    assert events.index("ReferenceStandardVersion:with_for_update") < events.index(
        "StandardRule:filter"
    )


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
    standard = SimpleNamespace(current_version=old, current_version_id=old.id)
    version = SimpleNamespace(
        id=2,
        status="review",
        standard_id=3,
        standard=standard,
        rules=[rule, evidence],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )
    added = []

    class Query:
        def __init__(self, value):
            self.value = value
            self.events = []
        def filter(self, *args, **kwargs):
            self.events.append("filter")
            return self
        def populate_existing(self):
            self.events.append("populate_existing")
            return self
        def with_for_update(self):
            self.events.append("with_for_update")
            return self
        def first(self):
            self.events.append("first")
            return self.value

    class Session:
        def __init__(self):
            self.queries = []
            self.version_queries = 0
        def query(self, model):
            name = getattr(model, "__name__", "")
            if name == "ReferenceStandardVersion":
                self.version_queries += 1
                value = version
            else:
                value = standard
            query = Query(value)
            self.queries.append(query)
            return query
        def add(self, value):
            added.append(value)
        def commit(self):
            return None
        def refresh(self, value):
            return None

    session = Session()
    result = publish_approved_version(session, 10, 2)
    assert result.version.status == "approved"
    assert old.status == "retired"
    assert len(result.projections) == 1
    assert result.projections[0].standard_rule_id == 7
    assert session.queries[0].events == ["filter", "first"]
    assert session.queries[1].events == [
        "filter",
        "populate_existing",
        "with_for_update",
        "first",
    ]
    assert session.queries[2].events == [
        "filter",
        "populate_existing",
        "with_for_update",
        "first",
    ]


def test_publish_locks_standard_before_rereading_target_version(monkeypatch):
    from app.services import standard_lifecycle

    monkeypatch.setattr(
        standard_lifecycle,
        "validate_version_rules",
        lambda _rules: SimpleNamespace(can_publish=True),
    )
    standard = SimpleNamespace(id=3, current_version=None, current_version_id=None)
    probe_version = SimpleNamespace(
        id=2,
        standard_id=3,
        standard=standard,
        status="review",
        rules=[],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )
    locked_version = SimpleNamespace(
        id=2,
        standard_id=3,
        standard=standard,
        status="review",
        rules=[],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )
    values = {
        "ReferenceStandardVersion": [probe_version, locked_version],
        "ReferenceStandard": [standard],
    }
    events = []

    class Query:
        def __init__(self, model_name, value):
            self.model_name = model_name
            self.value = value

        def filter(self, *_conditions):
            events.append(f"{self.model_name}:filter")
            return self

        def populate_existing(self):
            events.append(f"{self.model_name}:populate_existing")
            return self

        def with_for_update(self):
            events.append(f"{self.model_name}:with_for_update")
            return self

        def first(self):
            events.append(f"{self.model_name}:first")
            return self.value

    class Session:
        def query(self, model):
            model_name = model.__name__
            events.append(f"query:{model_name}")
            return Query(model_name, values[model_name].pop(0))

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    result = publish_approved_version(Session(), 10, 2)

    assert [event for event in events if event.startswith("query:")] == [
        "query:ReferenceStandardVersion",
        "query:ReferenceStandard",
        "query:ReferenceStandardVersion",
    ]
    assert events.index("ReferenceStandard:populate_existing") < events.index(
        "ReferenceStandard:with_for_update"
    )
    assert events.index("ReferenceStandard:with_for_update") < events.index(
        "ReferenceStandardVersion:with_for_update"
    )
    assert events.index("ReferenceStandardVersion:populate_existing") < events.index(
        "ReferenceStandardVersion:with_for_update"
    )
    assert result.version is locked_version
    assert locked_version.status == "approved"
    assert probe_version.status == "review"


def test_legacy_publish_entry_uses_ad_evidence_only_exception():
    evidence = SimpleNamespace(
        id=8,
        machine_actionability="evidence-only",
        rule_type="qualitative_direction",
        lower=None,
        upper=None,
        unit=None,
        applicability={},
        conditions={},
        target_state_type="evidence",
        clinical_dimension="cognition",
        framework=None,
        biomarker_axis=None,
        stage=None,
        indicator=SimpleNamespace(
            canonical_key="mmse",
            abnormal_direction="ordinal_low",
            allows_numeric_comparison=False,
        ),
        source_segment=None,
    )
    standard = SimpleNamespace(
        id=3,
        current_version=None,
        current_version_id=None,
        disease=SimpleNamespace(code="ad", name="AD（展示名已修改）"),
    )
    version = SimpleNamespace(
        id=2,
        standard_id=3,
        standard=standard,
        status="review",
        rules=[evidence],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )

    class Query:
        def __init__(self, value): self.value = value
        def filter(self, *args, **kwargs): return self
        def populate_existing(self): return self
        def with_for_update(self): return self
        def first(self): return self.value

    class Session:
        def query(self, model):
            return Query(version if model.__name__ == "ReferenceStandardVersion" else standard)
        def add(self, value): return None
        def commit(self): return None
        def rollback(self): raise AssertionError("successful publication must not roll back")
        def refresh(self, value): return None

    result = publish_approved_version(Session(), 10, 2)

    assert result.version.status == "approved"
    assert result.projections == []


def test_transition_to_approved_uses_ad_evidence_only_exception():
    evidence = SimpleNamespace(
        machine_actionability="evidence-only",
        rule_type="qualitative_direction",
        lower=None,
        upper=None,
        unit=None,
        applicability={},
        conditions={},
        target_state_type="evidence",
        clinical_dimension="cognition",
        framework=None,
        biomarker_axis=None,
        stage=None,
        indicator=SimpleNamespace(
            canonical_key="mmse",
            abnormal_direction="ordinal_low",
            allows_numeric_comparison=False,
        ),
        source_segment=None,
    )
    version = SimpleNamespace(
        id=2,
        status="review",
        rules=[evidence],
        standard=SimpleNamespace(
            disease=SimpleNamespace(code="ad", name="AD（展示名已修改）")
        ),
        approved_by=None,
        approved_at=None,
        effective_from=None,
        retired_at=None,
    )

    class Query:
        def filter(self, *args, **kwargs): return self
        def with_for_update(self): return self
        def first(self): return version

    class Session:
        def query(self, model): return Query()
        def commit(self): return None
        def refresh(self, value): return None

    result = transition_version(Session(), 10, 2, "approved")

    assert result.status == "approved"


def test_submit_review_version_is_transaction_neutral_when_commit_is_false():
    from app.services import standard_lifecycle

    assert hasattr(standard_lifecycle, "submit_review_version")
    submit_review_version = standard_lifecycle.submit_review_version
    version = SimpleNamespace(id=2, status="draft")

    class Query:
        def filter(self, *args, **kwargs): return self
        def with_for_update(self): return self
        def first(self): return version

    class Session:
        commits = 0
        flushes = 0
        def query(self, model): return Query()
        def flush(self): self.flushes += 1
        def commit(self): self.commits += 1
        def refresh(self, value): return None

    db = Session()
    result = submit_review_version(db, version_id=2, commit=False)

    assert result.status == "review"
    assert db.flushes == 1
    assert db.commits == 0


def test_transition_version_locks_row_before_status_transition():
    version = SimpleNamespace(
        id=2,
        status="draft",
        approved_by=None,
        approved_at=None,
        effective_from=None,
        retired_at=None,
    )

    class Query:
        def __init__(self):
            self.events = []

        def filter(self, *conditions):
            self.events.append("filter")
            return self

        def with_for_update(self):
            self.events.append("with_for_update")
            return self

        def first(self):
            self.events.append("first")
            return version

        def get(self, _version_id):
            self.events.append("get")
            return version

    class Session:
        def __init__(self):
            self.query_result = Query()

        def query(self, _model):
            return self.query_result

        def commit(self):
            return None

        def refresh(self, _value):
            return None

    session = Session()

    transition_version(session, 10, 2, "review")

    assert session.query_result.events[:3] == ["filter", "with_for_update", "first"]


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


class _AtomicLifecycleSession:
    def __init__(self, commit_error=None):
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.events = []
        self.candidate = SimpleNamespace(
            id=5,
            version_id=2,
            segment_id=8,
            status="accepted",
            candidate_json={"indicator_name": "ALT", "rule_type": "numeric_range", "numeric": {"upper": 40, "unit": "U/L"}},
        )
        self.version = SimpleNamespace(id=2, status="draft")

    def query(self, model):
        name = model.__name__
        session = self

        class Query:
            def get(self, _id):
                session.events.append(f"{name}:get")
                return session.candidate

            def filter(self, *args, **kwargs):
                session.events.append(f"{name}:filter")
                return self

            def populate_existing(self):
                session.events.append(f"{name}:populate_existing")
                return self

            def with_for_update(self):
                session.events.append(f"{name}:with_for_update")
                return self

            def first(self):
                session.events.append(f"{name}:first")
                return session.version if name == "ReferenceStandardVersion" else session.candidate

        return Query()

    def add(self, _value):
        self.events.append("add")

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, _value):
        return None


def test_materialize_candidate_locks_version_and_updates_candidate_in_one_commit():
    from app.services.standard_lifecycle import materialize_candidate

    db = _AtomicLifecycleSession()
    rule = materialize_candidate(db, candidate_id=5, admin_id=10, reason="逐条审核通过")
    assert rule.version_id == 2
    assert db.candidate.status == "materialized"
    assert db.commits == 1
    assert db.rollbacks == 0
    assert db.events.index("ReferenceStandardVersion:with_for_update") < db.events.index("StandardParseCandidate:with_for_update")


def test_materialize_candidate_rolls_back_rule_and_status_together():
    from app.services.standard_lifecycle import materialize_candidate

    db = _AtomicLifecycleSession(commit_error=RuntimeError("commit failed"))
    with pytest.raises(RuntimeError, match="commit failed"):
        materialize_candidate(db, candidate_id=5, admin_id=10, reason="审核通过")
    assert db.rollbacks == 1


def test_publish_rejects_zero_calculable_rules_before_mutation(monkeypatch):
    report = SimpleNamespace(can_publish=False, errors=[SimpleNamespace(code="calculable_rules_missing")])
    monkeypatch.setattr("app.services.standard_lifecycle.validate_version_rules", lambda *args, **kwargs: report)
    from app.services.standard_lifecycle import publish_review_version

    version = SimpleNamespace(id=2, standard_id=3, status="review", rules=[])
    standard = SimpleNamespace(id=3, current_version=None)

    class PublishSession:
        commits = 0
        mutations = []

        def query(self, model):
            value = version if model.__name__ == "ReferenceStandardVersion" else standard

            class Query:
                def filter(self, *args, **kwargs): return self
                def populate_existing(self): return self
                def with_for_update(self): return self
                def first(self): return value

            return Query()

    db = PublishSession()
    with pytest.raises(ValueError, match="校验错误"):
        publish_review_version(db, version_id=2, admin_id=10)
    assert db.commits == 0
    assert db.mutations == []


def test_publish_allows_ad_evidence_only_version_and_creates_no_projection():
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
        conditions={},
        target_state_type="evidence",
        clinical_dimension="cognition",
        framework=None,
        biomarker_axis=None,
        stage=None,
        indicator=SimpleNamespace(
            canonical_key="mmse",
            name_en="MMSE",
            name_cn="简易精神状态检查",
            abnormal_direction="ordinal_low",
        ),
        source_segment=None,
    )
    standard = SimpleNamespace(
        id=3,
        current_version=None,
        current_version_id=None,
        disease=SimpleNamespace(code="ad", name="AD（展示名已修改）"),
    )
    version = SimpleNamespace(
        id=2,
        standard_id=3,
        status="review",
        rules=[evidence],
        approved_by=None,
        approved_at=None,
        effective_from=None,
    )
    added = []

    class Query:
        def __init__(self, value):
            self.value = value
        def filter(self, *args, **kwargs): return self
        def populate_existing(self): return self
        def with_for_update(self): return self
        def first(self): return self.value

    class Session:
        def query(self, model):
            return Query(version if model.__name__ == "ReferenceStandardVersion" else standard)
        def add(self, value): added.append(value)
        def flush(self): return None
        def commit(self): return None
        def refresh(self, value): return None
        def rollback(self): raise AssertionError("successful publication must not roll back")

    from app.services.standard_lifecycle import publish_review_version

    result = publish_review_version(Session(), version_id=2, admin_id=10)

    assert result.version.status == "approved"
    assert result.projections == []
    assert standard.current_version_id == 2


def test_retire_current_version_clears_pointer_and_disables_projection():
    from app.services.standard_lifecycle import retire_current_version

    version = SimpleNamespace(id=2, status="approved", retired_at=None, standard_id=3)
    standard = SimpleNamespace(id=3, current_version=version, current_version_id=2)
    projections = [SimpleNamespace(is_current_projection=True)]
    logs = []

    class Query:
        def __init__(self, value):
            self.value = value

        def filter(self, *args, **kwargs):
            return self

        def populate_existing(self):
            return self

        def with_for_update(self):
            return self

        def first(self):
            return self.value

        def update(self, values, synchronize_session=False):
            for projection in projections:
                projection.is_current_projection = values["is_current_projection"]

    class Session:
        commits = 0

        def query(self, model):
            name = model.__name__
            if name == "ReferenceStandard":
                return Query(standard)
            if name == "ReferenceStandardVersion":
                return Query(version)
            return Query(projections)

        def add(self, value):
            logs.append(value)

        def commit(self):
            self.commits += 1

        def refresh(self, _value):
            return None

    result = retire_current_version(Session(), version_id=2, admin_id=10)
    assert result.status == "retired"
    assert result.retired_at is not None
    assert standard.current_version_id is None
    assert standard.current_version is None
    assert all(not item.is_current_projection for item in projections)


class _SeedQuery:
    def __init__(self, value):
        self.value = value
        self.events = []

    def filter(self, *conditions):
        self.events.append("filter")
        return self

    def with_for_update(self):
        self.events.append("with_for_update")
        return self

    def first(self):
        self.events.append("first")
        return self.value


class _SeedDb:
    def __init__(self, values):
        self.values = {name: list(items) for name, items in values.items()}
        self.added = []
        self.commits = 0
        self.flushes = 0
        self.queries = []

    def query(self, model):
        values = self.values.get(model.__name__, [])
        query = _SeedQuery(values.pop(0) if values else None)
        self.queries.append((model.__name__, query))
        return query

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = len(self.added) + 20
        self.added.append(value)

    def commit(self):
        self.commits += 1

    def flush(self):
        self.flushes += 1

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
    assert db.queries[0][0] == "Disease"
    assert db.queries[0][1].events[:3] == ["filter", "with_for_update", "first"]
    assert db.queries[1][0] == "StandardDocument"
    assert db.queries[1][1].events[:3] == ["filter", "with_for_update", "first"]


def test_seed_new_standard_keeps_parent_locks_until_version_commit(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    disease = SimpleNamespace(id=2, name="阿尔茨海默病")
    document = SimpleNamespace(
        id=9,
        file_path=str(source),
        file_type="docx",
        content_hash="c" * 64,
        version=None,
    )
    db = _SeedDb({
        "Disease": [disease],
        "StandardDocument": [document],
        "ReferenceStandard": [None],
    })

    version = seed_standard_draft(db, 2, 9, "AD-2026-08", admin_id=7)

    assert version.standard_document_id == document.id
    assert db.flushes == 1
    assert db.commits == 1


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
