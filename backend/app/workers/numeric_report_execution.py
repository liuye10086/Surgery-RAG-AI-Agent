"""Execute the admitted baseline without clinical model, evidence, or LLM calls."""

from datetime import datetime

from app.services.numeric_prediction import predict_numeric
from app.services.numeric_report_publication import build_numeric_document, build_numeric_publication, validate_numeric_snapshot
from app.services.report_generation_errors import safe_code


def execute_numeric_report(payload, send):
    phase = 'model_loading'
    sequence = 0

    def audit(event):
        nonlocal sequence
        sequence += 1
        send({'kind': 'audit', 'phase': phase, 'child_sequence': sequence, 'audit': event})

    try:
        snapshot = payload['snapshot']
        context, numeric = validate_numeric_snapshot(snapshot, payload['context'])
        send({'kind': 'phase', 'phase': phase})
        phase = 'prediction'
        send({'kind': 'phase', 'phase': phase})
        prediction = predict_numeric(numeric, expected_algorithm=context.algorithm)
        for result in prediction.predictions:
            audit({'kind': 'task_finished', 'phase': phase, 'task': result.task_id,
                   'result_state': result.status, 'reason_code': result.reason})
        phase = 'standard_evidence'
        send({'kind': 'phase', 'phase': phase})
        audit({'kind': 'evidence_resolved', 'phase': phase, 'result_state': 'not_requested'})
        phase = 'rendering'
        send({'kind': 'phase', 'phase': phase})
        document = build_numeric_document(payload['report_id'], datetime.fromisoformat(payload['created_at']),
                                            snapshot, context, prediction)
        publication = build_numeric_publication(snapshot, prediction, document)
        phase = 'persistence'
        send({'kind': 'publication', 'phase': phase, 'publication': publication.model_dump(mode='json')})
    except Exception as exc:
        code = getattr(exc, 'code', None)
        if code is None and isinstance(exc, ValueError) and len(exc.args) == 1:
            code = exc.args[0]
        if code in ('numeric_algorithm_mismatch', 'numeric_implementation_changed', 'numeric_loaded_code_mismatch'):
            code = 'generation_context_changed'
        send({'kind': 'error', 'phase': phase, 'code': safe_code(code)})
