"""Build a pinned renderer artifact from installed Chromium and licensed Noto CJK."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.report_pdf_renderer_manifest import (
    APP_ROOT,
    RENDERER_FILES,
    PRINT_OPTIONS,
    file_sha,
    load_renderer_manifest,
)


def build(font_dir, output_dir):
    fonts = Path(font_dir).resolve(strict=True)
    font = fonts / "NotoSansCJKsc-Regular.otf"
    license_file = fonts / "LICENSE"
    if (
        not font.is_file()
        or not license_file.is_file()
        or "SIL OPEN FONT LICENSE"
        not in license_file.read_text(encoding="utf-8").upper()
    ):
        raise ValueError("licensed_noto_cjk_font_required")
    from fontTools.ttLib import TTFont

    with TTFont(font) as face:
        family = face["name"].getDebugName(1)
        if family != "Noto Sans CJK SC":
            raise ValueError("noto_cjk_sc_required")
    latin = fonts / "NotoSans-Regular.ttf"
    latin_license = fonts / "LICENSE-latin"
    if (
        not latin.is_file()
        or not latin_license.is_file()
        or "SIL OPEN FONT LICENSE"
        not in latin_license.read_text(encoding="utf-8").upper()
    ):
        raise ValueError("licensed_noto_latin_font_required")
    with TTFont(latin) as face:
        if (
            face["name"].getDebugName(1) != "Noto Sans"
            or 0x2079 not in face.getBestCmap()
        ):
            raise ValueError("noto_latin_math_coverage_required")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as runtime:
        chromium_sha = file_sha(runtime.chromium.executable_path)
        browser = runtime.chromium.launch(headless=True)
        try:
            chromium_version = browser.version
        finally:
            browser.close()
    sources = {relative: file_sha(APP_ROOT / relative) for relative in RENDERER_FILES}
    manifest = dict(
        schema_version="pdf_renderer.v1",
        source_files=sources,
        template_sha256=sources["templates/report_pdf.html"],
        chart_renderer_sha256=sources["services/report_document_builder.py"],
        markdown_adapter_sha256=sources["services/pdf_generator.py"],
        font_files=[
            dict(
                path="fonts/NotoSansCJKsc-Regular.otf",
                sha256=file_sha(font),
                license="fonts/LICENSE",
                license_sha256=file_sha(license_file),
            ),
            dict(
                path="fonts/NotoSans-Regular.ttf",
                sha256=file_sha(latin),
                license="fonts/LICENSE-latin",
                license_sha256=file_sha(latin_license),
            ),
        ],
        playwright_version=importlib.metadata.version("playwright"),
        fonttools_version=importlib.metadata.version("fonttools"),
        chromium_version=chromium_version,
        chromium_sha256=chromium_sha,
        platform=platform.system(),
        print_options=PRINT_OPTIONS,
    )
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode()
    digest = hashlib.sha256(raw).hexdigest()
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    final = output / digest
    if final.exists():
        load_renderer_manifest(final / "manifest.json")
        return final / "manifest.json"
    staging = Path(tempfile.mkdtemp(prefix=".renderer-", dir=output))
    (staging / "fonts").mkdir()
    shutil.copyfile(font, staging / "fonts" / font.name)
    shutil.copyfile(license_file, staging / "fonts" / "LICENSE")
    shutil.copyfile(latin, staging / "fonts" / latin.name)
    shutil.copyfile(latin_license, staging / "fonts" / "LICENSE-latin")
    (staging / "manifest.json").write_bytes(raw)
    load_renderer_manifest(staging / "manifest.json")
    staging.rename(final)
    return final / "manifest.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--font-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    print(build(args.font_dir, args.output_dir))
