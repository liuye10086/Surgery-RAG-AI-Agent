"""Deterministic source-segment binding for approved manifest rules."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.models import Disease, ReferenceStandard, ReferenceStandardVersion, StandardRule, StandardSegment
from app.services.standard_manifest import load_standard_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_DIRECTORY = PROJECT_ROOT / "standard_manifests"
SUPPORTED_DATASETS = frozenset({"ad", "fatty_liver"})


class StandardSourceBindingError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SourceBindingPlan:
    dataset: str
    version_id: int
    total_rules: int
    to_bind: tuple[tuple[int, int], ...]
    consistent: int


def normalize_source_text(value: str) -> str:
    return "\n".join(
        line.rstrip() for line in str(value).replace("\r\n", "\n").split("\n")
    ).strip()


def resolve_manifest_source_segment(
    db: Any,
    *,
    version_id: int,
    source: Any,
) -> StandardSegment:
    expected = normalize_source_text(getattr(source, "raw_text", "") or "")
    if not expected:
        raise StandardSourceBindingError("source_segment_missing")
    query = db.query(StandardSegment).filter(StandardSegment.version_id == version_id)
    for field in ("paragraph_index", "table_index", "row_index", "column_index"):
        value = getattr(source, field, None)
        if value is not None:
            query = query.filter(getattr(StandardSegment, field) == value)
    expected_location = tuple(
        getattr(source, field, None)
        for field in ("paragraph_index", "table_index", "row_index", "column_index")
    )
    matches = [
        item
        for item in query.all()
        if tuple(
            getattr(item, field, None)
            for field in ("paragraph_index", "table_index", "row_index", "column_index")
        ) == expected_location
        and normalize_source_text(item.raw_text) == expected
    ]
    if not matches:
        raise StandardSourceBindingError("source_segment_missing")
    if len(matches) != 1:
        raise StandardSourceBindingError("source_segment_ambiguous")
    return matches[0]


def _approved_rule_entries(manifest: Any) -> dict[str, Any]:
    if getattr(manifest, "review_state", None) != "approved":
        raise StandardSourceBindingError("manifest_not_approved")
    return {
        entry.entry_id: entry
        for entry in manifest.entries
        if entry.entry_kind == "rule" and entry.review_status == "approved"
    }


def _current_approved_version(db: Any, dataset: str) -> Any:
    standard = (
        db.query(ReferenceStandard)
        .join(Disease, ReferenceStandard.disease_id == Disease.id)
        .filter(Disease.code == dataset)
        .first()
    )
    if standard is None:
        raise StandardSourceBindingError("current_standard_missing")
    version = getattr(standard, "current_version", None)
    if version is None and getattr(standard, "current_version_id", None) is not None:
        version = db.query(ReferenceStandardVersion).filter(
            ReferenceStandardVersion.id == standard.current_version_id
        ).first()
    if version is None or getattr(version, "status", None) != "approved":
        raise StandardSourceBindingError("current_standard_not_approved")
    return version


def _validate_manifest_for_version(manifest: Any, version: Any, dataset: str) -> dict[str, Any]:
    if dataset not in SUPPORTED_DATASETS or manifest.dataset != dataset:
        raise StandardSourceBindingError("standard_dataset_invalid")
    if getattr(version, "version_label", None) != manifest.target_version_label:
        raise StandardSourceBindingError("manifest_version_label_mismatch")
    if getattr(version, "content_hash", None) != manifest.source_document_sha256:
        raise StandardSourceBindingError("manifest_document_hash_mismatch")
    document = getattr(version, "standard_document", None)
    if document is not None and getattr(document, "content_hash", None) != manifest.source_document_sha256:
        raise StandardSourceBindingError("manifest_document_hash_mismatch")
    return _approved_rule_entries(manifest)


def plan_current_standard_bindings(db: Any, dataset: str) -> SourceBindingPlan:
    if dataset not in SUPPORTED_DATASETS:
        raise StandardSourceBindingError("standard_dataset_invalid")
    manifest = load_standard_manifest(MANIFEST_DIRECTORY / f"{dataset}.v1.json")
    version = _current_approved_version(db, dataset)
    entries = _validate_manifest_for_version(manifest, version, dataset)
    rules = list(getattr(version, "rules", None) or ())
    if not rules:
        raise StandardSourceBindingError("current_standard_rules_missing")

    to_bind: list[tuple[int, int]] = []
    consistent = 0
    for rule in rules:
        entry_id = (getattr(rule, "applicability", {}) or {}).get("_manifest_entry_id")
        entry = entries.get(entry_id)
        if entry is None:
            raise StandardSourceBindingError("manifest_entry_id_missing")
        segment = resolve_manifest_source_segment(
            db, version_id=version.id, source=entry.source
        )
        current_source_id = getattr(rule, "source_segment_id", None)
        if current_source_id is None:
            to_bind.append((rule.id, segment.id))
        elif current_source_id == segment.id:
            consistent += 1
        else:
            raise StandardSourceBindingError("source_binding_conflict")
    return SourceBindingPlan(
        dataset=dataset,
        version_id=version.id,
        total_rules=len(rules),
        to_bind=tuple(to_bind),
        consistent=consistent,
    )


def apply_current_standard_bindings(db: Any, plan: SourceBindingPlan) -> SourceBindingPlan:
    for rule_id, segment_id in plan.to_bind:
        rule = db.query(StandardRule).filter(
            StandardRule.id == rule_id,
            StandardRule.version_id == plan.version_id,
        ).with_for_update().first()
        if rule is None or getattr(rule, "source_segment_id", None) is not None:
            raise StandardSourceBindingError("source_binding_conflict")
        rule.source_segment_id = segment_id
    return SourceBindingPlan(
        dataset=plan.dataset,
        version_id=plan.version_id,
        total_rules=plan.total_rules,
        to_bind=(),
        consistent=plan.total_rules,
    )
