from copy import deepcopy
import pytest
from test_synthetic_report_publication import build_fixture
from app.services.pdf_generator import _markdown_to_safe_html


def test_synthetic_pdf_html_uses_saved_numeric_values_without_clinical_evidence():
    _, publication = build_fixture()
    html = _markdown_to_safe_html(publication.content, publication.prediction_result,
        publication.evidence_snapshot, report_document=publication.report_document.model_dump(mode='json'))
    assert '<table>' in html and '2024-02-29' in html and '2024-08-31' in html
    assert '尚无临床有效性结论' in html and '未执行临床标准评价' in html
    assert '22' in html and '临床获批' not in html


@pytest.mark.parametrize('field', ['content', 'prediction', 'evidence'])
def test_pdf_rejects_mismatched_saved_numeric_parts(field):
    _, publication = build_fixture()
    content, prediction, evidence = publication.content, deepcopy(publication.prediction_result), deepcopy(publication.evidence_snapshot)
    if field == 'content': content += '<script>alert(1)</script>'
    if field == 'prediction': prediction['predictions'][0]['value'] = 99
    if field == 'evidence': evidence['clinical_validity_claim'] = True
    with pytest.raises(ValueError):
        _markdown_to_safe_html(content, prediction, evidence,
            report_document=publication.report_document.model_dump(mode='json'))


def test_numeric_pdf_keeps_unavailable_results_empty_and_explains_reason():
    _, publication = build_fixture(unavailable=True)
    html = _markdown_to_safe_html(publication.content, publication.prediction_result,
        publication.evidence_snapshot, report_document=publication.report_document.model_dump(mode='json'))
    from xml.etree import ElementTree
    tables = ElementTree.fromstring('<div>' + html + '</div>').findall('table')
    rows = [[cell.text for cell in row.findall('td')] for row in tables[1].findall('tbody/tr')]
    assert [(row[3], row[4], row[6]) for row in rows] == [('不可用', '—', '人群条件尚未确认')] * 2


@pytest.mark.parametrize('document', [None, {'schema_version': 'synthetic_numeric_report_document.v2'}])
def test_numeric_pdf_never_falls_back_for_missing_or_unknown_document(document):
    _, publication = build_fixture()
    with pytest.raises(ValueError):
        _markdown_to_safe_html(publication.content, publication.prediction_result,
            publication.evidence_snapshot, report_document=document)
