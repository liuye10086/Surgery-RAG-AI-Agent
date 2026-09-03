"""Command-layer and audit transaction contracts for operator cases."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError


def _visit(day="2026-01-01", value=42):
    return SimpleNamespace(
        id=1,
        case_id=3,
        visit_date=date.fromisoformat(day),
        visit_index=1,
        indicators=[{"name": "ALT", "value": value, "unit": "U/L"}],
        notes=None,
    )


def _case():
    return SimpleNamespace(
        id=3,
        user_id=7,
        disease_id=11,
        patient_label="CASE-2345-6789",
        anonymous_case_code="CASE-2345-6789",
        age=56,
        sex="male",
        baseline_stage="pre_cirrhosis",
        notes=None,
        status="active",
        visits=[_visit()],
        disease=SimpleNamespace(
            id=11,
            code="fatty_liver",
            operator_enabled=True,
        ),
    )


def _create_payload(*, visits=None):
    from app.schemas.longitudinal_case import OperatorCaseCreate

    return OperatorCaseCreate(
        disease_id=11,
        age=56,
        sex="male",
        baseline_stage="pre_cirrhosis",
        notes=None,
        visits=visits
        or [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
            }
        ],
    )


def _save_payload(**overrides):
    from app.schemas.operator_case_workspace import OperatorCaseSave

    values = {
        "age": 56,
        "sex": "male",
        "baseline_stage": "pre_cirrhosis",
        "notes": None,
        "visits": [
            {
                "visit_date": "2026-01-01",
                "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}],
            }
        ],
    }
    values.update(overrides)
    return OperatorCaseSave.model_validate(values)


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


def test_idempotency_key_requires_uuid_and_create_hash_is_visit_order_invariant():
    from app.services.operator_case_idempotency import (
        IdempotencyKeyError,
        hash_case_create,
        parse_idempotency_key,
    )

    key = parse_idempotency_key("5f0a6f11-7a08-47dc-9ac8-f7961962bd9d")
    assert str(key) == "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d"
    for invalid in (None, "", "not-a-uuid"):
        with pytest.raises(IdempotencyKeyError):
            parse_idempotency_key(invalid)

    first = _create_payload(
        visits=[
            {"visit_date": "2026-02-01", "indicators": [{"name": "ALT", "value": 43, "unit": "U/L"}]},
            {"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}]},
        ]
    )
    second = _create_payload(visits=list(reversed(first.visits)))
    assert hash_case_create(first) == hash_case_create(second)


def test_existing_idempotency_replay_checks_hash_owner_and_deleted_resource():
    from app.services.operator_case_idempotency import (
        IdempotencyConflictError,
        get_idempotency_replay,
    )

    key = "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d"
    row = SimpleNamespace(request_sha256="a" * 64, resource_id=3)
    case = _case()
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [row, case]
    assert get_idempotency_replay(db, 7, key, "a" * 64) is case

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = row
    with pytest.raises(IdempotencyConflictError) as mismatch:
        get_idempotency_replay(db, 7, key, "b" * 64)
    assert mismatch.value.code == "idempotency_key_reused"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [row, None]
    with pytest.raises(IdempotencyConflictError) as deleted:
        get_idempotency_replay(db, 7, key, "a" * 64)
    assert deleted.value.code == "idempotency_resource_missing"


def test_create_command_commits_case_visits_audit_and_idempotency_once():
    from app.db.models import (
        OperatorCase,
        OperatorCaseChangeLog,
        OperatorCaseVisit,
        OperatorIdempotencyKey,
    )
    from app.services.operator_case_commands import create_operator_case_command

    db = MagicMock()

    def assign_case_id(row):
        if isinstance(row, OperatorCase) and row.id is None:
            row.id = 3

    db.add.side_effect = assign_case_id
    disease = SimpleNamespace(id=11, code="fatty_liver", operator_enabled=True)
    with patch("app.services.operator_case_commands.require_operator_disease", return_value=disease), patch(
        "app.services.operator_case_commands.get_idempotency_replay", return_value=None
    ), patch(
        "app.services.operator_case_commands._generate_unique_anonymous_case_code",
        return_value="CASE-2345-6789",
    ):
        result = create_operator_case_command(
            db,
            7,
            _create_payload(),
            "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
        )

    rows = [call.args[0] for call in db.add.call_args_list]
    assert result.id == 3
    assert any(isinstance(row, OperatorCaseVisit) for row in rows)
    assert any(isinstance(row, OperatorCaseChangeLog) for row in rows)
    assert any(isinstance(row, OperatorIdempotencyKey) for row in rows)
    db.commit.assert_called_once()
    db.rollback.assert_not_called()


def test_create_command_rolls_back_everything_when_audit_fails():
    from app.services.operator_case_commands import create_operator_case_command

    db = MagicMock()
    disease = SimpleNamespace(id=11, code="fatty_liver", operator_enabled=True)
    with patch("app.services.operator_case_commands.require_operator_disease", return_value=disease), patch(
        "app.services.operator_case_commands.get_idempotency_replay", return_value=None
    ), patch(
        "app.services.operator_case_commands._generate_unique_anonymous_case_code",
        return_value="CASE-2345-6789",
    ), patch(
        "app.services.operator_case_commands.append_case_change_log",
        side_effect=RuntimeError("audit failed"),
    ):
        with pytest.raises(RuntimeError, match="audit failed"):
            create_operator_case_command(
                db,
                7,
                _create_payload(),
                "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
            )

    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_concurrent_idempotency_loser_rolls_back_and_returns_winner():
    from app.services.operator_case_commands import create_operator_case_command

    winner = _case()
    db = MagicMock()
    disease = SimpleNamespace(id=11, code="fatty_liver", operator_enabled=True)
    with patch("app.services.operator_case_commands.require_operator_disease", return_value=disease), patch(
        "app.services.operator_case_commands.get_idempotency_replay",
        side_effect=[None, winner],
    ), patch(
        "app.services.operator_case_commands._generate_unique_anonymous_case_code",
        return_value="CASE-2345-6789",
    ), patch(
        "app.services.operator_case_commands.add_idempotency_result",
        side_effect=IntegrityError("unique", {}, Exception("unique")),
    ):
        result = create_operator_case_command(
            db,
            7,
            _create_payload(),
            "5f0a6f11-7a08-47dc-9ac8-f7961962bd9d",
        )

    assert result is winner
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_aggregate_save_noop_writes_nothing_and_requires_no_reason():
    from app.services.operator_case_commands import save_operator_case_command

    case = _case()
    db = MagicMock()
    with patch("app.services.operator_case_commands.get_operator_case_for_write", return_value=case), patch(
        "app.services.operator_case_commands.append_case_change_log"
    ) as audit:
        result = save_operator_case_command(db, 7, 3, _save_payload())

    assert result is case
    audit.assert_not_called()
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_aggregate_save_requires_reason_for_real_change():
    from app.services.operator_case_commands import (
        OperatorCaseCommandError,
        save_operator_case_command,
    )

    db = MagicMock()
    with patch("app.services.operator_case_commands.get_operator_case_for_write", return_value=_case()):
        with pytest.raises(OperatorCaseCommandError) as caught:
            save_operator_case_command(db, 7, 3, _save_payload(age=57))

    assert caught.value.code == "change_reason_required"
    db.commit.assert_not_called()


def test_aggregate_save_applies_profile_timeline_and_one_audit_in_one_commit():
    from app.services.operator_case_commands import save_operator_case_command

    case = _case()
    db = MagicMock()
    payload = _save_payload(
        age=57,
        change_reason="更正年龄并补充复查",
        visits=[
            {"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}]},
            {"visit_date": "2026-02-01", "indicators": [{"name": "AST", "value": 31, "unit": "U/L"}]},
        ],
    )
    with patch("app.services.operator_case_commands.get_operator_case_for_write", return_value=case), patch(
        "app.services.operator_case_commands.replace_case_visits_in_session"
    ) as replace, patch(
        "app.services.operator_case_commands.append_case_change_log"
    ) as audit:
        result = save_operator_case_command(db, 7, 3, payload)

    assert result is case
    assert case.age == 57
    replace.assert_called_once()
    assert audit.call_args.kwargs["action"] == "case_updated"
    assert audit.call_args.kwargs["reason"] == "更正年龄并补充复查"
    db.commit.assert_called_once()


def test_aggregate_save_rolls_back_when_transaction_commit_fails():
    from app.services.operator_case_commands import save_operator_case_command

    db = MagicMock()
    db.commit.side_effect = RuntimeError("database failed")
    with patch("app.services.operator_case_commands.get_operator_case_for_write", return_value=_case()), patch(
        "app.services.operator_case_commands.replace_case_visits_in_session"
    ), patch("app.services.operator_case_commands.append_case_change_log"):
        with pytest.raises(RuntimeError, match="database failed"):
            save_operator_case_command(
                db,
                7,
                3,
                _save_payload(age=57, change_reason="更正年龄"),
            )

    db.rollback.assert_called_once()


def test_delete_command_writes_audit_and_deletes_in_one_commit():
    from app.services.operator_case_commands import delete_operator_case_command

    case = _case()
    db = MagicMock()
    with patch("app.services.operator_case_commands.get_operator_case_for_write", return_value=case), patch(
        "app.services.operator_case_commands.append_case_change_log"
    ) as audit:
        delete_operator_case_command(db, 7, 3)

    assert audit.call_args.kwargs["action"] == "deleted"
    db.delete.assert_called_once_with(case)
    db.commit.assert_called_once()
