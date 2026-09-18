"""Phase-four acceptance gates: no database, subprocess or external calls."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/run_numeric_history_acceptance.py'


def runner():
    assert SCRIPT.is_file(), 'phase-four acceptance runner is not implemented'
    spec = importlib.util.spec_from_file_location('history_acceptance', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def playwright_sync_api():
    """Import the real sync_api even if an earlier test left stubs behind.

    backend/tests/test_pdf_generation.py installs mock playwright entries and
    then pops them, leaving the real package half-imported for the rest of the
    session; a later `from playwright import sync_api` then re-executes
    playwright/sync_api/__init__.py against a parent without `_impl`. Dropping
    the whole hierarchy first guarantees a complete, consistent import.
    """
    import importlib
    import sys
    for name in [key for key in sys.modules
                 if key == 'playwright' or key.startswith('playwright.')]:
        del sys.modules[name]
    return importlib.import_module('playwright.sync_api')


def argv(tmp_path, *extra):
    return [
        '--source-dir', str(ROOT / 'outputs/synthetic-prediction-cases/2026-09-15-switch-v2'),
        '--legacy-bundle', str(ROOT / 'outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json'),
        '--history-bundle', str(ROOT / 'outputs/numeric-history-integration/2026-09-16-v1/bundle.json'),
        '--renderer', str(ROOT / 'outputs/numeric-history-renderers/2026-09-16-v1'
            '/328b86684e9c123ee776934b93e453a20ae4c49e4dbeb9929bcb0f53406acb6e/manifest.json'),
        '--output', str(tmp_path / 'output'), *extra]


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://test:secret@127.0.0.1/surgery_rag_phase4_test')
    for key in ('PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize('url', ['', 'postgresql://localhost/surgery_rag_test',
    'postgresql://localhost/business', 'postgresql://remote/surgery_rag_phase4_test',
    'postgresql://localhost/surgery_rag_phase4_test?host=remote',
    'postgresql://localhost/surgery_rag_phase4_test#secret',
    'postgresql://localhost/surgery_rag_phase4_test?',
    'postgresql://localhost/surgery_rag_phase4_test#'])
def test_rejects_unsafe_database_without_writing(tmp_path, monkeypatch, capsys, isolated, url):
    module = runner()
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    assert module.main(argv(tmp_path, '--apply', '--allow-external-llm')) == 2
    assert not (tmp_path / 'output').exists()
    assert 'secret' not in capsys.readouterr().out


@pytest.mark.parametrize('key', ['PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'])
def test_rejects_libpq_redirects(tmp_path, monkeypatch, isolated, key):
    module = runner()
    monkeypatch.setenv(key, 'secret-override')
    with pytest.raises(ValueError, match='isolated_test_database_required'):
        module.validate_database_url()


def test_apply_needs_external_authorization_before_reading_assets(tmp_path, isolated, capsys):
    module = runner()
    assert module.main(argv(tmp_path, '--apply')) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'external_llm_authorization_required'
    assert not (tmp_path / 'output').exists()


def test_existing_output_preserved(tmp_path, isolated):
    module = runner()
    output = tmp_path / 'output'
    output.mkdir()
    marker = output / 'original'
    marker.write_text('preserve')
    assert module.main(argv(tmp_path)) == 2
    assert marker.read_text() == 'preserve'


def test_argument_error_redacts_user_supplied_secrets(capsys):
    assert runner().main(['--database-url', 'postgresql://secret:password@host/db']) == 2
    assert json.loads(capsys.readouterr().out) == {'status': 'error', 'error': 'invalid_arguments'}


def test_actual_frozen_preflight_has_no_network_spawn_or_writes(tmp_path, monkeypatch, capsys, isolated):
    module = runner()
    import sqlalchemy
    def forbidden(*args, **kwargs):
        pytest.fail('preflight must not connect, spawn, or write')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(sqlalchemy, 'create_engine', forbidden)
    monkeypatch.setattr(Path, 'mkdir', forbidden)
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    monkeypatch.setattr(module, 'execute', forbidden)
    assert module.main(argv(tmp_path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['database_connected'] is False
    assert result['services_started'] is False
    identity = result['identities']
    assert identity['legacy']['bundle_sha256'] == module.LEGACY_SHA
    assert identity['history']['bundle_sha256'] == module.HISTORY_SHA
    assert [case['scenario'] for case in identity['source']['cases']] == ['ad', 'fatty_liver', 'ad_partial']
    assert identity['source']['cases'][0]['history_state'] == 'observed'
    assert identity['source']['cases'][2]['history_state'] == 'confirmed_none'
    assert not (tmp_path / 'output').exists()


def test_tampered_source_is_rejected_before_case_selection(tmp_path, monkeypatch, isolated):
    module = runner()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'manifest.json').write_text('{}')
    with pytest.raises(ValueError, match='frozen_source_mismatch'):
        module.inspect_source(source)


def test_renderer_drift_is_rejected_without_starting_driver(tmp_path, monkeypatch):
    module = runner()
    path = tmp_path / 'manifest.json'
    path.write_text('{}')
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('driver forbidden'))
    with pytest.raises(ValueError, match='frozen_renderer_mismatch'):
        module.inspect_renderer(path)


def test_owned_processes_are_reused():
    from scripts.run_numeric_report_acceptance import OwnedProcesses
    assert runner().OwnedProcesses is OwnedProcesses


def test_browser_validates_independent_partial_results():
    from scripts.numeric_history_acceptance_browser import validate_prediction
    partial = {'predictions': [
        {'horizon_months': 6, 'status': 'available', 'value': 20.0,
         'algorithm': {'model_id': 'ridge:main_anchor'}},
        {'horizon_months': 12, 'status': 'abstain', 'value': None, 'reason': 'history_not_observed',
         'algorithm': {'model_id': 'random_forest:history_v1:value_history'}}],
        'baseline_predictions': [{'status': 'available', 'value': 21.0}, {'status': 'available', 'value': 21.0}]}
    validate_prediction(partial, 'ad_partial')
    partial['predictions'][1]['value'] = 21.0
    with pytest.raises(AssertionError):
        validate_prediction(partial, 'ad_partial')


def test_execute_direct_call_cannot_bypass_external_authorization(tmp_path, isolated, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, 'preflight', lambda *a: pytest.fail('must stop before preflight'))
    with pytest.raises(ValueError, match='external_llm_authorization_required'):
        module.execute(SimpleNamespace(apply=True, allow_external_llm=False), {})


def test_execute_rechecks_identity_before_writing(tmp_path, isolated, monkeypatch):
    module = runner()
    monkeypatch.setattr(module, 'preflight', lambda *a: {'changed': True})
    args = SimpleNamespace(apply=True, allow_external_llm=True, output=tmp_path / 'output')
    with pytest.raises(ValueError, match='preflight_identity_changed'):
        module.execute(args, {'original': True})
    assert not args.output.exists()


def test_apply_renderer_failure_preserves_safe_failure_and_restores_env(tmp_path, isolated, monkeypatch):
    module = runner()
    from app.services import report_pdf_renderer_manifest
    import os
    original = dict(os.environ)
    monkeypatch.setattr(module, 'preflight', lambda *a: {})
    def fail(*args):
        raise RuntimeError('secret postgresql://private-credential@host/private')
    monkeypatch.setattr(report_pdf_renderer_manifest, 'load_renderer_manifest', fail)
    args = SimpleNamespace(apply=True, allow_external_llm=True, output=tmp_path / 'output',
        renderer=tmp_path / 'renderer', legacy_bundle=tmp_path / 'legacy')
    assert module.execute(args, {}) == 1
    raw = (args.output / 'result.json').read_text()
    result = json.loads(raw)
    assert result['status'] == 'failed'
    assert result['error_type'] == 'RuntimeError'
    assert result['error_location'][-1]['function'] == 'fail'
    assert 'secret' not in raw and 'credential' not in raw
    assert dict(os.environ) == original


def test_busy_port_never_kills_existing_listener():
    module = runner()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(ValueError, match='port_in_use'):
            module.require_free_ports((listener.getsockname()[1],))
        assert listener.fileno() >= 0


def test_pdf_verification_uses_installed_runtime_and_actual_saved_values(tmp_path):
    import fitz
    from scripts.numeric_history_acceptance_browser import verify_pdf
    target = tmp_path / 'report.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), '20.12 21.00')
        pdf.save(target)
    document = {'prediction': {'predictions': [{'status': 'available', 'value': 20.123}],
        'baseline_predictions': [{'status': 'available', 'value': 21.0}]}}
    assert verify_pdf(target, document, 'ad') == 1
    document['prediction']['predictions'][0]['value'] = 10.0
    with pytest.raises(AssertionError, match='pdf_saved_value_missing'):
        verify_pdf(target, document, 'ad')


def test_pdf_partial_reason_survives_layout_line_breaks(tmp_path):
    import pymupdf
    from scripts.numeric_history_acceptance_browser import verify_pdf
    target = tmp_path / 'partial.pdf'
    with pymupdf.open() as pdf:
        page = pdf.new_page()
        page.insert_text((50, 50), '历史不足\n缺少已观察\n历史', fontname='china-s')
        pdf.save(target)
    assert verify_pdf(target, {'prediction': {'predictions': [], 'baseline_predictions': []}}, 'ad_partial') == 1


@pytest.fixture
def successful_execution(tmp_path, isolated, monkeypatch):
    """Exercise execute's lifecycle with all external boundaries disabled."""
    module = runner()
    import sqlalchemy
    import sqlalchemy.orm
    from app.services import report_pdf_renderer_manifest, prediction_case_source
    from app.core import security
    from scripts import numeric_report_acceptance_browser, numeric_history_acceptance_browser
    events = []
    class Database:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def execute(self, statement, params=None):
            value = '0031' if str(statement).startswith('SELECT version_num') else 0
            return SimpleNamespace(scalar_one=lambda: value)
    class Engine:
        def connect(self):
            return Database()
        def begin(self):
            return Database()
        def dispose(self):
            events.append('engine_disposed')
    class Processes:
        def close(self):
            events.append('owned_closed')
    engine, owned = Engine(), Processes()
    monkeypatch.setattr(module, 'preflight', lambda *a: {'source': {}})
    monkeypatch.setattr(report_pdf_renderer_manifest, 'load_renderer_manifest', lambda *a: (None, module.RENDERER_SHA))
    monkeypatch.setattr(sqlalchemy, 'create_engine', lambda *a: engine)
    monkeypatch.setattr(sqlalchemy.orm, 'sessionmaker', lambda *a, **k: object())
    monkeypatch.setattr(prediction_case_source, 'seed_prediction_cases', lambda *a: [1, 2, 3])
    monkeypatch.setattr(numeric_report_acceptance_browser, 'convert_source_package', lambda *a: tmp_path)
    monkeypatch.setattr(security, 'create_access_token', lambda *a: 'test-token')
    monkeypatch.setattr(module, 'OwnedProcesses', lambda *a: owned)
    monkeypatch.setattr(numeric_history_acceptance_browser, 'run_scenarios', lambda *a: events.append('scenarios_completed'))
    args = SimpleNamespace(apply=True, allow_external_llm=True, output=tmp_path / 'output',
        renderer=tmp_path / 'renderer', legacy_bundle=tmp_path / 'legacy', source_dir=tmp_path / 'source')
    return module, args, engine, owned, events


@pytest.mark.parametrize('fail_owned,fail_engine', [(True, False), (False, True), (True, True)])
def test_cleanup_failures_fail_result_and_attempt_each_cleanup(successful_execution, monkeypatch, fail_owned, fail_engine):
    import os
    module, args, engine, owned, events = successful_execution
    previous = dict(os.environ)
    def close():
        events.append('owned_closed')
        if fail_owned:
            raise RuntimeError('secret-owned-close')
    def dispose():
        events.append('engine_disposed')
        if fail_engine:
            raise OSError('secret-engine-dispose')
    monkeypatch.setattr(owned, 'close', close)
    monkeypatch.setattr(engine, 'dispose', dispose)
    assert module.execute(args, {'source': {}}) == 1
    assert events == ['scenarios_completed', 'owned_closed', 'engine_disposed']
    raw = (args.output / 'result.json').read_text()
    result = json.loads(raw)
    assert result['status'] == 'failed'
    assert [item['stage'] for item in result['cleanup_errors']] == (
        (['owned_processes'] if fail_owned else []) + (['database_engine'] if fail_engine else []))
    assert 'secret-' not in raw
    assert dict(os.environ) == previous


def test_result_write_failure_returns_failure_and_restores_environment(successful_execution, monkeypatch, capsys):
    import os
    module, args, engine, owned, events = successful_execution
    previous = dict(os.environ)
    def cannot_write(*args, **kwargs):
        raise OSError('secret-storage-error')
    monkeypatch.setattr(Path, 'write_text', cannot_write)
    assert module.execute(args, {'source': {}}) == 1
    assert events == ['scenarios_completed', 'owned_closed', 'engine_disposed']
    assert dict(os.environ) == previous
    message = json.loads(capsys.readouterr().out)
    assert message == {'status': 'failed', 'error': 'acceptance_result_write_failed', 'error_type': 'OSError'}


def test_success_is_returned_only_after_cleanup_and_result_written(successful_execution):
    module, args, engine, owned, events = successful_execution
    assert module.execute(args, {'source': {}}) == 0
    assert events == ['scenarios_completed', 'owned_closed', 'engine_disposed']
    assert json.loads((args.output / 'result.json').read_text())['status'] == 'passed'


@pytest.mark.parametrize('field', ['sources', 'retrieval_meta', 'evidence_snapshot_sha256',
    'report_document_sha256', 'generation_context', 'context_sha256'])
def test_history_comparison_detects_saved_evidence_and_context_changes(field):
    from scripts.numeric_history_acceptance_browser import saved_facts
    original = {'id': 1, 'status': 'completed', field: {'saved': 'original'}, 'download_count': 0}
    assert saved_facts(original) != saved_facts({**original, field: {'saved': 'changed'}})
    assert saved_facts(original) == saved_facts({**original, 'download_count': 2})


def test_audit_requires_exactly_one_started_and_completed_narrative():
    from scripts.numeric_history_acceptance_browser import narrative_invocations
    events = [{'kind': 'invocation_started', 'task': 'report_narrative', 'phase': 'rendering'},
        {'kind': 'task_finished', 'task': 'report_narrative', 'phase': 'rendering', 'result_state': 'available'}]
    detail = {'generation_audit': {'events': events}}
    assert narrative_invocations(detail) == {'invocation_started': 1, 'task_finished': 1}
    with pytest.raises(AssertionError):
        narrative_invocations({'generation_audit': {'events': events + [events[0]]}})
    with pytest.raises(AssertionError):
        narrative_invocations({'generation_audit': {'events': events[:1]}})


def test_legacy_completion_keeps_prompt_and_ridge_for_both_saved_tasks():
    from scripts.numeric_history_acceptance_browser import validate_legacy_document
    document = {
        'generation_context': {'prompt_version': 'numeric_narrative.prompt.v1', 'model_bundle': {
            'model_id': 'ridge:main_anchor', 'models': [
                {'task_id': 'ad.mmse.6m', 'feature_names': ['anchor_value']},
                {'task_id': 'ad.mmse.12m', 'feature_names': ['anchor_value']}] }},
        'narrative': {'prompt_version': 'numeric_narrative.prompt.v1'},
        'prediction': {'algorithm': {'model_id': 'ridge:main_anchor'}, 'predictions': [
            {'task_id': 'ad.mmse.6m'}, {'task_id': 'ad.mmse.12m'}]}}
    validate_legacy_document(document)
    document['generation_context']['prompt_version'] = 'numeric_narrative.prompt.v2'
    with pytest.raises(AssertionError):
        validate_legacy_document(document)


@pytest.mark.parametrize('diagnostic_failure', [None, 'screenshot', 'json'])
def test_browser_failure_saves_safe_diagnostics_and_always_closes(tmp_path, monkeypatch, diagnostic_failure):
    from scripts import numeric_history_acceptance_browser as browser_module
    sync_api = playwright_sync_api()
    events = []
    class Page:
        url = 'http://user:secret@127.0.0.1:15173/operator?token=secret#secret'
        request = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
            status=200, json=lambda: {'anonymous_case_code': 'CASE-TEST'}))
        def on(self, event, callback):
            callback(RuntimeError('secret page message'))
        def goto(self, *args):
            raise TimeoutError('secret navigation message')
        def screenshot(self, **kwargs):
            events.append('screenshot_attempted')
            assert kwargs['path'] == str(tmp_path / 'browser-failure.png')
            if diagnostic_failure == 'screenshot':
                raise RuntimeError('secret screenshot error')
    page = Page()
    context = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page)
    browser = SimpleNamespace(new_context=lambda **k: context, close=lambda: events.append('browser_closed'))
    class Runtime:
        chromium = SimpleNamespace(launch=lambda **k: browser)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append('driver_closed')
    monkeypatch.setattr(sync_api, 'sync_playwright', Runtime)
    if diagnostic_failure == 'json':
        def fail_write(*args, **kwargs):
            raise OSError('secret write error')
        monkeypatch.setattr(Path, 'write_text', fail_write)
    owned = SimpleNamespace(env={}, stop=lambda *a: None, start=lambda *a: None, ready=lambda *a: None)
    args = SimpleNamespace(output=tmp_path, legacy_bundle=tmp_path / 'legacy')
    identities = {'source': {'cases': [{'scenario': 'ad'}, {'scenario': 'fatty_liver'}]}}
    result = {'checks': {}}
    with pytest.raises(TimeoutError, match='secret navigation message'):
        browser_module.run_scenarios(args, identities, [1, 2], ['token-a', 'token-b', 'token-c'], owned, result)
    assert events == ['screenshot_attempted', 'browser_closed', 'driver_closed']
    diagnostic = result['checks']['browser_failure']
    assert diagnostic['page_url'] == 'http://127.0.0.1:15173/operator'
    assert diagnostic['page_error_types'] == ['RuntimeError']
    assert diagnostic['error_type'] == 'TimeoutError'
    assert diagnostic['error_location'][-1]['function'] == 'goto'
    assert 'secret' not in json.dumps(diagnostic)
    if diagnostic_failure != 'json':
        assert json.loads((tmp_path / 'browser-failure.json').read_text()) == diagnostic
    else:
        assert diagnostic['diagnostic_errors'][-1] == {'stage': 'json', 'error_type': 'OSError'}


def test_shell_readiness_uses_the_sidebar_nav_not_the_case_list():
    """The v2 failure used the case-list region, absent on the report view."""
    from scripts.numeric_history_acceptance_browser import shell_locator
    calls = []
    class Page:
        def get_by_role(self, role, name=None, exact=False):
            calls.append((role, name, exact))
            return 'locator'
    assert shell_locator(Page()) == 'locator'
    assert calls == [('button', '我的病例', True)]


@pytest.mark.parametrize('value,expected', [
    ('http://127.0.0.1:15173/operator', 'http://127.0.0.1:15173/operator'),
    ('http://user:secret@127.0.0.1:15173/operator?token=secret#frag', 'http://127.0.0.1:15173/operator'),
    ('http://user:secret@127.0.0.1:99999/operator', '127.0.0.1:99999/operator'),
    ('http://user:secret@127.0.0.1:abc/operator', '127.0.0.1:abc/operator'),
    ('user:secret@host/path', 'host/path'),
    ('http://[::1]:15173/operator?t=secret', 'http://[::1]:15173/operator'),
    ('about:blank', 'about:blank'),
])
def test_safe_page_url_never_returns_credentials(value, expected):
    from scripts.numeric_history_acceptance_browser import safe_page_url
    result = safe_page_url(value)
    assert result == expected
    assert 'secret' not in result


def test_browser_close_failure_does_not_replace_the_original_failure(tmp_path, monkeypatch):
    from scripts import numeric_history_acceptance_browser as browser_module
    sync_api = playwright_sync_api()
    events = []
    class Page:
        url = 'http://127.0.0.1:15173/operator'
        request = SimpleNamespace(get=lambda *a, **k: SimpleNamespace(
            status=200, json=lambda: {'anonymous_case_code': 'CASE-TEST'}))
        def on(self, event, callback):
            callback(RuntimeError('page error'))
        def goto(self, *args):
            raise TimeoutError('original failure')
        def screenshot(self, **kwargs):
            events.append('screenshot')
    page = Page()
    context = SimpleNamespace(add_init_script=lambda *a: None, new_page=lambda: page)
    def close():
        events.append('browser_closed')
        raise RuntimeError('teardown exploded')
    browser = SimpleNamespace(new_context=lambda **k: context, close=close)
    class Runtime:
        chromium = SimpleNamespace(launch=lambda **k: browser)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            events.append('driver_closed')
    monkeypatch.setattr(sync_api, 'sync_playwright', Runtime)
    owned = SimpleNamespace(env={}, stop=lambda *a: None, start=lambda *a: None, ready=lambda *a: None)
    args = SimpleNamespace(output=tmp_path, legacy_bundle=tmp_path / 'legacy')
    identities = {'source': {'cases': [{'scenario': 'ad'}, {'scenario': 'fatty_liver'}]}}
    result = {'checks': {}}
    with pytest.raises(TimeoutError, match='original failure'):
        browser_module.run_scenarios(args, identities, [1, 2], ['a', 'b', 'c'], owned, result)
    assert events == ['screenshot', 'browser_closed', 'driver_closed']
    assert result['checks']['browser_close_errors'] == ['RuntimeError']
    assert result['checks']['browser_failure']['error_type'] == 'TimeoutError'
