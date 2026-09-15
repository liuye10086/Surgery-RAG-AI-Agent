from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
import subprocess
import sys

import pytest

from test_numeric_prediction import numeric_fixture


def test_history_validation_import_does_not_load_inference_or_retriever():
    code = '''import sys
from app.services.numeric_report_evidence import validate_numeric_evidence
from app.services.numeric_report_narrative import validate_numeric_narrative
assert 'app.services.numeric_prediction' not in sys.modules
assert 'app.rag.pipeline' not in sys.modules
assert 'torch' not in sys.modules
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def numeric():
    from app.schemas.numeric_prediction import NumericInput
    return NumericInput.model_validate(numeric_fixture())


def chunk(cid=1, **metadata):
    n = numeric()
    doc = SimpleNamespace(id=1, title='认知评分输入记录', filename='reference.txt', version=1,
                          active_generation=1, is_current=True, access_scope='operator', department_id=None)
    return SimpleNamespace(id=cid, document_id=1, document=doc, content='锚点前已有认知评分记录。',
                           is_current=True, generation=1, chunk_metadata={
                               'numeric_reference_version': 'numeric_reference.v1', 'disease_code': 'ad',
                               'subject_id': 'other', 'dependency_group_id': 'other-group',
                               'known_on': n.anchor_date.isoformat(), 'pool': 'development_pool',
                               'source': n.source.model_dump(mode='json'), **metadata})


class DB:
    def __init__(self, chunks):
        self.chunks = chunks
    def query(self, *args):
        return self
    def options(self, *args):
        return self
    def join(self, *args):
        return self
    def filter(self, *args):
        return self
    def all(self):
        return self.chunks
    def begin_nested(self):
        return nullcontext()


@pytest.mark.parametrize('change', ['subject', 'group', 'future', 'disease', 'scope', 'current', 'generation', 'department', 'pool'])
def test_capture_excludes_unavailable_references(change):
    from app.services.numeric_report_evidence import capture_numeric_references
    n, c = numeric(), chunk()
    if change == 'subject': c.chunk_metadata['subject_id'] = n.subject_id
    elif change == 'group': c.chunk_metadata['dependency_group_id'] = n.dependency_group_id
    elif change == 'future': c.chunk_metadata['known_on'] = '2099-01-01'
    elif change == 'disease': c.chunk_metadata['disease_code'] = 'fatty_liver'
    elif change == 'pool': c.chunk_metadata['pool'] = 'challenge_pool'
    elif change == 'scope': c.document.access_scope = 'chat'
    elif change == 'current': c.document.is_current = False
    elif change == 'department': c.document.department_id = 2
    else: c.generation = 2
    assert capture_numeric_references(DB([c]), n).candidates == []


def test_capture_freezes_text_and_retrieval_rejects_drift(monkeypatch):
    from app.services import numeric_report_evidence as service
    c, n = chunk(), numeric()
    db = DB([c])
    context = service.capture_numeric_references(db, n)
    assert context.candidates[0].content == c.content
    c.content += '变更'
    with pytest.raises(ValueError, match='reference_context_changed'):
        service.retrieve_numeric_evidence(db, n, context)


def test_retrieval_empty_has_no_fake_branch_execution():
    from app.services import numeric_report_evidence as service
    n = numeric()
    context = service.capture_numeric_references(DB([]), n)
    result = service.retrieve_numeric_evidence(DB([]), n, context)
    assert (result.status, result.vector_status, result.fulltext_status, result.items) == ('empty', 'not_run', 'not_run', [])


def test_capture_accepts_explicit_real_reference_source():
    from app.services import numeric_report_evidence as service
    c = chunk()
    c.chunk_metadata['source'].update(source_kind='real', is_synthetic=False, generator_version=None)
    context = service.capture_numeric_references(DB([c]), numeric())
    assert len(context.candidates) == 1
    assert context.candidates[0].source.source_kind == 'real'


@pytest.mark.parametrize('field,value', [('version', 2), ('access_scope', 'chat'), ('department_id', 3), ('is_current', False)])
def test_retrieval_rejects_document_permission_or_version_drift(field, value):
    from app.services import numeric_report_evidence as service
    c, n = chunk(), numeric()
    db = DB([c])
    context = service.capture_numeric_references(db, n)
    setattr(c.document, field, value)
    with pytest.raises(ValueError, match='reference_context_changed'):
        service.retrieve_numeric_evidence(db, n, context)


def test_retrieval_records_partial_branch_failure(monkeypatch):
    from app.services import numeric_report_evidence as service
    from app.rag.pipeline import RetrievedChunk
    c, n = chunk(), numeric()
    db = DB([c])
    context = service.capture_numeric_references(db, n)
    def fail(*args, **kwargs): raise RuntimeError('secret connection details')
    monkeypatch.setattr(service, '_vector_search', fail)
    def fulltext(*args, **kwargs):
        assert kwargs['allowed_chunk_ids'] == [1]
        return [RetrievedChunk(c, 0.0, fulltext_score=0.5, fulltext_rank=1)]
    monkeypatch.setattr(service, '_fulltext_search', fulltext)
    result = service.retrieve_numeric_evidence(db, n, context)
    assert (result.status, result.vector_status, result.fulltext_status) == ('partial', 'failed', 'complete')
    assert result.items[0].fulltext_rank == 1
    monkeypatch.setattr(service, '_fulltext_search', fail)
    with pytest.raises(ValueError, match='numeric_retrieval_failed'):
        service.retrieve_numeric_evidence(db, n, context)


def test_saved_evidence_rejects_changed_query(monkeypatch):
    from app.services import numeric_report_evidence as service
    n = numeric()
    context = service.capture_numeric_references(DB([]), n)
    evidence = service.retrieve_numeric_evidence(DB([]), n, context)
    evidence.query = 'unrelated query'
    with pytest.raises(ValueError, match='numeric_reference_identity_mismatch'):
        service.validate_numeric_evidence(evidence, context, n)


@pytest.mark.parametrize('branch', ['_vector_search', '_fulltext_search'])
def test_allowlist_is_applied_before_database_top_k(monkeypatch, branch):
    from app.rag import pipeline
    monkeypatch.setattr(pipeline, 'embed_texts', lambda x: [[0.1]])
    class SQLDB:
        def execute(self, sql, params):
            assert params['allowed_chunk_ids'] == [2, 4]
            assert str(sql).index('business_chunk.id = ANY') < str(sql).index('LIMIT :top_k')
            return SimpleNamespace(fetchall=lambda: [])
    assert getattr(pipeline, branch)(SQLDB(), '评分', 3, allowed_chunk_ids=[2, 4]) == []
    assert getattr(pipeline, branch)(None, '评分', 3, allowed_chunk_ids=[]) == []
