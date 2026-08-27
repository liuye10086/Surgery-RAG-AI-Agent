"""Immutable disease release sets with atomic active pointers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


class ReleaseSetError(ValueError):
    """Stable, privacy-safe disease release set error."""


REQUIRED_TASKS = {
    "fatty_liver": {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "fatty_liver.next_stage",
        "fatty_liver.next_visit_trend.alt",
        "fatty_liver.next_visit_trend.ast",
        "fatty_liver.next_visit_trend.ggt",
        "fatty_liver.next_visit_trend.tbil",
        "fatty_liver.next_visit_trend.alb",
        "fatty_liver.next_visit_trend.plt",
        "fatty_liver.next_visit_trend.afp",
    },
    "ad": {
        "ad.pre_dementia_to_dementia",
        "ad.next_stage",
        "ad.next_visit_trend.mmse",
        "ad.next_visit_trend.moca",
        "ad.next_visit_trend.cdr",
        "ad.next_visit_trend.plasma_nfl",
        "ad.next_visit_trend.plasma_ptau217",
    },
}


@dataclass(frozen=True)
class DiseaseReleaseSet:
    dataset: str
    release_set_id: str
    status: str
    data_release_id: str
    dataset_manifest_sha256: str
    split_sha256: str
    bundles: tuple[dict[str, Any], ...]
    created_at: datetime
    record_path: Path
    record_sha256: str


@dataclass(frozen=True)
class ReleaseSetPointer:
    dataset: str
    release_set_id: str
    release_set_sha256: str
    changed_by: str
    changed_at: datetime


@dataclass(frozen=True)
class ReviewReleaseSetResult:
    release_set: DiseaseReleaseSet
    review_path: Path


@dataclass(frozen=True)
class ReleaseSetDeactivation:
    dataset: str
    previous_release_set_id: str
    changed_by: str
    changed_at: datetime


def _safe_identity(value: str, code: str) -> str:
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 120 or not re.fullmatch(r"[\w.@+-]+", cleaned):
        raise ReleaseSetError(code)
    return cleaned


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path, code: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseSetError(code) from exc
    if not isinstance(value, dict):
        raise ReleaseSetError(code)
    return value


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ReleaseSetError("registry_path_escape") from exc
    return path


def _candidate_file(base: Path, relative: object, code: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ReleaseSetError(code)
    value = Path(relative)
    if value.is_absolute() or ":" in relative:
        raise ReleaseSetError(code)
    resolved = (base / value).resolve()
    if not resolved.is_file():
        raise ReleaseSetError(code)
    return resolved


def _copy_immutable_file(source: Path, destination: Path, expected_sha256: str) -> None:
    if _sha256(source) != expected_sha256:
        raise ReleaseSetError("candidate_bundle_hash_mismatch")
    if destination.exists():
        if not destination.is_file() or _sha256(destination) != expected_sha256:
            raise ReleaseSetError("immutable_registry_conflict")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise ReleaseSetError("registry_import_in_progress")
    try:
        shutil.copyfile(source, temporary)
        if _sha256(temporary) != expected_sha256:
            raise ReleaseSetError("candidate_bundle_hash_mismatch")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _import_dataset_manifest(
    manifest_source: Path,
    registry_root: Path,
    data_release_id: str,
    expected_manifest_sha256: str,
) -> Path:
    if _sha256(manifest_source) != expected_manifest_sha256:
        raise ReleaseSetError("dataset_manifest_hash_mismatch")
    manifest = _read_json(manifest_source, "dataset_manifest_invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ReleaseSetError("dataset_manifest_invalid")
    destination_root = registry_root / "datasets" / data_release_id
    for relative, expected in files.items():
        if (
            not isinstance(relative, str)
            or not isinstance(expected, str)
            or Path(relative).is_absolute()
            or ":" in relative
            or ".." in Path(relative).parts
        ):
            raise ReleaseSetError("dataset_manifest_invalid")
        source = manifest_source.parent / relative
        if not source.is_file():
            raise ReleaseSetError("dataset_file_missing")
        _copy_immutable_file(source, destination_root / relative, expected)
    destination = destination_root / "manifest.json"
    _copy_immutable_file(
        manifest_source, destination, expected_manifest_sha256
    )
    return destination


def _import_candidate_bundles(
    candidate_path: Path,
    candidate: dict[str, Any],
    registry_root: Path,
) -> list[dict[str, Any]]:
    base = candidate_path.parent.resolve()
    dataset = str(candidate["dataset"])
    release_set_id = str(candidate["release_set_id"])
    data_release_id = str(candidate.get("data_release_id", "")).strip()
    manifest_sha256 = str(candidate.get("dataset_manifest_sha256", ""))
    bundles = candidate["bundles"]
    manifest_sources = {
        _candidate_file(base, item.get("manifest_path"), "dataset_manifest_missing")
        for item in bundles
        if isinstance(item, dict)
    }
    if len(manifest_sources) != 1 or not data_release_id:
        raise ReleaseSetError("candidate_manifest_invalid")
    manifest_destination = _import_dataset_manifest(
        manifest_sources.pop(),
        registry_root,
        data_release_id,
        manifest_sha256,
    )
    imported: list[dict[str, Any]] = []
    for index, item in enumerate(bundles):
        if not isinstance(item, dict):
            raise ReleaseSetError("candidate_manifest_invalid")
        task = str(item.get("task", ""))
        safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "_", task)
        if not task or not safe_task:
            raise ReleaseSetError("candidate_manifest_invalid")
        destination_dir = (
            registry_root
            / "bundles"
            / dataset
            / release_set_id
            / f"{index:02d}-{safe_task}"
        )
        rewritten = dict(item)
        for path_field, hash_field in (
            ("model_path", "model_sha256"),
            ("metadata_path", "metadata_sha256"),
            ("evaluation_path", "evaluation_sha256"),
        ):
            source = _candidate_file(
                base, item.get(path_field), "candidate_bundle_missing"
            )
            expected = str(item.get(hash_field, ""))
            destination = destination_dir / source.name
            _copy_immutable_file(source, destination, expected)
            rewritten[path_field] = destination.relative_to(
                registry_root
            ).as_posix()
        rewritten["manifest_path"] = manifest_destination.relative_to(
            registry_root
        ).as_posix()
        imported.append(rewritten)
    return imported


def _atomic_replace_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ReleaseSetError("pointer_update_in_progress")
    data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_immutable_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise ReleaseSetError("record_already_exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        raise ReleaseSetError("record_already_exists")
    data = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, indent=2
    ).encode("utf-8")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            raise ReleaseSetError("record_already_exists")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_release_set_record(
    dataset: str,
    release_set_id: str,
    registry_root: Path,
) -> DiseaseReleaseSet:
    if dataset not in REQUIRED_TASKS:
        raise ReleaseSetError("unsupported_disease")
    root = Path(registry_root).resolve()
    path = root / "release_sets" / dataset / f"{release_set_id}.json"
    if not path.is_file():
        raise ReleaseSetError("release_set_missing")
    raw = _read_json(path, "release_set_invalid")
    required = {
        "schema_version",
        "dataset",
        "release_set_id",
        "status",
        "data_release_id",
        "dataset_manifest_sha256",
        "split_sha256",
        "bundles",
        "created_at",
    }
    if not required.issubset(raw) or raw.get("dataset") != dataset or raw.get("release_set_id") != release_set_id:
        raise ReleaseSetError("release_set_invalid")
    try:
        created_at = datetime.fromisoformat(str(raw["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseSetError("release_set_invalid") from exc
    if created_at.tzinfo is None or not isinstance(raw["bundles"], list):
        raise ReleaseSetError("release_set_invalid")
    return DiseaseReleaseSet(
        dataset=dataset,
        release_set_id=release_set_id,
        status=str(raw["status"]),
        data_release_id=str(raw["data_release_id"]),
        dataset_manifest_sha256=str(raw["dataset_manifest_sha256"]),
        split_sha256=str(raw["split_sha256"]),
        bundles=tuple(dict(item) for item in raw["bundles"]),
        created_at=created_at,
        record_path=path,
        record_sha256=_sha256(path),
    )


def read_active_pointer(
    registry_root: Path, dataset: str
) -> ReleaseSetPointer:
    if dataset not in REQUIRED_TASKS:
        raise ReleaseSetError("unsupported_disease")
    path = Path(registry_root).resolve() / "active" / f"{dataset}.json"
    if not path.is_file():
        raise ReleaseSetError("active_pointer_missing")
    raw = _read_json(path, "active_pointer_invalid")
    if raw.get("status") == "inactive":
        raise ReleaseSetError("active_pointer_inactive")
    try:
        changed_at = datetime.fromisoformat(
            str(raw["changed_at"]).replace("Z", "+00:00")
        )
        pointer = ReleaseSetPointer(
            dataset=str(raw["dataset"]),
            release_set_id=str(raw["release_set_id"]),
            release_set_sha256=str(raw["release_set_sha256"]),
            changed_by=str(raw["changed_by"]),
            changed_at=changed_at,
        )
    except (KeyError, ValueError) as exc:
        raise ReleaseSetError("active_pointer_invalid") from exc
    if pointer.dataset != dataset or pointer.changed_at.tzinfo is None:
        raise ReleaseSetError("active_pointer_invalid")
    return pointer


def load_disease_release_set(
    dataset: str, registry_root: Path
) -> DiseaseReleaseSet:
    pointer = read_active_pointer(registry_root, dataset)
    release_set = load_release_set_record(
        dataset, pointer.release_set_id, registry_root
    )
    if release_set.record_sha256 != pointer.release_set_sha256:
        raise ReleaseSetError("active_pointer_hash_mismatch")
    return release_set


def review_release_set(
    candidate_manifest: Path,
    registry_root: Path,
    *,
    reviewer: str,
    reviewed_at: datetime,
    note: str,
) -> ReviewReleaseSetResult:
    reviewer_id = _safe_identity(reviewer, "reviewer_required")
    review_note = note.strip()
    if not review_note or len(review_note) > 2000:
        raise ReleaseSetError("review_note_required")
    if reviewed_at.tzinfo is None:
        raise ReleaseSetError("review_time_invalid")
    candidate_path = Path(candidate_manifest).resolve()
    candidate = _read_json(candidate_path, "candidate_manifest_invalid")
    dataset = str(candidate.get("dataset", ""))
    if dataset not in REQUIRED_TASKS:
        raise ReleaseSetError("unsupported_disease")
    bundles = candidate.get("bundles")
    if not isinstance(bundles, list):
        raise ReleaseSetError("candidate_manifest_invalid")
    tasks = {str(item.get("task")) for item in bundles if isinstance(item, dict)}
    if tasks != REQUIRED_TASKS[dataset]:
        raise ReleaseSetError("required_bundle_missing")
    root = Path(registry_root).resolve()
    release_set_id = str(candidate.get("release_set_id", "")).strip()
    if not release_set_id:
        raise ReleaseSetError("release_set_id_required")
    imported_bundles = _import_candidate_bundles(
        candidate_path, candidate, root
    )
    release_payload = {
        "schema_version": "longitudinal_disease_release_set.v1",
        "dataset": dataset,
        "release_set_id": release_set_id,
        "status": "reviewed",
        "data_release_id": str(candidate.get("data_release_id", "")),
        "dataset_manifest_sha256": str(
            candidate.get("dataset_manifest_sha256", "0" * 64)
        ),
        "split_sha256": str(candidate.get("split_sha256", "0" * 64)),
        "bundles": imported_bundles,
        "created_at": reviewed_at.isoformat(),
    }
    release_path = (
        root / "release_sets" / dataset / f"{release_set_id}.json"
    )
    _write_immutable_json(release_path, release_payload)
    release_set = load_release_set_record(dataset, release_set_id, root)
    review_id = "review-set-" + hashlib.sha256(
        f"{dataset}|{release_set_id}|{reviewed_at.isoformat()}".encode("utf-8")
    ).hexdigest()[:24]
    review_path = root / "reviews" / f"{review_id}.json"
    _write_immutable_json(
        review_path,
        {
            "schema_version": "longitudinal_disease_release_set_review.v1",
            "review_id": review_id,
            "dataset": dataset,
            "release_set_id": release_set_id,
            "release_set_path": release_path.relative_to(root).as_posix(),
            "release_set_sha256": release_set.record_sha256,
            "reviewer": reviewer_id,
            "reviewed_at": reviewed_at.isoformat(),
            "note": review_note,
        },
    )
    return ReviewReleaseSetResult(release_set, review_path)


def preload_release_set(
    dataset: str,
    release_set_id: str,
    registry_root: Path,
) -> DiseaseReleaseSet:
    release_set = load_release_set_record(dataset, release_set_id, registry_root)
    tasks = {str(item.get("task")) for item in release_set.bundles}
    if release_set.bundles and tasks != REQUIRED_TASKS[dataset]:
        raise ReleaseSetError("required_bundle_missing")
    try:
        from app.services.longitudinal_model_registry import (
            _suite_entry_from_bundle,
        )

        entries = [
            _suite_entry_from_bundle(bundle, Path(registry_root).resolve())
            for bundle in release_set.bundles
        ]
    except ReleaseSetError:
        raise
    except Exception as exc:
        raise ReleaseSetError("bundle_preload_failed") from exc
    if any(entry.status.status != "available" for entry in entries):
        raise ReleaseSetError("bundle_preload_failed")
    return release_set


def _write_activation(
    release_set: DiseaseReleaseSet,
    root: Path,
    *,
    actor: str,
    changed_at: datetime,
    action: str,
) -> ReleaseSetPointer:
    actor_id = _safe_identity(actor, "actor_required")
    if changed_at.tzinfo is None:
        raise ReleaseSetError("change_time_invalid")
    pointer_payload = {
        "schema_version": "longitudinal_disease_release_pointer.v1",
        "dataset": release_set.dataset,
        "release_set_id": release_set.release_set_id,
        "release_set_sha256": release_set.record_sha256,
        "changed_by": actor_id,
        "changed_at": changed_at.isoformat(),
    }
    _atomic_replace_json(
        root / "active" / f"{release_set.dataset}.json", pointer_payload
    )
    activation_id = hashlib.sha256(
        f"{action}|{release_set.dataset}|{release_set.release_set_id}|{changed_at.isoformat()}".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    _write_immutable_json(
        root / "activation_log" / f"{action}-{activation_id}.json",
        {**pointer_payload, "action": action},
    )
    return ReleaseSetPointer(
        dataset=release_set.dataset,
        release_set_id=release_set.release_set_id,
        release_set_sha256=release_set.record_sha256,
        changed_by=actor_id,
        changed_at=changed_at,
    )


def enable_release_set(
    review_path: Path,
    registry_root: Path,
    *,
    enabled_by: str,
    enabled_at: datetime,
) -> ReleaseSetPointer:
    root = Path(registry_root).resolve()
    review = _read_json(Path(review_path), "review_record_invalid")
    dataset = str(review.get("dataset", ""))
    release_set_id = str(review.get("release_set_id", ""))
    release_set = load_release_set_record(dataset, release_set_id, root)
    if _sha256(release_set.record_path) != review.get("release_set_sha256"):
        raise ReleaseSetError("integrity_chain_broken")
    preloaded = preload_release_set(dataset, release_set_id, root)
    return _write_activation(
        preloaded,
        root,
        actor=enabled_by,
        changed_at=enabled_at,
        action="enable",
    )


def rollback_release_set(
    dataset: str,
    target_release_set_id: str,
    registry_root: Path,
    *,
    actor: str,
    changed_at: datetime,
) -> ReleaseSetPointer:
    root = Path(registry_root).resolve()
    preloaded = preload_release_set(dataset, target_release_set_id, root)
    return _write_activation(
        preloaded,
        root,
        actor=actor,
        changed_at=changed_at,
        action="rollback",
    )


def deactivate_release_set(
    dataset: str,
    expected_release_set_id: str,
    registry_root: Path,
    *,
    actor: str,
    changed_at: datetime,
) -> ReleaseSetDeactivation:
    """Atomically restore the pre-v3 state after a first activation."""
    if dataset not in REQUIRED_TASKS:
        raise ReleaseSetError("unsupported_disease")
    actor_id = _safe_identity(actor, "actor_required")
    expected_id = _safe_identity(
        expected_release_set_id, "release_set_id_invalid"
    )
    if changed_at.tzinfo is None:
        raise ReleaseSetError("change_time_invalid")
    root = Path(registry_root).resolve()
    current = read_active_pointer(root, dataset)
    if current.release_set_id != expected_id:
        raise ReleaseSetError("active_pointer_changed")
    pointer_payload = {
        "schema_version": "longitudinal_disease_release_pointer.v1",
        "status": "inactive",
        "dataset": dataset,
        "previous_release_set_id": current.release_set_id,
        "previous_release_set_sha256": current.release_set_sha256,
        "changed_by": actor_id,
        "changed_at": changed_at.isoformat(),
    }
    _atomic_replace_json(root / "active" / f"{dataset}.json", pointer_payload)
    activation_id = hashlib.sha256(
        f"deactivate|{dataset}|{current.release_set_id}|{changed_at.isoformat()}".encode(
            "utf-8"
        )
    ).hexdigest()[:24]
    _write_immutable_json(
        root / "activation_log" / f"deactivate-{activation_id}.json",
        {**pointer_payload, "action": "deactivate"},
    )
    return ReleaseSetDeactivation(
        dataset=dataset,
        previous_release_set_id=current.release_set_id,
        changed_by=actor_id,
        changed_at=changed_at,
    )
