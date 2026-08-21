"""Offline longitudinal progression model training tests."""

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
MODULE_PATH = ROOT / "scripts" / "train_progression_model.py"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def load_trainer():
    spec = importlib.util.spec_from_file_location("train_progression_model", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_sqlite_db():
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker

    from app.db.models import CaseRecord, Disease

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    engine = create_engine("sqlite:///:memory:")
    Disease.__table__.create(engine)
    CaseRecord.__table__.create(engine)
    return sessionmaker(bind=engine)()


class TrainProgressionModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trainer = load_trainer()

    def test_load_all_patients_includes_real_and_synthetic_300(self):
        from app.db.models import CaseRecord, Disease

        db = make_sqlite_db()
        disease = Disease(name="脂肪肝")
        db.add(disease)
        db.flush()
        for index in range(1, 301):
            patient_id = f"P{index:03d}"
            db.add(
                CaseRecord(
                    disease_id=disease.id,
                    patient_label=patient_id,
                    indicators=[{"name": "alt", "value": index}],
                    confirmed=index % 2 == 0,
                    case_metadata={
                        "visit_date": "2024-01-01",
                        "source_dataset": "longitudinal_300",
                        "is_synthetic": index >= 151,
                    },
                )
            )
        db.add(
            CaseRecord(
                disease_id=disease.id,
                patient_label="manual-case",
                indicators=[{"name": "alt", "value": 1}],
                confirmed=True,
                case_metadata={},
            )
        )
        db.commit()

        patients = self.trainer.load_all_patients(db, "fatty_liver")

        self.assertEqual(len(patients), 300)
        self.assertIn("P001", patients)
        self.assertIn("P151", patients)
        self.assertIn("P300", patients)
        self.assertNotIn("manual-case", patients)

    def test_patient_kfold_cv_never_splits_a_patient_across_fold_sides(self):
        rows = [[float(patient), float(visit)] for patient in range(10) for visit in range(2)]
        labels = [patient % 2 for patient in range(10) for _ in range(2)]
        patient_ids = [f"P{patient:03d}" for patient in range(10) for _ in range(2)]

        fold_results = self.trainer.patient_kfold_cv(
            rows,
            labels,
            patient_ids,
            k=5,
        )

        self.assertEqual(len(fold_results), 5)
        for fold in fold_results:
            train_patients = {patient_ids[i] for i in fold["train_indices"]}
            validation_patients = {
                patient_ids[i] for i in fold["validation_indices"]
            }
            self.assertTrue(train_patients.isdisjoint(validation_patients))

    def test_build_training_rows_uses_latest_visit_confirmed_label(self):
        patients = {
            "P001": [
                {
                    "visit_date": "2024-06-01",
                    "indicators": [{"name": "alt", "value": 90}],
                    "confirmed": True,
                },
                {
                    "visit_date": "2024-01-01",
                    "indicators": [{"name": "alt", "value": 60}],
                    "confirmed": False,
                },
            ]
        }

        rows, labels, patient_ids, feature_names = self.trainer.build_training_rows(
            patients
        )

        self.assertEqual(patient_ids, ["P001"])
        self.assertEqual(labels, [1])
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]), len(feature_names))
        self.assertIn("alt.slope", feature_names)

    def test_build_training_rows_excludes_cdr_from_ad_features(self):
        patients = {
            "P001": [
                {
                    "visit_date": "2024-01-01",
                    "indicators": [
                        {"name": "cdr", "value": 0.5},
                        {"name": "mmse", "value": 22},
                    ],
                    "confirmed": False,
                },
                {
                    "visit_date": "2024-06-01",
                    "indicators": [
                        {"name": "cdr", "value": 1},
                        {"name": "mmse", "value": 18},
                    ],
                    "confirmed": True,
                },
            ]
        }

        _, _, _, feature_names = self.trainer.build_training_rows(
            patients,
            dataset="ad",
        )

        self.assertFalse(any(name.startswith("cdr.") for name in feature_names))
        self.assertIn("mmse.slope", feature_names)

    def test_requirements_pin_requested_ml_versions(self):
        requirements = (ROOT / "backend" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("scikit-learn==1.9.0", requirements)
        self.assertIn("joblib==1.5.3", requirements)


if __name__ == "__main__":
    unittest.main()
