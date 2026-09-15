from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.schemas.numeric_report import NumericGenerationContext
from app.services.numeric_report_publication import build_numeric_document, build_numeric_publication, verify_numeric_integrity


def fixture(disease='ad'):
    from test_synthetic_report_publication import publication_fixture
    from app.services.prediction_case_source import convert_legacy_input
    from app.services.numeric_prediction import numeric_input_sha256, numeric_algorithm_identity, predict_numeric
    from app.services.report_integrity import compute_input_snapshot_sha256
    snapshot, _, _ = publication_fixture(disease)
    numeric = convert_legacy_input(snapshot['numeric_input'])
    snapshot.update(schema_version='numeric_report_input.v1', report_kind='numeric_prediction',
        numeric_input=numeric.model_dump(mode='json'), source_binding_sha256=snapshot.pop('engineering_source_sha256'))
    snapshot['input_snapshot_sha256'] = compute_input_snapshot_sha256(snapshot)
    context = NumericGenerationContext(disease_code=disease, numeric_input_sha256=numeric_input_sha256(numeric),
        source_binding_sha256=snapshot['source_binding_sha256'], algorithm=numeric_algorithm_identity())
    prediction = predict_numeric(numeric)
    document = build_numeric_document(7, datetime(2026, 9, 14, tzinfo=timezone.utc), snapshot, context, prediction)
    return snapshot, build_numeric_publication(snapshot, prediction, document)


@pytest.mark.parametrize('disease,indicator', [('ad','MMSE'),('fatty_liver','ALT')])
def test_one_numeric_publication_preserves_source_only_in_saved_metadata(disease, indicator):
    snapshot, publication = fixture(disease)
    assert publication.generation_fingerprint_version == 'v4'
    assert publication.report_document.schema_version == 'numeric_report_document.v1'
    assert indicator in publication.content and '6 月' in publication.content and '12 月' in publication.content
    assert '合成' not in publication.content and 'synthetic' not in publication.content
    assert publication.report_document.numeric_input.source.is_synthetic is True
    assert publication.evidence_snapshot['source']['is_synthetic'] is True
    assert verify_numeric_integrity(snapshot, snapshot['input_snapshot_sha256'], publication.generation_fingerprint,
        publication.prediction_result, publication.content, publication.evidence_snapshot, publication.evidence_snapshot_sha256,
        publication.report_document.model_dump(mode='json'), publication.report_document_sha256, [])


@pytest.mark.parametrize('part', ['content','prediction_result','report_document','evidence_snapshot','snapshot'])
def test_numeric_saved_parts_reject_tampering(part):
    snapshot, publication = fixture()
    saved = publication.model_dump(mode='json')
    if part == 'content': saved[part] += '\nchanged'
    elif part == 'prediction_result': saved[part]['predictions'][0]['value'] += 1
    elif part == 'report_document': saved[part]['identity']['age'] += 1
    elif part == 'evidence_snapshot': saved[part]['source']['dataset_version'] = 'different'
    else: snapshot['numeric_input']['source']['dataset_version'] = 'different'
    assert not verify_numeric_integrity(snapshot, snapshot['input_snapshot_sha256'], saved['generation_fingerprint'],
        saved['prediction_result'], saved['content'], saved['evidence_snapshot'], saved['evidence_snapshot_sha256'],
        saved['report_document'], saved['report_document_sha256'], [])


def test_unknown_document_version_and_legacy_publication_are_not_interchangeable():
    from app.schemas.report_document import parse_publication, parse_report_document
    _, publication = fixture()
    assert parse_publication(publication.model_dump(mode='json')) == publication
    raw = publication.report_document.model_dump(mode='json')
    raw['schema_version'] = 'numeric_report_document.v99'
    with pytest.raises(ValueError): parse_report_document(raw)
