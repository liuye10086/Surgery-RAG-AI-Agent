"""Real API/worker/browser/archive scenarios for frozen phase-four inputs."""
import hashlib
import json
from pathlib import Path
import sys
import traceback
from urllib.parse import urlsplit

from scripts.numeric_report_acceptance_browser import saved_facts as legacy_saved_facts

ROOT = Path(__file__).resolve().parents[1]
# The SPA is served by a Vite dev server: first paint depends on module
# transform, so wait for the rendered shell instead of guessing a delay.
SHELL_TIMEOUT_MS = 90000
MAX_BODY_TEXT = 4000


def safe_page_url(value):
    """Drop credentials, query and fragment from a browser URL."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme and parsed.hostname:
            port = ':%d' % parsed.port if parsed.port is not None else ''
            host = '[%s]' % parsed.hostname if ':' in parsed.hostname else parsed.hostname
            return '%s://%s%s%s' % (parsed.scheme, host, port, parsed.path)
    except ValueError:
        pass
    # Even when parsing fails (bad port, no scheme) never return userinfo.
    return value.rpartition('@')[2].split('?', 1)[0].split('#', 1)[0]


def shell_locator(page):
    """The operator-shell readiness signal.

    The sidebar nav exists whichever panel is active, so it is the condition to
    wait for. The case list is NOT: after a finished report the app returns to
    the report view, where that region is absent.
    """
    return page.get_by_role('button', name='我的病例', exact=True)


def save_browser_failure(output, page, page_errors, exc, result):
    """Persist safe evidence so a failed run leaves facts, never credentials."""
    diagnostic = {
        'page_url': safe_page_url(getattr(page, 'url', '') or ''),
        'page_error_types': sorted(set(page_errors)),
        'error_type': type(exc).__name__,
        'error_location': [{'file': Path(frame.filename).name, 'line': frame.lineno,
                            'function': frame.name}
                           for frame in traceback.extract_tb(exc.__traceback__)],
        'diagnostic_errors': [],
    }
    if page is not None:
        try:
            page.screenshot(path=str(output / 'browser-failure.png'), full_page=True)
        except Exception as error:
            diagnostic['diagnostic_errors'].append(
                {'stage': 'screenshot', 'error_type': type(error).__name__})
        try:
            diagnostic['body_text'] = page.locator('body').inner_text()[:MAX_BODY_TEXT]
        except Exception as error:
            diagnostic['diagnostic_errors'].append({'stage': 'body', 'error_type': type(error).__name__})
    result.setdefault('checks', {})['browser_failure'] = diagnostic
    try:
        (output / 'browser-failure.json').write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as error:
        diagnostic['diagnostic_errors'].append({'stage': 'json', 'error_type': type(error).__name__})


def saved_facts(detail):
    facts = legacy_saved_facts(detail)
    facts.update({name: detail[name] for name in (
        'sources', 'retrieval_meta', 'evidence_snapshot_sha256', 'report_document_sha256',
        'generation_context', 'context_sha256', 'generation_audit') if name in detail})
    return facts


def narrative_invocations(detail):
    events = [event for event in detail['generation_audit']['events']
              if event['task'] == 'report_narrative']
    started = [event for event in events if event['kind'] == 'invocation_started']
    finished = [event for event in events if event['kind'] == 'task_finished']
    assert len(started) == len(finished) == 1, 'narrative_invocation_count_mismatch'
    assert finished[0]['result_state'] == 'available', 'narrative_completion_missing'
    return {'invocation_started': len(started), 'task_finished': len(finished)}


def validate_legacy_document(document):
    context, prediction = document['generation_context'], document['prediction']
    assert context['prompt_version'] == document['narrative']['prompt_version'] == 'numeric_narrative.prompt.v1'
    # v2 has a shared Ridge identity; it does not have per-row v3 descriptors.
    assert context['model_bundle']['model_id'] == prediction['algorithm']['model_id'] == 'ridge:main_anchor'
    models = {model['task_id']: model for model in context['model_bundle']['models']}
    assert len(prediction['predictions']) == 2
    for row in prediction['predictions']:
        assert models[row['task_id']]['feature_names'] == ['anchor_value']


def validate_prediction(prediction, scenario):
    rows = sorted(prediction['predictions'], key=lambda row: row['horizon_months'])
    assert [row['horizon_months'] for row in rows] == [6, 12]
    assert len(prediction['baseline_predictions']) == 2
    assert all(row['status'] == 'available' and row['value'] is not None
               for row in prediction['baseline_predictions'])
    for row in rows:
        history = scenario.startswith('ad') and row['horizon_months'] == 12
        assert row['algorithm']['model_id'] == (
            'random_forest:history_v1:value_history' if history else 'ridge:main_anchor')
        if scenario == 'ad_partial' and history:
            assert (row['status'], row['value'], row['reason']) == ('abstain', None, 'history_not_observed')
        else:
            assert row['status'] == 'available' and row['value'] is not None


def verify_pdf(path, document, scenario):
    import pymupdf
    with pymupdf.open(path) as reader:
        text = ''.join(page.get_text() for page in reader)
        page_count = len(reader)
    for row in document['prediction']['predictions'] + document['prediction']['baseline_predictions']:
        if row['status'] == 'available':
            assert f"{row['value']:.2f}" in text, 'pdf_saved_value_missing'
    if scenario == 'ad_partial':
        compact = ''.join(text.split())
        assert '历史不足' in compact and '缺少已观察历史' in compact, 'pdf_partial_reason_missing'
    return page_count


def run_scenarios(args, identities, ids, tokens, owned, result):
    from playwright.sync_api import sync_playwright, expect
    output = args.output.resolve()
    api_command = [sys.executable, '-m', 'uvicorn', 'backend.tests.e2e.report_test_server:app',
                   '--host', '127.0.0.1', '--port', '18060']

    def restart_api(model):
        owned.stop('api')
        owned.env['NUMERIC_MODEL_BUNDLE'] = str(model.resolve())
        owned.start('api', api_command, ROOT)
        owned.ready('http://127.0.0.1:18060/health')

    restart_api(args.legacy_bundle)
    owned.start('frontend', ['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
        '--host', '127.0.0.1', '--port', '15173', '--strictPort'], ROOT / 'frontend')
    owned.ready('http://127.0.0.1:15173')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        page, errors = None, []
        try:
            context = browser.new_context(base_url='http://127.0.0.1:15173', viewport={'width': 1440, 'height': 1200})
            context.add_init_script('localStorage.setItem("token",' + json.dumps(tokens[0]) + ')')
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            auth, other, doctor = [{'Authorization': 'Bearer ' + token} for token in tokens]

            def write_json(name, value):
                (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

            def read(report_id):
                response = page.request.get(f'/api/v1/operator/reports/{report_id}', headers=auth)
                assert response.status == 200, 'report_read_failed'
                return response.json()

            def wait_for_shell():
                expect(shell_locator(page)).to_be_visible(timeout=SHELL_TIMEOUT_MS)

            def open_case(index):
                response = page.request.get(f'/api/v1/operator/longitudinal-cases/{ids[index]}', headers=auth)
                assert response.status == 200
                page.goto('/operator')
                wait_for_shell()
                page.get_by_role('button', name='我的病例', exact=True).click()
                page.locator('.case-list__item').filter(has_text=response.json()['anonymous_case_code']).click()
                expect(page.get_by_role('region', name='病例只读摘要')).to_be_visible()
                expect(page.get_by_text('已绑定版本的输入只读', exact=True)).to_be_visible()
                assert page.locator('.workspace input:not([disabled]),.workspace textarea:not([disabled]),.workspace select:not([disabled])').count() == 0

            def admit(version, index):
                scenario = identities['source']['cases'][index]['scenario']
                open_case(index)
                button = page.get_by_role('button', name='生成报告', exact=True)
                expect(button).to_be_enabled(timeout=15000)
                page.screenshot(path=str(output / f'{version}-{scenario}-case.png'), full_page=True)
                with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/report-jobs')) as captured:
                    button.click()
                response = captured.value
                assert response.status == 202
                assert response.request.post_data_json == {'model_options': {}, 'report_kind': 'numeric_prediction'}
                report_id = response.json()['report_id']
                detail = read(report_id)
                assert detail['status'] == 'generating'
                expected_context = 'numeric_generation_context.v2' if version == 'b' else 'numeric_generation_context.v3'
                assert detail['generation_context']['schema_version'] == expected_context
                if version == 'b':
                    assert detail['generation_context']['algorithm'] == identities['legacy']['algorithm']
                else:
                    assert detail['generation_context']['algorithm']['bundle_sha256'] == identities['history']['bundle_sha256']
                source = detail['input_snapshot']['numeric_input']['source']
                assert source['run_id'] == identities['source']['source_run_id']
                assert source['manifest_sha256'] == identities['source']['import_manifest_sha256']
                assert source['is_synthetic'] is True
                entry = {'version': version, 'scenario': scenario, 'case_id': ids[index], 'report_id': report_id,
                    'idempotency_key': response.request.headers['idempotency-key'], 'source': source}
                result['reports'].append(entry)
                write_json(f'{version}-{scenario}-queued.json', detail)
                return entry

            def replay(entry):
                response = page.request.post(f"/api/v1/operator/longitudinal-cases/{entry['case_id']}/report-jobs",
                    headers={**auth, 'Idempotency-Key': entry['idempotency_key']},
                    data={'model_options': {}, 'report_kind': 'numeric_prediction'})
                assert response.status == 202 and response.json()['report_id'] == entry['report_id']
                entry['idempotency_replayed_original'] = True

            def open_history(entry):
                page.goto('/operator')
                wait_for_shell()
                page.get_by_role('button', name='历史报告', exact=True).click()
                page.get_by_role('button', name='筛选', exact=True).click()
                row = page.locator(f'.history-row[data-report-id="{entry["report_id"]}"]')
                expect(row).to_be_visible(timeout=15000)
                row.locator('.open-report').click()
                expect(page.locator('.numeric-report')).to_be_visible(timeout=15000)

            def finish(entry):
                version, scenario, report_id = entry['version'], entry['scenario'], entry['report_id']
                result['external_llm']['worker_invocations'] += 1
                owned.worker('app.workers.report_worker')
                detail = read(report_id)
                write_json(f'{version}-{scenario}-report.json', detail)
                assert detail['status'] == 'completed', 'report_generation_failed'
                document = detail['report_document']
                expected = ('v5', 'numeric_report_document.v2') if version == 'b' else ('v6', 'numeric_report_document.v3')
                assert (detail['generation_fingerprint_version'], document['schema_version']) == expected
                assert detail['evidence_snapshot']['vector_status'] == detail['evidence_snapshot']['fulltext_status'] == 'complete'
                assert detail['evidence_snapshot']['items'], 'real_reference_retrieval_empty'
                assert document['narrative']['status'] == 'completed'
                entry['narrative_audit'] = narrative_invocations(detail)
                result['external_llm']['audited_invocations'] = (
                    result['external_llm'].get('audited_invocations', 0) + entry['narrative_audit']['invocation_started'])
                result['external_llm']['completed_reports'] += 1
                if version == 'c':
                    assert document['generation_context']['algorithm']['bundle_sha256'] == identities['history']['bundle_sha256']
                    validate_prediction(document['prediction'], scenario)
                else:
                    assert document['generation_context']['algorithm'] == identities['legacy']['algorithm']
                    validate_legacy_document(document)
                open_history(entry)
                result_region = page.get_by_role('region', name='6／12月数值结果')
                expect(result_region).to_be_visible()
                rows = result_region.locator('tbody tr')
                assert rows.count() == 2
                for index, prediction in enumerate(sorted(document['prediction']['predictions'], key=lambda row: row['horizon_months'])):
                    cells = rows.nth(index).locator('td').all_text_contents()
                    assert cells[3] == (f"{prediction['value']:.2f}" if prediction['status'] == 'available' else '—')
                    baseline = next(row for row in document['prediction']['baseline_predictions'] if row['task_id'] == prediction['task_id'])
                    assert cells[4] == f"{baseline['value']:.2f}"
                if scenario == 'ad_partial':
                    assert '历史不足，未预测' in rows.nth(1).inner_text()
                    assert '缺少已观察历史' in rows.nth(1).inner_text()
                    assert '随机森林' in rows.nth(1).inner_text()
                if version == 'c' and scenario == 'ad':
                    assert 'Ridge' in rows.nth(0).inner_text() and '随机森林' in rows.nth(1).inner_text()
                page.screenshot(path=str(output / f'{version}-{scenario}-report.png'), full_page=True)
                page.get_by_role('region', name='已保存的结果说明').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'{version}-{scenario}-narrative.png'), full_page=True)
                prepare = page.get_by_role('button', name='准备 PDF', exact=True)
                prepare.scroll_into_view_if_needed()
                expect(prepare).to_be_enabled(timeout=10000)
                prepare.click()
                expect(page.get_by_text('正在准备 PDF，可离开页面', exact=True)).to_be_visible(timeout=10000)
                owned.worker('app.workers.report_pdf_worker')
                download = page.get_by_role('button', name='下载 PDF', exact=True)
                expect(download).to_be_enabled(timeout=20000)
                with page.expect_download() as saved:
                    download.click()
                target = output / f'{version}-{scenario}.pdf'
                saved.value.save_as(target)
                response = page.request.get(f'/api/v1/operator/reports/{report_id}/download', headers=auth)
                assert response.status == 200 and response.body() == target.read_bytes()
                assert response.body().startswith(b'%PDF-')
                entry.update(pdf_sha256=hashlib.sha256(response.body()).hexdigest(),
                    pdf_pages=verify_pdf(target, document, scenario),
                    retrieved_count=len(detail['evidence_snapshot']['items']),
                    llm_response_model=document['narrative']['response_model'])
                for suffix in ('', '/download'):
                    assert page.request.get(f'/api/v1/operator/reports/{report_id}{suffix}', headers=other).status == 404
                    assert page.request.get(f'/api/v1/operator/reports/{report_id}{suffix}', headers=doctor).status == 403
                entry['non_owner_404_and_wrong_role_403'] = True
                replay(entry)
                return saved_facts(detail)

            originals = []
            old_liver = admit('b', 1)
            originals.append((old_liver, finish(old_liver)))
            old_ad = admit('b', 0)
            restart_api(args.history_bundle)
            replay(old_ad)
            originals.append((old_ad, finish(old_ad)))
            result['checks']['queued_v2_completed_with_c_selected'] = True
            for index in range(3):
                entry = admit('c', index)
                originals.append((entry, finish(entry)))

            # Cancel a genuine queued job without ever executing its model or LLM.
            open_case(0)
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/report-jobs')) as captured:
                page.get_by_role('button', name='生成报告', exact=True).click()
            assert captured.value.status == 202
            cancelled_id = captured.value.json()['report_id']
            page.get_by_role('button', name='取消生成', exact=True).click()
            expect(page.get_by_text('报告生成已取消；以下为已保存的资料和已确认审计记录。', exact=True)).to_be_visible(timeout=15000)
            assert read(cancelled_id)['status'] == 'cancelled'
            result['checks']['cancelled_report_id'] = cancelled_id
            page.screenshot(path=str(output / 'cancelled.png'), full_page=True)

            # No workers during history verification; both a valid rollback and
            # a missing current bundle must preserve already saved facts/bytes.
            for stage, selected in (('restored-b', args.legacy_bundle),
                                    ('missing-current-bundle', output / 'intentionally-absent-bundle.json')):
                restart_api(selected)
                for entry, original in originals:
                    report_id = entry['report_id']
                    assert saved_facts(read(report_id)) == original
                    response = page.request.get(f'/api/v1/operator/reports/{report_id}/download', headers=auth)
                    target = output / f"{entry['version']}-{entry['scenario']}.pdf"
                    assert response.status == 200 and response.body() == target.read_bytes()
                    entry[stage + '_history_and_pdf_unchanged'] = True
                    open_history(entry)
                    expect(page.get_by_role('button', name='下载 PDF', exact=True)).to_be_enabled(timeout=10000)
                    page.screenshot(path=str(output / f"{entry['version']}-{entry['scenario']}-{stage}.png"), full_page=True)
            restart_api(args.legacy_bundle)
            assert not errors, 'browser_page_errors'
            result['checks']['page_errors'] = errors
            assert result['external_llm']['completed_reports'] == 5
            assert result['external_llm']['audited_invocations'] == 5
        except BaseException as exc:
            save_browser_failure(output, page, errors, exc, result)
            raise
        finally:
            try:
                browser.close()
            except Exception as error:
                # A raising teardown must never replace the in-flight failure,
                # so record it as evidence instead of letting it propagate.
                result.setdefault('checks', {}).setdefault('browser_close_errors', []).append(
                    type(error).__name__)
