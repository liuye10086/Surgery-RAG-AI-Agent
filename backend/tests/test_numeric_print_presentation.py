from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import xml.etree.ElementTree as ET
import pytest


@pytest.mark.parametrize('value,expected', [(1.005,'1.01'), (22.56701016,'22.57'), (0,'0.00'), (-0.001,'0.00'), (None,'—')])
def test_print_result_rounding(value, expected):
    from app.services.pdf_generator import _numeric_display_value
    assert _numeric_display_value(value) == expected


def test_print_presentation_preserves_canonical_document_and_values():
    from test_numeric_report_v2 import v2_fixture
    from app.services.pdf_generator import _markdown_to_safe_html
    from app.services.numeric_report_v2 import render_numeric_v2_document
    _, pub = v2_fixture()
    document = pub.report_document.model_dump(mode='json')
    before = deepcopy(document)
    html = _markdown_to_safe_html(pub.content, pub.prediction_result, pub.evidence_snapshot, report_document=document)
    root = ET.fromstring('<root>'+html+'</root>')
    table = next(t for t in root.iter('table') if '模型预测' in ''.join(t.itertext()))
    rows = table.findall('tbody/tr')
    predictions = sorted(pub.report_document.prediction.predictions, key=lambda p:p.horizon_months)
    for row, prediction in zip(rows,predictions):
        expected = str(Decimal(str(prediction.value)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
        assert row.findall('td')[3].text == expected
    assert '展示值已四舍五入至两位小数' in html
    assert root.find("div[@class='numeric-references-print']/h2").text == '参考附录'
    assert list(root)[-1].attrib['class'] == 'numeric-versions-print'
    assert document == before
    assert render_numeric_v2_document(document) == pub.content


def test_print_reference_blocks_keep_all_ids_and_text_in_order():
    import markdown
    from test_numeric_report_v2 import v2_fixture
    from app.services.pdf_generator import _NumericPrintExtension
    _, pub = v2_fixture()
    content = '## 检索参考\n\n检索完成。\n\n### 参考 7：记录甲\n\n第一段。\n\n### 参考 3：记录乙\n\n第二段。\n\n## 模型与生成版本\n\n固定版本。'
    root = ET.fromstring('<root>'+markdown.markdown(content,extensions=[_NumericPrintExtension(pub.report_document)])+'</root>')
    blocks = root.findall("div[@class='numeric-references-print']/div[@class='numeric-reference-print']")
    assert [(b.find('h3').text, b.find('p').text) for b in blocks] == [('参考 7：记录甲','第一段。'),('参考 3：记录乙','第二段。')]
    assert list(root)[-1].find('h2').text == '模型与生成版本'
    assert list(root)[-1].find('p').text == '固定版本。'
