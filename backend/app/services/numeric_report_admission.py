"""Source-independent numeric admission and fixed generation context."""

from app.core.config import settings
from app.db.models import User
from app.schemas.numeric_report import NumericGenerationContext
from app.services.prediction_case_source import validate_prediction_case
from app.services.numeric_prediction import numeric_algorithm_identity, numeric_input_sha256
from app.services.longitudinal_case_service import build_input_snapshot
from app.services.report_generation_errors import ReportJobError
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_job_repository import context_hash


def require_numeric_actor(db, user_id, *, for_update=False):
    query = db.query(User).filter_by(id=user_id)
    actor = (query.with_for_update() if for_update else query).first()
    if actor is None or actor.role not in ("ai_operator", "admin"):
        raise ReportJobError("auth_expired", 401)


def build_numeric_snapshot(case):
    if not settings.NUMERIC_REPORTS_ENABLED:
        raise ReportJobError("numeric_reports_unavailable", 503)
    if getattr(case, "status", None) != "active":
        raise ReportJobError("case_archived")
    if not case.disease.operator_enabled:
        raise ReportJobError("disease_disabled")
    if getattr(case, "prediction_source", None) is None and getattr(case, "engineering_source", None) is None:
        raise ReportJobError("prediction_source_required")
    try:
        numeric = validate_prediction_case(case)
        snapshot = build_input_snapshot(case, case.visits, {})
    except ValueError as exc:
        raise ReportJobError("prediction_source_invalid") from exc
    snapshot.update(
        schema_version="numeric_report_input.v1", user_id=case.user_id,
        report_kind="numeric_prediction", numeric_input=numeric.model_dump(mode="json"),
        source_binding_sha256=context_hash(getattr(case, "prediction_source", None) if getattr(case, "prediction_source", None) is not None else case.engineering_source),
    )
    snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
    return snapshot


def capture_numeric_context(snapshot):
    return NumericGenerationContext(
        disease_code=snapshot["disease_code"], numeric_input_sha256=numeric_input_sha256(snapshot["numeric_input"]),
        source_binding_sha256=snapshot["source_binding_sha256"], algorithm=numeric_algorithm_identity(),
    )
