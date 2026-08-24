import markdown
import bleach

from app.services.pdf_generator import ALLOWED_ATTRS, ALLOWED_TAGS


def test_longitudinal_markdown_keeps_required_sections_and_warning():
    content = """## 疾病阶段与进展结局预测

> 合成数据；不构成诊断

| 指标 | 趋势 |
| --- | --- |
| ALT | likely_rising |
"""
    html = bleach.clean(markdown.markdown(content, extensions=["tables"]), tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    assert "疾病阶段与进展结局预测" in html
    assert "合成数据" in html
    assert "不构成诊断" in html
    assert "<table>" in html
