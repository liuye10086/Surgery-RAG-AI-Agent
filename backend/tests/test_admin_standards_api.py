import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError


os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")

from app.schemas.standard import StandardCreate, StandardVersionCreate, StandardVersionOut


class _Query:
    def __init__(self, value):
        self.value = value
        self.events = []
        self.for_update = False

    def filter(self, *conditions):
        self.events.append("filter")
        return self

    def with_for_update(self):
        self.events.append("with_for_update")
        self.for_update = True
        return self

    def populate_existing(self):
        self.events.append("populate_existing")
        return self

    def first(self):
        self.events.append("first")
        return self.value

    def update(self, _values, synchronize_session=False):
        self.events.append("update")
        return 0


class _Db:
    def __init__(self, values=None, *, commit_error=None):
        self.values = {name: list(items) for name, items in (values or {}).items()}
        self.commit_error = commit_error
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self.queries = []

    def query(self, model):
        values = self.values.get(model.__name__, [])
        query = _Query(values.pop(0) if values else None)
        self.queries.append(query)
        return query

    def add(self, value):
        if getattr(value, "id", None) is None:
            value.id = len(self.added) + 1
        self.added.append(value)

    def delete(self, value):
        self.deleted.append(value)

    def flush(self):
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = self.added.index(value) + 1

    def commit(self):
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error
        for version in self.deleted:
            document = getattr(version, "standard_document", None)
            if document is not None:
                document.version = None

    def refresh(self, value):
        return None

    def rollback(self):
        self.rollbacks += 1


def _call_create_standard(db, disease_id=2):
    from app.api.admin_standards import create_standard

    return create_standard(
        StandardCreate(disease_id=disease_id),
        admin=SimpleNamespace(id=7),
        db=db,
    )


def _call_create_version(db, standard_id=4, document_id=9):
    from app.api.admin_standards import create_version

    return create_version(
        standard_id,
        StandardVersionCreate(
            standard_document_id=document_id,
            version_label="AD-2026-08",
        ),
        admin=SimpleNamespace(id=7),
        db=db,
    )


def test_standard_create_accepts_only_disease_id():
    payload = StandardCreate(disease_id=2)
    assert payload.model_dump() == {"disease_id": 2}
    assert "name" not in StandardCreate.model_fields


def test_standard_version_contract_uses_standard_document_id():
    payload = StandardVersionCreate(
        standard_document_id=9,
        version_label="AD-2026-08",
    )
    assert payload.standard_document_id == 9
    assert "document_id" not in StandardVersionOut.model_fields


def test_version_delete_route_is_registered():
    from app.api.admin_standards import router

    route = next(
        route for route in router.routes
        if route.path == "/admin/reference-standard-versions/{version_id}"
        and "DELETE" in route.methods
    )
    assert route.status_code == 204


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


def test_create_standard_returns_404_when_disease_is_missing():
    db = _Db({"Disease": [None]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_standard(db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "疾病不存在"


def test_create_standard_uses_disease_name():
    disease = SimpleNamespace(id=2, name="阿尔茨海默病")
    db = _Db({"Disease": [disease], "ReferenceStandard": [None]})

    standard = _call_create_standard(db)

    assert standard.disease_id == 2
    assert standard.name == "阿尔茨海默病标准"
    assert standard.description is None
    assert db.queries[0].events[:3] == ["filter", "with_for_update", "first"]


def test_create_standard_rejects_existing_disease_collection():
    disease = SimpleNamespace(id=2, name="阿尔茨海默病")
    db = _Db({"Disease": [disease], "ReferenceStandard": [SimpleNamespace(id=4)]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_standard(db)

    assert exc_info.value.status_code == 409


def test_create_standard_maps_unique_constraint_race_to_409():
    disease = SimpleNamespace(id=2, name="阿尔茨海默病")
    db = _Db(
        {"Disease": [disease], "ReferenceStandard": [None]},
        commit_error=IntegrityError("insert", {}, Exception("duplicate disease")),
    )

    with pytest.raises(HTTPException) as exc_info:
        _call_create_standard(db)

    assert exc_info.value.status_code == 409
    assert db.rollbacks == 1


def test_create_version_checks_standard_before_document():
    db = _Db({"ReferenceStandard": [None]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "标准集合不存在"


def test_create_version_returns_404_for_missing_standard_document():
    db = _Db({"ReferenceStandard": [SimpleNamespace(id=4)], "StandardDocument": [None]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "标准文档不存在"


def test_create_version_rejects_locked_standard_document(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    document = SimpleNamespace(
        id=9,
        file_type="docx",
        file_path=str(source),
        content_hash="a" * 64,
        version=SimpleNamespace(id=3),
    )
    db = _Db({"ReferenceStandard": [SimpleNamespace(id=4)], "StandardDocument": [document]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "标准文档已关联版本"


def test_create_version_rejects_missing_standard_document_file(tmp_path):
    document = SimpleNamespace(
        id=9,
        file_type=".DOCX",
        file_path=str(tmp_path / "missing.docx"),
        content_hash="a" * 64,
        version=None,
    )
    db = _Db({"ReferenceStandard": [SimpleNamespace(id=4)], "StandardDocument": [document]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "标准文件不存在"


def test_create_version_rejects_non_docx_standard_document(tmp_path):
    source = tmp_path / "standard.pdf"
    source.write_bytes(b"pdf")
    document = SimpleNamespace(
        id=9,
        file_type="pdf",
        file_path=str(source),
        content_hash="a" * 64,
        version=None,
    )
    db = _Db({"ReferenceStandard": [SimpleNamespace(id=4)], "StandardDocument": [document]})

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 422


def test_create_version_uses_stored_hash_and_locks_document(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"contents do not match stored hash")
    standard = SimpleNamespace(id=4, current_version_id=3)
    document = SimpleNamespace(
        id=9,
        file_type="docx",
        file_path=str(source),
        content_hash="b" * 64,
        version=None,
    )
    db = _Db({"ReferenceStandard": [standard], "StandardDocument": [document]})

    version = _call_create_version(db)

    assert version.standard_id == 4
    assert version.standard_document_id == 9
    assert version.content_hash == "b" * 64
    assert version.created_by == 7
    assert version.supersedes_version_id == 3
    assert version.status == "draft"
    assert db.queries[1].events[:3] == ["filter", "with_for_update", "first"]


def test_create_version_maps_document_unique_constraint_race_to_409(tmp_path):
    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    document = SimpleNamespace(
        id=9,
        file_type="docx",
        file_path=str(source),
        content_hash="a" * 64,
        version=None,
    )
    db = _Db(
        {"ReferenceStandard": [SimpleNamespace(id=4, current_version_id=None)], "StandardDocument": [document]},
        commit_error=IntegrityError("insert", {}, Exception("duplicate standard_document_id")),
    )

    with pytest.raises(HTTPException) as exc_info:
        _call_create_version(db)

    assert exc_info.value.status_code == 409
    assert db.rollbacks == 1


def test_parse_deterministic_candidate_does_not_use_llm_adapter(monkeypatch, tmp_path):
    from app.api.admin_standards import parse_version

    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    segment = SimpleNamespace(
        section_title="参考范围",
        paragraph_index=None,
        table_index=1,
        row_index=1,
        column_index=1,
        raw_text="ALT 7-40 U/L",
        segment_type="table_cell",
        source_metadata={},
    )
    candidate = SimpleNamespace(
        segment=segment,
        indicator_name="ALT",
        rule_type="numeric_range",
        target_state_type="reference",
        target_state_value=None,
        machine_actionability="calculable",
        evidence_type="standard_table",
        applicability={},
        interpretation=None,
        numeric=None,
    )
    parsed = SimpleNamespace(segments=[segment], rule_candidates=[candidate])
    version = SimpleNamespace(
        id=5,
        status="draft",
        parser_version="v1",
        standard_document=SimpleNamespace(file_type=".DOCX", file_path=str(source)),
        segments=[],
        candidates=[],
    )
    db = _Db({"ReferenceStandardVersion": [version]})
    llm_calls = []
    monkeypatch.setattr("app.api.admin_standards.parse_standard_docx", lambda *args, **kwargs: parsed)
    monkeypatch.setattr(
        "app.api.admin_standards.build_llm_candidate",
        lambda *args, **kwargs: llm_calls.append((args, kwargs)),
    )
    monkeypatch.setattr("app.api.admin_standards.LLM_CANDIDATE_ADAPTER", object())

    result = parse_version(5, admin=SimpleNamespace(id=7), db=db)

    assert result == {"version_id": 5, "segments": 1, "candidates": 1}
    assert llm_calls == []
    assert [item.source_type for item in db.added if hasattr(item, "source_type")] == ["deterministic"]
    assert db.queries[0].events[:3] == ["filter", "with_for_update", "first"]


def test_parse_deterministic_candidate_persists_sex_and_parse_warnings(monkeypatch, tmp_path):
    from app.api.admin_standards import parse_version

    source = tmp_path / "standard.docx"
    source.write_bytes(b"docx")
    segment = SimpleNamespace(
        section_title="参考范围",
        paragraph_index=None,
        table_index=1,
        row_index=1,
        column_index=1,
        raw_text="ALT 约 7-40 U/L",
        segment_type="table_cell",
        source_metadata={},
    )
    candidate = SimpleNamespace(
        segment=segment,
        indicator_name="ALT",
        rule_type="numeric_range",
        target_state_type="reference",
        target_state_value=None,
        machine_actionability="evidence-only",
        evidence_type="standard_table",
        applicability={},
        interpretation=None,
        numeric=None,
        sex="female",
        parse_warnings=("approximate_language",),
    )
    parsed = SimpleNamespace(segments=[segment], rule_candidates=[candidate])
    version = SimpleNamespace(
        id=5,
        status="draft",
        parser_version="v2",
        standard_document=SimpleNamespace(file_type=".DOCX", file_path=str(source)),
        segments=[],
        candidates=[],
    )
    db = _Db({"ReferenceStandardVersion": [version]})
    monkeypatch.setattr("app.api.admin_standards.parse_standard_docx", lambda *args, **kwargs: parsed)

    parse_version(5, admin=SimpleNamespace(id=7), db=db)

    stored_candidate = next(item for item in db.added if hasattr(item, "candidate_json"))
    assert stored_candidate.candidate_json["sex"] == "female"
    assert stored_candidate.candidate_json["parse_warnings"] == ["approximate_language"]


@pytest.mark.parametrize("version_status", ["draft", "review"])
def test_delete_version_allows_unapproved_states_and_unlocks_document(version_status):
    from app.api.admin_standards import delete_version

    document = SimpleNamespace(version=None)
    version = SimpleNamespace(id=5, status=version_status, standard_document=document)
    document.version = version
    db = _Db({"ReferenceStandardVersion": [version]})

    assert delete_version(5, admin=SimpleNamespace(id=7), db=db) is None
    assert db.deleted == [version]
    assert document.version is None


def test_delete_version_locks_row_before_checking_mutable_status():
    from app.api.admin_standards import delete_version

    version = SimpleNamespace(id=5, status="draft", standard_document=None)
    db = _Db({"ReferenceStandardVersion": [version]})

    delete_version(5, admin=SimpleNamespace(id=7), db=db)

    assert db.queries[0].events[:3] == ["filter", "with_for_update", "first"]


@pytest.mark.parametrize(
    ("endpoint_name", "version_status"),
    [("submit_review", "draft")],
)
def test_lifecycle_route_locks_row_before_status_transition(endpoint_name, version_status):
    from app.api import admin_standards

    version = SimpleNamespace(id=5, status=version_status)
    db = _Db({"ReferenceStandardVersion": [version]})

    getattr(admin_standards, endpoint_name)(5, admin=SimpleNamespace(id=7), db=db)

    assert db.queries[0].events[:3] == ["filter", "with_for_update", "first"]


def test_validation_endpoint_uses_ad_disease_key(monkeypatch):
    from app.api.admin_standards import validate_version

    captured = {}
    version = SimpleNamespace(
        id=5,
        rules=[SimpleNamespace(machine_actionability="evidence-only")],
        standard=SimpleNamespace(disease=SimpleNamespace(name="阿尔茨海默病")),
    )
    db = _Db({"ReferenceStandardVersion": [version]})

    def fake_validate(rules, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            errors=[], warnings=[], infos=[], projection_count=0,
            calculable_rule_count=0, blocked_rule_count=0,
        )

    monkeypatch.setattr("app.api.admin_standards.validate_version_rules", fake_validate)

    validate_version(5, admin=SimpleNamespace(id=7), db=db)

    assert captured == {"disease_key": "ad", "require_calculable": False}


def test_retire_route_delegates_to_current_version_service():
    from app.api import admin_standards

    version = SimpleNamespace(id=5, status="approved", standard_id=3, retired_at=None)
    standard = SimpleNamespace(id=3, current_version_id=5, current_version=version)
    db = _Db({"ReferenceStandard": [standard], "ReferenceStandardVersion": [version]})

    admin_standards.retire_version(5, admin=SimpleNamespace(id=7), db=db)

    assert db.queries[0].events[:3] == ["filter", "populate_existing", "with_for_update"]
    assert db.commits == 1
    assert standard.current_version_id is None


@pytest.mark.parametrize("version_status", ["approved", "retired"])
def test_delete_version_rejects_immutable_states(version_status):
    from app.api.admin_standards import delete_version

    version = SimpleNamespace(id=5, status=version_status)
    db = _Db({"ReferenceStandardVersion": [version]})

    with pytest.raises(HTTPException) as exc_info:
        delete_version(5, admin=SimpleNamespace(id=7), db=db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "已批准或已退役版本不可删除"
    assert db.deleted == []
