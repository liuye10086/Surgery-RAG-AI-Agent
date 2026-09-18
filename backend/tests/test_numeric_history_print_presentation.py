"""Saved v3 print behavior; no renderer, database or external model required."""
from copy import deepcopy
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

import pytest

from test_numeric_report_v3 import v3_inputs, saved_narrative


def history_package_fixture(tmp_path, disease='ad'):
    """Independent fictional package for S6; never rebind an existing source."""
    import hashlib
    import json
    from test_prediction_case_source import package_fixture
    directory = package_fixture(tmp_path, 'synthetic', disease)
    records = directory / 'records.jsonl'
    record = json.loads(records.read_text(encoding='utf-8'))
    if disease == 'ad':
        for packet in record['numeric_input']['packets']:
            packet['input_observations'] = [r for r in packet['input_observations'] if r['observation_id'] == packet['anchor_observation_id']]
            packet.update(history_state='confirmed_none', history_coverage='complete')
    data = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
    records.write_bytes(data)
    manifest_path = directory / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['records'] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    return directory


@pytest.mark.parametrize('disease', ['ad', 'fatty_liver'])
def test_archive_fixture_loads_as_an_independent_valid_package(tmp_path, disease):
    from app.services.prediction_case_source import load_prediction_case_package, numeric_display_visits
    from app.services.numeric_history_bundle import predict_numeric_history_bundle
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    from test_numeric_history_bundle import history_bundle_fixture
    profile, numeric = load_prediction_case_package(history_package_fixture(tmp_path, disease))[0]
    assert numeric.source.source_kind == 'synthetic'
    assert profile.age == 70
    prediction = predict_numeric_history_bundle(numeric, NumericHistoryBundle.model_validate(history_bundle_fixture()))
    assert [p.status for p in prediction.predictions] == (['available', 'abstain'] if disease == 'ad' else ['available', 'available'])
    assert [p.status for p in prediction.baseline_predictions] == ['available', 'available']
    assert [p.value for p in prediction.baseline_predictions] == ([22.0, 22.0] if disease == 'ad' else [47.5, 47.5])
    # This is the same input projection used when seed_prediction_cases creates
    # the fresh visit rows before binding the new case.
    visits = numeric_display_visits(numeric.model_dump(mode='json'))
    assert len(visits) == (1 if disease == 'ad' else 2)


def publication(disease='ad', history_state='confirmed_none', failure=None):
    from app.services.numeric_report_v3 import build_numeric_v3_document, build_numeric_v3_publication
    snapshot, context, prediction, evidence = v3_inputs(disease, history_state, failure)
    # Deliberately reversed persisted arrays must still print 6 then 12 months.
    prediction.predictions.reverse()
    prediction.baseline_predictions.reverse()
    document = build_numeric_v3_document(7, datetime(2026, 9, 16, tzinfo=timezone.utc), snapshot,
        context, prediction, evidence, saved_narrative(context, prediction, evidence))
    return build_numeric_v3_publication(snapshot, prediction, document)


def render(pub, **overrides):
    from app.services.pdf_generator import _markdown_to_safe_html
    args = dict(markdown_content=pub.content, prediction_result=pub.prediction_result,
        evidence_snapshot=pub.evidence_snapshot, report_document=pub.report_document.model_dump(mode='json'))
    args.update(overrides)
    return _markdown_to_safe_html(**args)


@pytest.mark.parametrize('disease', ['ad', 'fatty_liver'])
def test_print_v3_sorted_independent_values_and_algorithms(disease):
    pub = publication(disease)
    before = pub.model_dump(mode='json')
    root = ET.fromstring('<root>' + render(pub) + '</root>')
    table = next(t for t in root.iter('table') if '模型预测' in ''.join(t.itertext()))
    rows = [[c.text for c in row.findall('td')] for row in table.findall('tbody/tr')]
    assert [r[0] for r in rows] == ['6 月', '12 月']
    assert rows[0][3] == ('14.00' if disease == 'ad' else '26.75')
    assert [r[5] for r in rows] == (['22.00', '22.00'] if disease == 'ad' else ['47.50', '47.50'])
    assert [r[6] for r in rows] == ['可用', '可用']
    if disease == 'ad':
        assert rows[1][3] == '—'
        assert '历史不足' in rows[1][4]
        assert '随机森林' in rows[1][-1]
    else:
        assert rows[1][3] == '26.75'
        assert all('Ridge' in row[-1] for row in rows)
        assert '随机森林' not in ''.join(root.itertext())
    assert root.find("div[@class='numeric-references-print']/h2").text == '参考附录'
    assert list(root)[-1].attrib['class'] == 'numeric-versions-print'
    assert pub.model_dump(mode='json') == before


def test_print_v3_error_keeps_baseline_and_hides_raw_and_source():
    pub = publication(history_state='observed', failure='bounds')
    html = render(pub)
    root = ET.fromstring('<root>' + html + '</root>')
    table = next(t for t in root.iter('table') if '模型预测' in ''.join(t.itertext()))
    row = table.findall('tbody/tr')[1].findall('td')
    assert row[3].text == '—'
    assert row[5].text == '22.00'
    assert '计算失败' in row[4].text and '超出允许范围' in row[4].text
    assert 'raw_prediction' not in html and 'source_binding' not in html and 'synthetic' not in html
    assert '50.00' not in html


def test_v3_print_template_retains_numeric_layout_without_legacy_version_notice(monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.services.pdf_generator import generate_pdf
    rendered = []
    page = SimpleNamespace(route=lambda *a: None, set_content=lambda html, **kw: rendered.append(html),
        evaluate=lambda *a: None, pdf=lambda **kw: b'%PDF-controlled-boundary')
    browser = SimpleNamespace(new_page=lambda: page, close=lambda: None)
    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kw: browser))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    pub = publication()
    generate_pdf(pub.content, prediction_result=pub.prediction_result, evidence_snapshot=pub.evidence_snapshot,
        report_document=pub.report_document.model_dump(mode='json'))
    html = rendered[0]
    assert '<div class="content numeric-print">' in html
    assert '历史报告未记录' not in html
    assert '<div class="numeric-history-results-print">' in html
    from html import unescape
    assert html.index('参考附录') < unescape(html).index('numeric.mixed_history.v1')


@pytest.mark.parametrize('part', ['content', 'prediction', 'baseline', 'evidence', 'document'])
def test_print_v3_rejects_mismatched_saved_facts(part):
    pub = publication()
    overrides = {}
    if part == 'content':
        overrides['markdown_content'] = pub.content + '\n<script>alert(1)</script>'
    elif part in ('prediction', 'baseline'):
        changed = deepcopy(pub.prediction_result)
        changed['predictions' if part == 'prediction' else 'baseline_predictions'][1]['value'] += 1
        overrides['prediction_result'] = changed
    elif part == 'evidence':
        overrides['evidence_snapshot'] = {**pub.evidence_snapshot, 'query': 'changed'}
    else:
        changed = pub.report_document.model_dump(mode='json')
        changed['prediction']['baseline_predictions'][1]['value'] += 1
        overrides['report_document'] = changed
    with pytest.raises(ValueError):
        render(pub, **overrides)


HISTORY_RENDERER_SOURCES = (
    'schemas/numeric_report_v3.py', 'schemas/numeric_history_bundle.py',
    'schemas/numeric_history_prediction.py', 'services/numeric_report_v3.py',
    'services/numeric_history_bundle.py', 'services/numeric_history_features.py',
    'services/prediction_history_features.py', 'services/synthetic_prediction_cases.py',
)


@pytest.mark.parametrize('changed_source', HISTORY_RENDERER_SOURCES)
def test_history_renderer_rejects_source_drift(tmp_path, monkeypatch, changed_source):
    """Load a valid resource identity, then reject changed bytes in each v3 dependency."""
    import json
    from contextlib import contextmanager
    from types import SimpleNamespace
    from app.services import report_pdf_renderer_manifest as manifest
    from app.services.report_pdf_errors import PdfError
    app = tmp_path / 'app'
    # Include the independently specified v3 dependencies even before production
    # supports them; the initial successful load is the RED assertion.
    sources = {}
    for name in set(manifest.RENDERER_FILES) | set(HISTORY_RENDERER_SOURCES):
        path = app / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((manifest.APP_ROOT / name).read_bytes())
        sources[name] = manifest.file_sha(path)
    monkeypatch.setattr(manifest, 'APP_ROOT', app)
    font = tmp_path / 'font'; font.write_bytes(b'controlled font fixture')
    license_file = tmp_path / 'license'; license_file.write_bytes(b'controlled license fixture')
    chromium = tmp_path / 'chromium'; chromium.write_bytes(b'controlled executable fixture')
    @contextmanager
    def playwright():
        yield SimpleNamespace(chromium=SimpleNamespace(executable_path=str(chromium)))
    monkeypatch.setattr('playwright.sync_api.sync_playwright', playwright)
    raw = dict(schema_version='pdf_renderer.v1', source_files=sources,
        template_sha256=sources['templates/report_pdf.html'],
        chart_renderer_sha256=sources['services/report_document_builder.py'],
        markdown_adapter_sha256=sources['services/pdf_generator.py'],
        font_files=[dict(path='font', sha256=manifest.file_sha(font), license='license', license_sha256=manifest.file_sha(license_file))],
        playwright_version=manifest.importlib.metadata.version('playwright'),
        fonttools_version=manifest.importlib.metadata.version('fonttools'),
        chromium_version='fixture', chromium_sha256=manifest.file_sha(chromium),
        platform=manifest.platform.system(), print_options=manifest.PRINT_OPTIONS)
    path = tmp_path / 'manifest.json'; path.write_text(json.dumps(raw), encoding='utf-8')
    loaded, _ = manifest.load_renderer_manifest(path)
    assert loaded.source_files[changed_source] == sources[changed_source]
    with (app / changed_source).open('ab') as stream:
        stream.write(b'\n# changed rendering dependency\n')
    with pytest.raises(PdfError, match='pdf_renderer_unavailable'):
        manifest.load_renderer_manifest(path)
