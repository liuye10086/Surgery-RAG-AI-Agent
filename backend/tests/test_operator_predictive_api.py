"""Operator predictive API 测试。"""
import unittest
from fastapi import HTTPException
from app.schemas.prediction import CaseRecordIn, DiseaseCreate, DiseaseUpdate, IndicatorInput


class DiseaseSchemaTests(unittest.TestCase):
    def test_disease_create_requires_name(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DiseaseCreate(name="")

    def test_disease_create_normalizes_name(self):
        d = DiseaseCreate(name=" 胆囊结石 ")
        self.assertEqual(d.name, "胆囊结石")

    def test_disease_out_construction(self):
        """_disease_to_out 显式构造（Pydantic v2 model_validate 无 update 参数）。"""
        from unittest.mock import MagicMock
        from app.api.operator import _disease_to_out

        d = MagicMock()
        d.id = 1
        d.name = "胆囊结石"
        d.description = None
        d.created_at = "2026-01-01T00:00:00"
        out = _disease_to_out(d, 5)
        self.assertEqual(out.id, 1)
        self.assertEqual(out.case_count, 5)


class CaseRecordSchemaTests(unittest.TestCase):
    def test_case_record_requires_indicators(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            CaseRecordIn(disease_id=1, indicators=[])

    def test_indicator_validates_name_value_unit(self):
        ind = IndicatorInput(name="TBIL", value=35.0, unit="μmol/L")
        self.assertEqual(ind.name, "TBIL")
        self.assertEqual(ind.value, 35.0)


class OperatorRouterEndpointTests(unittest.TestCase):
    def test_case_endpoints_registered(self):
        """先写：实现前 /operator/cases 未注册 → 本测试为红。"""
        from app.api.operator import router
        paths = {r.path for r in router.routes}
        self.assertTrue(
            {"/operator/cases", "/operator/diseases"}.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
