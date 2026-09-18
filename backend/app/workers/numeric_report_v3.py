"""Execute the frozen trained model, bounded retrieval and one narrative call."""
from datetime import datetime
from sqlalchemy import text
from app.db.session import SessionLocal
from app.services.numeric_history_bundle import predict_numeric_history_bundle, verify_numeric_history_runtime
from app.services.numeric_report_evidence import retrieve_numeric_evidence
from app.services.numeric_report_narrative_v2 import generate_numeric_narrative_v2
from app.services.numeric_report_v3 import validate_numeric_v3_snapshot, build_numeric_v3_document, build_numeric_v3_publication
from app.services.report_generation_errors import safe_code


def execute_numeric_v3_report(payload, send):
    phase, sequence = 'model_loading', 0

    def audit(event):
        nonlocal sequence
        sequence += 1
        send({'kind': 'audit', 'phase': phase, 'child_sequence': sequence, 'audit': event})

    try:
        snapshot = payload['snapshot']
        context, numeric = validate_numeric_v3_snapshot(snapshot, payload['context'])
        send({'kind': 'phase', 'phase': phase})
        verify_numeric_history_runtime(context.model_bundle)
        from app.services.numeric_report_v2_admission import current_numeric_retrieval_settings
        from app.services.numeric_report_narrative_v2 import PROMPT
        if context.prompt_text != PROMPT or context.retrieval_settings != current_numeric_retrieval_settings():
            raise ValueError('generation_context_changed')
        phase = 'prediction'
        send({'kind': 'phase', 'phase': phase})
        prediction = predict_numeric_history_bundle(numeric, context.model_bundle)
        for result in prediction.predictions:
            audit({'kind': 'task_finished', 'phase': phase, 'task': result.task_id,
                'result_state': 'available' if result.status == 'available' else 'unavailable', 'reason_code': result.reason})
        phase = 'standard_evidence'
        send({'kind': 'phase', 'phase': phase})
        with SessionLocal() as db:
            db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
            evidence = retrieve_numeric_evidence(db, numeric, context.references)
        audit({'kind': 'evidence_resolved', 'phase': phase,
            'result_state': 'available' if evidence.items else 'unavailable'})
        phase = 'rendering'
        send({'kind': 'phase', 'phase': phase})
        audit({'kind': 'invocation_started', 'phase': phase, 'task': 'report_narrative'})
        narrative = generate_numeric_narrative_v2(numeric, prediction, evidence, llm_model=context.llm_model)
        audit({'kind': 'task_finished', 'phase': phase, 'task': 'report_narrative', 'result_state': 'available'})
        document = build_numeric_v3_document(payload['report_id'], datetime.fromisoformat(payload['created_at']),
            snapshot, context, prediction, evidence, narrative)
        publication = build_numeric_v3_publication(snapshot, prediction, document)
        send({'kind': 'publication', 'phase': 'persistence', 'publication': publication.model_dump(mode='json')})
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code is None and isinstance(exc, ValueError) and len(exc.args) == 1:
            code = exc.args[0]
        send({'kind': 'error', 'phase': phase, 'code': safe_code(code)})
