"""Real browser scenarios used only by run_numeric_report_acceptance.py."""
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DISEASES = ('ad', 'fatty_liver')


def convert_source_package(source_dir, identity, output):
    """Retain verified synthetic facts while exercising the current import contract."""
    from app.services.synthetic_case_source import load_synthetic_case_package
    from app.services.prediction_case_source import convert_legacy_input, load_prediction_case_package
    from app.schemas.prediction_case_source import PredictionPackageManifest, PredictionPackageRecord
    rows = []
    source = None
    for patient, old in load_synthetic_case_package(source_dir, identity['subjects']):
        numeric = convert_legacy_input(old).model_dump(mode='json')
        source = numeric.pop('source')
        source.pop('manifest_sha256')
        source.pop('input_file_sha256')
        source.update(dataset_id='numeric_acceptance.synthetic_prediction_cases', dataset_version=identity['source_run_id'])
        for packet in numeric['packets']:
            packet['source'] = source
        rows.append(PredictionPackageRecord(age=patient.age, sex=patient.sex,
            baseline_stage=patient.baseline_stage, numeric_input=numeric).model_dump(mode='json'))
    content = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode('utf-8')
    manifest = PredictionPackageManifest(schema_version='prediction_case_package.v1', source=source,
        records={'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()},
        record_count=len(rows), clinical_validity_claim=False)
    output.mkdir(exist_ok=False)
    (output / 'records.jsonl').write_bytes(content)
    raw = manifest.model_dump_json(indent=2).encode('utf-8')
    (output / 'manifest.json').write_bytes(raw)
    load_prediction_case_package(output)
    identity['import_manifest_sha256'] = hashlib.sha256(raw).hexdigest()
    identity['dataset_id'] = source['dataset_id']
    identity['dataset_version'] = source['dataset_version']
    return output


def saved_facts(detail):
    """Exclude mutable delivery counters; compare all saved clinical/generation facts."""
    fields = ('id', 'status', 'content', 'input_snapshot', 'input_snapshot_sha256',
              'prediction_result', 'evidence_snapshot', 'report_document',
              'generation_fingerprint', 'generation_fingerprint_version')
    return {name: detail[name] for name in fields if name in detail}


def run_scenarios(args, identities, ids, tokens, owned, result):
    from playwright.sync_api import sync_playwright, expect
    output = args.output.resolve()
    api_command = [sys.executable, '-m', 'uvicorn', 'backend.tests.e2e.report_test_server:app',
                   '--host', '127.0.0.1', '--port', '18060']

    def restart_api(model, enabled=True):
        owned.stop('api')
        owned.env['NUMERIC_MODEL_BUNDLE'] = str(model.resolve())
        owned.env['NUMERIC_REPORTS_ENABLED'] = str(enabled).lower()
        owned.start('api', api_command, ROOT)
        owned.ready('http://127.0.0.1:18060/health')

    restart_api(args.model_a)
    owned.start('frontend', ['node', str(ROOT / 'frontend/node_modules/vite/bin/vite.js'),
        '--host', '127.0.0.1', '--port', '15173', '--strictPort'], ROOT / 'frontend')
    owned.ready('http://127.0.0.1:15173')
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            context = browser.new_context(base_url='http://127.0.0.1:15173', viewport={'width': 1440, 'height': 1200})
            context.add_init_script('localStorage.setItem("token",' + json.dumps(tokens[0]) + ')')
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            auth = {'Authorization': 'Bearer ' + tokens[0]}
            other = {'Authorization': 'Bearer ' + tokens[1]}

            def read(report_id):
                response = page.request.get(f'/api/v1/operator/reports/{report_id}', headers=auth)
                assert response.status == 200, 'report_read_failed'
                return response.json()

            def open_case(case_id):
                response = page.request.get(f'/api/v1/operator/longitudinal-cases/{case_id}', headers=auth)
                assert response.status == 200
                page.goto('/operator')
                page.get_by_role('button', name='我的病例', exact=True).click()
                page.locator('.case-list__item').filter(has_text=response.json()['anonymous_case_code']).click()
                expect(page.get_by_role('region', name='病例只读摘要')).to_be_visible()
                expect(page.get_by_text('已绑定版本的输入只读', exact=True)).to_be_visible()
                assert page.locator('.workspace input:not([disabled]),.workspace textarea:not([disabled]),.workspace select:not([disabled])').count() == 0

            def admit(label, index):
                disease = DISEASES[index]
                case_id = ids[label][index]
                open_case(case_id)
                button = page.get_by_role('button', name='生成报告', exact=True)
                expect(button).to_be_enabled(timeout=15000)
                page.screenshot(path=str(output / f'{label}-{disease}-case.png'), full_page=True)
                with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/report-jobs')) as captured:
                    button.click()
                response = captured.value
                assert response.status == 202
                assert response.request.post_data_json == {'model_options': {}, 'report_kind': 'numeric_prediction'}
                key = response.request.headers['idempotency-key']
                report_id = response.json()['report_id']
                detail = read(report_id)
                assert detail['status'] == 'generating'
                assert detail['generation_context']['algorithm'] == identities[label]['algorithm']
                source = detail['input_snapshot']['numeric_input']['source']
                assert source['run_id'] == identities[label]['source_run_id']
                assert source['is_synthetic'] is True
                expected_manifest = identities[label].get('import_manifest_sha256', identities[label]['source_manifest_sha256'])
                assert source['manifest_sha256'] == expected_manifest
                if label == 'b':
                    assert (source['dataset_id'], source['dataset_version']) == (identities[label]['dataset_id'], identities[label]['dataset_version'])
                entry = {'version': label, 'disease': disease, 'case_id': case_id, 'report_id': report_id,
                         'idempotency_key': key, 'source': source, 'admission_model': identities[label]['algorithm']}
                result['reports'].append(entry)
                return entry

            def replay(entry):
                response = page.request.post(f"/api/v1/operator/longitudinal-cases/{entry['case_id']}/report-jobs",
                    headers={**auth, 'Idempotency-Key': entry['idempotency_key']},
                    data={'model_options': {}, 'report_kind': 'numeric_prediction'})
                assert response.status == 202
                assert response.json()['report_id'] == entry['report_id']
                entry['idempotency_replayed_original'] = True

            def finish(entry):
                label, disease, report_id = entry['version'], entry['disease'], entry['report_id']
                owned.worker('app.workers.report_worker')
                detail = read(report_id)
                # Preserve failed terminal snapshots too; never rerun a failed LLM call.
                (output / f'{label}-{disease}-report.json').write_text(json.dumps(detail, ensure_ascii=False, indent=2), encoding='utf-8')
                assert detail['status'] == 'completed', 'report_generation_failed'
                assert detail['generation_fingerprint_version'] == 'v5'
                assert detail['report_document']['generation_context']['algorithm'] == identities[label]['algorithm']
                assert detail['evidence_snapshot']['vector_status'] == detail['evidence_snapshot']['fulltext_status'] == 'complete'
                assert detail['evidence_snapshot']['items']
                assert detail['report_document']['narrative']['status'] == 'completed'
                # Open saved history through the real page even when API restarted mid-queue.
                page.goto('/operator')
                page.get_by_role('button', name='历史报告', exact=True).click()
                # The update banner may already disappear after automatic refresh.
                # The filter action is always present and requests current history.
                page.get_by_role('button', name='筛选', exact=True).click()
                row = page.locator(f'.history-row[data-report-id="{report_id}"]')
                expect(row).to_be_visible(timeout=15000)
                row.locator('.open-report').click()
                expect(page.locator('.numeric-report')).to_be_visible(timeout=15000)
                assert not any(word in page.locator('.report-inner').inner_text()
                               for word in ('合成', 'synthetic', '工程绑定', '来源批次'))
                expect(page.get_by_role('region', name='6／12月数值结果')).to_be_visible()
                assert page.locator('.numeric-report tbody tr').count() >= 2
                page.screenshot(path=str(output / f'{label}-{disease}-report.png'), full_page=True)
                page.get_by_role('region', name='已保存的结果说明').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'{label}-{disease}-narrative.png'), full_page=True)
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
                target = output / f'{label}-{disease}.pdf'
                saved.value.save_as(target)
                response = page.request.get(f'/api/v1/operator/reports/{report_id}/download', headers=auth)
                assert response.status == 200 and response.body() == target.read_bytes()
                assert response.body().startswith(b'%PDF-')
                entry.update(pdf_sha256=hashlib.sha256(response.body()).hexdigest(),
                    retrieved_count=len(detail['evidence_snapshot']['items']),
                    llm_response_model=detail['report_document']['narrative']['response_model'])
                for suffix in ('', '/download'):
                    assert page.request.get(f'/api/v1/operator/reports/{report_id}{suffix}', headers=other).status == 404
                entry['owner_404'] = True
                replay(entry)
                return saved_facts(detail)

            # Four genuine LLM calls: A fatty liver first, A AD queued across switch,
            # then B AD and fatty liver. No automatic retries or fake adapters.
            old_liver = admit('a', 1)
            old_liver_facts = finish(old_liver)
            old_ad = admit('a', 0)
            queued = read(old_ad['report_id'])
            (output / 'a-ad-queued.json').write_text(json.dumps(queued, ensure_ascii=False, indent=2), encoding='utf-8')
            restart_api(args.model_b)
            replay(old_liver)
            replay(old_ad)
            old_ad_facts = finish(old_ad)
            result['checks']['queued_a_executed_with_current_b'] = True
            originals = [(old_liver, old_liver_facts), (old_ad, old_ad_facts)]
            for index in range(2):
                entry = admit('b', index)
                originals.append((entry, finish(entry)))
            assert old_ad['source']['dataset_version'] != result['reports'][2]['source']['dataset_version']

            # Explicit queued cancellation without invoking a report worker.
            open_case(ids['b'][0])
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/report-jobs')) as captured:
                page.get_by_role('button', name='生成报告', exact=True).click()
            assert captured.value.status == 202
            cancelled_id = captured.value.json()['report_id']
            page.get_by_role('button', name='取消生成', exact=True).click()
            expect(page.get_by_text('报告生成已取消；以下为已保存的资料和已确认审计记录。', exact=True)).to_be_visible(timeout=15000)
            assert page.locator('.numeric-report tbody tr').count() == 0
            assert read(cancelled_id)['status'] == 'cancelled'
            page.screenshot(path=str(output / 'cancelled.png'), full_page=True)
            result['checks']['cancelled_report_id'] = cancelled_id

            restart_api(args.model_b, enabled=False)
            open_case(ids['b'][0])
            expect(page.get_by_text('数值预测报告功能未启用，不能生成报告。', exact=True)).to_be_visible(timeout=15000)
            assert page.get_by_role('button', name='生成报告', exact=True).count() == 0
            rejected = page.request.post(f"/api/v1/operator/longitudinal-cases/{ids['b'][0]}/report-jobs",
                headers={**auth, 'Idempotency-Key': str(uuid4())}, data={'model_options': {}, 'report_kind': 'numeric_prediction'})
            assert rejected.status in (409, 503), 'closed_gate_http_not_rejected'
            page.screenshot(path=str(output / 'feature-closed.png'), full_page=True)
            result['checks']['closed_gate_http_status'] = rejected.status
            # Saved facts and archive bytes stay identical after restart with B active
            # and admission closed. No worker is running during these reads.
            for entry, original in originals:
                report_id = entry['report_id']
                assert saved_facts(read(report_id)) == original
                raw = page.request.get(f'/api/v1/operator/reports/{report_id}/download', headers=auth)
                target = output / f"{entry['version']}-{entry['disease']}.pdf"
                assert raw.status == 200 and raw.body() == target.read_bytes()
                entry['restart_history_and_pdf_unchanged'] = True
                page.goto('/operator')
                page.get_by_role('button', name='历史报告', exact=True).click()
                page.get_by_role('button', name='筛选', exact=True).click()
                row = page.locator(f'.history-row[data-report-id="{report_id}"]')
                expect(row).to_be_visible(timeout=15000)
                row.locator('.open-report').click()
                expect(page.locator('.numeric-report')).to_be_visible()
                expect(page.get_by_role('button', name='下载 PDF', exact=True)).to_be_enabled(timeout=10000)
                page.screenshot(path=str(output / f"{entry['version']}-{entry['disease']}-history-restarted.png"), full_page=True)
            assert not errors, 'browser_page_errors'
            result['checks']['page_errors'] = errors
            result['checks']['completed_external_llm_reports'] = 4
        finally:
            browser.close()
