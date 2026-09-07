"""Subset a verified font to the exact document characters before embedding."""

import base64
import html
import io
import unicodedata
from pathlib import Path
from fontTools import subset
from fontTools.ttLib import TTFont
from app.services.report_pdf_renderer_manifest import resource_path
from app.services.report_pdf_errors import PdfError


def controlled_font_css(manifest, manifest_path, document_html, title):
    # Include print furniture and the explicit browser font readiness probe.
    text = html.unescape(document_html) + title + "第 页0123456789脂肪肝阿尔茨海默病"
    required = {
        ord(ch)
        for ch in text
        if unicodedata.category(ch) not in ("Cc", "Cf", "Zl", "Zp")
    }
    remaining = set(required)
    faces = []
    for item in manifest.font_files:
        path = resource_path(Path(manifest_path).resolve().parent, item.path)
        with TTFont(path, recalcTimestamp=False) as font:
            available = set(font.getBestCmap() or {})
            selected = remaining & available
            remaining -= selected
            if not selected:
                continue
            options = subset.Options()
            options.recalc_timestamp = False
            worker = subset.Subsetter(options=options)
            worker.populate(unicodes=selected)
            worker.subset(font)
            output = io.BytesIO()
            font.save(output)
            encoded = base64.b64encode(output.getvalue()).decode("ascii")
            faces.append(
                "@font-face{font-family:ReportCJK;src:url(data:font/otf;base64,"
                + encoded
                + ') format("opentype");font-weight:400;font-style:normal;unicode-range:'
                + ",".join(f"U+{code:X}" for code in sorted(selected))
                + ";}"
            )
    if remaining:
        raise PdfError("pdf_font_unavailable")
    return (
        "".join(faces)
        + "body,th,td,svg text{font-family:ReportCJK,sans-serif !important;}"
    )
