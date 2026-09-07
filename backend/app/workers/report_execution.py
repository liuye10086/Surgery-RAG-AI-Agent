"""Child-process execution exclusively from the admitted snapshot and context."""

from datetime import datetime
from app.schemas.report_document import ReportGenerationContext
from app.services.report_integrity import compute_input_snapshot_sha256
from app.services.report_job_repository import context_hash
from app.services.report_generation_context import (
    load_pinned_model_suite,
    build_pinned_evidence,
)
from app.services.report_input_audit import run_audited_prediction
from app.services.report_document_builder import build_report_document
from app.services.report_publication import build_publication
from app.services.report_generation_errors import safe_code


def execute_report(input_payload, send_message):
    phase = "model_loading"
    audit_sequence = 0

    def send_audit(event):
        nonlocal audit_sequence
        audit_sequence += 1
        send_message({"kind": "audit", "phase": phase, "child_sequence": audit_sequence, "audit": event})
    try:
        snapshot = input_payload["snapshot"]
        context = ReportGenerationContext.model_validate(input_payload["context"])
        if (
            compute_input_snapshot_sha256(snapshot) != input_payload["snapshot_sha256"]
            or context_hash(input_payload["context"]) != input_payload["context_sha256"]
        ):
            raise ValueError("generation_context_integrity_failed")
        send_message({"kind": "phase", "phase": phase})
        suite = load_pinned_model_suite(context, input_payload["registry_root"])
        from app.services.disease_catalog import DISEASE_CAPABILITIES

        phase = "prediction"
        send_message({"kind": "phase", "phase": phase})
        audited = run_audited_prediction(
            snapshot,
            DISEASE_CAPABILITIES[context.disease_code].adapter,
            suite,
            minimum_visits=context.minimum_visits,
            on_event=send_audit,
        )
        phase = "standard_evidence"
        send_message({"kind": "phase", "phase": phase})
        from app.db.session import SessionLocal

        evidence = build_pinned_evidence(snapshot, context, SessionLocal)
        send_audit({"kind": "evidence_resolved", "phase": phase, "result_state": "available"})
        from app.services.longitudinal_signal_interpreter import (
            attach_signal_interpretation,
        )
        from app.services.longitudinal_prediction import (
            prediction_result_to_dict,
            validate_prediction_result,
        )

        prediction = prediction_result_to_dict(
            attach_signal_interpretation(
                validate_prediction_result(audited.prediction),
                snapshot["visits"],
                evidence.bundle.standard,
            )
        )
        prediction["evidence"]["sources"] = list(evidence.sources_projection)
        phase = "rendering"
        send_message({"kind": "phase", "phase": phase})
        document = build_report_document(
            input_payload["report_id"],
            datetime.fromisoformat(input_payload["created_at"]),
            snapshot,
            context,
            prediction,
            audited.model_runs,
            evidence,
        )
        publication = build_publication(snapshot, prediction, evidence, document)
        phase = "persistence"
        send_message(
            {
                "kind": "publication",
                "phase": phase,
                "publication": publication.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code is None and isinstance(exc, ValueError) and len(exc.args) == 1:
            code = exc.args[0]
        send_message({"kind": "error", "phase": phase, "code": safe_code(code)})
