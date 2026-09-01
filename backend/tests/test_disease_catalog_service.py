from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.db.models import AIReport, CaseRecord, Disease, OperatorCase, ReferenceStandard


class FakeDb:
    def __init__(self, disease=None, counts=None):
        self.disease = disease
        self.counts = dict(counts or {})
        self.locked = False

    def query(self, model):
        if model is Disease:
            query = MagicMock()
            query.filter.return_value = query
            query.with_for_update.side_effect = lambda: self._lock(query)
            query.first.return_value = self.disease
            return query
        model_counts = {
            OperatorCase: "operator_cases",
            CaseRecord: "case_records",
            AIReport: "ai_reports",
            ReferenceStandard: "reference_standards",
        }
        query = MagicMock()
        query.filter.return_value = query
        query.count.return_value = self.counts.get(model_counts[model], 0)
        return query

    def _lock(self, query):
        self.locked = True
        return query


def test_capability_registry_uses_stable_codes():
    from app.services.disease_catalog import DISEASE_CAPABILITIES

    assert set(DISEASE_CAPABILITIES) == {"fatty_liver", "ad"}
    assert DISEASE_CAPABILITIES["fatty_liver"].adapter.dataset == "fatty_liver"
    assert DISEASE_CAPABILITIES["ad"].adapter.dataset == "ad"


def test_require_operator_disease_rejects_missing_disabled_and_unsupported():
    from app.services.disease_catalog import (
        DiseaseCapabilityMissingError,
        DiseaseDisabledError,
        DiseaseNotFoundError,
        require_operator_disease,
    )

    with pytest.raises(DiseaseNotFoundError):
        require_operator_disease(FakeDb(), 1)
    with pytest.raises(DiseaseDisabledError):
        require_operator_disease(
            FakeDb(SimpleNamespace(id=1, code="fatty_liver", operator_enabled=False)),
            1,
        )
    with pytest.raises(DiseaseCapabilityMissingError):
        require_operator_disease(
            FakeDb(SimpleNamespace(id=2, code="gastric_cancer", operator_enabled=True)),
            2,
        )


def test_require_operator_disease_returns_supported_row_and_optionally_locks():
    from app.services.disease_catalog import require_operator_disease

    disease = SimpleNamespace(id=1, code="ad", operator_enabled=True)
    db = FakeDb(disease)
    assert require_operator_disease(db, 1, for_update=True) is disease
    assert db.locked is True


def test_require_enabled_case_disease_distinguishes_disabled_and_unsupported():
    from app.services.disease_catalog import (
        DiseaseCapabilityMissingError,
        DiseaseDisabledError,
        require_enabled_case_disease,
    )

    with pytest.raises(DiseaseDisabledError):
        require_enabled_case_disease(
            SimpleNamespace(
                disease=SimpleNamespace(
                    id=1,
                    code="ad",
                    operator_enabled=False,
                )
            )
        )
    with pytest.raises(DiseaseCapabilityMissingError):
        require_enabled_case_disease(
            SimpleNamespace(
                disease=SimpleNamespace(
                    id=2,
                    code="gastric_cancer",
                    operator_enabled=True,
                )
            )
        )


def test_disease_usage_counts_covers_all_referencing_models():
    from app.services.disease_catalog import disease_usage_counts

    counts = disease_usage_counts(
        FakeDb(
            counts={
                "operator_cases": 2,
                "case_records": 3,
                "ai_reports": 4,
                "reference_standards": 1,
            }
        ),
        7,
    )
    assert counts.operator_cases == 2
    assert counts.case_records == 3
    assert counts.ai_reports == 4
    assert counts.reference_standards == 1
    assert counts.total == 10


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "Fatty_Liver", "name": "脂肪肝"},
        {"code": "fatty-liver", "name": "脂肪肝"},
        {"code": "1fatty_liver", "name": "脂肪肝"},
        {"code": " fatty_liver ", "name": "脂肪肝"},
    ],
)
def test_disease_create_rejects_noncanonical_code(payload):
    from app.schemas.prediction import DiseaseCreate

    with pytest.raises(ValidationError):
        DiseaseCreate.model_validate(payload)


def test_disease_create_defaults_disabled_and_strips_display_text():
    from app.schemas.prediction import DiseaseCreate

    payload = DiseaseCreate(
        code="gastric_cancer",
        name=" 胃癌 ",
        description=" 试运行疾病 ",
    )
    assert payload.code == "gastric_cancer"
    assert payload.name == "胃癌"
    assert payload.description == "试运行疾病"
    assert "operator_enabled" not in payload.model_fields


def test_disease_update_cannot_accept_code_or_unknown_fields():
    from app.schemas.prediction import DiseaseUpdate

    with pytest.raises(ValidationError):
        DiseaseUpdate.model_validate({"code": "renamed"})
    with pytest.raises(ValidationError):
        DiseaseUpdate.model_validate({"unknown": True})
