from pathlib import Path


def test_model_dir_points_to_backend_app_ml_models():
    from app.services.model_paths import MODEL_DIR

    expected = Path(__file__).resolve().parents[1] / "app" / "ml_models"
    assert MODEL_DIR == expected


def test_longitudinal_registry_does_not_import_legacy_progression_engine():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "longitudinal_model_registry.py"
    ).read_text(encoding="utf-8")
    assert "from app.services.model_paths import MODEL_DIR" in source
    assert "progression_engine" not in source
