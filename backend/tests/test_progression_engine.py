"""Longitudinal progression feature extraction tests."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import joblib
from sklearn.dummy import DummyClassifier

from app.services import progression_engine
from app.services.progression_engine import (
    DISCLAIMER,
    extract_features,
    load_model,
    predict_progression,
)


class ExtractFeaturesTests(unittest.TestCase):
    def test_single_visit_has_no_slope(self):
        visits = [
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "alt", "value": 60}],
            }
        ]

        features = extract_features(visits)

        self.assertEqual(features["alt"]["first"], 60.0)
        self.assertEqual(features["alt"]["last"], 60.0)
        self.assertEqual(features["alt"]["delta"], 0.0)
        self.assertEqual(features["alt"]["delta_pct"], 0.0)
        self.assertIsNone(features["alt"]["slope"])
        self.assertEqual(features["alt"]["rises_count"], 0)
        self.assertEqual(features["alt"]["n_observations"], 1)

    def test_multi_visit_computes_slope_and_rises(self):
        visits = [
            {
                "visit_date": "2024-06-01",
                "indicators": [{"name": "alt", "value": 90}],
            },
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "alt", "value": 60}],
            },
            {
                "visit_date": "2024-03-01",
                "indicators": [{"name": "alt", "value": 70}],
            },
        ]

        features = extract_features(visits)

        self.assertEqual(features["alt"]["first"], 60.0)
        self.assertEqual(features["alt"]["last"], 90.0)
        self.assertEqual(features["alt"]["delta"], 30.0)
        self.assertAlmostEqual(features["alt"]["delta_pct"], 0.5)
        self.assertAlmostEqual(features["alt"]["slope"], 15.0)
        self.assertEqual(features["alt"]["rises_count"], 2)
        self.assertEqual(features["alt"]["n_observations"], 3)

    def test_missing_indicator_values_are_skipped(self):
        visits = [
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "alt", "value": 60}],
            },
            {"visit_date": "2024-03-01", "indicators": []},
            {
                "visit_date": "2024-06-01",
                "indicators": [
                    {"name": "alt", "value": 90},
                    {"name": "ast", "value": None},
                ],
            },
        ]

        features = extract_features(visits)

        self.assertEqual(features["alt"]["n_observations"], 2)
        self.assertEqual(features["alt"]["rises_count"], 1)
        self.assertAlmostEqual(features["alt"]["slope"], 15.0)
        self.assertNotIn("ast", features)

    def test_zero_first_value_has_no_delta_percentage(self):
        visits = [
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "x", "value": 0}],
            },
            {
                "visit_date": "2024-03-01",
                "indicators": [{"name": "x", "value": 5}],
            },
        ]

        features = extract_features(visits)

        self.assertIsNone(features["x"]["delta_pct"])


class ProgressionInferenceTests(unittest.TestCase):
    def test_risk_bands_are_owned_by_longitudinal_module(self):
        self.assertEqual(progression_engine._BANDS[0][0], 0.8)
    def tearDown(self):
        load_model.cache_clear()

    def test_load_model_raises_clear_error_when_artifact_is_missing(self):
        with TemporaryDirectory() as directory:
            with patch.object(progression_engine, "MODEL_DIR", Path(directory)):
                load_model.cache_clear()
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    "nonexistent_dataset",
                ):
                    load_model("nonexistent_dataset")

    def test_predict_progression_uses_meta_order_and_returns_risk_disclosures(self):
        visits = [
            {
                "visit_date": "2024-01-01",
                "indicators": [{"name": "alt", "value": 60}],
            },
            {
                "visit_date": "2024-06-01",
                "indicators": [{"name": "alt", "value": 90}],
            },
        ]
        model = DummyClassifier(strategy="constant", constant=1)
        model.fit([[0.0, 0.0], [1.0, 1.0]], [0, 1])
        meta = {
            "feature_names": ["alt.last", "alt.first"],
            "trained_on": 300,
            "cv_auc_mean": 0.9624794908230078,
            "cv_auc_std": 0.05137066818472216,
        }

        with TemporaryDirectory() as directory:
            model_dir = Path(directory)
            joblib.dump(model, model_dir / "fatty_liver_progression_model.joblib")
            (model_dir / "fatty_liver_progression_model.meta.json").write_text(
                __import__("json").dumps(meta),
                encoding="utf-8",
            )
            with patch.object(progression_engine, "MODEL_DIR", model_dir):
                load_model.cache_clear()
                result = predict_progression("fatty_liver", visits)

        self.assertEqual(result["risk_band"], "极高")
        self.assertEqual(result["risk_score"], 1.0)
        self.assertEqual(result["disclaimer"], DISCLAIMER)
        self.assertIn("0.9625", result["model_caveat"])
        self.assertIn("不直接等同于真实世界预测准确率", result["model_caveat"])
        self.assertEqual(result["model_meta"]["trained_on"], 300)
        self.assertEqual(result["feature_summary"][0]["indicator"], "alt")


if __name__ == "__main__":
    unittest.main()
