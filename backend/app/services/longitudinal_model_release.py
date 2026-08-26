"""Explicit immutable review and enable workflow for longitudinal artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.schemas.longitudinal_model_registry import (
    RELEASE_RECORD_SCHEMA_VERSION,
    REVIEW_RECORD_SCHEMA_VERSION,
    TASK_CONTRACTS,
    ReleaseRecord,
    ReviewRecord,
)
from app.services.longitudinal_model_registry import (
    sha256_file,
    validate_candidate_bundle,
)


class ModelReleaseError(ValueError):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ReviewResult:
    record: ReviewRecord
    path: Path


@dataclass(frozen=True)
class ReleaseResult:
    record: ReleaseRecord
    path: Path


def _audit_identity(value: str, code: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 120 or not re.fullmatch(r"[\w.@+-]+", cleaned):
        raise ModelReleaseError(code)
    return cleaned


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ModelReleaseError("registry_path_escape") from exc
    return resolved


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ModelReleaseError("record_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ModelReleaseError("record_already_exists")
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode(
        "utf-8"
    )
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise ModelReleaseError("record_already_exists")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _record_id(prefix: str, parts: list[str]) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def review_candidate(
    bundle_dir: Path,
    registry_root: Path,
    *,
    reviewer: str,
    reviewed_at: datetime,
    note: str,
) -> ReviewResult:
    reviewer_id = _audit_identity(reviewer, "reviewer_required")
    review_note = note.strip()
    if not review_note or len(review_note) > 2000:
        raise ModelReleaseError("review_note_required")
    if reviewed_at.tzinfo is None:
        raise ModelReleaseError("review_time_invalid")
    validation = validate_candidate_bundle(Path(bundle_dir), inspect_model=True)
    if validation.status.reason_code != "lifecycle_not_enabled" or validation.metadata is None:
        raise ModelReleaseError("candidate_invalid")
    if validation.model_path is None or validation.metadata_path is None:
        raise ModelReleaseError("candidate_invalid")

    source_model = Path(validation.model_path)
    source_metadata = Path(validation.metadata_path)
    metadata = validation.metadata
    root = Path(registry_root).resolve()
    bundle_target = root / "bundles" / metadata.model_contract.model_id
    if bundle_target.exists():
        raise ModelReleaseError("record_already_exists")
    bundle_target.parent.mkdir(parents=True, exist_ok=True)
    temporary_bundle = bundle_target.with_name(bundle_target.name + ".tmp")
    if temporary_bundle.exists():
        raise ModelReleaseError("record_already_exists")
    temporary_bundle.mkdir()
    target_model = temporary_bundle / source_model.name
    target_metadata = temporary_bundle / source_metadata.name
    try:
        shutil.copy2(source_model, target_model)
        shutil.copy2(source_metadata, target_metadata)
        if (
            sha256_file(source_model) != sha256_file(target_model)
            or sha256_file(source_metadata) != sha256_file(target_metadata)
        ):
            raise ModelReleaseError("copy_hash_mismatch")
        temporary_bundle.replace(bundle_target)
    finally:
        if temporary_bundle.exists():
            shutil.rmtree(temporary_bundle)

    final_model = bundle_target / source_model.name
    final_metadata = bundle_target / source_metadata.name
    model_hash = sha256_file(final_model)
    metadata_hash = sha256_file(final_metadata)
    timestamp = reviewed_at.isoformat()
    review_id = _record_id(
        "review",
        [metadata.task, model_hash, metadata_hash, timestamp],
    )
    record = ReviewRecord(
        schema_version=REVIEW_RECORD_SCHEMA_VERSION,
        review_id=review_id,
        task=metadata.task,
        model_id=metadata.model_contract.model_id,
        status="reviewed",
        production_enabled=False,
        reviewer=reviewer_id,
        reviewed_at=reviewed_at,
        note=review_note,
        model_sha256=model_hash,
        metadata_sha256=metadata_hash,
        model_path=final_model.relative_to(root).as_posix(),
        metadata_path=final_metadata.relative_to(root).as_posix(),
    )
    path = root / "reviews" / f"{review_id}.json"
    try:
        _atomic_json(path, record.model_dump(mode="json"))
    except Exception:
        if bundle_target.exists():
            shutil.rmtree(bundle_target)
        raise
    return ReviewResult(record=record, path=path)


def enable_review(
    review_path: Path,
    registry_root: Path,
    *,
    enabled_by: str,
    enabled_at: datetime,
) -> ReleaseResult:
    enabler = _audit_identity(enabled_by, "enabler_required")
    if enabled_at.tzinfo is None:
        raise ModelReleaseError("enable_time_invalid")
    root = Path(registry_root).resolve()
    path = _inside(root, Path(review_path))
    if not path.is_file():
        raise ModelReleaseError("review_record_missing")
    try:
        review = ReviewRecord.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError) as exc:
        raise ModelReleaseError("review_record_invalid") from exc
    model_path = _inside(root, root / review.model_path)
    metadata_path = _inside(root, root / review.metadata_path)
    if not model_path.is_file() or not metadata_path.is_file():
        raise ModelReleaseError("candidate_missing")
    if (
        sha256_file(model_path) != review.model_sha256
        or sha256_file(metadata_path) != review.metadata_sha256
    ):
        raise ModelReleaseError("integrity_chain_broken")
    validation = validate_candidate_bundle(model_path.parent, inspect_model=True)
    if validation.status.reason_code != "lifecycle_not_enabled" or validation.metadata is None:
        raise ModelReleaseError("candidate_invalid")
    metadata = validation.metadata
    if metadata.task != review.task or metadata.model_contract.model_id != review.model_id:
        raise ModelReleaseError("integrity_chain_broken")

    release_dir = root / "releases" / TASK_CONTRACTS[review.task].artifact_stem
    if release_dir.is_dir() and any(release_dir.glob("*.json")):
        raise ModelReleaseError("multiple_enabled_artifacts")
    review_hash = sha256_file(path)
    timestamp = enabled_at.isoformat()
    release_id = _record_id(
        "release",
        [review.task, review.model_sha256, review.metadata_sha256, review_hash, timestamp],
    )
    record = ReleaseRecord(
        schema_version=RELEASE_RECORD_SCHEMA_VERSION,
        release_id=release_id,
        review_id=review.review_id,
        task=review.task,
        model_id=review.model_id,
        status="enabled",
        production_enabled=True,
        enabled_by=enabler,
        enabled_at=enabled_at,
        model_sha256=review.model_sha256,
        metadata_sha256=review.metadata_sha256,
        review_sha256=review_hash,
        model_path=review.model_path,
        metadata_path=review.metadata_path,
        review_path=path.relative_to(root).as_posix(),
    )
    release_path = release_dir / f"{release_id}.json"
    _atomic_json(release_path, record.model_dump(mode="json"))
    return ReleaseResult(record=record, path=release_path)
