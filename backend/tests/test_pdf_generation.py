"""PDF 生成单元测试。"""

import unittest
from unittest.mock import MagicMock, patch


class TestPdfGenerator(unittest.TestCase):
    """generate_pdf 测试。"""

    def setUp(self):
        from app.services.pdf_generator import generate_pdf
        self.func = generate_pdf

    @staticmethod
    def _install_mock_playwright():
        """在 sys.modules 中安装模拟的 playwright.sync_api 模块。"""
        import sys
        from unittest.mock import MagicMock

        mock_page = MagicMock()
        mock_page.pdf.return_value = b"%PDF-1.4 fake"

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium

        mock_sync = MagicMock(return_value=mock_pw)
        mock_pw.__enter__.return_value = mock_pw

        mock_sync_api = MagicMock()
        mock_sync_api.sync_playwright = mock_sync

        sys.modules["playwright"] = MagicMock()
        sys.modules["playwright.sync_api"] = mock_sync_api
        return mock_sync_api

    @staticmethod
    def _remove_mock_playwright():
        import sys
        sys.modules.pop("playwright.sync_api", None)
        sys.modules.pop("playwright", None)

    def test_markdown_to_html_pipeline(self):
        """Markdown → HTML → bleach → Jinja2 → Playwright 管道正确。"""
        import app.services.pdf_generator as pdf_gen

        class FakeTemplate:
            def render(self, **kwargs):
                return f"<html><body>{kwargs['content']}</body></html>"

        self._install_mock_playwright()
        try:
            with patch.object(
                pdf_gen._jinja_env,
                "get_template",
                return_value=FakeTemplate(),
            ):
                pdf_bytes = self.func("# Test\n\nContent", "Test")
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        finally:
            self._remove_mock_playwright()

    def test_template_exists(self):
        """模板文件 report_pdf.html 存在且可加载。"""
        from app.services.pdf_generator import _jinja_env

        template = _jinja_env.get_template("report_pdf.html")
        self.assertIsNotNone(template)

    def test_template_renders_with_chinese(self):
        """模板支持中文渲染。"""
        from app.services.pdf_generator import _jinja_env

        template = _jinja_env.get_template("report_pdf.html")
        html = template.render(
            title="测试报告",
            content="<h1>你好世界</h1><p>这是一段中文内容。</p>",
        )
        self.assertIn("测试报告", html)
        self.assertIn("你好世界", html)
        self.assertIn("中文内容", html)
        self.assertIn("A4", html)

    def test_template_escapes_html_in_title(self):
        """模板对标题做 HTML 转义（Jinja2 autoescape）。"""
        from app.services.pdf_generator import _jinja_env

        template = _jinja_env.get_template("report_pdf.html")
        html = template.render(
            title='<script>alert("xss")</script>',
            content="<p>safe</p>",
        )
        self.assertNotIn('<script>alert("xss")</script>', html)
        self.assertIn("&lt;script&gt;", html)

    def test_template_has_pdf_styles(self):
        """模板包含 PDF 打印样式。"""
        from app.services.pdf_generator import _jinja_env

        template = _jinja_env.get_template("report_pdf.html")
        html = template.render(title="Test", content="<p>content</p>")
        self.assertIn("page-break", html)

    def test_markdown_extensions_configured(self):
        """markdown 库包含 tables 和 fenced_code 扩展。"""
        import markdown as md_lib

        html = md_lib.markdown(
            "| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('hi')\n```",
            extensions=["tables", "fenced_code"],
        )
        self.assertIn("<table>", html)
        self.assertIn("<pre>", html)

    def test_allowed_tags_are_reasonable(self):
        """允许的 HTML 标签白名单覆盖报告常见元素。"""
        from app.services.pdf_generator import ALLOWED_TAGS

        essential = {"h1", "h2", "h3", "h4", "p", "ul", "ol", "li",
                     "table", "thead", "tbody", "tr", "th", "td",
                     "strong", "em", "code", "pre", "blockquote",
                     "a", "span", "div"}
        self.assertTrue(essential.issubset(ALLOWED_TAGS))

    def test_dangerous_tags_excluded(self):
        """危险标签不在白名单中。"""
        from app.services.pdf_generator import ALLOWED_TAGS

        dangerous = {"script", "iframe", "object", "embed", "style", "link", "meta"}
        for tag in dangerous:
            self.assertNotIn(tag, ALLOWED_TAGS)


class TestPdfErrorHandling(unittest.TestCase):
    """PDF 生成错误处理测试。"""

    def test_missing_playwright_raises_runtime_error(self):
        """playwright 未安装时抛出 RuntimeError。

        注意：若 playwright 已安装，则通过 mock __import__ 模拟导入失败。
        """
        import builtins
        import app.services.pdf_generator as pdf_gen

        _real_import = builtins.__import__

        def _block_playwright(name, *args, **kwargs):
            if name == "playwright.sync_api" or name.startswith("playwright.sync_api."):
                raise ImportError(f"No module named '{name}'")
            return _real_import(name, *args, **kwargs)

        with patch("app.services.pdf_generator.markdown.markdown",
                   return_value="<p>test</p>"):
            with patch("app.services.pdf_generator.bleach.clean",
                       return_value="<p>test</p>"):
                class FakeTemplate:
                    def render(self, **kw):
                        return "<html><body>test</body></html>"

                with patch.object(
                    pdf_gen._jinja_env,
                    "get_template",
                    return_value=FakeTemplate(),
                ):
                    with patch("builtins.__import__", side_effect=_block_playwright):
                        with self.assertRaises(RuntimeError) as ctx:
                            pdf_gen.generate_pdf("# test", "test")
                        self.assertIn("pip install playwright", str(ctx.exception))

    def test_browser_crash_raises_runtime_error(self):
        """Playwright 启动失败时抛出 RuntimeError。"""
        import app.services.pdf_generator as pdf_gen

        # 注入会抛异常的 mock
        mock_sync = MagicMock(side_effect=Exception("Browser not found"))
        mock_sync_api = MagicMock()
        mock_sync_api.sync_playwright = mock_sync
        import sys
        sys.modules["playwright.sync_api"] = mock_sync_api

        try:
            with patch("app.services.pdf_generator.markdown.markdown",
                       return_value="<p>test</p>"):
                with patch("app.services.pdf_generator.bleach.clean",
                           return_value="<p>test</p>"):
                    class FakeTemplate:
                        def render(self, **kw):
                            return "<html><body>test</body></html>"

                    with patch.object(
                        pdf_gen._jinja_env,
                        "get_template",
                        return_value=FakeTemplate(),
                    ):
                        with self.assertRaises(RuntimeError) as ctx:
                            pdf_gen.generate_pdf("# test", "test")
                        self.assertIn("PDF", str(ctx.exception))
        finally:
            sys.modules.pop("playwright.sync_api", None)


if __name__ == "__main__":
    unittest.main()
