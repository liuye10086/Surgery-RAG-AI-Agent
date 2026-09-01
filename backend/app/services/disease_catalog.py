"""Disease capability registry and AI-operator permission rules."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from app.db.models import (
    AIReport,
    CaseRecord,
    Disease,
    OperatorCase,
    ReferenceStandard,
)
from app.services.disease_progression import (
    AD_ADAPTER,
    FATTY_LIVER_ADAPTER,
    DiseaseProgressionAdapter,
)


@dataclass(frozen=True)
class DiseaseCapability:
    code: str
    adapter: DiseaseProgressionAdapter


DISEASE_CAPABILITIES = MappingProxyType(
    {
        "fatty_liver": DiseaseCapability("fatty_liver", FATTY_LIVER_ADAPTER),
        "ad": DiseaseCapability("ad", AD_ADAPTER),
    }
)


class DiseaseCatalogError(ValueError):
    """Base error translated to a stable API message by route layers."""


class DiseaseNotFoundError(DiseaseCatalogError):
    pass


class DiseaseDisabledError(DiseaseCatalogError):
    pass


class DiseaseCapabilityMissingError(DiseaseCatalogError):
    pass


@dataclass(frozen=True)
class DiseaseUsageCounts:
    operator_cases: int
    case_records: int
    ai_reports: int
    reference_standards: int

    @property
    def total(self) -> int:
        return (
            self.operator_cases
            + self.case_records
            + self.ai_reports
            + self.reference_standards
        )


def require_disease_capability(code: str) -> DiseaseCapability:
    try:
        return DISEASE_CAPABILITIES[code]
    except KeyError as exc:
        raise DiseaseCapabilityMissingError(
            "该疾病未配置 AI 操作者能力"
        ) from exc


def require_operator_disease(
    db,
    disease_id: int,
    *,
    for_update: bool = False,
) -> Disease:
    query = db.query(Disease).filter(Disease.id == disease_id)
    if for_update:
        query = query.with_for_update()
    disease = query.first()
    if disease is None:
        raise DiseaseNotFoundError("疾病不存在")
    if not disease.operator_enabled:
        raise DiseaseDisabledError("该疾病已停用")
    require_disease_capability(disease.code)
    return disease


def require_enabled_case_disease(case: OperatorCase) -> Disease:
    disease = getattr(case, "disease", None)
    if disease is None:
        raise DiseaseNotFoundError("疾病不存在")
    if not disease.operator_enabled:
        raise DiseaseDisabledError("该疾病已停用")
    require_disease_capability(disease.code)
    return disease


def disease_usage_counts(db, disease_id: int) -> DiseaseUsageCounts:
    return DiseaseUsageCounts(
        operator_cases=db.query(OperatorCase)
        .filter(OperatorCase.disease_id == disease_id)
        .count(),
        case_records=db.query(CaseRecord)
        .filter(CaseRecord.disease_id == disease_id)
        .count(),
        ai_reports=db.query(AIReport)
        .filter(AIReport.disease_id == disease_id)
        .count(),
        reference_standards=db.query(ReferenceStandard)
        .filter(ReferenceStandard.disease_id == disease_id)
        .count(),
    )
