"""Verify a built renderer manifest; requests never bless changed resources."""

from pathlib import Path
import hashlib
import importlib.metadata
import json
import platform
from pydantic import BaseModel, ConfigDict, Field
from app.services.report_pdf_errors import PdfError

APP_ROOT = Path(__file__).resolve().parents[1]
RENDERER_FILES = (
    "templates/report_pdf.html",
    "services/pdf_generator.py",
    "services/report_document_renderer.py",
    "services/report_document_builder.py",
    "services/report_evidence_presentation.py",
    "schemas/report_document.py",
    "schemas/longitudinal_evidence.py",
    "services/report_pdf_fonts.py",
)
PRINT_OPTIONS = {
    "format": "A4",
    "margin": {"top": "20mm", "bottom": "20mm", "left": "22mm", "right": "22mm"},
    "print_background": True,
    "display_header_footer": True,
}


class FontFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: str
    license_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RendererManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(pattern=r"^pdf_renderer\.v1$")
    template_sha256: str
    chart_renderer_sha256: str
    markdown_adapter_sha256: str
    source_files: dict[str, str]
    font_files: list[FontFile] = Field(min_length=1, max_length=4)
    playwright_version: str
    fonttools_version: str
    chromium_version: str
    chromium_sha256: str
    platform: str
    print_options: dict


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resource_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise PdfError("pdf_renderer_unavailable")
    result = (root / path).resolve(strict=True)
    if not result.is_relative_to(root):
        raise PdfError("pdf_renderer_unavailable")
    return result


def load_renderer_manifest(path):
    try:
        manifest_path = Path(path).resolve(strict=True)
        if manifest_path.stat().st_size > 65536:
            raise ValueError()
        raw = manifest_path.read_bytes()
        manifest = RendererManifest.model_validate_json(raw)
        if (
            manifest.platform != platform.system()
            or manifest.playwright_version != importlib.metadata.version("playwright")
            or manifest.fonttools_version != importlib.metadata.version("fonttools")
            or manifest.print_options != PRINT_OPTIONS
            or set(manifest.source_files) != set(RENDERER_FILES)
        ):
            raise ValueError()
        for relative, digest in manifest.source_files.items():
            if file_sha(APP_ROOT / relative) != digest:
                raise ValueError()
        if (
            manifest.template_sha256
            != manifest.source_files["templates/report_pdf.html"]
            or manifest.markdown_adapter_sha256
            != manifest.source_files["services/pdf_generator.py"]
            or manifest.chart_renderer_sha256
            != manifest.source_files["services/report_document_builder.py"]
        ):
            raise ValueError()
        for font in manifest.font_files:
            if (
                file_sha(resource_path(manifest_path.parent, font.path)) != font.sha256
                or file_sha(resource_path(manifest_path.parent, font.license))
                != font.license_sha256
            ):
                raise ValueError()
        from playwright.sync_api import sync_playwright

        with sync_playwright() as runtime:
            if file_sha(runtime.chromium.executable_path) != manifest.chromium_sha256:
                raise ValueError()
        return manifest, hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        raise PdfError("pdf_renderer_unavailable") from None
