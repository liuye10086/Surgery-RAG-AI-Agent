"""Persistence and ownership rules for operator longitudinal cases."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError

from app.db.models import OperatorCase, OperatorCaseVisit
from app.schemas.longitudinal_case import (
    OperatorCaseCreate,
    OperatorCaseUpdate,
    VisitCreate,
    VisitUpdate,
)
from app.services.disease_catalog import (
    DiseaseNotFoundError,
    require_enabled_case_disease,
    require_operator_disease,
)
from app.services.indicator_validation import validate_indicators, validate_visits


class LongitudinalCaseError(ValueError):
    """Base error translated to an HTTP response by the API layer."""


class CaseNotFoundError(LongitudinalCaseError):
    pass


class VisitNotFoundError(LongitudinalCaseError):
    pass


class DuplicateVisitDateError(LongitudinalCaseError):
    pass


class VisitLimitError(LongitudinalCaseError):
    pass


class ArchivedCaseError(LongitudinalCaseError):
    pass


def _validate_visit_count(count: int) -> None:
    if count < 1:
        raise VisitLimitError("病例至少需要 1 次访视")
    if count > 10:
        raise VisitLimitError("每个病例最多保存 10 次访视")


def _owned_case_query(db, user_id: int, case_id: int):
    return (
        db.query(OperatorCase)
        .filter(OperatorCase.id == case_id, OperatorCase.user_id == user_id)
        .first()
    )


def get_operator_case(db, user_id: int, case_id: int) -> OperatorCase:
    """Load a case only through its owner predicate.

    The service intentionally does not distinguish a missing case from a case
    owned by another user; the API maps both to HTTP 404 to avoid enumeration.
    """

    case = _owned_case_query(db, user_id, case_id)
    if case is None:
        raise CaseNotFoundError("病例不存在")
    return case


def get_operator_case_for_write(db, user_id: int, case_id: int) -> OperatorCase:
    """Load and lock an owned case, enforcing write eligibility."""

    case = get_operator_case(db, user_id, case_id)
    # Refresh with SELECT .. FOR UPDATE so every mutation serializes against
    # status changes.  The refresh call is harmless for mocked/transient cases.
    try:
        db.refresh(case, with_for_update=True)
    except (TypeError, AttributeError):
        pass
    case_status = getattr(case, "status", "active")
    if case_status != "active":
        message = "病例已归档，当前只读" if case_status == "archived" else "病例状态未知，当前只读"
        raise ArchivedCaseError(message)
    require_enabled_case_disease(case)
    return case


def create_operator_case(
    db, user_id: int, payload: OperatorCaseCreate
) -> OperatorCase:
    disease = require_operator_disease(db, payload.disease_id)
    validate_visits(disease.code, payload.visits)

    visits = sorted(payload.visits, key=lambda item: item.visit_date)
    if len({item.visit_date for item in visits}) != len(visits):
        raise DuplicateVisitDateError("同一病例不能重复使用访视日期")
    _validate_visit_count(len(visits))

    case = OperatorCase(
        user_id=user_id,
        disease_id=payload.disease_id,
        patient_label=payload.patient_label,
        age=payload.age,
        sex=payload.sex,
        baseline_stage=payload.baseline_stage,
        notes=payload.notes,
        status="active",
    )
    db.add(case)
    db.flush()
    for index, visit_payload in enumerate(visits, start=1):
        db.add(
            OperatorCaseVisit(
                case=case,
                visit_date=visit_payload.visit_date,
                visit_index=index,
                indicators=[item.model_dump() for item in visit_payload.indicators],
                notes=visit_payload.notes,
            )
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateVisitDateError("同一病例不能重复使用访视日期") from exc
    db.refresh(case)
    return case


def list_operator_cases(
    db, user_id: int, disease_id: int | None = None, status: str | None = None
) -> list[OperatorCase]:
    query = db.query(OperatorCase).filter(OperatorCase.user_id == user_id)
    if disease_id is not None:
        query = query.filter(OperatorCase.disease_id == disease_id)
    if status is not None:
        query = query.filter(OperatorCase.status == status)
    return query.order_by(OperatorCase.updated_at.desc(), OperatorCase.id.desc()).all()


def update_operator_case(
    db, user_id: int, case_id: int, payload: OperatorCaseUpdate
) -> OperatorCase:
    case = get_operator_case_for_write(db, user_id, case_id)
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(case, field, value)
    db.commit()
    db.refresh(case)
    return case


def delete_operator_case(db, user_id: int, case_id: int) -> None:
    case = get_operator_case_for_write(db, user_id, case_id)
    db.delete(case)
    db.commit()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _ordered_visits(db, case_id: int, case: OperatorCase | None = None) -> list[Any]:
    visits = (
        db.query(OperatorCaseVisit)
        .filter(OperatorCaseVisit.case_id == case_id)
        .order_by(OperatorCaseVisit.visit_date.asc(), OperatorCaseVisit.id.asc())
        .all()
    )
    # A mocked session or an already-loaded transient case may not provide a
    # query result. The relationship is a valid fallback and is also useful in
    # callers that build a snapshot before a flush.
    if not isinstance(visits, list):
        visits = list(getattr(case, "visits", ()) or ())
    return sorted(visits, key=lambda item: (_as_date(item.visit_date), item.id or 0))


def _reindex_visits(db, case_id: int, case: OperatorCase | None = None) -> list[Any]:
    visits = _ordered_visits(db, case_id, case)
    # The unique (case_id, visit_index) constraint makes a direct swap unsafe:
    # assigning 1->2 before 2->1 can transiently collide. Move rows to a
    # temporary, valid positive range first, then assign their final indexes.
    for offset, visit in enumerate(visits, start=1):
        visit.visit_index = 1000 + offset
    try:
        db.flush()
    except AttributeError:
        pass
    for index, visit in enumerate(visits, start=1):
        visit.visit_index = index
    try:
        db.flush()
    except AttributeError:
        pass
    return visits


def add_visit(db, user_id: int, case_id: int, payload: VisitCreate) -> OperatorCaseVisit:
    case = get_operator_case_for_write(db, user_id, case_id)
    validate_indicators(case.disease.code, payload.indicators)
    visits = _ordered_visits(db, case_id, case)
    duplicate = (
        db.query(OperatorCaseVisit)
        .filter(
            OperatorCaseVisit.case_id == case_id,
            OperatorCaseVisit.visit_date == payload.visit_date,
        )
        .first()
    )
    if duplicate is not None:
        raise DuplicateVisitDateError("同一病例不能重复添加同一访视日期")
    _validate_visit_count(len(visits) + 1)

    visit = OperatorCaseVisit(
        case_id=case_id,
        visit_date=payload.visit_date,
        visit_index=len(visits) + 1,
        indicators=[indicator.model_dump() for indicator in payload.indicators],
        notes=payload.notes,
    )
    db.add(visit)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateVisitDateError("同一病例不能重复添加同一访视日期") from exc

    # Date order, rather than insertion order, is the canonical timeline.
    _reindex_visits(db, case_id, case)
    db.commit()
    db.refresh(visit)
    return visit


def _owned_visit_query(db, user_id: int, case_id: int, visit_id: int):
    case = get_operator_case_for_write(db, user_id, case_id)
    visit = (
        db.query(OperatorCaseVisit)
        .filter(
            OperatorCaseVisit.id == visit_id,
            OperatorCaseVisit.case_id == case.id,
        )
        .first()
    )
    if visit is None:
        raise VisitNotFoundError("访视不存在")
    return case, visit


def update_visit(
    db, user_id: int, case_id: int, visit_id: int, payload: VisitUpdate
) -> OperatorCaseVisit:
    case, visit = _owned_visit_query(db, user_id, case_id, visit_id)
    values = payload.model_dump(exclude_unset=True)
    if payload.indicators is not None:
        validate_indicators(case.disease.code, payload.indicators)
    if "visit_date" in values:
        duplicate = (
            db.query(OperatorCaseVisit)
            .filter(
                OperatorCaseVisit.case_id == case_id,
                OperatorCaseVisit.visit_date == values["visit_date"],
                OperatorCaseVisit.id != visit_id,
            )
            .first()
        )
        if duplicate is not None:
            raise DuplicateVisitDateError("同一病例不能重复使用访视日期")
    if "indicators" in values:
        values["indicators"] = [item.model_dump() for item in values["indicators"]]
    for field, value in values.items():
        setattr(visit, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateVisitDateError("同一病例不能重复使用访视日期") from exc
    _reindex_visits(db, case_id, case)
    db.commit()
    db.refresh(visit)
    return visit


def replace_visits(
    db, user_id: int, case_id: int, payloads: Iterable[VisitCreate]
) -> list[OperatorCaseVisit]:
    """Replace an entire case timeline in one transaction.

    Replacing rows avoids transient unique-date conflicts when an operator
    edits or reorders multiple visits at once. Visit IDs are intentionally
    not part of the editor contract; the immutable report snapshot preserves
    the submitted history used for prediction.
    """
    case = get_operator_case_for_write(db, user_id, case_id)
    payloads = list(payloads)
    validate_visits(case.disease.code, payloads)
    _validate_visit_count(len(payloads))
    dates = [payload.visit_date for payload in payloads]
    if len(dates) != len(set(dates)):
        raise DuplicateVisitDateError("同一病例不能重复使用访视日期")

    ordered = sorted(payloads, key=lambda payload: payload.visit_date)
    try:
        db.query(OperatorCaseVisit).filter(
            OperatorCaseVisit.case_id == case_id
        ).delete(synchronize_session=False)
        for index, payload in enumerate(ordered, start=1):
            db.add(
                OperatorCaseVisit(
                    case_id=case_id,
                    visit_date=payload.visit_date,
                    visit_index=index,
                    indicators=[item.model_dump() for item in payload.indicators],
                    notes=payload.notes,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateVisitDateError("同一病例不能重复使用访视日期") from exc

    return _ordered_visits(db, case_id, case)


def delete_visit(db, user_id: int, case_id: int, visit_id: int) -> None:
    case, visit = _owned_visit_query(db, user_id, case_id, visit_id)
    visits = _ordered_visits(db, case_id, case)
    _validate_visit_count(len(visits) - 1)
    db.delete(visit)
    db.commit()
    _reindex_visits(db, case_id, case)
    db.commit()


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return {
        "name": getattr(value, "name"),
        "value": getattr(value, "value"),
        "unit": getattr(value, "unit"),
    }


def build_input_snapshot(
    case: OperatorCase,
    visits: Iterable[Any],
    model_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, privacy-bounded snapshot for prediction/reporting."""

    ordered = sorted(
        list(visits),
        key=lambda item: (_as_date(item.visit_date), getattr(item, "id", 0) or 0),
    )
    snapshot_visits = []
    for index, visit in enumerate(ordered, start=1):
        indicators = getattr(visit, "indicators", []) or []
        snapshot_visits.append(
            {
                "visit_date": _as_date(visit.visit_date).isoformat(),
                "visit_index": index,
                "indicators": [_dump(indicator) for indicator in indicators],
                "notes": getattr(visit, "notes", None),
            }
        )

    disease = getattr(case, "disease", None)
    disease_code = getattr(disease, "code", None)
    if disease_code:
        validate_visits(disease_code, snapshot_visits)
    return {
        "schema_version": "longitudinal_input.v1",
        "case_id": getattr(case, "id", None),
        "disease_id": getattr(case, "disease_id", None),
        "disease": getattr(disease, "name", None),
        "disease_code": disease_code,
        "patient_label": getattr(case, "patient_label", None),
        "age": getattr(case, "age", None),
        "sex": getattr(case, "sex", None),
        "baseline_stage": getattr(case, "baseline_stage", None),
        "case_notes": getattr(case, "notes", None),
        "visits": snapshot_visits,
        "model_options": dict(model_options or {}),
    }
