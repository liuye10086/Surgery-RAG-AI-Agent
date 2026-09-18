"""Strict explicit version routing for the existing numeric bundle setting."""
import json
from pathlib import Path

from app.core.config import settings

ROUTES = {'numeric_model_bundle.v1': 'numeric_generation_context.v2',
          'numeric_model_bundle.v2': 'numeric_generation_context.v3'}


def load_configured_numeric_bundle():
    if not settings.NUMERIC_MODEL_BUNDLE:
        return None
    path = Path(settings.NUMERIC_MODEL_BUNDLE)
    def read_bounded():
        if path.is_symlink() or not path.is_file():
            raise ValueError('numeric_model_invalid_file')
        with path.open('rb') as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError('numeric_model_file_too_large')
        return raw

    raw = read_bounded()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('numeric_model_duplicate_json_key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('numeric_model_nonfinite_json')

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)
    version = value.get('schema_version') if isinstance(value, dict) else None
    if not isinstance(version, str) or version not in ROUTES:
        raise ValueError('numeric_model_unknown_schema')
    if version == 'numeric_model_bundle.v1':
        from app.services.numeric_model_bundle import load_numeric_model_bundle, verify_numeric_bundle_runtime
        bundle = load_numeric_model_bundle(path)
        verify_numeric_bundle_runtime(bundle)
    else:
        from app.services.numeric_history_bundle import load_numeric_history_bundle, verify_numeric_history_runtime
        bundle = load_numeric_history_bundle(path)
        verify_numeric_history_runtime(bundle)
    if bundle != type(bundle).model_validate(value) or json.loads(read_bounded(), object_pairs_hook=pairs,
                                                      parse_constant=invalid_constant) != value:
        raise ValueError('numeric_model_configuration_changed')
    return bundle


def capture_configured_numeric_context(snapshot, db):
    bundle = load_configured_numeric_bundle()
    if bundle is None:
        from app.services.numeric_report_admission import capture_numeric_context
        return capture_numeric_context(snapshot)
    if bundle.schema_version == 'numeric_model_bundle.v1':
        from app.services.numeric_report_v2_admission import capture_numeric_v2_context
        context = capture_numeric_v2_context(snapshot, db)
    else:
        from app.services.numeric_report_v3_admission import capture_numeric_v3_context
        context = capture_numeric_v3_context(snapshot, db)
    if context.model_bundle != bundle:
        raise ValueError('numeric_model_configuration_changed')
    return context


def evaluate_configured_numeric_readiness(case, db):
    from app.schemas.operator_case_workspace import OperatorCaseReportReadiness, OperatorCaseReadinessBlocker
    from app.services.numeric_report_admission import build_numeric_snapshot
    from app.services.report_generation_errors import ReportJobError
    blockers = []
    try:
        context = capture_configured_numeric_context(build_numeric_snapshot(case), db)
        if context.schema_version != 'numeric_generation_context.v1' and not settings.DEEPSEEK_API_KEY:
            raise ValueError('numeric_narrative_configuration_missing')
    except ReportJobError as error:
        blockers.append(OperatorCaseReadinessBlocker(code=error.code, message=error.message))
    except (ValueError, OSError):
        blockers.append(OperatorCaseReadinessBlocker(code='model_unavailable', message='数值预测模型或说明生成配置不可用'))
    ready = not blockers
    return OperatorCaseReportReadiness(ready=ready, case_ready=ready, timeline_ready=ready,
        model_ready=ready, visit_count=len(case.visits), minimum_visits=1, blockers=blockers)
