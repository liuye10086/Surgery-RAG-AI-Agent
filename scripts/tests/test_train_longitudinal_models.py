from datetime import date, timedelta

from app.services.disease_progression import FATTY_LIVER_ADAPTER
from scripts.train_longitudinal_models import build_prefix_training_rows, patient_grouped_cv


def test_prefix_label_uses_event_date_after_as_of():
    patient = {"event_dates": {"cirrhosis_date": "2025-01-01"}, "final_stage": "cirrhosis"}
    assert FATTY_LIVER_ADAPTER.outcome_label(patient, date(2024, 1, 1), timedelta(days=365)) == 0
    assert FATTY_LIVER_ADAPTER.outcome_label(patient, date(2024, 6, 1), timedelta(days=365)) == 1


def test_grouped_folds_keep_patient_prefixes_together():
    rows = [[float(i)] for i in range(10)]
    labels = [i % 2 for i in range(10)]
    groups = [f"P{i // 2}" for i in range(10)]
    folds = patient_grouped_cv(rows, labels, groups, lambda: __import__("sklearn.dummy", fromlist=["DummyClassifier"]).DummyClassifier(strategy="prior"), n_splits=5)
    for fold in folds:
        assert set(fold.train_groups).isdisjoint(fold.validation_groups)


def test_prefix_rows_exclude_unknown_labels_and_keep_as_of():
    visits = [
        {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 10}]},
        {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 20}]},
    ]
    result = build_prefix_training_rows({"P1": visits}, FATTY_LIVER_ADAPTER)
    assert result["groups"] == []
    assert result["as_of_dates"] == []


def test_train_outcome_model_persists_uncalibrated_metadata(tmp_path):
    from scripts.train_longitudinal_models import train_outcome_model

    patients = {}
    for index in range(6):
        patients[f"P{index}"] = {
            "event_dates": {"cirrhosis_date": "2024-06-01"} if index % 2 else {},
            "final_stage": "cirrhosis" if index % 2 else "fatty_liver",
            "visits": [
                {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 10 + index}]},
                {"visit_date": "2024-02-01", "indicators": [{"name": "ALT", "value": 11 + index}]},
            ],
        }
    result = train_outcome_model("fatty_liver", patients, FATTY_LIVER_ADAPTER, tmp_path)
    assert result["calibration_status"] == "not_calibrated"
    assert (tmp_path / "fatty_liver_longitudinal_outcome_365d.joblib").exists()
