"""S3 admission tests; all fixtures are fictional and use no database or LLM."""
import json
from copy import deepcopy

import pytest

from test_numeric_history_bundle import history_bundle_fixture
from test_numeric_model_bundle import bundle_fixture
from test_numeric_prediction import numeric_fixture
from test_numeric_report_evidence import DB


def configure(monkeypatch, tmp_path, version='v2'):
    from app.core.config import settings
    from app.services import numeric_history_bundle, numeric_model_bundle, numeric_report_v2_admission
    # Fictional fixture identities deliberately cannot pass a real runtime gate.
    monkeypatch.setattr(numeric_history_bundle, 'verify_numeric_history_runtime', lambda b: None)
    monkeypatch.setattr(numeric_model_bundle, 'verify_numeric_bundle_runtime', lambda b: None)
    monkeypatch.setattr(numeric_report_v2_admission, 'verify_numeric_bundle_runtime', lambda b: None)
    raw = history_bundle_fixture() if version == 'v2' else bundle_fixture()
    path = tmp_path / 'bundle.json'
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', str(path))
    return path


def snapshot(kind='synthetic', disease='ad'):
    return dict(schema_version='numeric_report_input.v1', report_kind='numeric_prediction',
                disease_code=disease, numeric_input=numeric_fixture(disease, kind), source_binding_sha256='a' * 64)


@pytest.mark.parametrize('version,expected', [('', 'v1'), ('v1', 'v2'), ('v2', 'v3')])
def test_explicit_dispatch_routes(monkeypatch, tmp_path, version, expected):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.core.config import settings
    if version:
        configure(monkeypatch, tmp_path, version)
    else:
        monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', '')
    context = capture_configured_numeric_context(snapshot(), DB([]))
    assert context.schema_version == 'numeric_generation_context.' + expected


@pytest.mark.parametrize('raw', ['{}', '[]', '{"schema_version":"unknown"}', '{"schema_version":[]}',
    '{"schema_version":"numeric_model_bundle.v2","schema_version":"numeric_model_bundle.v1"}',
    '{"schema_version":"numeric_model_bundle.v2","x":NaN}', '{broken'])
def test_unknown_or_malformed_configuration_never_falls_back(monkeypatch, tmp_path, raw):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    path = configure(monkeypatch, tmp_path)
    path.write_text(raw, encoding='utf-8')
    with pytest.raises(ValueError):
        capture_configured_numeric_context(snapshot(), DB([]))


@pytest.mark.parametrize('version', ['', 'v1', 'v2'])
def test_real_source_only_rejected_by_history_route(monkeypatch, tmp_path, version):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.core.config import settings
    if version:
        configure(monkeypatch, tmp_path, version)
    else:
        monkeypatch.setattr(settings, 'NUMERIC_MODEL_BUNDLE', '')
    if version == 'v2':
        with pytest.raises(ValueError, match='synthetic_required'):
            capture_configured_numeric_context(snapshot('real'), DB([]))
    else:
        assert capture_configured_numeric_context(snapshot('real'), DB([]))


@pytest.mark.parametrize('disease', ['ad', 'fatty_liver'])
def test_context_freezes_identity_without_requiring_history(monkeypatch, tmp_path, disease):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    configure(monkeypatch, tmp_path)
    saved = snapshot(disease=disease)
    for packet in saved['numeric_input']['packets']:
        packet['input_observations'] = packet['input_observations'][1:]
        packet['history_state'] = 'confirmed_none'
    context = capture_configured_numeric_context(saved, DB([]))
    result = predict_numeric_history_bundle(saved['numeric_input'], context.model_bundle)
    assert context.numeric_input.model_dump(mode='json') == saved['numeric_input']
    assert context.algorithm == result.algorithm
    assert len(context.task_algorithms) == 4
    assert all(context.task_algorithms[p.task_id] == p.algorithm for p in result.predictions)
    assert context.prompt_version == 'numeric_narrative.prompt.v2'
    assert context.template_version == 'numeric_report.zh-CN.v3'
    assert context.references.candidates == []
    if disease == 'ad':
        assert result.predictions[1].status == 'abstain'
        assert result.baseline_predictions[1].status == 'available'


@pytest.mark.parametrize('field', ['source', 'digest', 'algorithm', 'task', 'prompt', 'reference'])
def test_context_rejects_saved_identity_tampering(monkeypatch, tmp_path, field):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3
    configure(monkeypatch, tmp_path)
    raw = capture_configured_numeric_context(snapshot(), DB([])).model_dump(mode='json')
    if field == 'source': raw['numeric_input']['source']['run_id'] = 'tampered'
    elif field == 'digest': raw['numeric_input_sha256'] = 'b' * 64
    elif field == 'algorithm': raw['algorithm']['bundle_sha256'] = 'b' * 64
    elif field == 'task': raw['task_algorithms']['ad.mmse.12m']['parameters_sha256'] = 'b' * 64
    elif field == 'prompt': raw['prompt_text'] += 'tampered'
    else: raw['references']['anchor_date'] = '2000-01-01'
    with pytest.raises(ValueError): NumericGenerationContextV3.model_validate(raw)


def test_incomplete_bundle_is_failure_not_history_abstention(monkeypatch, tmp_path):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    path = configure(monkeypatch, tmp_path)
    raw = json.loads(path.read_text(encoding='utf-8'))
    raw['task_assignments'].pop()
    path.write_text(json.dumps(raw), encoding='utf-8')
    with pytest.raises(ValueError): capture_configured_numeric_context(snapshot(), DB([]))


def admission_environment(monkeypatch, tmp_path):
    from contextlib import nullcontext
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from app.services import report_generation_service as service
    from app.db.models import User, Disease, AIReport
    from test_synthetic_case_capability import case
    configure(monkeypatch, tmp_path)
    for flag in ('NUMERIC_REPORTS_ENABLED', 'REPORT_JOBS_ENABLED', 'REPORT_JOBS_ACCEPTING'):
        monkeypatch.setattr(service.settings, flag, True)
    value = case()
    actor = SimpleNamespace(id=8, role='ai_operator')
    db = MagicMock()
    def query(model, *args):
        q = MagicMock()
        q.filter.return_value = q.filter_by.return_value = q.populate_existing.return_value = q.with_for_update.return_value = q
        q.first.return_value = actor if model is User else value.disease if model is Disease else None
        q.count.return_value = 0
        q.all.return_value = []
        return q
    db.query.side_effect = query
    def add(row):
        if isinstance(row, AIReport): row.id = 42
    db.add.side_effect = add
    monkeypatch.setattr(service, '_replay', lambda *args: None)
    monkeypatch.setattr(service, 'get_operator_case', lambda *args: value)
    monkeypatch.setattr(service, 'get_operator_case_for_write', lambda *args: value)
    monkeypatch.setattr(service, 'db_now', lambda db: datetime.now(timezone.utc))
    return service, value, actor, db, lambda: nullcontext(db)


def submit_fixture(env, key=None):
    from uuid import uuid4
    service, value, actor, db, factory = env
    return service.submit_report_job(actor.id, value.id, key or str(uuid4()),
        {'report_kind': 'numeric_prediction', 'model_options': {}}, factory, '.')


def test_service_saves_v3_and_double_captures(monkeypatch, tmp_path):
    from app.services import numeric_model_dispatch as dispatch
    from app.db.models import ReportGenerationJob
    env = admission_environment(monkeypatch, tmp_path)
    original, captures = dispatch.capture_configured_numeric_context, []
    def capture(snapshot, db):
        context = original(snapshot, db)
        captures.append(context)
        return context
    monkeypatch.setattr(dispatch, 'capture_configured_numeric_context', capture)
    assert submit_fixture(env).report_id == 42
    jobs = [call.args[0] for call in env[3].add.call_args_list if isinstance(call.args[0], ReportGenerationJob)]
    assert len(captures) == 2 and captures[0] == captures[1]
    assert jobs[0].generation_context['schema_version'] == 'numeric_generation_context.v3'
    env[3].commit.assert_called_once()


@pytest.mark.parametrize('drift', ['prompt', 'model', 'empty', 'input'])
def test_service_rejects_double_capture_drift_without_writing(monkeypatch, tmp_path, drift):
    from app.services import numeric_model_dispatch as dispatch
    from app.services import numeric_report_narrative_v2 as narrative
    env = admission_environment(monkeypatch, tmp_path)
    original = dispatch.capture_configured_numeric_context
    if drift == 'input':
        from app.services import numeric_report_admission as admission
        build = admission.build_numeric_snapshot
        snapshots = []
        def changed_snapshot(case):
            saved = build(case)
            if snapshots: saved['case_version'] = 'changed'
            snapshots.append(saved)
            return saved
        monkeypatch.setattr(admission, 'build_numeric_snapshot', changed_snapshot)
    def capture(snapshot, db):
        context = original(snapshot, db)
        if drift == 'prompt': monkeypatch.setattr(narrative, 'PROMPT', narrative.PROMPT + '变更')
        elif drift == 'model': monkeypatch.setattr(env[0].settings, 'DEEPSEEK_MODEL', 'changed-model')
        elif drift == 'empty': monkeypatch.setattr(env[0].settings, 'NUMERIC_MODEL_BUNDLE', '')
        return context
    monkeypatch.setattr(dispatch, 'capture_configured_numeric_context', capture)
    with pytest.raises(env[0].ReportJobError) as failure: submit_fixture(env)
    assert failure.value.code == ('case_changed' if drift == 'input' else 'generation_context_changed')
    env[3].add.assert_not_called()
    env[3].commit.assert_not_called()


@pytest.mark.parametrize('change,code', [('role', 'auth_expired'), ('disease', 'disease_disabled'), ('owner', 'case_not_found')])
def test_service_preserves_admission_permissions(monkeypatch, tmp_path, change, code):
    from app.services.longitudinal_case_service import CaseNotFoundError
    env = admission_environment(monkeypatch, tmp_path)
    if change == 'role': env[2].role = 'patient'
    elif change == 'disease': env[1].disease.operator_enabled = False
    else:
        def missing(*args): raise CaseNotFoundError('missing')
        monkeypatch.setattr(env[0], 'get_operator_case', missing)
    with pytest.raises(env[0].ReportJobError) as failure: submit_fixture(env)
    assert failure.value.code == code
    env[3].add.assert_not_called()


def test_idempotent_hit_returns_saved_report_without_reading_current_bundle(monkeypatch, tmp_path):
    from app.schemas.report_generation import JobAccepted
    env = admission_environment(monkeypatch, tmp_path)
    saved = JobAccepted(report_id=19, batch_id='00000000-0000-4000-8000-000000000001', status='completed', status_url='/status', events_url='/events')
    monkeypatch.setattr(env[0], '_replay', lambda *args: saved)
    monkeypatch.setattr(env[0].settings, 'NUMERIC_MODEL_BUNDLE', 'does-not-exist')
    assert submit_fixture(env) == saved
    env[3].add.assert_not_called()


@pytest.mark.parametrize('failure', ['missing_key', 'bad_bundle', 'runtime', 'none'])
def test_readiness_uses_same_strict_route(monkeypatch, tmp_path, failure):
    from app.services.numeric_model_dispatch import evaluate_configured_numeric_readiness
    from app.services.numeric_report_v3_admission import evaluate_numeric_v3_readiness
    from app.services import numeric_history_bundle
    from app.core.config import settings
    from test_synthetic_case_capability import case
    path = configure(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, 'NUMERIC_REPORTS_ENABLED', True)
    monkeypatch.setattr(settings, 'DEEPSEEK_API_KEY', '' if failure == 'missing_key' else 'fictional-key')
    if failure == 'bad_bundle': path.write_text('{}', encoding='utf-8')
    if failure == 'runtime':
        def fail(bundle): raise ValueError('numeric_history_implementation_changed')
        monkeypatch.setattr(numeric_history_bundle, 'verify_numeric_history_runtime', fail)
    for evaluate in (evaluate_configured_numeric_readiness, evaluate_numeric_v3_readiness):
        result = evaluate(case(), DB([]))
        assert result.ready is (failure == 'none')
        assert [b.code for b in result.blockers] == ([] if failure == 'none' else ['model_unavailable'])


def test_actual_readiness_caller_selects_v3(monkeypatch, tmp_path):
    from app.api import operator
    from app.core.config import settings
    from types import SimpleNamespace
    from test_synthetic_case_capability import case
    configure(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, 'NUMERIC_REPORTS_ENABLED', True)
    monkeypatch.setattr(settings, 'DEEPSEEK_API_KEY', 'fictional-key')
    monkeypatch.setattr(operator, 'get_operator_case', lambda *args: case())
    result = operator.get_longitudinal_report_readiness(17, 'numeric_prediction', DB([]), SimpleNamespace(id=8))
    assert result.ready is True


@pytest.mark.parametrize('mutation', ['missing_task', 'extra_task', 'unit', 'source_mismatch', 'extra_field'])
def test_context_rejects_strict_input_and_task_corruption(monkeypatch, tmp_path, mutation):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3
    configure(monkeypatch, tmp_path)
    raw = capture_configured_numeric_context(snapshot(), DB([])).model_dump(mode='json')
    if mutation == 'missing_task': raw['task_algorithms'].pop('ad.mmse.6m')
    elif mutation == 'extra_task': raw['task_algorithms']['unknown'] = raw['task_algorithms']['ad.mmse.6m']
    elif mutation == 'unit': raw['numeric_input']['packets'][0]['input_observations'][0]['unit'] = 'U/L'
    elif mutation == 'source_mismatch': raw['numeric_input']['packets'][0]['source']['run_id'] = 'other'
    else: raw['extra'] = True
    with pytest.raises(ValueError): NumericGenerationContextV3.model_validate(raw)


def test_dispatch_rejects_changed_loader_result(monkeypatch, tmp_path):
    from app.services.numeric_model_dispatch import load_configured_numeric_bundle
    from app.services import numeric_history_bundle
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    configure(monkeypatch, tmp_path)
    raw = history_bundle_fixture()
    raw['implementation_sha256'] = '8' * 64
    other = NumericHistoryBundle.model_validate(raw)
    monkeypatch.setattr(numeric_history_bundle, 'load_numeric_history_bundle', lambda path: other)
    with pytest.raises(ValueError, match='configuration_changed'): load_configured_numeric_bundle()


def test_final_dispatch_read_is_bounded(monkeypatch, tmp_path):
    from app.services.numeric_model_dispatch import load_configured_numeric_bundle
    from app.services import numeric_history_bundle
    path = configure(monkeypatch, tmp_path)
    original = numeric_history_bundle.load_numeric_history_bundle
    def changed(path):
        bundle = original(path)
        path.write_bytes(b' ' * (8 * 1024 * 1024 + 1))
        return bundle
    monkeypatch.setattr(numeric_history_bundle, 'load_numeric_history_bundle', changed)
    with pytest.raises(ValueError, match='file_too_large'): load_configured_numeric_bundle()


@pytest.mark.parametrize('task', ['ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m'])
def test_every_task_parameter_is_bound(monkeypatch, tmp_path, task):
    from app.services.numeric_model_dispatch import capture_configured_numeric_context
    from app.schemas.numeric_report_v3 import NumericGenerationContextV3
    configure(monkeypatch, tmp_path)
    raw = capture_configured_numeric_context(snapshot(), DB([])).model_dump(mode='json')
    raw['task_algorithms'][task]['parameters_sha256'] = 'f' * 64
    with pytest.raises(ValueError, match='identity_mismatch'): NumericGenerationContextV3.model_validate(raw)
