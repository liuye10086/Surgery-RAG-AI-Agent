from copy import deepcopy
import hashlib
import json

import pytest

from test_numeric_prediction import numeric_fixture
from test_synthetic_case_source import case_fixture


@pytest.mark.parametrize('kind', ['synthetic', 'real'])
def test_new_binding_and_corruption(kind):
    from app.services.prediction_case_source import build_prediction_binding, validate_prediction_case
    case, _ = case_fixture()
    raw = numeric_fixture(kind=kind)
    case.prediction_source = build_prediction_binding(case, raw)
    assert validate_prediction_case(case).model_dump(mode='json') == raw
    case.visits[0].indicators[0]['value'] += 1
    with pytest.raises(ValueError):
        validate_prediction_case(case)


def test_legacy_requires_original_binding_and_preserves_it():
    from app.services.prediction_case_source import validate_prediction_case
    from app.services.synthetic_case_source import build_engineering_binding
    case, raw = case_fixture()
    with pytest.raises(ValueError):
        validate_prediction_case(case)
    case.engineering_source = build_engineering_binding(case, raw)
    saved = deepcopy(case.engineering_source)
    numeric = validate_prediction_case(case)
    assert numeric.source.source_kind == 'synthetic'
    assert numeric.schema_version == 'numeric_input.v1'
    assert case.engineering_source == saved
    case.prediction_source = {}
    with pytest.raises(ValueError):
        validate_prediction_case(case)


def package_fixture(tmp_path, kind='real', disease='ad'):
    directory = tmp_path / 'package'
    directory.mkdir()
    numeric = numeric_fixture(disease=disease, kind=kind)
    source = numeric['packets'][0]['source']
    # Explicitly fictional input exercises the real-source contract only.
    record = {'age': 70, 'sex': 'female', 'baseline_stage': 'mci' if disease == 'ad' else 'pre_cirrhosis',
              'numeric_input': {k: v for k, v in numeric.items() if k != 'source'}}
    data = (json.dumps(record, ensure_ascii=False) + '\n').encode('utf-8')
    (directory / 'records.jsonl').write_bytes(data)
    manifest = {'schema_version': 'prediction_case_package.v1', 'source': source,
                'records': {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()},
                'record_count': 1, 'clinical_validity_claim': False}
    (directory / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    return directory


@pytest.mark.parametrize('kind', ['synthetic', 'real'])
def test_version_package_loads_both_sources_and_rejects_changed_file(tmp_path, kind):
    from app.services.prediction_case_source import load_prediction_case_package
    directory = package_fixture(tmp_path, kind)
    records = load_prediction_case_package(directory)
    assert len(records) == 1
    assert records[0][1].source.source_kind == kind
    assert records[0][1].source.input_file_sha256 == hashlib.sha256((directory / 'records.jsonl').read_bytes()).hexdigest()
    with (directory / 'records.jsonl').open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError):
        load_prediction_case_package(directory)


def test_seed_rejects_nonisolated_database_before_io(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.prediction_case_source import seed_prediction_cases
    with pytest.raises(ValueError, match='isolated_test_database_required'):
        seed_prediction_cases(sessionmaker(bind=create_engine('sqlite://')), tmp_path, 8)


def test_cli_dry_run_and_no_business_fallback(tmp_path, monkeypatch, capsys):
    import runpy
    from pathlib import Path
    import sqlalchemy
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/import_prediction_cases.py'))['main']
    directory = package_fixture(tmp_path)
    args = ['--package-dir', str(directory), '--user-id', '8']
    monkeypatch.setattr(sqlalchemy, 'create_engine', lambda *a, **kw: pytest.fail('unexpected_database_io'))
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://private-secret@localhost/business')
    assert main(args) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'test_database_url_required'
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost:1/app_test')
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out) == {'status': 'dry_run', 'selected_count': 1}


def test_cli_rejects_redirect_before_engine_with_stable_error(tmp_path, monkeypatch, capsys):
    import runpy
    from pathlib import Path
    import sqlalchemy
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/import_prediction_cases.py'))['main']
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost/app_test')
    monkeypatch.setenv('PGHOSTADDR', 'private-redirect')
    monkeypatch.setattr(sqlalchemy, 'create_engine', lambda *a, **kw: pytest.fail('unexpected_database_io'))
    assert main(['--package-dir', str(tmp_path), '--user-id', '8', '--apply']) == 2
    assert json.loads(capsys.readouterr().out)['error'] == 'isolated_test_database_required'


@pytest.mark.parametrize('mutation', ['unknown_source', 'duplicate', 'clinical_claim'])
def test_invalid_manifest_and_duplicate_subjects_rejected(tmp_path, mutation):
    from app.services.prediction_case_source import load_prediction_case_package
    directory = package_fixture(tmp_path)
    path = directory / 'manifest.json'
    manifest = json.loads(path.read_bytes())
    if mutation == 'unknown_source':
        manifest['source']['source_kind'] = 'unknown'
    elif mutation == 'clinical_claim':
        manifest['clinical_validity_claim'] = 0
    else:
        data = (directory / 'records.jsonl').read_bytes() * 2
        (directory / 'records.jsonl').write_bytes(data)
        manifest['record_count'] = 2
        manifest['records'] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        load_prediction_case_package(directory)
