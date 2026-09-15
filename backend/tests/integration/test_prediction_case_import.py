"""Actual PostgreSQL transactions using explicitly fictional source-contract fixtures."""

import hashlib
import json

import pytest
from sqlalchemy.orm import sessionmaker

from app.db.models import OperatorCase, OperatorCaseVisit, OperatorCaseChangeLog
from app.services import prediction_case_source as source
from test_prediction_case_source import package_fixture


@pytest.mark.parametrize('kind', ['synthetic', 'real'])
def test_package_import_and_duplicate_version_are_atomic(db, integration_engine, tmp_path, kind):
    factory = sessionmaker(bind=integration_engine)
    package = package_fixture(tmp_path, kind)
    ids = source.seed_prediction_cases(factory, package, 1)
    with factory() as session:
        case = session.get(OperatorCase, ids[0])
        assert source.validate_prediction_case(case).source.source_kind == kind
        assert session.query(OperatorCaseVisit).count() == 2
        assert session.query(OperatorCaseChangeLog).count() == 1
    with pytest.raises(source.PredictionCaseSourceError, match='prediction_version_already_imported'):
        source.seed_prediction_cases(factory, package, 1)
    with factory() as session:
        assert session.query(OperatorCase).count() == 1
        assert session.query(OperatorCaseVisit).count() == 2
        assert session.query(OperatorCaseChangeLog).count() == 1


def test_failed_second_binding_rolls_back_all_case_visit_and_audit_rows(db, integration_engine, tmp_path, monkeypatch):
    factory = sessionmaker(bind=integration_engine)
    package = package_fixture(tmp_path)
    data = (package / 'records.jsonl').read_bytes()
    second = json.loads(data)
    numeric = second['numeric_input']
    numeric['subject_id'] = 'fictional-second'
    for packet in numeric['packets']:
        packet['subject_id'] = numeric['subject_id']
        packet['sample_id'] = f"fictional-second:{packet['horizon_months']}m"
    data += (json.dumps(second) + '\n').encode()
    (package / 'records.jsonl').write_bytes(data)
    manifest = json.loads((package / 'manifest.json').read_bytes())
    manifest.update(record_count=2, records={'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    (package / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    original, calls = source.build_prediction_binding, []
    def fail_second(case, numeric):
        calls.append(case.id)
        if len(calls) == 2:
            raise ValueError('simulated_binding_failure')
        return original(case, numeric)
    monkeypatch.setattr(source, 'build_prediction_binding', fail_second)
    with pytest.raises(ValueError, match='simulated_binding_failure'):
        source.seed_prediction_cases(factory, package, 1)
    assert len(calls) == 2
    with factory() as session:
        assert session.query(OperatorCase).count() == 0
        assert session.query(OperatorCaseVisit).count() == 0
        assert session.query(OperatorCaseChangeLog).count() == 0
