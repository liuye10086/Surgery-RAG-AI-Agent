from pathlib import Path

from fastapi import status


def test_admin_standard_router_registers_all_lifecycle_paths():
    from app.api.admin_standards import router

    paths = {route.path for route in router.routes}
    assert {
        "/admin/reference-standards",
        "/admin/reference-standards/{standard_id}/versions",
        "/admin/reference-standard-versions/{version_id}/parse",
        "/admin/reference-standard-versions/{version_id}/approve",
        "/admin/reference-standard-rules/{rule_id}",
    }.issubset(paths)


def test_admin_standard_router_requires_admin_dependency():
    source = Path(__file__).parents[1].joinpath("app/api/admin_standards.py").read_text(encoding="utf-8")
    assert "require_admin" in source
    assert "status_code=status.HTTP_409_CONFLICT" in source


def test_docx_type_check_accepts_uploaded_extension_format():
    from app.api.admin_standards import _is_docx_document

    assert _is_docx_document("docx")
    assert _is_docx_document(".docx")
    assert not _is_docx_document("pdf")
