"""Synthetic admission identities, separate from clinical releases and evidence."""

from app.core.config import settings
from app.db.models import User
from app.schemas.synthetic_report_context import SyntheticGenerationContext
from app.schemas.operator_case_workspace import OperatorCaseReportReadiness, OperatorCaseReadinessBlocker
from app.services.synthetic_case_source import validate_engineering_case
from app.services.synthetic_numeric_prediction import numeric_algorithm_identity, numeric_input_sha256
from app.services.longitudinal_case_service import build_input_snapshot
from app.services.report_generation_errors import ReportJobError
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_job_repository import context_hash


def require_synthetic_actor(db, user_id, *, for_update=False):
    query = db.query(User).filter_by(id=user_id)
    actor = (query.with_for_update() if for_update else query).first()
    if actor is None or actor.role not in ("ai_operator", "admin"):
        raise ReportJobError("auth_expired", 401)


def build_synthetic_snapshot(case):
    if not settings.SYNTHETIC_REPORTS_ENABLED:
        raise ReportJobError("synthetic_reports_unavailable", 503)
    if getattr(case, "status", None) != "active":
        raise ReportJobError("case_archived")
    if not case.disease.operator_enabled:
        raise ReportJobError("disease_disabled")
    if case.engineering_source is None:
        raise ReportJobError("synthetic_source_required")
    try:
        numeric = validate_engineering_case(case)
        snapshot = build_input_snapshot(case, case.visits, {})
    except ValueError as exc:
        raise ReportJobError("synthetic_source_invalid") from exc
    snapshot.update(
        schema_version="synthetic_numeric_report_input.v1", user_id=case.user_id,
        report_kind="synthetic_numeric", numeric_input=numeric.model_dump(mode="json"),
        engineering_source_sha256=context_hash(case.engineering_source),
    )
    snapshot["input_snapshot_sha256"] = compute_input_snapshot_sha256(snapshot)
    return snapshot


def capture_synthetic_context(snapshot):
    return SyntheticGenerationContext(
        disease_code=snapshot["disease_code"], numeric_input_sha256=numeric_input_sha256(snapshot["numeric_input"]),
        engineering_source_sha256=snapshot["engineering_source_sha256"], algorithm=numeric_algorithm_identity(),
    )


def evaluate_synthetic_case_readiness(case):
    blockers = []
    try:
        capture_synthetic_context(build_synthetic_snapshot(case))
    except ReportJobError as error:
        blockers.append(OperatorCaseReadinessBlocker(code=error.code, message=error.message))
    except ValueError:
        blockers.append(OperatorCaseReadinessBlocker(code="model_unavailable", message="合成基线实现身份不可用"))
    ready = not blockers
    return OperatorCaseReportReadiness(ready=ready, case_ready=ready, timeline_ready=ready,
        model_ready=ready, visit_count=len(case.visits), minimum_visits=1, blockers=blockers)
