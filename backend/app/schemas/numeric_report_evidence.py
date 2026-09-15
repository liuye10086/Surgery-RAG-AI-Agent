"""Frozen reference facts and bounded narrative; provenance stays in backend metadata."""

from datetime import date
import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.numeric_prediction import PredictionSource
from app.schemas.synthetic_numeric_prediction import Identifier, Sha, StrictNumericModel


def json_sha256(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class NumericReferenceChunk(StrictNumericModel):
    chunk_id: int = Field(gt=0, strict=True)
    document_id: int = Field(gt=0, strict=True)
    document_version: int = Field(gt=0, strict=True)
    generation: int = Field(gt=0, strict=True)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=16000)
    content_sha256: Sha
    department_id: None = None
    access_scope: Literal['operator', 'both']
    disease_code: Literal['ad', 'fatty_liver']
    subject_id: Identifier
    dependency_group_id: Identifier
    known_on: date
    pool: Literal['development_pool'] = 'development_pool'
    source: PredictionSource

    @model_validator(mode='after')
    def valid_content(self):
        if self.content_sha256 != hashlib.sha256(self.content.encode('utf-8')).hexdigest():
            raise ValueError('numeric_reference_content_hash_mismatch')
        return self


class NumericReferenceContext(StrictNumericModel):
    schema_version: Literal['numeric_reference_context.v1'] = 'numeric_reference_context.v1'
    input_sha256: Sha
    disease_code: Literal['ad', 'fatty_liver']
    anchor_date: date
    catalog_sha256: Sha
    candidates: list[NumericReferenceChunk]

    @model_validator(mode='after')
    def valid_catalog(self):
        if (self.catalog_sha256 != json_sha256([c.model_dump(mode='json') for c in self.candidates])
                or len({c.chunk_id for c in self.candidates}) != len(self.candidates)
                or any(c.disease_code != self.disease_code or c.known_on > self.anchor_date for c in self.candidates)):
            raise ValueError('numeric_reference_catalog_mismatch')
        return self


class NumericRetrievedEvidence(NumericReferenceChunk):
    score: float = Field(gt=0)
    vector_score: float | None = None
    vector_rank: int | None = Field(default=None, gt=0, strict=True)
    fulltext_score: float | None = Field(default=None, ge=0)
    fulltext_rank: int | None = Field(default=None, gt=0, strict=True)


class NumericRagEvidence(StrictNumericModel):
    schema_version: Literal['numeric_rag_evidence.v1'] = 'numeric_rag_evidence.v1'
    input_sha256: Sha
    context_sha256: Sha
    status: Literal['complete', 'partial', 'empty']
    vector_status: Literal['complete', 'failed', 'not_run']
    fulltext_status: Literal['complete', 'failed', 'not_run']
    embedding_model: Identifier
    collection_name: Identifier
    rrf_k: int = Field(ge=0, strict=True)
    query: str = Field(min_length=1, max_length=4000)
    items: list[NumericRetrievedEvidence]

    @model_validator(mode='after')
    def valid_status_and_scores(self):
        branches = (self.vector_status, self.fulltext_status)
        if branches == ('failed', 'failed') or len({c.chunk_id for c in self.items}) != len(self.items):
            raise ValueError('numeric_evidence_invalid')
        expected = 'partial' if 'failed' in branches else ('complete' if self.items else 'empty')
        if self.status != expected or ('not_run' in branches and (branches != ('not_run', 'not_run') or self.items)):
            raise ValueError('numeric_evidence_status_mismatch')
        previous = float('inf')
        for item in self.items:
            ranks = []
            for branch in ('vector', 'fulltext'):
                rank, score = getattr(item, branch + '_rank'), getattr(item, branch + '_score')
                if (rank is None) != (score is None) or (rank is not None and getattr(self, branch + '_status') != 'complete'):
                    raise ValueError('numeric_evidence_branch_mismatch')
                if rank is not None:
                    ranks.append(rank)
            if not ranks or abs(item.score - sum(1 / (self.rrf_k + r) for r in ranks)) > 1e-12 or item.score > previous:
                raise ValueError('numeric_evidence_rrf_mismatch')
            previous = item.score
        return self


class NumericNarrativeSection(StrictNumericModel):
    title: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=1200)
    citation_ids: list[int] = Field(max_length=10)


class NumericNarrativeContent(StrictNumericModel):
    sections: list[NumericNarrativeSection] = Field(min_length=1, max_length=4)
    limitations: list[str] = Field(min_length=1, max_length=6)


class NumericNarrative(NumericNarrativeContent):
    schema_version: Literal['numeric_narrative.v1'] = 'numeric_narrative.v1'
    status: Literal['completed'] = 'completed'
    model: Identifier
    response_model: str | None = None
    prompt_version: Literal['numeric_narrative.prompt.v1'] = 'numeric_narrative.prompt.v1'
    prompt_sha256: Sha
    input_sha256: Sha
    prediction_sha256: Sha
    evidence_sha256: Sha
    output_sha256: Sha
    response_text: str = Field(min_length=1, max_length=24000)

    @model_validator(mode='after')
    def valid_response(self):
        if self.output_sha256 != hashlib.sha256(self.response_text.encode('utf-8')).hexdigest():
            raise ValueError('numeric_narrative_output_hash_mismatch')
        parsed = NumericNarrativeContent.model_validate_json(self.response_text)
        if parsed.model_dump() != self.model_dump(include={'sections', 'limitations'}):
            raise ValueError('numeric_narrative_response_mismatch')
        if any(not x.strip() or len(x) > 600 for x in self.limitations):
            raise ValueError('numeric_narrative_limitations_invalid')
        return self
