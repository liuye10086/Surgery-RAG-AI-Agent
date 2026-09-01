from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.db.models import Disease
from app.schemas.prediction import DiseaseCreate, DiseaseUpdate
from app.services.disease_catalog import DiseaseUsageCounts


ADMIN = SimpleNamespace(id=1, role="admin")


def _disease(**overrides):
    values = {
        "id": 7,
        "code": "fatty_liver",
        "name": "脂肪肝",
        "description": None,
        "operator_enabled": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _query(*, first=None, all_rows=None):
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.order_by.return_value = query
    query.first.return_value = first
    query.all.return_value = list(all_rows or [])
    return query


def test_admin_disease_routes_require_admin():
    from app.api.admin_diseases import router

    for route in router.routes:
        dependencies = {
            getattr(dependency.call, "__name__", "")
            for dependency in route.dependant.dependencies
        }
        assert "require_admin" in dependencies


def test_create_disease_defaults_disabled_and_returns_usage_state():
    from app.api.admin_diseases import create_disease

    db = MagicMock()
    db.query.side_effect = [_query(first=None), _query(first=None)]
    db.refresh.side_effect = lambda disease: (
        setattr(disease, "id", 8),
        setattr(disease, "created_at", datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )
    payload = DiseaseCreate(
        code="gastric_cancer",
        name="胃癌",
        description="待配置能力",
    )
    with patch(
        "app.api.admin_diseases.disease_usage_counts",
        return_value=DiseaseUsageCounts(0, 0, 0, 0),
    ):
        result = create_disease(payload, admin=ADMIN, db=db)

    added = db.add.call_args.args[0]
    assert added.code == "gastric_cancer"
    assert added.operator_enabled is False
    assert result.can_delete is True
    db.commit.assert_called_once_with()


def test_enable_rejects_unregistered_code_without_commit():
    from app.api.admin_diseases import update_disease

    disease = _disease(code="gastric_cancer", operator_enabled=False)
    db = MagicMock()
    db.query.return_value = _query(first=disease)

    with pytest.raises(HTTPException) as error:
        update_disease(
            disease.id,
            DiseaseUpdate(operator_enabled=True),
            db=db,
            admin=ADMIN,
        )

    assert error.value.status_code == 422
    assert error.value.detail == "该疾病尚未配置预测能力，不能启用"
    assert disease.operator_enabled is False
    db.commit.assert_not_called()


def test_enable_rejects_unregistered_code_before_combined_update_mutates_row():
    from app.api.admin_diseases import update_disease

    disease = _disease(
        code="gastric_cancer",
        name="胃癌",
        description="原始描述",
        operator_enabled=False,
    )
    db = MagicMock()
    db.query.side_effect = [_query(first=disease), _query(first=None)]

    with pytest.raises(HTTPException) as error:
        update_disease(
            disease.id,
            DiseaseUpdate(
                name="更新后的胃癌",
                description="更新后的描述",
                operator_enabled=True,
            ),
            db=db,
            admin=ADMIN,
        )

    assert error.value.status_code == 422
    assert error.value.detail == "该疾病尚未配置预测能力，不能启用"
    assert disease.name == "胃癌"
    assert disease.description == "原始描述"
    assert disease.operator_enabled is False
    db.commit.assert_not_called()


def test_code_is_not_part_of_update_contract():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiseaseUpdate.model_validate({"code": "ad"})


def test_disable_updates_only_permission_state():
    from app.api.admin_diseases import update_disease

    disease = _disease(operator_enabled=True)
    db = MagicMock()
    db.query.return_value = _query(first=disease)
    with patch(
        "app.api.admin_diseases.disease_usage_counts",
        return_value=DiseaseUsageCounts(2, 1, 3, 1),
    ):
        result = update_disease(
            disease.id,
            DiseaseUpdate(operator_enabled=False),
            db=db,
            admin=ADMIN,
        )

    assert disease.operator_enabled is False
    assert result.can_delete is False
    db.commit.assert_called_once_with()


def test_delete_rejects_any_usage():
    from app.api.admin_diseases import delete_disease

    disease = _disease()
    db = MagicMock()
    db.query.return_value = _query(first=disease)
    with patch(
        "app.api.admin_diseases.disease_usage_counts",
        return_value=DiseaseUsageCounts(1, 0, 0, 0),
    ):
        with pytest.raises(HTTPException) as error:
            delete_disease(disease.id, db=db, admin=ADMIN)

    assert error.value.status_code == 409
    assert error.value.detail == "该疾病已被业务数据引用，不能删除"
    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_delete_unused_disease_succeeds():
    from app.api.admin_diseases import delete_disease

    disease = _disease()
    db = MagicMock()
    db.query.return_value = _query(first=disease)
    with patch(
        "app.api.admin_diseases.disease_usage_counts",
        return_value=DiseaseUsageCounts(0, 0, 0, 0),
    ):
        response = delete_disease(disease.id, db=db, admin=ADMIN)

    assert response.status_code == 204
    db.delete.assert_called_once_with(disease)
    db.commit.assert_called_once_with()


@pytest.mark.parametrize(
    "constraint_name",
    [
        "fk_operator_cases_disease",
        "fk_case_records_disease",
        "fk_ai_reports_disease",
        "reference_standards_disease_id_fkey",
    ],
)
def test_delete_fk_race_maps_every_disease_reference_to_conflict(constraint_name):
    from app.api.admin_diseases import delete_disease

    disease = _disease()
    db = MagicMock()
    db.query.return_value = _query(first=disease)
    db.commit.side_effect = IntegrityError(
        "delete",
        {},
        SimpleNamespace(diag=SimpleNamespace(constraint_name=constraint_name)),
    )
    with patch(
        "app.api.admin_diseases.disease_usage_counts",
        return_value=DiseaseUsageCounts(0, 0, 0, 0),
    ):
        with pytest.raises(HTTPException) as error:
            delete_disease(disease.id, db=db, admin=ADMIN)

    assert error.value.status_code == 409
    assert error.value.detail == "该疾病已被业务数据引用，不能删除"
    db.rollback.assert_called_once_with()


def test_duplicate_code_and_name_are_conflicts():
    from app.api.admin_diseases import create_disease

    payload = DiseaseCreate(code="ad", name="阿尔茨海默病")
    for query_index, expected_detail in (
        (0, "疾病代码已存在"),
        (1, "疾病名称已存在"),
    ):
        db = MagicMock()
        queries = [_query(first=None), _query(first=None)]
        queries[query_index].first.return_value = (7,)
        db.query.side_effect = queries
        with pytest.raises(HTTPException) as error:
            create_disease(payload, admin=ADMIN, db=db)
        assert error.value.status_code == 409
        assert error.value.detail == expected_detail
