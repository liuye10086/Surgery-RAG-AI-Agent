"""Operator predictive API 测试。"""
import unittest
from fastapi import HTTPException
from app.schemas.prediction import DiseaseCreate, DiseaseUpdate


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


if __name__ == "__main__":
    unittest.main()
