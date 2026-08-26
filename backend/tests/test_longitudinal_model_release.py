from datetime import datetime, timezone
import importlib.util
from pathlib import Path

import pytest


def _registry_test_module():
    path = Path(__file__).with_name("test_longitudinal_model_registry.py")
    spec = importlib.util.spec_from_file_location("registry_test_helpers", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_review_records_identity_time_note_and_matching_hashes(tmp_path):
    from app.services.longitudinal_model_registry import sha256_file
    from app.services.longitudinal_model_release import review_candidate

    helpers = _registry_test_module()
    bundle, model_path, metadata_path, _ = helpers._write_candidate_bundle(
        tmp_path / "source"
    )
    result = review_candidate(
        bundle,
        tmp_path / "registry",
        reviewer="owner-1",
        reviewed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        note="P0-05 contract review",
    )
    assert result.record.model_sha256 == sha256_file(model_path)
    assert result.record.metadata_sha256 == sha256_file(metadata_path)
    assert result.record.reviewer == "owner-1"
    assert result.path.is_file()


def test_enable_revalidates_review_and_refuses_conflicting_task(tmp_path):
    from app.services.longitudinal_model_release import (
        ModelReleaseError,
        enable_review,
        review_candidate,
    )

    helpers = _registry_test_module()
    bundle, _, _, _ = helpers._write_candidate_bundle(tmp_path / "source")
    registry = tmp_path / "registry"
    review = review_candidate(
        bundle,
        registry,
        reviewer="owner-1",
        reviewed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        note="reviewed",
    )
    first = enable_review(
        review.path,
        registry,
        enabled_by="owner-1",
        enabled_at=datetime(2026, 8, 26, 1, tzinfo=timezone.utc),
    )
    assert first.record.status == "enabled"
    with pytest.raises(ModelReleaseError) as error:
        enable_review(
            review.path,
            registry,
            enabled_by="owner-2",
            enabled_at=datetime(2026, 8, 26, 2, tzinfo=timezone.utc),
        )
    assert error.value.code == "multiple_enabled_artifacts"


def test_review_never_overwrites_existing_record(tmp_path):
    from app.services.longitudinal_model_release import ModelReleaseError, review_candidate

    helpers = _registry_test_module()
    bundle, _, _, _ = helpers._write_candidate_bundle(tmp_path / "source")
    kwargs = dict(
        bundle_dir=bundle,
        registry_root=tmp_path / "registry",
        reviewer="owner-1",
        reviewed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        note="reviewed",
    )
    review_candidate(**kwargs)
    with pytest.raises(ModelReleaseError) as error:
        review_candidate(**kwargs)
    assert error.value.code == "record_already_exists"


def test_enable_rejects_review_path_outside_registry(tmp_path):
    from app.services.longitudinal_model_release import ModelReleaseError, enable_review

    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ModelReleaseError) as error:
        enable_review(
            outside,
            tmp_path / "registry",
            enabled_by="owner",
            enabled_at=datetime.now(timezone.utc),
        )
    assert error.value.code == "registry_path_escape"


def test_relative_registry_root_supports_review_then_enable(tmp_path, monkeypatch):
    from app.services.longitudinal_model_release import enable_review, review_candidate

    helpers = _registry_test_module()
    bundle, _, _, _ = helpers._write_candidate_bundle(tmp_path / "source")
    monkeypatch.chdir(tmp_path)
    review = review_candidate(
        bundle,
        Path("registry"),
        reviewer="owner",
        reviewed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        note="relative root review",
    )
    release = enable_review(
        review.path,
        Path("registry"),
        enabled_by="owner",
        enabled_at=datetime(2026, 8, 26, 1, tzinfo=timezone.utc),
    )
    assert release.path.is_file()
