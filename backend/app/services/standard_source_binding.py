"""Deterministic source-segment binding for approved manifest rules."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

from app.db.models import Disease, ReferenceStandard, ReferenceStandardVersion, StandardRule, StandardSegment
from app.services.operator_indicator_catalog import _project_root
from app.services.standard_manifest import load_standard_manifest


PROJECT_ROOT = _project_root()
MANIFEST_DIRECTORY = PROJECT_ROOT / "standard_manifests"
SUPPORTED_DATASETS = frozenset({"ad", "fatty_liver"})
SOURCE_LOCATOR_FIELDS = (
    "paragraph_index",
    "table_index",
    "row_index",
    "column_index",
)


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


def source_locator_tuple(source: Any) -> tuple[Any, Any, Any, Any]:
    """Return the complete stable source location, including intentional nulls."""
    return tuple(getattr(source, field, None) for field in SOURCE_LOCATOR_FIELDS)


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except (OSError, TypeError, ValueError):
        return None


def approved_manifest_path(dataset: str) -> Path:
    if dataset not in SUPPORTED_DATASETS:
        raise StandardSourceBindingError("standard_dataset_invalid")
    return MANIFEST_DIRECTORY / f"{dataset}.v1.json"


def validate_rule_source_binding(
    rule: Any,
    *,
    version_id: int,
    manifest_entry: Any,
) -> None:
    """Require an approved rule to retain its exact manifest source binding."""
    source = getattr(rule, "source_segment", None)
    expected_source = getattr(manifest_entry, "source", None)
    if source is None or expected_source is None:
        raise StandardSourceBindingError("standard_integrity_failed")
    if getattr(source, "version_id", None) != version_id:
        raise StandardSourceBindingError("standard_integrity_failed")
    actual_text = normalize_source_text(getattr(source, "raw_text", "") or "")
    expected_text = normalize_source_text(getattr(expected_source, "raw_text", "") or "")
    if not actual_text or actual_text != expected_text:
        raise StandardSourceBindingError("standard_integrity_failed")
    if source_locator_tuple(source) != source_locator_tuple(expected_source):
        raise StandardSourceBindingError("standard_integrity_failed")


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
    for field in SOURCE_LOCATOR_FIELDS:
        value = getattr(source, field, None)
        if value is not None:
            query = query.filter(getattr(StandardSegment, field) == value)
    expected_location = source_locator_tuple(source)
    matches = [
        item
        for item in query.all()
        if source_locator_tuple(item) == expected_location
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
    entries: dict[str, Any] = {}
    for entry in manifest.entries:
        if entry.entry_kind != "rule" or entry.review_status != "approved":
            continue
        if entry.entry_id in entries:
            raise StandardSourceBindingError("manifest_entry_id_duplicate")
        entries[entry.entry_id] = entry
    return entries


def _rules_by_manifest_entry_id(rules: Any) -> dict[str, Any]:
    entries: dict[str, Any] = {}
    for rule in rules:
        entry_id = (getattr(rule, "applicability", None) or {}).get("_manifest_entry_id")
        if not isinstance(entry_id, str) or not entry_id:
            raise StandardSourceBindingError("manifest_entry_id_missing")
        if entry_id in entries:
            raise StandardSourceBindingError("manifest_entry_id_duplicate")
        entries[entry_id] = rule
    return entries


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
    if document is None or getattr(document, "content_hash", None) != manifest.source_document_sha256:
        raise StandardSourceBindingError("manifest_document_hash_mismatch")
    if _sha256_file(Path(str(getattr(document, "file_path", "")))) != manifest.source_document_sha256:
        raise StandardSourceBindingError("manifest_document_hash_mismatch")
    return _approved_rule_entries(manifest)


def validate_version_manifest_rule_bindings(version: Any, dataset: str) -> None:
    """Fail closed unless a version has a complete, uniquely bound approved manifest."""
    if dataset not in SUPPORTED_DATASETS:
        raise StandardSourceBindingError("standard_dataset_invalid")
    manifest = load_standard_manifest(approved_manifest_path(dataset))
    entries = _validate_manifest_for_version(manifest, version, dataset)
    rules_by_entry = _rules_by_manifest_entry_id(getattr(version, "rules", None) or ())
    if set(rules_by_entry) != set(entries):
        raise StandardSourceBindingError("manifest_rule_set_mismatch")
    for entry_id, rule in rules_by_entry.items():
        validate_rule_source_binding(
            rule,
            version_id=version.id,
            manifest_entry=entries[entry_id],
        )


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
