from types import SimpleNamespace

import pytest

from app.schemas.standard import RulePatch
from app.services.standard_lifecycle import ImmutableVersionError, update_draft_rule


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
