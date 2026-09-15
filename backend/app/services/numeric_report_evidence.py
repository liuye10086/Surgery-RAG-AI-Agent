"""Capture eligible input-only references, then search only the frozen catalog."""

import hashlib
from datetime import date

from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.db.models import Chunk, Document
from app.schemas.numeric_prediction import NumericInput
from app.schemas.numeric_report_evidence import (
    NumericReferenceChunk, NumericReferenceContext, NumericRetrievedEvidence, NumericRagEvidence, json_sha256,
)
from app.services.numeric_report_publication import _saved_input_sha256


class NumericEvidenceError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _numeric(value):
    return NumericInput.model_validate(value.model_dump(mode='python') if hasattr(value, 'model_dump') else value)


def _vector_search(*args, **kwargs):
    from app.rag.pipeline import _vector_search as search
    return search(*args, **kwargs)


def _fulltext_search(*args, **kwargs):
    from app.rag.pipeline import _fulltext_search as search
    return search(*args, **kwargs)


def context_sha256(context):
    return json_sha256(context)


def _query(numeric):
    indicator = 'MMSE 认知评分' if numeric.disease_code == 'ad' else 'ALT 肝功能'
    rows = sorted(numeric.packets[0].input_observations, key=lambda r: (r.measured_on, r.observation_id))[-6:]
    facts = '；'.join(f'{r.measured_on.isoformat()} {r.value:g} {r.unit}' for r in rows)
    return f'{indicator} 锚点前已知测量 既往变化 预测参考 输入记录；{facts}'


def _reference(chunk, numeric):
    doc, metadata = chunk.document, chunk.chunk_metadata or {}
    try:
        if (metadata.get('numeric_reference_version') != 'numeric_reference.v1'
                or metadata.get('disease_code') != numeric.disease_code
                or metadata.get('subject_id') == numeric.subject_id
                or metadata.get('dependency_group_id') == numeric.dependency_group_id
                or metadata.get('pool') != 'development_pool'
                or doc.department_id is not None or doc.access_scope not in {'operator', 'both'}
                or doc.is_current is not True or chunk.is_current is not True
                or chunk.generation != doc.active_generation
                or date.fromisoformat(metadata['known_on']) > numeric.anchor_date):
            return None
        return NumericReferenceChunk(
            chunk_id=chunk.id, document_id=chunk.document_id, document_version=doc.version,
            generation=chunk.generation, title=doc.title or doc.filename, content=chunk.content,
            content_sha256=hashlib.sha256(chunk.content.encode('utf-8')).hexdigest(),
            department_id=doc.department_id, access_scope=doc.access_scope,
            **{k: metadata[k] for k in ('disease_code', 'subject_id', 'dependency_group_id', 'known_on', 'pool', 'source')},
        )
    except (KeyError, ValueError, TypeError):
        return None


def capture_numeric_references(db, numeric) -> NumericReferenceContext:
    numeric = _numeric(numeric)
    chunks = (db.query(Chunk).options(joinedload(Chunk.document)).join(Document, Document.id == Chunk.document_id)
              .filter(Chunk.is_current.is_(True), Document.is_current.is_(True),
                      Chunk.generation == Document.active_generation, Document.department_id.is_(None),
                      Document.access_scope.in_(['operator', 'both']),
                      Chunk.chunk_metadata['numeric_reference_version'].astext == 'numeric_reference.v1',
                      Chunk.chunk_metadata['disease_code'].astext == numeric.disease_code).all())
    candidates = sorted((reference for c in chunks if (reference := _reference(c, numeric)) is not None),
                        key=lambda c: c.chunk_id)
    return NumericReferenceContext(input_sha256=_saved_input_sha256(numeric), disease_code=numeric.disease_code,
                                   anchor_date=numeric.anchor_date, candidates=candidates,
                                   catalog_sha256=json_sha256([c.model_dump(mode='json') for c in candidates]))


def validate_numeric_evidence(evidence, context, numeric):
    """Validate only saved facts; never resolve current DB documents."""
    numeric = _numeric(numeric)
    context = NumericReferenceContext.model_validate(context)
    evidence = NumericRagEvidence.model_validate(evidence)
    if (context.input_sha256 != _saved_input_sha256(numeric)
            or (context.disease_code, context.anchor_date) != (numeric.disease_code, numeric.anchor_date)
            or evidence.input_sha256 != context.input_sha256 or evidence.context_sha256 != context_sha256(context)
            or evidence.query != _query(numeric)
            or any(c.subject_id == numeric.subject_id or c.dependency_group_id == numeric.dependency_group_id for c in context.candidates)):
        raise NumericEvidenceError('numeric_reference_identity_mismatch')
    lookup = {c.chunk_id: c for c in context.candidates}
    for item in evidence.items:
        if item.chunk_id not in lookup or item.model_dump(include=set(NumericReferenceChunk.model_fields)) != lookup[item.chunk_id].model_dump():
            raise NumericEvidenceError('numeric_evidence_not_in_catalog')
    return evidence


def retrieve_numeric_evidence(db, numeric, context) -> NumericRagEvidence:
    from app.rag.pipeline import _rrf_fuse
    numeric = _numeric(numeric)
    context = NumericReferenceContext.model_validate(context)
    if context.input_sha256 != _saved_input_sha256(numeric):
        raise NumericEvidenceError('numeric_reference_identity_mismatch')
    # Compare the entire eligible catalog, including additions, before any embedding call.
    if capture_numeric_references(db, numeric) != context:
        raise NumericEvidenceError('numeric_reference_context_changed')
    query = _query(numeric)
    common = dict(input_sha256=context.input_sha256, context_sha256=context_sha256(context), query=query,
                  embedding_model=settings.EMBEDDING_MODEL, collection_name=settings.VECTOR_COLLECTION_NAME,
                  rrf_k=settings.RETRIEVER_FUSION_K)
    if not context.candidates:
        return NumericRagEvidence(**common, status='empty', vector_status='not_run', fulltext_status='not_run', items=[])
    allowed = [c.chunk_id for c in context.candidates]
    results, statuses = {}, {}
    for name, search, top_k in (
        ('vector', _vector_search, settings.RETRIEVER_TOP_K_VECTOR),
        ('fulltext', _fulltext_search, settings.RETRIEVER_TOP_K_FULLTEXT),
    ):
        try:
            with db.begin_nested():
                results[name] = search(db, query, top_k, department_id=None, access_scope='operator', allowed_chunk_ids=allowed)
            statuses[name] = 'complete'
        except Exception:
            # Do not expose driver/provider exception text or label failed work complete.
            results[name], statuses[name] = [], 'failed'
    if all(s == 'failed' for s in statuses.values()):
        raise NumericEvidenceError('numeric_retrieval_failed')
    fused = _rrf_fuse(results['vector'], results['fulltext'], settings.RETRIEVER_FINAL_TOP_K, k=common['rrf_k'])
    catalog = {c.chunk_id: c for c in context.candidates}
    items = []
    for result in fused:
        actual = _reference(result.chunk, numeric)
        if actual is None or catalog.get(result.chunk.id) != actual:
            raise NumericEvidenceError('numeric_reference_context_changed')
        items.append(NumericRetrievedEvidence(**actual.model_dump(), **{
            name: getattr(result, name) for name in ('score', 'vector_score', 'vector_rank', 'fulltext_score', 'fulltext_rank')}))
    state = 'partial' if 'failed' in statuses.values() else ('complete' if items else 'empty')
    evidence = NumericRagEvidence(**common, status=state, vector_status=statuses['vector'], fulltext_status=statuses['fulltext'], items=items)
    return validate_numeric_evidence(evidence, context, numeric)
