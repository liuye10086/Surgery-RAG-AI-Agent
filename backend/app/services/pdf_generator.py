"""AI 操作者报告 PDF 生成服务。

管道：
  1. markdown.markdown(content) → HTML
  2. bleach.clean(html, tags=ALLOWED_TAGS, ...) → 安全 HTML
  3. Jinja2 渲染完整 HTML
  4. Playwright（无头 Chromium）→ PDF bytes
"""

import logging
from pathlib import Path

import bleach
import markdown
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 允许的 HTML 标签白名单
# ---------------------------------------------------------------------------

ALLOWED_TAGS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "strong", "em", "code", "pre",
    "blockquote", "hr", "br",
    "sup", "sub", "a", "span", "div",
}

ALLOWED_ATTRS = {
    "a": ["href", "title"],
    "span": ["class"],
    "div": ["class"],
    "th": ["align"],
    "td": ["align"],
}

# ---------------------------------------------------------------------------
# Jinja2 模板环境
# ---------------------------------------------------------------------------

_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_jinja_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), autoescape=True)


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def generate_pdf(markdown_content: str, title: str = "分析报告") -> bytes:
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
    # 1. Markdown → HTML
    html_body = markdown.markdown(
        markdown_content,
        extensions=["tables", "fenced_code", "codehilite", "nl2br"],
    )

    # 2. 安全过滤
    safe_html = bleach.clean(
        html_body,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
    )

    # 3. Jinja2 渲染完整 HTML 页面
    template = _jinja_env.get_template("report_pdf.html")
    full_html = template.render(
        title=title,
        content=safe_html,
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
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(full_html, timeout=30000)
            # 等待字体和样式加载完毕
            page.wait_for_timeout(500)
            pdf_bytes = page.pdf(
                format="A4",
                margin={"top": "20mm", "bottom": "20mm", "left": "22mm", "right": "22mm"},
                print_background=True,
                display_header_footer=True,
                header_template=(
                    f'<div style="font-size:9pt;color:#666;font-family:SimSun,Microsoft YaHei,sans-serif;'
                    f'text-align:center;width:100%;padding:0 22mm">{title}</div>'
                ),
                footer_template=(
                    '<div style="font-size:9pt;color:#666;font-family:SimSun,Microsoft YaHei,sans-serif;'
                    'text-align:center;width:100%;padding:0 22mm">'
                    '第 <span class="pageNumber"></span> 页'
                    '</div>'
                ),
            )
            browser.close()
            return pdf_bytes
    except Exception as exc:
        logger.exception("PDF generation failed for title='%s'", title)
        raise RuntimeError(f"PDF 生成失败: {exc}") from exc
