"""Longitudinal progression prediction API tests."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

VISITS = [
    {
        "visit_date": "2024-01-01",
        "indicators": [{"name": "alt", "value": 60, "unit": "U/L"}],
    },
    {
        "visit_date": "2024-03-01",
        "indicators": [{"name": "alt", "value": 70, "unit": "U/L"}],
    },
    {
        "visit_date": "2024-06-01",
        "indicators": [{"name": "alt", "value": 90, "unit": "U/L"}],
    },
]

PREDICTION = {
    "risk_band": "高",
    "risk_score": 0.76,
    "feature_summary": [
        {
            "indicator": "alt",
            "first": 60.0,
            "last": 90.0,
            "slope": 15.0,
            "rises_count": 2,
        }
    ],
    "model_meta": {
        "trained_on": 300,
        "cv_auc_mean": 0.9625,
        "cv_auc_std": 0.0514,
    },
    "disclaimer": "固定风险披露",
    "model_caveat": "交叉验证准确率：0.9625（该数值主要反映训练数据构造方式，不直接等同于真实世界预测准确率）",
}


def make_client(role: str = "ai_operator") -> TestClient:
    from app.api.deps import get_current_user
    from app.api.operator import router
    from app.db.session import get_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    disease = SimpleNamespace(id=1, name="脂肪肝")
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = disease

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        role=role,
    )
    return TestClient(app)


class ProgressionSchemaTests(unittest.TestCase):
    def test_request_limits_visits_to_ten(self):
        from app.schemas.progression import LongitudinalPredictRequest

        with self.assertRaises(ValidationError):
            LongitudinalPredictRequest(disease_id=1, visits=VISITS[:1] * 11)

    def test_response_requires_model_caveat(self):
        from app.schemas.progression import ProgressionPredictionOut

        fields = ProgressionPredictionOut.model_fields
        self.assertIn("model_caveat", fields)


class ProgressionEndpointTests(unittest.TestCase):
    @patch("app.api.operator.predict_progression", return_value=PREDICTION)
    def test_endpoint_returns_structured_risk_and_both_disclosures(self, predict):
        response = make_client().post(
            "/api/v1/operator/progression-predictions",
            json={"disease_id": 1, "visits": VISITS},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["risk_band"], "高")
        self.assertEqual(body["feature_summary"][0]["indicator"], "alt")
        self.assertEqual(body["disclaimer"], "固定风险披露")
        self.assertIn("0.9625", body["model_caveat"])
        predict.assert_called_once()

    def test_endpoint_requires_ai_operator_role(self):
        response = make_client(role="user").post(
            "/api/v1/operator/progression-predictions",
            json={"disease_id": 1, "visits": VISITS},
        )

        self.assertEqual(response.status_code, 403)

    @patch(
        "app.api.operator.predict_progression",
        side_effect=FileNotFoundError("该疾病尚无可用进展预测模型"),
    )
    def test_missing_model_returns_422_with_clear_error(self, predict):
        response = make_client().post(
            "/api/v1/operator/progression-predictions",
            json={"disease_id": 1, "visits": VISITS},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("尚无可用进展预测模型", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
