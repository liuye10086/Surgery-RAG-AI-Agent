"""Command-layer and audit transaction contracts for operator cases."""

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_append_case_change_log_snapshots_identity_without_committing():
    from app.db.models import OperatorCaseChangeLog
    from app.services.operator_case_audit import append_case_change_log

    db = MagicMock()
    case = SimpleNamespace(id=3, anonymous_case_code="CASE-2345-6789")
    changes = {"profile": {"age": {"before": 56, "after": 57}}}

    log = append_case_change_log(
        db,
        case=case,
        actor_id=7,
        action="profile_updated",
        reason="  更正录入错误  ",
        changes=changes,
    )

    assert isinstance(log, OperatorCaseChangeLog)
    assert log.case_id == 3
    assert log.case_id_snapshot == 3
    assert log.anonymous_case_code_snapshot == "CASE-2345-6789"
    assert log.actor_id == 7
    assert log.actor_id_snapshot == 7
    assert log.reason == "更正录入错误"
    assert log.changes == changes
    db.add.assert_called_once_with(log)
    db.flush.assert_called_once()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_creation_and_deletion_audit_payloads_are_privacy_bounded():
    from app.services.operator_case_audit import (
        build_creation_changes,
        build_deletion_changes,
    )

    case = SimpleNamespace(
        disease_id=11,
        baseline_stage="pre_cirrhosis",
        patient_label="private-label",
        age=56,
        sex="male",
    )

    created = build_creation_changes(case, visit_count=1)
    deleted = build_deletion_changes()

    assert created == {
        "created": {
            "disease_id": 11,
            "baseline_stage": "pre_cirrhosis",
            "visit_count": 1,
            "profile_fields": ["age", "sex", "baseline_stage", "notes"],
        }
    }
    assert deleted == {"deleted": {"before": True, "after": False}}
