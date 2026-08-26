import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.standard_manifest import StandardManifest


def _entry(entry_id: str = "fatty-alt-reference") -> dict:
    return {
        "entry_id": entry_id,
        "entry_kind": "rule",
        "review_status": "pending",
        "review_note": None,
        "source": {
            "table_index": 1,
            "row_index": 1,
            "paragraph_index": None,
            "column_index": None,
            "raw_text": "ALT（谷丙转氨酶） | 男性约 9–50；女性约 7–40 | U/L",
        },
        "indicator": {
            "canonical_key": "alt",
            "name_en": "ALT",
            "name_cn": "谷丙转氨酶",
            "aliases": ["谷丙转氨酶", "丙氨酸氨基转移酶"],
            "domain": "laboratory",
            "specimen_or_modality": "serum",
            "data_type": "numeric",
            "scale_or_method": None,
            "default_unit": "U/L",
            "clinical_dimension": "liver_injury",
            "allows_numeric_comparison": True,
            "abnormal_direction": "high",
        },
        "rule": {
            "rule_type": "numeric_range",
            "comparator": None,
            "lower": 9.0,
            "upper": 50.0,
            "lower_inclusive": True,
            "upper_inclusive": True,
            "unit": "U/L",
            "sex": "male",
            "category": "reference",
            "applicability": {},
            "target_state_type": "control",
            "target_state_value": "reference",
            "clinical_dimension": "liver_injury",
            "evidence_type": "standard_table",
            "machine_actionability": "evidence-only",
            "actionability_reason": "原文使用约数",
            "interpretation": "男性约 9–50 U/L",
            "priority": 0,
            "conflict_group": None,
            "framework": None,
            "biomarker_axis": None,
            "biomarker_state": None,
            "stage": None,
            "clinical_function": None,
            "conditions": {},
        },
    }


def _manifest() -> dict:
    return {
        "schema_version": "standard_manifest.v1",
        "dataset": "fatty_liver",
        "disease_name": "脂肪肝",
        "source_document_sha256": "f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba",
        "target_version_label": "fatty-liver-2026-08-25",
        "review_state": "pending",
        "reviewed_at": None,
        "entries": [_entry()],
    }


def test_manifest_rejects_unknown_fields_and_duplicate_entry_ids():
    payload = _manifest()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        StandardManifest.model_validate(payload)

    payload = _manifest()
    payload["entries"].append(_entry())
    with pytest.raises(ValidationError, match="entry_id"):
        StandardManifest.model_validate(payload)


def test_approved_manifest_cannot_contain_pending_entries():
    payload = _manifest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    with pytest.raises(ValidationError, match="pending"):
        StandardManifest.model_validate(payload)


def test_no_safe_rule_entry_has_no_rule_payload():
    payload = _manifest()
    payload["entries"][0]["entry_kind"] = "no_safe_rule"
    payload["entries"][0]["rule"] = None
    payload["entries"][0]["review_status"] = "approved"
    manifest = StandardManifest.model_validate(payload)
    assert manifest.entries[0].rule is None


def test_no_safe_rule_can_record_document_level_absence():
    payload = _manifest()
    payload["entries"][0]["entry_kind"] = "no_safe_rule"
    payload["entries"][0]["rule"] = None
    payload["entries"][0]["source"] = {
        "document_absence_terms": ["AFP", "甲胎蛋白"],
    }

    manifest = StandardManifest.model_validate(payload)

    assert manifest.entries[0].source.document_absence_terms == ["AFP", "甲胎蛋白"]


def test_rule_cannot_use_document_level_absence_as_source():
    payload = _manifest()
    payload["entries"][0]["source"] = {
        "document_absence_terms": ["ALT"],
    }

    with pytest.raises(ValidationError, match="no_safe_rule"):
        StandardManifest.model_validate(payload)


def test_reserved_applicability_keys_are_rejected():
    payload = _manifest()
    payload["entries"][0]["rule"]["applicability"] = {"_manifest_entry_id": "forged"}
    with pytest.raises(ValidationError, match="保留"):
        StandardManifest.model_validate(payload)


def test_ad_ratio_canonical_key_accepts_beta_symbol():
    payload = _manifest()
    payload["entries"][0]["indicator"]["canonical_key"] = "aβ42/aβ40"
    manifest = StandardManifest.model_validate(payload)
    assert manifest.entries[0].indicator.canonical_key == "aβ42/aβ40"


def _parsed(raw_text: str):
    return SimpleNamespace(segments=[SimpleNamespace(
        paragraph_index=None,
        table_index=1,
        row_index=1,
        column_index=None,
        raw_text=raw_text,
    )])


def test_manifest_rejects_hash_or_source_text_mismatch(tmp_path: Path):
    from app.services.standard_manifest import validate_standard_manifest

    source = tmp_path / "fatty.docx"
    source.write_bytes(b"wrong")
    manifest = StandardManifest.model_validate(_manifest())
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "source_hash_mismatch" in {item.code for item in result.errors}
    assert "source_segment_mismatch" not in {item.code for item in result.errors}

    source.write_bytes(b"stable")
    payload = _manifest()
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed("different text"),
    )
    assert "source_segment_mismatch" in {item.code for item in result.errors}


def test_document_level_absence_is_checked_against_all_segments(tmp_path: Path):
    from app.services.standard_manifest import validate_standard_manifest

    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    payload["entries"][0]["entry_kind"] = "no_safe_rule"
    payload["entries"][0]["rule"] = None
    payload["entries"][0]["source"] = {
        "document_absence_terms": ["AFP", "甲胎蛋白"],
    }
    manifest = StandardManifest.model_validate(payload)

    absent = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed("PLT（血小板计数） | 按实验室参考范围"),
    )
    assert "source_absence_contradicted" not in {item.code for item in absent.errors}

    present = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed("AFP（甲胎蛋白） | ≤ 7 | ng/mL"),
    )
    assert "source_absence_contradicted" in {item.code for item in present.errors}


def test_core_indicator_coverage_requires_explicit_conclusion(tmp_path: Path):
    from app.services.standard_manifest import validate_standard_manifest

    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "core_indicator_missing" in {item.code for item in result.errors}
    assert "afp" in result.missing_core_indicators


def test_review_markdown_is_deterministic_and_contains_decision_fields():
    from app.services.standard_manifest import render_standard_review_markdown

    manifest = StandardManifest.model_validate(_manifest())
    first = render_standard_review_markdown(manifest)
    second = render_standard_review_markdown(manifest)
    assert first == second
    assert "fatty-alt-reference" in first
    assert "evidence-only" in first
    assert "审核状态" in first


def test_approved_manifest_requires_a_safe_calculable_rule(tmp_path: Path):
    from app.services.standard_manifest import validate_standard_manifest

    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    payload["entries"][0]["review_status"] = "approved"
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "approved_calculable_rule_missing" in {item.code for item in result.errors}


def test_approved_blocked_entry_is_rejected_by_lint(tmp_path: Path):
    from app.services.standard_manifest import validate_standard_manifest

    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    payload["entries"][0]["review_status"] = "approved"
    payload["entries"][0]["rule"]["machine_actionability"] = "blocked"
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "approved_blocked_rule" in {item.code for item in result.errors}
