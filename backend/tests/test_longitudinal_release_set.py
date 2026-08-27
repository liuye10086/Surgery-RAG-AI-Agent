from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest


NOW = datetime(2026, 8, 27, tzinfo=timezone.utc)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _release_record(root: Path, dataset: str, release_set_id: str) -> Path:
    payload = {
        "schema_version": "longitudinal_disease_release_set.v1",
        "dataset": dataset,
        "release_set_id": release_set_id,
        "status": "reviewed",
        "data_release_id": f"{dataset}-data-v1",
        "dataset_manifest_sha256": "a" * 64,
        "split_sha256": "b" * 64,
        "bundles": [],
        "created_at": NOW.isoformat(),
    }
    return _write_json(
        root / "release_sets" / dataset / f"{release_set_id}.json", payload
    )


def _review_record(root: Path, release_path: Path, review_id: str) -> Path:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    return _write_json(
        root / "reviews" / f"{review_id}.json",
        {
            "schema_version": "longitudinal_disease_release_set_review.v1",
            "review_id": review_id,
            "dataset": release["dataset"],
            "release_set_id": release["release_set_id"],
            "release_set_path": release_path.relative_to(root).as_posix(),
            "release_set_sha256": _sha(release_path),
            "reviewer": "owner",
            "reviewed_at": NOW.isoformat(),
            "note": "reviewed",
        },
    )


def _seed_active(root: Path, dataset: str, release_set_id: str):
    release = _release_record(root, dataset, release_set_id)
    _write_json(
        root / "active" / f"{dataset}.json",
        {
            "schema_version": "longitudinal_disease_release_pointer.v1",
            "dataset": dataset,
            "release_set_id": release_set_id,
            "release_set_sha256": _sha(release),
            "changed_by": "owner",
            "changed_at": NOW.isoformat(),
        },
    )
    return release


def test_release_set_requires_declared_outcome_stage_and_trend_bundles(tmp_path):
    from app.services.longitudinal_release_set import (
        ReleaseSetError,
        review_release_set,
    )

    tasks = [
        "ad.pre_dementia_to_dementia",
        "ad.next_visit_trend.mmse",
        "ad.next_visit_trend.moca",
        "ad.next_visit_trend.cdr",
        "ad.next_visit_trend.plasma_nfl",
        "ad.next_visit_trend.plasma_ptau217",
    ]
    candidate = _write_json(
        tmp_path / "candidate.json",
        {
            "schema_version": "longitudinal_disease_release_set_candidate.v1",
            "dataset": "ad",
            "release_set_id": "ad-set-v1",
            "data_release_id": "ad-data-v1",
            "dataset_manifest": "dataset/manifest.json",
            "bundles": [
                {"task": task, "bundle_dir": f"bundles/{index}"}
                for index, task in enumerate(tasks)
            ],
        },
    )

    with pytest.raises(ReleaseSetError, match="required_bundle_missing"):
        review_release_set(
            candidate,
            tmp_path / "registry",
            reviewer="owner",
            reviewed_at=NOW,
            note="review",
        )


def test_review_rejects_complete_manifest_when_bundle_files_are_missing(tmp_path):
    from app.services.longitudinal_release_set import (
        REQUIRED_TASKS,
        ReleaseSetError,
        review_release_set,
    )

    manifest = _write_json(
        tmp_path / "candidate" / "dataset" / "manifest.json",
        {"files": {}},
    )
    candidate = _write_json(
        tmp_path / "candidate" / "ad.candidate-set.json",
        {
            "schema_version": "longitudinal_disease_release_set_candidate.v1",
            "dataset": "ad",
            "release_set_id": "ad-set-v1",
            "data_release_id": "ad-data-v1",
                "dataset_manifest_sha256": _sha(manifest),
            "split_sha256": "b" * 64,
            "bundles": [
                {
                    "task": task,
                    "artifact_type": (
                        "outcome"
                        if task == "ad.pre_dementia_to_dementia"
                        else "stage"
                        if task == "ad.next_stage"
                        else "trend"
                    ),
                    "indicator": task.rsplit(".", 1)[-1]
                    if ".next_visit_trend." in task
                    else None,
                    "model_path": f"missing/{index}.joblib",
                    "metadata_path": f"missing/{index}.meta.json",
                    "evaluation_path": f"missing/{index}.evaluation.json",
                    "manifest_path": "dataset/manifest.json",
                    "model_sha256": "c" * 64,
                    "metadata_sha256": "d" * 64,
                    "evaluation_sha256": "e" * 64,
                }
                for index, task in enumerate(sorted(REQUIRED_TASKS["ad"]))
            ],
        },
    )

    with pytest.raises(ReleaseSetError, match="candidate_bundle_missing"):
        review_release_set(
            candidate,
            tmp_path / "registry",
            reviewer="owner",
            reviewed_at=NOW,
            note="review",
        )

    assert not (tmp_path / "registry" / "reviews").exists()


def test_failed_preload_does_not_change_active_pointer(tmp_path, monkeypatch):
    import app.services.longitudinal_release_set as release_sets

    root = tmp_path / "registry"
    _seed_active(root, "ad", "ad-set-v1")
    new_release = _release_record(root, "ad", "ad-set-v2")
    review = _review_record(root, new_release, "review-v2")
    monkeypatch.setattr(
        release_sets,
        "preload_release_set",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            release_sets.ReleaseSetError("preload_failed")
        ),
    )

    with pytest.raises(release_sets.ReleaseSetError, match="preload_failed"):
        release_sets.enable_release_set(
            review, root, enabled_by="owner", enabled_at=NOW
        )

    assert release_sets.read_active_pointer(root, "ad").release_set_id == "ad-set-v1"


def test_rollback_atomically_restores_previous_release_set(tmp_path, monkeypatch):
    import app.services.longitudinal_release_set as release_sets

    root = tmp_path / "registry"
    _release_record(root, "fatty_liver", "fl-set-v1")
    _seed_active(root, "fatty_liver", "fl-set-v2")
    monkeypatch.setattr(
        release_sets,
        "preload_release_set",
        lambda dataset, release_set_id, registry_root: release_sets.load_release_set_record(
            dataset, release_set_id, registry_root
        ),
    )

    release_sets.rollback_release_set(
        "fatty_liver",
        "fl-set-v1",
        root,
        actor="owner",
        changed_at=NOW,
    )

    assert (
        release_sets.read_active_pointer(root, "fatty_liver").release_set_id
        == "fl-set-v1"
    )


def test_deactivate_restores_pre_v3_state_for_first_release(tmp_path):
    import app.services.longitudinal_release_set as release_sets

    root = tmp_path / "registry"
    _seed_active(root, "ad", "ad-set-v1")

    release_sets.deactivate_release_set(
        "ad",
        "ad-set-v1",
        root,
        actor="owner",
        changed_at=NOW,
    )

    pointer = json.loads((root / "active" / "ad.json").read_text(encoding="utf-8"))
    assert pointer["status"] == "inactive"
    assert pointer["previous_release_set_id"] == "ad-set-v1"
    with pytest.raises(release_sets.ReleaseSetError, match="active_pointer_inactive"):
        release_sets.read_active_pointer(root, "ad")


def test_deactivate_rejects_stale_expected_release(tmp_path):
    import app.services.longitudinal_release_set as release_sets

    root = tmp_path / "registry"
    _seed_active(root, "ad", "ad-set-v2")

    with pytest.raises(release_sets.ReleaseSetError, match="active_pointer_changed"):
        release_sets.deactivate_release_set(
            "ad",
            "ad-set-v1",
            root,
            actor="owner",
            changed_at=NOW,
        )

    assert release_sets.read_active_pointer(root, "ad").release_set_id == "ad-set-v2"


def test_loaded_suite_remains_immutable_after_pointer_switch(tmp_path, monkeypatch):
    import app.services.longitudinal_release_set as release_sets

    root = tmp_path / "registry"
    _seed_active(root, "ad", "ad-set-v1")
    loaded = release_sets.load_disease_release_set("ad", root)
    second = _release_record(root, "ad", "ad-set-v2")
    review = _review_record(root, second, "review-v2")
    monkeypatch.setattr(
        release_sets,
        "preload_release_set",
        lambda dataset, release_set_id, registry_root: release_sets.load_release_set_record(
            dataset, release_set_id, registry_root
        ),
    )
    release_sets.enable_release_set(
        review, root, enabled_by="owner", enabled_at=NOW
    )

    assert loaded.release_set_id == "ad-set-v1"
    assert release_sets.load_disease_release_set("ad", root).release_set_id == "ad-set-v2"
