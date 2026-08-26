from app.services.longitudinal_model_registry import load_model_registry


def test_missing_longitudinal_artifacts_degrade_to_explicit_empty_registry(tmp_path):
    assert load_model_registry("fatty_liver", model_dir=tmp_path) == {}


def test_legacy_progression_artifacts_remain_ignored_by_longitudinal_registry(tmp_path):
    (tmp_path / "fatty_liver_progression_model.joblib").write_bytes(b"legacy")
    (tmp_path / "fatty_liver_progression_model.meta.json").write_text("{}", encoding="utf-8")
    assert load_model_registry("fatty_liver", model_dir=tmp_path) == {}
