"""Scalar-only history projections with stable (created_at,id) keyset pagination."""

from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import select, func, case, tuple_

from app.db.models import AIReport, ReportGenerationJob, ReportPdfArchive
from app.schemas.operator import ReportListOut, ReportListItem
from app.schemas.report_history import HistoryFilters, HistoryItem, ReportHistoryPage
from app.services.report_history_cursor import encode_cursor, decode_cursor
from app.services.report_saved_identity import saved_report_identity
from app.services.report_generation_errors import safe_code


def history_projection(user_id, analysis_type=None):
    r, j = AIReport.__table__.c, ReportGenerationJob.__table__.c
    a = ReportPdfArchive.__table__.c
    visits = r.input_snapshot["visits"]
    statement = (
        select(
            r.id,
            r.user_id,
            r.status,
            r.analysis_type,
            r.disease_id,
            r.operator_case_id,
            (r.download_count + func.coalesce(a.delivery_count, 0)).label(
                "download_count"
            ),
            func.coalesce(a.state, "not_requested").label("pdf_status"),
            r.created_at,
            r.updated_at,
            r.error_stage,
            r.error_message,
            r.input_snapshot_sha256,
            r.generation_batch_id,
            r.generation_fingerprint,
            r.input_snapshot["anonymous_case_code"].astext.label("anonymous_case_code"),
            r.input_snapshot["disease"].astext.label("disease_name"),
            r.input_snapshot["baseline_stage"].astext.label("baseline_stage"),
            case(
                (func.jsonb_typeof(visits) == "array", func.jsonb_array_length(visits)),
                else_=None,
            ).label("visit_count"),
            func.coalesce(
                r.prediction_result["release_set"]["release_set_id"].astext,
                r.prediction_result["release_set"]["data_release_id"].astext,
                j.generation_context["release_set_id"].astext,
            ).label("model_version_summary"),
        )
        .select_from(
            AIReport.__table__.outerjoin(
                ReportGenerationJob.__table__,
                (j.report_id == r.id) & (j.user_id == r.user_id),
            ).outerjoin(ReportPdfArchive.__table__, a.report_id == r.id)
        )
        .where(r.user_id == user_id)
    )
    if analysis_type is not None:
        statement = statement.where(r.analysis_type == analysis_type)
    return statement


def project_history_item(row):
    data = dict(row)
    identity = saved_report_identity(
        data["id"], {"anonymous_case_code": data["anonymous_case_code"]}
    )
    data.update(
        title=identity.title,
        query=identity.title,
        anonymous_case_code=identity.anonymous_case_code,
    )
    if data["error_message"]:
        data["error_message"] = safe_code(data["error_message"])
    return HistoryItem.model_validate(data)


def filter_digest(filters):
    payload = filters.model_dump(mode="json")
    for field in ("created_from", "created_before"):
        if getattr(filters, field) is not None:
            payload[field] = (
                getattr(filters, field).astimezone(timezone.utc).isoformat()
            )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read_history(db, user_id, filters: HistoryFilters, *, limit=20, cursor=None, key):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("history_limit_invalid")
    r = AIReport.__table__.c
    # Include historical predictive rows alongside the current longitudinal discriminator.
    statement = history_projection(user_id).where(
        r.analysis_type.in_(["predictive", "longitudinal_predictive"])
    )
    if filters.disease_code:
        disease = func.coalesce(
            r.input_snapshot["disease_code"].astext,
            case(
                (r.input_snapshot["disease"].astext == "脂肪肝", "fatty_liver"),
                (r.input_snapshot["disease"].astext == "阿尔茨海默病", "ad"),
            ),
        )
        statement = statement.where(disease == filters.disease_code)
    if filters.anonymous_case_code:
        statement = statement.where(
            r.input_snapshot["anonymous_case_code"].astext
            == filters.anonymous_case_code
        )
    if filters.status:
        statement = statement.where(r.status == filters.status)
    if filters.created_from:
        statement = statement.where(r.created_at >= filters.created_from)
    if filters.created_before:
        statement = statement.where(r.created_at < filters.created_before)
    digest = filter_digest(filters)
    if cursor:
        boundary = decode_cursor(cursor, key, user_id=user_id, filters_sha256=digest)
        statement = statement.where(
            tuple_(r.created_at, r.id)
            < tuple_(datetime.fromisoformat(boundary["created_at"]), boundary["id"])
        )
    rows = (
        db.execute(
            statement.order_by(r.created_at.desc(), r.id.desc()).limit(limit + 1)
        )
        .mappings()
        .all()
    )
    has_more = len(rows) > limit
    items = [project_history_item(row) for row in rows[:limit]]
    next_cursor = None
    if has_more:
        last = items[-1]
        next_cursor = encode_cursor(
            dict(
                v=1,
                user_id=user_id,
                filters_sha256=digest,
                created_at=last.created_at.isoformat(),
                id=last.id,
            ),
            key,
        )
    return ReportHistoryPage(items=items, has_more=has_more, next_cursor=next_cursor)


def read_offset_reports(db, user_id, *, skip=0, limit=20, analysis_type=None):
    statement = history_projection(user_id, analysis_type)
    total = db.execute(
        select(func.count()).select_from(statement.subquery())
    ).scalar_one()
    rows = (
        db.execute(
            statement.order_by(AIReport.created_at.desc(), AIReport.id.desc())
            .offset(skip)
            .limit(limit)
        )
        .mappings()
        .all()
    )
    return ReportListOut(
        reports=[
            ReportListItem.model_validate(project_history_item(row).model_dump())
            for row in rows
        ],
        total=total,
    )
