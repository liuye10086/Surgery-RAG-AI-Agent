from app.services.longitudinal_model_registry import load_model_registry


def test_missing_longitudinal_artifacts_degrade_to_explicit_empty_registry(tmp_path):
    assert load_model_registry("fatty_liver", model_dir=tmp_path) == {}
