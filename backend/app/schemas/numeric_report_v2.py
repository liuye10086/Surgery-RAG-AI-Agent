"""Saved trained predictions, retrieved facts and narrative for one generation."""

import hashlib
from typing import Literal
from pydantic import Field, model_validator
from app.schemas.synthetic_numeric_prediction import StrictNumericModel, Sha
from app.schemas.numeric_prediction import NumericInput
from app.schemas.numeric_report import NumericReportIdentity
from app.schemas.numeric_model_bundle import NumericModelBundle, TrainedNumericAlgorithm, TrainedNumericPrediction, json_sha256
from app.schemas.numeric_report_evidence import NumericReferenceContext, NumericRagEvidence, NumericNarrative


class NumericRetrievalSettings(StrictNumericModel):
    embedding_model: str = Field(min_length=1)
    collection_name: str = Field(min_length=1)
    rrf_k: int = Field(ge=0, strict=True)
    vector_top_k: int = Field(gt=0, strict=True)
    fulltext_top_k: int = Field(gt=0, strict=True)
    final_top_k: int = Field(gt=0, strict=True)


class NumericGenerationContextV2(StrictNumericModel):
    schema_version: Literal['numeric_generation_context.v2'] = 'numeric_generation_context.v2'
    disease_code: Literal['ad', 'fatty_liver']
    numeric_input_sha256: Sha
    source_binding_sha256: Sha
    model_bundle: NumericModelBundle
    algorithm: TrainedNumericAlgorithm
    references: NumericReferenceContext
    llm_model: str = Field(min_length=1, max_length=200)
    prompt_text: str = Field(min_length=1, max_length=16000)
    prompt_sha256: Sha
    retrieval_settings: NumericRetrievalSettings
    prompt_version: Literal['numeric_narrative.prompt.v1'] = 'numeric_narrative.prompt.v1'
    template_version: Literal['numeric_report.zh-CN.v2'] = 'numeric_report.zh-CN.v2'

    @model_validator(mode='after')
    def fixed_model_and_references(self):
        bundle = self.model_bundle.model_dump(mode='json')
        bundle['models'].sort(key=lambda m: m['task_id'])
        expected = TrainedNumericAlgorithm(implementation_sha256=self.model_bundle.implementation_sha256,
            parameters_sha256=json_sha256(bundle['models']), bundle_sha256=json_sha256(bundle))
        if (self.prompt_sha256 != hashlib.sha256(self.prompt_text.encode('utf-8')).hexdigest()
                or self.algorithm != expected or self.references.input_sha256 != self.numeric_input_sha256
                or self.references.disease_code != self.disease_code):
            raise ValueError('numeric_context_identity_mismatch')
        return self


class NumericReportDocumentV2(StrictNumericModel):
    schema_version: Literal['numeric_report_document.v2'] = 'numeric_report_document.v2'
    template_version: Literal['numeric_report.zh-CN.v2'] = 'numeric_report.zh-CN.v2'
    identity: NumericReportIdentity
    generation_context: NumericGenerationContextV2
    numeric_input: NumericInput
    prediction: TrainedNumericPrediction
    evidence: NumericRagEvidence
    narrative: NumericNarrative

    @model_validator(mode='after')
    def same_generation(self):
        identity, context, numeric, result = self.identity, self.generation_context, self.numeric_input, self.prediction
        if len({identity.disease_code, context.disease_code, numeric.disease_code, result.disease_code}) != 1:
            raise ValueError('numeric_report_disease_mismatch')
        if (identity.anchor_date, numeric.subject_id, numeric.dependency_group_id, numeric.source,
                context.numeric_input_sha256, context.algorithm) != (
                result.anchor_date, result.subject_id, result.dependency_group_id, result.source,
                result.input_sha256, result.algorithm) or numeric.anchor_date != identity.anchor_date:
            raise ValueError('numeric_report_generation_mismatch')
        if (self.narrative.model != context.llm_model or self.narrative.prompt_version != context.prompt_version
                or self.narrative.prompt_sha256 != context.prompt_sha256
                or (self.evidence.embedding_model,self.evidence.collection_name,self.evidence.rrf_k) != (
                    context.retrieval_settings.embedding_model,context.retrieval_settings.collection_name,context.retrieval_settings.rrf_k)
                or len(self.evidence.items)>context.retrieval_settings.final_top_k
                or self.evidence.input_sha256 != context.numeric_input_sha256):
            raise ValueError('numeric_report_narrative_mismatch')
        return self


class NumericPublicationV2(StrictNumericModel):
    content: str
    prediction_result: dict
    sources: list[dict]
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal['complete', 'partial']
    standard_evidence_status: Literal['not_requested'] = 'not_requested'
    reference_case_status: Literal['available', 'no_eligible_cases', 'reference_query_failed']
    report_document: NumericReportDocumentV2
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal['v5'] = 'v5'

    @model_validator(mode='after')
    def saved_facts(self):
        if (TrainedNumericPrediction.model_validate(self.prediction_result) != self.report_document.prediction
                or NumericRagEvidence.model_validate(self.evidence_snapshot) != self.report_document.evidence):
            raise ValueError('numeric_publication_contract_mismatch')
        return self
