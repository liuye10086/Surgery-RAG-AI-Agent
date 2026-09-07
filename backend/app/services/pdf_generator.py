"""AI 操作者报告 PDF 生成服务。

管道：
  1. markdown.markdown(content) → HTML
  2. bleach.clean(html, tags=ALLOWED_TAGS, ...) → 安全 HTML
  3. Jinja2 渲染完整 HTML
  4. Playwright（无头 Chromium）→ PDF bytes
"""

import asyncio
import html as _html
import logging
import math
import sys
import xml.etree.ElementTree as etree
from pathlib import Path
from typing import Any

import bleach
import markdown
from jinja2 import Environment, FileSystemLoader
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

# Windows 上 Playwright 需要 ProactorEventLoop 才能生成子进程
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 允许的 HTML 标签白名单
# ---------------------------------------------------------------------------

ALLOWED_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "ul",
    "ol",
    "li",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "strong",
    "em",
    "code",
    "pre",
    "blockquote",
    "hr",
    "br",
    "sup",
    "sub",
    "a",
    "span",
    "div",
    "svg",
    "line",
    "polyline",
    "circle",
    "text",
}

ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "span": ["class"],
    "div": ["class"],
    "th": ["align"],
    "td": ["align"],
    "svg": ["viewBox", "role", "aria-label"],
    "line": ["x1", "y1", "x2", "y2"],
    "polyline": ["points"],
    "circle": ["cx", "cy", "r"],
    "text": ["x", "y"],
}

# ---------------------------------------------------------------------------
# Jinja2 模板环境
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)


class _CriticalSectionBlocksTreeprocessor(Treeprocessor):
    """Group critical report sections so print CSS can keep them together."""

    _SECTION_CLASSES = {
        "报告摘要": "report-summary",
        "关键进展信号": "signal-block",
        "参考标准和相似病例": "evidence-block",
        "人工复核重点": "review-block",
    }

    def run(self, root):
        children = list(root)
        rewritten = []
        index = 0
        while index < len(children):
            child = children[index]
            heading = "".join(child.itertext()).strip() if child.tag == "h2" else ""
            section_class = next(
                (
                    css_class
                    for title, css_class in self._SECTION_CLASSES.items()
                    if heading.endswith(title)
                ),
                None,
            )
            if section_class is None:
                rewritten.append(child)
                index += 1
                continue

            wrapper = etree.Element("div", {"class": section_class})
            wrapper.append(child)
            index += 1
            while index < len(children) and children[index].tag != "h2":
                wrapper.append(children[index])
                index += 1
            rewritten.append(wrapper)

        root[:] = rewritten
        return root


def _chart(name, unit, points):
    from app.services.report_document_builder import calendar_positions

    values = [point["value"] for point in points]
    positions = calendar_positions([point["visit_date"] for point in points])
    low = min(values)
    span = max(values) - low or 1.0
    dots = [
        {"x": 42 + position * 360, "y": 116 - (point["value"] - low) / span * 96}
        for point, position in zip(points, positions)
    ]
    return {
        "name": name,
        "unit": unit,
        "count": len(points),
        "dots": dots,
        "first_date": points[0]["visit_date"],
        "last_date": points[-1]["visit_date"],
        "points": " ".join(f"{point['x']:.2f},{point['y']:.2f}" for point in dots),
    }


def _document_observation_charts(report_document):
    from app.schemas.report_document import ReportDocument

    document = ReportDocument.model_validate(report_document)
    return [
        _chart(
            chart.label, chart.unit, [p.model_dump(mode="json") for p in chart.points]
        )
        for chart in document.charts
    ]


def _persisted_observation_charts(prediction_result):
    from datetime import date

    charts = []
    indicators = ((prediction_result or {}).get("observation") or {}).get(
        "indicators"
    ) or {}
    for name, item in indicators.items():
        if not isinstance(item, dict) or item.get("unit_state") != "consistent":
            continue
        points = []
        for row in item.get("series") or []:
            if (
                not isinstance(row, dict)
                or type(row.get("value")) not in (int, float)
                or not math.isfinite(row["value"])
            ):
                continue
            try:
                day = date.fromisoformat(row["visit_date"]).isoformat()
            except (KeyError, ValueError, TypeError):
                continue
            points.append({"visit_date": day, "value": row["value"]})
        if len(points) >= 3:
            charts.append(_chart(name, item.get("unit") or "单位未提供", points))
    return charts


class _ObservedChartsTreeprocessor(Treeprocessor):
    def __init__(self, md, charts: list[dict[str, Any]]):
        super().__init__(md)
        self.charts = charts

    def run(self, root):
        if not self.charts:
            return root
        for index, child in enumerate(list(root)):
            heading = "".join(child.itertext()).strip() if child.tag == "h2" else ""
            if not heading.endswith("已观察到的纵向变化"):
                continue
            block = etree.Element("div", {"class": "observed-charts-print"})
            title = etree.SubElement(block, "h3")
            title.text = "已观察到的变化图（不是模型预测）"
            for chart in self.charts:
                chart_block = etree.SubElement(
                    block, "div", {"class": "observed-chart-print"}
                )
                label = etree.SubElement(
                    chart_block, "div", {"class": "chart-title-print"}
                )
                strong = etree.SubElement(label, "strong")
                strong.text = chart["name"]
                detail = etree.SubElement(label, "span")
                detail.text = f"{chart['unit']}；{chart['count']} 次有效观察"
                svg = etree.SubElement(
                    chart_block,
                    "svg",
                    {
                        "viewBox": "0 0 420 150",
                        "role": "img",
                        "aria-label": f"{chart['name']} 已观察值趋势图",
                    },
                )
                etree.SubElement(
                    svg, "line", {"x1": "36", "y1": "12", "x2": "36", "y2": "124"}
                )
                etree.SubElement(
                    svg, "line", {"x1": "36", "y1": "124", "x2": "410", "y2": "124"}
                )
                etree.SubElement(svg, "polyline", {"points": chart["points"]})
                for point in chart["dots"]:
                    etree.SubElement(
                        svg,
                        "circle",
                        {
                            "cx": f"{point['x']:.2f}",
                            "cy": f"{point['y']:.2f}",
                            "r": "4",
                        },
                    )
                first_label = etree.SubElement(svg, "text", {"x": "38", "y": "143"})
                first_label.text = chart.get("first_date", "首次观察")
                last_label = etree.SubElement(svg, "text", {"x": "350", "y": "143"})
                last_label.text = chart.get("last_date", "最近观察")
            root.insert(index + 1, block)
            break
        return root


class _LongitudinalPrintExtension(Extension):
    def __init__(
        self, prediction_result: dict[str, Any] | None = None, *, report_document=None
    ):
        super().__init__()
        self.charts = (
            _document_observation_charts(report_document)
            if report_document is not None
            else _persisted_observation_charts(prediction_result)
        )

    def extendMarkdown(self, md):
        md.treeprocessors.register(
            _ObservedChartsTreeprocessor(md, self.charts),
            "observed_charts",
            6,
        )
        md.treeprocessors.register(
            _CriticalSectionBlocksTreeprocessor(md),
            "critical_section_blocks",
            5,
        )


def _markdown_to_safe_html(
    markdown_content: str,
    prediction_result: dict[str, Any] | None = None,
    evidence_snapshot: dict[str, Any] | None = None,
    *,
    report_document: dict | None = None,
) -> str:
    """Render saved Markdown and preserve only approved print structure."""
    if evidence_snapshot is not None:
        from app.schemas.longitudinal_evidence import EvidenceBundle
        from app.services.evidence_bundle import verify_evidence_bundle

        bundle = EvidenceBundle.model_validate(evidence_snapshot)
        if not verify_evidence_bundle(bundle):
            raise ValueError("evidence_integrity_mismatch")
    html_body = markdown.markdown(
        markdown_content,
        extensions=[
            "tables",
            "fenced_code",
            _LongitudinalPrintExtension(
                prediction_result, report_document=report_document
            ),
        ],
    )
    return bleach.clean(
        html_body,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
    )


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def generate_pdf(
    markdown_content: str,
    title: str = "分析报告",
    prediction_result: dict[str, Any] | None = None,
    evidence_snapshot: dict[str, Any] | None = None,
    *,
    report_document: dict | None = None,
    renderer_manifest: str | None = None,
    on_phase=None,
) -> bytes:
    """将 Markdown 报告转换为 PDF bytes。

    使用 Playwright 无头 Chromium 渲染 HTML 并输出 PDF。

    Args:
        markdown_content: 完整的报告 Markdown 文本。
        title: 报告标题。

    Returns:
        PDF 文件的二进制内容。

    Raises:
        RuntimeError: PDF 生成过程中发生错误。
    """

    def phase(value):
        if on_phase is not None:
            on_phase(value)

    font_css = ""
    manifest = None
    if renderer_manifest:
        from app.services.report_pdf_renderer_manifest import load_renderer_manifest

        manifest, _ = load_renderer_manifest(renderer_manifest)
    phase("html")
    # 1-2. Markdown → 带打印分组的安全 HTML
    safe_html = _markdown_to_safe_html(
        markdown_content,
        prediction_result,
        evidence_snapshot,
        report_document=report_document,
    )

    # 3. Jinja2 渲染完整 HTML 页面
    template = _jinja_env.get_template("report_pdf.html")
    release_set = (prediction_result or {}).get("release_set") or {}
    saved_model_version = release_set.get("release_set_id") or release_set.get(
        "data_release_id"
    )
    model_version_notice = (
        f"报告生成时保存的模型版本：{saved_model_version}。当前模型变化不会影响这份历史报告。"
        if saved_model_version
        else "报告生成时保存的模型版本：历史报告未记录。当前模型变化不会影响这份历史报告。"
    )
    full_html = template.render(
        title=title,
        content=safe_html,
        model_version_notice=model_version_notice,
    )
    if manifest:
        from app.services.report_pdf_fonts import controlled_font_css

        font_css = controlled_font_css(manifest, renderer_manifest, full_html, title)
        full_html = full_html.replace(
            "</head>", "<style>" + font_css + "</style></head>"
        )

    # 4. Playwright HTML → PDF
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "playwright 未安装。请运行: pip install playwright && playwright install chromium"
        )

    try:
        with sync_playwright() as p:
            phase("browser_launch")
            browser = p.chromium.launch(headless=True)
            try:
                if manifest and browser.version != manifest.chromium_version:
                    raise ValueError("pdf_renderer_unavailable")
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(full_html, timeout=30000)
                phase("fonts")
                page.evaluate("async () => { await document.fonts.ready; }")
                if manifest and not page.evaluate(
                    """() => [...document.fonts].some(f => f.family === 'ReportCJK' && f.status === 'loaded') && document.fonts.check('16px "ReportCJK"', '脂肪肝阿尔茨海默病')"""
                ):
                    raise ValueError("pdf_font_unavailable")
                phase("print")
                pdf_bytes = page.pdf(
                    format="A4",
                    margin={
                        "top": "20mm",
                        "bottom": "20mm",
                        "left": "22mm",
                        "right": "22mm",
                    },
                    print_background=True,
                    display_header_footer=True,
                    header_template=(
                        ("<style>" + font_css + "</style>" if font_css else "")
                        + f'<div style="font-size:9pt;color:#666;font-family:ReportCJK,SimSun,Microsoft YaHei,sans-serif;'
                        f'text-align:center;width:100%;padding:0 22mm">{_html.escape(title)}</div>'
                    ),
                    footer_template=(
                        ("<style>" + font_css + "</style>" if font_css else "")
                        + '<div style="font-size:9pt;color:#666;font-family:ReportCJK,SimSun,Microsoft YaHei,sans-serif;'
                        'text-align:center;width:100%;padding:0 22mm">'
                        '第 <span class="pageNumber"></span> 页'
                        "</div>"
                    ),
                )
                return pdf_bytes
            finally:
                browser.close()
    except Exception:
        logger.warning("PDF generation failed")
        raise RuntimeError("PDF 生成失败") from None
