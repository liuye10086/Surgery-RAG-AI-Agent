import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.standard_evidence import (
    StandardEvidenceError,
    build_standard_evidence,
    preflight_standard,
)


@pytest.fixture(autouse=True)
def approved_manifest(monkeypatch):
    """Keep evidence tests isolated from repository medical-standard content."""
    def load_manifest(path):
        dataset = Path(path).name.split(".", 1)[0]
        return SimpleNamespace(
            dataset=dataset,
            review_state="approved",
            target_version_label="2026.1",
            source_document_sha256=hashlib.sha256(b"approved standard content").hexdigest(),
            entries=[
                SimpleNamespace(
                    entry_id="test-alt-reference",
                    entry_kind="rule",
                    review_status="approved",
                    source=SimpleNamespace(
                        paragraph_index=2,
                        table_index=1,
                        row_index=3,
                        column_index=2,
                        raw_text="ALT 7-40 U/L",
                    ),
                )
            ],
        )

    monkeypatch.setattr(
        "app.services.standard_evidence.load_standard_manifest",
        load_manifest,
        raising=False,
    )


class _Query:
    def __init__(self, value):
        self.value = value

    def filter(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def first(self):
        return self.value


def _db(value):
    return SimpleNamespace(query=lambda model: _Query(value))


def _approved(tmp_path: Path, *, disease_id=1, disease_code="fatty_liver", actionability="calculable"):
    content = b"approved standard content"
    path = tmp_path / "standard.txt"
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    segment = SimpleNamespace(
        id=11, version_id=6, section_title="Reference", paragraph_index=2, table_index=1,
        row_index=3, column_index=2, page_number=4, raw_text="ALT 7-40 U/L",
    )
    indicator = SimpleNamespace(canonical_key="alt", name_en="ALT", aliases=[])
    rule = SimpleNamespace(
        id=7, indicator=indicator, source_segment=segment, machine_actionability=actionability,
        unit="U/L", lower=7, upper=40, lower_inclusive=True, upper_inclusive=True,
        applicability={"_manifest_sha256": digest, "_manifest_entry_id": "test-alt-reference"}, interpretation="within reference", conflict_group=None,
    )
    document = SimpleNamespace(
        id=5, title="Fatty liver standard", filename="standard.txt", file_path=str(path),
        content_hash=digest, issuer="Society", publication_date=None,
        external_identifier="STD-1", source_url="https://example.test/std",
    )
    version = SimpleNamespace(
        id=6, standard_id=9, version_label="2026.1", content_hash=digest,
        parser_version="parser-1", approved_at=None, effective_from=None,
        status="approved", standard_document=document, rules=[rule], segments=[segment],
    )
    standard = SimpleNamespace(
        id=9, disease_id=disease_id, name="Fatty liver", current_version=version,
        disease=SimpleNamespace(code=disease_code),
    )
    return standard


@pytest.fixture
def approved_standard(tmp_path):
    return _approved(tmp_path)


def test_preflight_rejects_document_hash_mismatch(tmp_path):
    standard = _approved(tmp_path)
    Path(standard.current_version.standard_document.file_path).write_bytes(b"changed")
    with pytest.raises(StandardEvidenceError) as error:
        preflight_standard(_db(standard), 1, "fatty_liver")
    assert error.value.code == "standard_integrity_failed"


def test_preflight_rejects_missing_or_unapproved_standard(tmp_path):
    with pytest.raises(StandardEvidenceError, match="standard_missing"):
        preflight_standard(_db(None), 1, "fatty_liver")
    standard = _approved(tmp_path)
    standard.current_version.status = "draft"
    with pytest.raises(StandardEvidenceError) as error:
        preflight_standard(_db(standard), 1, "fatty_liver")
    assert error.value.code == "standard_not_approved"


def test_preflight_rejects_rule_manifest_not_bound_to_document(tmp_path):
    standard = _approved(tmp_path)
    standard.current_version.rules[0].applicability["_manifest_sha256"] = "b" * 64

    with pytest.raises(StandardEvidenceError) as error:
        preflight_standard(_db(standard), 1, "fatty_liver")

    assert error.value.code == "standard_integrity_failed"


@pytest.mark.parametrize(
    "source",
    [
        None,
        SimpleNamespace(
            id=7,
            version_id=99,
            paragraph_index=2,
            table_index=1,
            row_index=3,
            column_index=2,
            raw_text="ALT 7-40 U/L",
        ),
    ],
)
def test_preflight_rejects_missing_or_cross_version_rule_source(source, approved_standard):
    approved_standard.current_version.rules[0].source_segment = source

    with pytest.raises(StandardEvidenceError) as caught:
        preflight_standard(_db(approved_standard), 1, "fatty_liver")

    assert caught.value.code == "standard_integrity_failed"


@pytest.mark.parametrize(
    "source_change",
    [
        {"raw_text": ""},
        {"raw_text": "drifted source text"},
        {"row_index": 4},
    ],
)
def test_preflight_rejects_empty_or_drifted_rule_source(source_change, approved_standard):
    source = approved_standard.current_version.rules[0].source_segment
    for field, value in source_change.items():
        setattr(source, field, value)

    with pytest.raises(StandardEvidenceError) as caught:
        preflight_standard(_db(approved_standard), 1, "fatty_liver")

    assert caught.value.code == "standard_integrity_failed"


def test_preflight_rejects_unexpected_locator_coordinate(approved_standard, monkeypatch):
    document_hash = approved_standard.current_version.content_hash
    monkeypatch.setattr(
        "app.services.standard_evidence.load_standard_manifest",
        lambda _path: SimpleNamespace(
            dataset="fatty_liver",
            review_state="approved",
            target_version_label="2026.1",
            source_document_sha256=document_hash,
            entries=[SimpleNamespace(
                entry_id="test-alt-reference",
                entry_kind="rule",
                review_status="approved",
                source=SimpleNamespace(
                    paragraph_index=2,
                    table_index=1,
                    row_index=3,
                    column_index=None,
                    raw_text="ALT 7-40 U/L",
                ),
            )],
        ),
    )
    approved_standard.current_version.rules[0].source_segment.column_index = 99

    with pytest.raises(StandardEvidenceError) as caught:
        preflight_standard(_db(approved_standard), 1, "fatty_liver")

    assert caught.value.code == "standard_integrity_failed"


@pytest.mark.parametrize("rule_count", [0, 2])
def test_preflight_requires_exactly_one_db_rule_per_approved_manifest_entry(
    approved_standard, rule_count
):
    rule = approved_standard.current_version.rules[0]
    approved_standard.current_version.rules = [rule] * rule_count

    with pytest.raises(StandardEvidenceError) as caught:
        preflight_standard(_db(approved_standard), 1, "fatty_liver")

    assert caught.value.code == "standard_integrity_failed"


def test_build_standard_evidence_contains_locator_and_safe_numeric_interpretation(tmp_path):
    standard = _approved(tmp_path)
    db = _db(standard)
    token = preflight_standard(db, 1, "fatty_liver")
    evidence = build_standard_evidence(
        db,
        token,
        {"case": {"age": 55, "sex": "female", "disease_code": "fatty_liver"},
         "visits": [{"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}], "visit_context": {}}]},
    )
    assert evidence.status == "available"
    assert evidence.document.external_identifier == "STD-1"
    assert evidence.rules[0].source.page_number == 4
    assert evidence.rules[0].numeric_interpretation == "above_range"


def test_build_standard_evidence_applies_rule_sex_before_calculating_alt(tmp_path, monkeypatch):
    standard = _approved(tmp_path)
    male_rule = standard.current_version.rules[0]
    male_rule.sex = "male"
    female_rule = SimpleNamespace(**{**male_rule.__dict__, "id": 8, "sex": "female"})
    female_rule.applicability = {
        **female_rule.applicability,
        "_manifest_entry_id": "test-alt-reference-female",
    }
    standard.current_version.rules = [male_rule, female_rule]
    source = SimpleNamespace(
        paragraph_index=2,
        table_index=1,
        row_index=3,
        column_index=2,
        raw_text="ALT 7-40 U/L",
    )
    monkeypatch.setattr(
        "app.services.standard_evidence.load_standard_manifest",
        lambda _path: SimpleNamespace(
            dataset="fatty_liver",
            review_state="approved",
            target_version_label="2026.1",
            source_document_sha256=standard.current_version.content_hash,
            entries=[
                SimpleNamespace(entry_id="test-alt-reference", entry_kind="rule", review_status="approved", source=source),
                SimpleNamespace(entry_id="test-alt-reference-female", entry_kind="rule", review_status="approved", source=source),
            ],
        ),
    )
    token = preflight_standard(_db(standard), 1, "fatty_liver")

    evidence = build_standard_evidence(
        _db(standard),
        token,
        {
            "case": {"age": 55, "sex": "male", "disease_code": "fatty_liver"},
            "visits": [{"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}], "visit_context": {}}],
        },
    )

    rules_by_id = {rule.rule_id: rule for rule in evidence.rules}
    assert rules_by_id[7].status == "calculable"
    assert rules_by_id[8].status == "not_applicable"
    assert rules_by_id[7].numeric_interpretation == "above_range"
    assert rules_by_id[8].numeric_interpretation is None


def test_ad_rules_remain_evidence_only(tmp_path):
    standard = _approved(tmp_path, disease_code="ad", actionability="calculable")
    token = preflight_standard(_db(standard), 1, "ad")
    evidence = build_standard_evidence(
        _db(standard), token,
        {"case": {"disease_code": "ad"}, "visits": [{"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42}]}]},
    )
    assert all(rule.status != "calculable" for rule in evidence.rules)
    assert all(rule.numeric_interpretation is None for rule in evidence.rules)


def test_missing_applicability_context_never_produces_numeric_interpretation(tmp_path):
    standard = _approved(tmp_path)
    standard.current_version.rules[0].applicability.update({"platform": "required"})
    token = preflight_standard(_db(standard), 1, "fatty_liver")

    evidence = build_standard_evidence(
        _db(standard), token,
        {"case": {"disease_code": "fatty_liver"}, "visits": [{"visit_date": "2026-01-01", "indicators": [{"name": "ALT", "value": 42, "unit": "U/L"}]}]},
    )

    assert evidence.rules[0].status == "missing_context"
    assert evidence.rules[0].numeric_interpretation is None


def test_no_matching_rule_is_not_applicable(tmp_path):
    standard = _approved(tmp_path)
    token = preflight_standard(_db(standard), 1, "fatty_liver")

    evidence = build_standard_evidence(
        _db(standard), token,
        {"case": {"disease_code": "fatty_liver"}, "visits": [{"visit_date": "2026-01-01", "indicators": [{"name": "AST", "value": 42, "unit": "U/L"}]}]},
    )

    assert evidence.rules == []
    assert evidence.status == "not_applicable"
