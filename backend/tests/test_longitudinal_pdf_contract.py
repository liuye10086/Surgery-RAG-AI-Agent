import markdown
import bleach
from pathlib import Path

from app.services import pdf_generator
from app.services.pdf_generator import ALLOWED_ATTRS, ALLOWED_TAGS


def test_pdf_template_reserves_page_margins_for_fragmented_content():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "templates"
        / "report_pdf.html"
    )
    template = template_path.read_text(encoding="utf-8")

    assert "margin: 20mm 22mm;" in template
    assert "margin: 0;" not in template


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


def test_pdf_html_groups_critical_sections_for_print_pagination():
    content = """# 纵向进展预测报告

## 1. 报告摘要

摘要正文。

## 7. 关键进展信号

- ALT：需要关注。

## 10. 人工复核重点

- 核对单位。

## 11. 模型和数据技术附录

附录正文。
"""

    html = pdf_generator._markdown_to_safe_html(content)

    assert '<div class="report-summary">' in html
    assert '<div class="signal-block">' in html
    assert '<div class="review-block">' in html
    assert "摘要正文。" in html
    assert "ALT：需要关注。" in html
    assert "核对单位。" in html


def test_pdf_only_charts_persisted_comparable_observation_series():
    prediction = {
        "observation": {
            "indicators": {
                "ALT": {
                    "unit": "U/L",
                    "unit_state": "consistent",
                    "series": [
                        {"visit_date": "2025-01-01", "value": 20, "unit": "U/L"},
                        {"visit_date": "2025-04-01", "value": 35, "unit": "U/L"},
                        {"visit_date": "2025-08-01", "value": 50, "unit": "U/L"},
                        {"visit_date": "2025-12-31", "value": 65, "unit": "U/L"},
                    ],
                },
                "体重": {
                    "unit": "kg",
                    "unit_state": "consistent",
                    "series": [
                        {"visit_date": "2025-01-01", "value": 80, "unit": "kg"},
                        {"visit_date": "2025-12-31", "value": 78, "unit": "kg"},
                    ],
                },
                "甘油三酯": {
                    "unit": None,
                    "unit_state": "conflict",
                    "series": [
                        {"visit_date": "2025-01-01", "value": 1.2, "unit": "mmol/L"},
                        {"visit_date": "2025-04-01", "value": 130, "unit": "mg/dL"},
                        {"visit_date": "2025-12-31", "value": 1.8, "unit": "mmol/L"},
                    ],
                },
            }
        }
    }
    content = """# 匿名纵向报告

## 4. 已观察到的纵向变化

| 指标 | 观察次数 |
| --- | ---: |
| ALT | 4 |
"""

    html = pdf_generator._markdown_to_safe_html(content, prediction)

    assert 'class="observed-charts-print"' in html
    assert '<div class="chart-title-print">' in html
    assert "ALT 已观察值趋势图" in html
    assert html.count("<circle") == 4
    assert "体重 已观察值趋势图" not in html
    assert "甘油三酯 已观察值趋势图" not in html
