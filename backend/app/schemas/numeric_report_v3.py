"""Strict saved admission context for the fixed mixed history bundle."""
import hashlib
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.synthetic_numeric_prediction import StrictNumericModel, Sha
from app.schemas.numeric_prediction import NumericInput
from app.schemas.numeric_history_bundle import NumericHistoryBundle
from app.schemas.numeric_history_prediction import MixedNumericAlgorithm, NumericTaskAlgorithm
from app.schemas.numeric_model_bundle import json_sha256
from app.schemas.numeric_report_evidence import NumericReferenceContext
from app.schemas.numeric_report_v2 import NumericRetrievalSettings


def numeric_v3_algorithms(bundle):
    """Describe saved parameters without executing any prediction."""
    from app.services.numeric_history_bundle import _descriptor, history_bundle_sha256
    legacy = {model.task_id: model for model in bundle.legacy_bundle.models}
    parameters, tasks = [], {}
    for assignment in sorted(bundle.task_assignments, key=lambda row: row.task_id):
        history = assignment.provider == 'history_rf'
        model = bundle.history_model if history else legacy[assignment.task_id]
        parameters.append(dict(task_id=assignment.task_id, parameters_sha256=model.parameters_sha256))
        tasks[assignment.task_id] = _descriptor(
            'random_forest:history_v1:value_history' if history else 'ridge:main_anchor',
            model.parameters_sha256)
    return MixedNumericAlgorithm(implementation_sha256=bundle.implementation_sha256,
        parameters_sha256=json_sha256(parameters), bundle_sha256=history_bundle_sha256(bundle)), tasks


class NumericGenerationContextV3(StrictNumericModel):
    schema_version: Literal['numeric_generation_context.v3'] = 'numeric_generation_context.v3'
    disease_code: Literal['ad', 'fatty_liver']
    numeric_input: NumericInput
    numeric_input_sha256: Sha
    source_binding_sha256: Sha
    model_bundle: NumericHistoryBundle
    algorithm: MixedNumericAlgorithm
    task_algorithms: dict[str, NumericTaskAlgorithm]
    references: NumericReferenceContext
    llm_model: str = Field(min_length=1, max_length=200)
    prompt_text: str = Field(min_length=1, max_length=16000)
    prompt_sha256: Sha
    retrieval_settings: NumericRetrievalSettings
    prompt_version: Literal['numeric_narrative.prompt.v2'] = 'numeric_narrative.prompt.v2'
    template_version: Literal['numeric_report.zh-CN.v3'] = 'numeric_report.zh-CN.v3'

    @model_validator(mode='after')
    def fixed_identity(self):
        from app.services.numeric_report_publication import _saved_input_sha256
        numeric = self.numeric_input
        if numeric.source.source_kind != 'synthetic':
            raise ValueError('numeric_history_synthetic_required')
        algorithm, tasks = numeric_v3_algorithms(self.model_bundle)
        if (self.disease_code != numeric.disease_code
                or self.numeric_input_sha256 != _saved_input_sha256(numeric)
                or self.algorithm != algorithm or self.task_algorithms != tasks
                or self.prompt_sha256 != hashlib.sha256(self.prompt_text.encode('utf-8')).hexdigest()
                or self.references.input_sha256 != self.numeric_input_sha256
                or self.references.disease_code != self.disease_code
                or self.references.anchor_date != numeric.anchor_date
                or any(row.subject_id == numeric.subject_id or row.dependency_group_id == numeric.dependency_group_id
                       for row in self.references.candidates)):
            raise ValueError('numeric_context_identity_mismatch')
        return self


from app.schemas.numeric_report import NumericReportIdentity
from app.schemas.numeric_history_prediction import NumericPredictionV3
from app.schemas.numeric_report_evidence import NumericRagEvidence, NumericNarrativeSection
from app.schemas.synthetic_numeric_prediction import Identifier


class NumericNarrativeSectionV2(NumericNarrativeSection):
    title: Literal['结果阅读说明', '参考证据说明']
    text: str = Field(min_length=1, max_length=100)
    citation_ids: list[int] = Field(max_length=10, strict=True)

    @model_validator(mode='before')
    @classmethod
    def strict_citations(cls, value):
        if isinstance(value, dict) and any(type(cid) is not int for cid in value.get('citation_ids', [])):
            raise ValueError('numeric_narrative_unknown_citation')
        return value


class NumericNarrativeContentV2(StrictNumericModel):
    sections: list[NumericNarrativeSectionV2] = Field(min_length=2, max_length=2)
    limitations: list[str] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def fixed_sections(self):
        if [s.title for s in self.sections] != ['结果阅读说明', '参考证据说明']:
            raise ValueError('numeric_narrative_sections_invalid')
        if any(not x.strip() or len(x) > 100 for x in self.limitations):
            raise ValueError('numeric_narrative_limitations_invalid')
        return self


class NumericNarrativeV2(NumericNarrativeContentV2):
    schema_version: Literal['numeric_narrative.v2'] = 'numeric_narrative.v2'
    status: Literal['completed'] = 'completed'
    model: Identifier
    response_model: str | None = Field(default=None, min_length=1, max_length=200)
    prompt_version: Literal['numeric_narrative.prompt.v2'] = 'numeric_narrative.prompt.v2'
    prompt_sha256: Sha
    input_sha256: Sha
    prediction_sha256: Sha
    evidence_sha256: Sha
    output_sha256: Sha
    response_text: str = Field(min_length=1, max_length=24000)

    @model_validator(mode='after')
    def saved_response(self):
        if self.output_sha256 != hashlib.sha256(self.response_text.encode('utf-8')).hexdigest():
            raise ValueError('numeric_narrative_output_hash_mismatch')
        parsed = NumericNarrativeContentV2.model_validate_json(self.response_text)
        if parsed.model_dump() != self.model_dump(include={'sections', 'limitations'}):
            raise ValueError('numeric_narrative_response_mismatch')
        return self


class NumericReportDocumentV3(StrictNumericModel):
    schema_version: Literal['numeric_report_document.v3'] = 'numeric_report_document.v3'
    template_version: Literal['numeric_report.zh-CN.v3'] = 'numeric_report.zh-CN.v3'
    identity: NumericReportIdentity
    generation_context: NumericGenerationContextV3
    numeric_input: NumericInput
    prediction: NumericPredictionV3
    evidence: NumericRagEvidence
    narrative: NumericNarrativeV2

    @model_validator(mode='after')
    def same_generation(self):
        identity, context, numeric, result = self.identity, self.generation_context, self.numeric_input, self.prediction
        if numeric != context.numeric_input:
            raise ValueError('numeric_report_input_mismatch')
        if any(p.algorithm != context.task_algorithms[p.task_id] for p in result.predictions):
            raise ValueError('numeric_prediction_algorithm_mismatch')
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


class NumericPublicationV3(StrictNumericModel):
    content: str
    prediction_result: dict
    sources: list[dict]
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal['complete', 'partial']
    standard_evidence_status: Literal['not_requested'] = 'not_requested'
    reference_case_status: Literal['available', 'no_eligible_cases', 'reference_query_failed']
    report_document: NumericReportDocumentV3
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal['v6'] = 'v6'

    @model_validator(mode='after')
    def saved_facts(self):
        if (NumericPredictionV3.model_validate(self.prediction_result) != self.report_document.prediction
                or NumericRagEvidence.model_validate(self.evidence_snapshot) != self.report_document.evidence):
            raise ValueError('numeric_publication_contract_mismatch')
        return self
