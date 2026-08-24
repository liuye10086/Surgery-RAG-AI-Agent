"""Persistence and ownership rules for operator longitudinal cases."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy.exc import IntegrityError

from app.db.models import Disease, OperatorCase, OperatorCaseVisit
from app.schemas.longitudinal_case import (
    OperatorCaseCreate,
    OperatorCaseUpdate,
    VisitCreate,
    VisitUpdate,
)


class LongitudinalCaseError(ValueError):
    """Base error translated to an HTTP response by the API layer."""


class CaseNotFoundError(LongitudinalCaseError):
    pass


class DiseaseNotFoundError(LongitudinalCaseError):
    pass


class VisitNotFoundError(LongitudinalCaseError):
    pass


class DuplicateVisitDateError(LongitudinalCaseError):
    pass


class VisitLimitError(LongitudinalCaseError):
    pass


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


def create_operator_case(
    db, user_id: int, payload: OperatorCaseCreate
) -> OperatorCase:
    if db.query(Disease).filter(Disease.id == payload.disease_id).first() is None:
        raise DiseaseNotFoundError("疾病不存在")

    case = OperatorCase(
        user_id=user_id,
        disease_id=payload.disease_id,
        patient_label=payload.patient_label,
        sex=payload.sex,
        baseline_stage=payload.baseline_stage,
        notes=payload.notes,
        status="active",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def list_operator_cases(
    db, user_id: int, disease_id: int | None = None
) -> list[OperatorCase]:
    query = db.query(OperatorCase).filter(OperatorCase.user_id == user_id)
    if disease_id is not None:
        query = query.filter(OperatorCase.disease_id == disease_id)
    return query.order_by(OperatorCase.updated_at.desc(), OperatorCase.id.desc()).all()


def update_operator_case(
    db, user_id: int, case_id: int, payload: OperatorCaseUpdate
) -> OperatorCase:
    case = get_operator_case(db, user_id, case_id)
    values = payload.model_dump(exclude_unset=True)
    if "disease_id" in values:
        if db.query(Disease).filter(Disease.id == values["disease_id"]).first() is None:
            raise DiseaseNotFoundError("疾病不存在")
    for field, value in values.items():
        setattr(case, field, value)
    db.commit()
    db.refresh(case)
    return case


def delete_operator_case(db, user_id: int, case_id: int) -> None:
    case = get_operator_case(db, user_id, case_id)
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
    for index, visit in enumerate(visits, start=1):
        visit.visit_index = index
    return visits


def add_visit(db, user_id: int, case_id: int, payload: VisitCreate) -> OperatorCaseVisit:
    case = get_operator_case(db, user_id, case_id)
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
    if len(visits) >= 10:
        raise VisitLimitError("每个病例最多保存 10 次访视")

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
    case = get_operator_case(db, user_id, case_id)
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
    case = get_operator_case(db, user_id, case_id)
    payloads = list(payloads)
    if len(payloads) > 10:
        raise VisitLimitError("每个病例最多保存 10 次访视")
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
    return {
        "schema_version": "longitudinal_input.v1",
        "case_id": getattr(case, "id", None),
        "disease_id": getattr(case, "disease_id", None),
        "disease": getattr(disease, "name", None),
        "patient_label": getattr(case, "patient_label", None),
        "sex": getattr(case, "sex", None),
        "baseline_stage": getattr(case, "baseline_stage", None),
        "case_notes": getattr(case, "notes", None),
        "visits": snapshot_visits,
        "model_options": dict(model_options or {}),
    }
