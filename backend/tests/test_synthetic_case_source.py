from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from test_synthetic_numeric_prediction import literal_input


def service():
    from app.services import synthetic_case_source
    return synthetic_case_source


def case_fixture():
    raw = literal_input()
    visits = [SimpleNamespace(id=i, case_id=17, visit_date=date.fromisoformat(row['measured_on']),
                              visit_index=i, indicators=[{'name': 'mmse', 'value': row['value'], 'unit': '分'}],
                              visit_context={'method': row['method']}, notes=None)
              for i, row in enumerate(raw['packets'][0]['input_observations'], 1)]
    return SimpleNamespace(id=17, user_id=8, disease_id=3,
                           disease=SimpleNamespace(code='ad'), age=70, sex='female',
                           baseline_stage='mci', notes=None, anonymous_case_code='CASE-123456789',
                           patient_label='CASE-123456789', visits=visits, engineering_source=None), raw


def test_binding_roundtrip_preserves_numeric_identity():
    case, raw = case_fixture()
    case.engineering_source = service().build_engineering_binding(case, raw)
    assert service().validate_engineering_case(case).model_dump(mode='json') == raw
    assert case.engineering_source['source_kind'] == 'synthetic'
    assert case.engineering_source['case_id'] == 17
    assert case.engineering_source['user_id'] == 8


@pytest.mark.parametrize('field,value', [('id', 18), ('user_id', 9), ('disease_id', 4),
                                         ('age', 71), ('sex', 'male'), ('baseline_stage', 'dementia'),
                                         ('notes', 'changed'), ('anonymous_case_code', 'CASE-999999999')])
def test_binding_rejects_case_mutation(field, value):
    case, raw = case_fixture()
    case.engineering_source = service().build_engineering_binding(case, raw)
    setattr(case, field, value)
    with pytest.raises(service().SyntheticCaseSourceError):
        service().validate_engineering_case(case)


@pytest.mark.parametrize('mutation', ['input', 'visit', 'visit_id', 'visit_owner', 'source', 'hash', 'extra', 'missing'])
def test_binding_rejects_corruption(mutation):
    case, raw = case_fixture()
    case.engineering_source = service().build_engineering_binding(case, raw)
    if mutation == 'input':
        for packet in case.engineering_source['numeric_input']['packets']:
            packet['input_observations'][0]['value'] = 25
    elif mutation == 'visit':
        case.visits[0].indicators[0]['value'] = 25
    elif mutation == 'visit_id':
        case.visits[0].id = 100
    elif mutation == 'visit_owner':
        case.visits[0].case_id = 99
    elif mutation == 'source':
        case.engineering_source['run_id'] = 'other'
    elif mutation == 'hash':
        case.engineering_source['numeric_input_sha256'] = 'f' * 64
    elif mutation == 'extra':
        case.engineering_source['future_outcome'] = 20
    else:
        case.engineering_source = None
    with pytest.raises(service().SyntheticCaseSourceError):
        service().validate_engineering_case(case)


def test_binding_creation_rejects_different_numeric_disease_and_existing_binding():
    case, raw = case_fixture()
    with pytest.raises(service().SyntheticCaseSourceError):
        service().build_engineering_binding(case, literal_input('fatty_liver'))
    case.engineering_source = service().build_engineering_binding(case, raw)
    with pytest.raises(service().SyntheticCaseSourceError):
        service().build_engineering_binding(case, raw)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package_fixture(tmp_path):
    # Copy only input-side files: loader must not read outcome/evaluation files.
    original = Path(__file__).resolve().parents[2] / 'outputs/synthetic-prediction-cases/2026-09-14-v1'
    directory = tmp_path / 'package'
    directory.mkdir()
    for name in ('manifest.json', 'patients.jsonl', 'prediction_inputs.jsonl'):
        (directory / name).write_bytes((original / name).read_bytes())
    patients = [json.loads(line) for line in (directory / 'patients.jsonl').read_text(encoding='utf-8').splitlines()]
    return directory, patients[0]['subject_id']


def test_loader_reads_selected_subject_and_only_input_files(tmp_path):
    directory, subject = package_fixture(tmp_path)
    result = service().load_synthetic_case_package(directory, [subject], trusted_root=tmp_path)
    assert len(result) == 1
    patient, numeric = result[0]
    assert patient.subject_id == numeric.subject_id == subject
    assert len(numeric.packets) == 2
    assert numeric.source.manifest_sha256 == sha((directory / 'manifest.json').read_bytes())
    assert all(row.measured_on <= numeric.anchor_date for row in numeric.packets[0].input_observations)


@pytest.mark.parametrize('mutation', ['bytes', 'run', 'version', 'subject', 'empty', 'duplicate', 'outside'])
def test_loader_rejects_invalid_packages_or_selection(tmp_path, mutation):
    directory, subject = package_fixture(tmp_path)
    selected = [subject]
    if mutation == 'bytes':
        with (directory / 'patients.jsonl').open('ab') as stream:
            stream.write(b'\n')
    elif mutation in ('run', 'version'):
        path = directory / 'manifest.json'
        manifest = json.loads(path.read_bytes())
        manifest['run_id' if mutation == 'run' else 'generator_version'] = 'forged'
        path.write_text(json.dumps(manifest), encoding='utf-8')
    elif mutation == 'subject':
        selected = ['absent']
    elif mutation == 'empty':
        selected = []
    elif mutation == 'duplicate':
        selected *= 2
    with pytest.raises(service().SyntheticCaseSourceError):
        service().load_synthetic_case_package(directory, selected,
                                             trusted_root=directory / 'other' if mutation == 'outside' else tmp_path)


@pytest.mark.parametrize('url', [
    'postgresql://localhost/app', 'postgresql://example.com/app_test',
    'sqlite:///app_test', 'postgresql://localhost/app_test?host=example.com',
    'postgresql://localhost/app_test?service=other',
])
def test_isolation_rejects_unsafe_database_urls(url):
    with pytest.raises(service().SyntheticCaseSourceError):
        service().require_isolated_test_database(make_url(url))


def test_isolation_accepts_local_postgres_test_url():
    service().require_isolated_test_database(make_url('postgresql+psycopg2://localhost/app_test'))


def test_seed_rejects_actual_unsafe_engine_before_database_io(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    factory = sessionmaker(bind=create_engine('sqlite://'))
    with pytest.raises(service().SyntheticCaseSourceError, match='isolated_test_database_required'):
        service().seed_synthetic_cases(factory, tmp_path, 8, ['subject'])


def test_display_projection_does_not_fabricate_missing_observations():
    raw = literal_input()
    for packet in raw['packets']:
        packet.update(input_observations=[], anchor_observation_id=None,
                      input_status='unavailable', input_reason='anchor_unavailable', history_state='unknown')
    with pytest.raises(service().SyntheticCaseSourceError, match='display_visits_required'):
        service().numeric_display_visits(raw)


def test_binding_creation_rejects_display_not_matching_input():
    case, raw = case_fixture()
    case.visits[0].indicators[0]['value'] = 29
    with pytest.raises(service().SyntheticCaseSourceError, match='engineering_display_input_mismatch'):
        service().build_engineering_binding(case, raw)


def test_loader_rejects_linked_package_file(tmp_path, monkeypatch):
    directory, subject = package_fixture(tmp_path)
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda p: p.name == 'patients.jsonl' or original(p))
    with pytest.raises(service().SyntheticCaseSourceError, match='synthetic_package_file_invalid'):
        service().load_synthetic_case_package(directory, [subject], trusted_root=tmp_path)


def test_seed_rejects_arbitrary_package_directory_before_query(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    # Constructing the engine does not connect. A query would fail on this unused port.
    factory = sessionmaker(bind=create_engine('postgresql://localhost:1/app_test'))
    with pytest.raises(service().SyntheticCaseSourceError, match='synthetic_package_path_invalid'):
        service().seed_synthetic_cases(factory, tmp_path, 8, ['subject'])


def cli_module():
    import runpy
    path = Path(__file__).resolve().parents[2] / 'scripts/seed_synthetic_numeric_cases.py'
    return runpy.run_path(str(path))


def cli_args():
    package = Path(__file__).resolve().parents[2] / 'outputs/synthetic-prediction-cases/2026-09-14-v1'
    subject = json.loads((package / 'patients.jsonl').read_text(encoding='utf-8').splitlines()[0])['subject_id']
    return ['--user-id', '8', '--subject-id', subject, '--package-dir', str(package)]


def test_cli_dry_run_never_creates_engine(monkeypatch, capsys):
    import sqlalchemy
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost:1/app_test')
    monkeypatch.setattr(sqlalchemy, 'create_engine', lambda *a, **kw: pytest.fail('dry_run_database_io'))
    assert cli_module()['main'](cli_args()) == 0
    assert json.loads(capsys.readouterr().out) == {'status': 'dry_run', 'selected_count': 1, 'is_synthetic': True}


def test_cli_never_falls_back_to_business_database(monkeypatch, capsys):
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://private-secret@localhost/business')
    assert cli_module()['main'](cli_args()) == 2
    output = capsys.readouterr().out
    assert json.loads(output)['error'] == 'test_database_url_required'
    assert 'private-secret' not in output


def test_cli_rejects_bad_arguments_without_echoing_them(capsys):
    assert cli_module()['main'](['--user-id', 'private-secret']) == 2
    output = capsys.readouterr().out
    assert 'private-secret' not in output
    assert json.loads(output)['error'] == 'invalid_arguments'


def test_cli_apply_routes_through_guarded_seed(monkeypatch, capsys):
    from app.services import synthetic_case_source
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost:1/app_test')
    calls = []
    def seed(factory, package_dir, user_id, subjects):
        calls.append((user_id, len(subjects)))
        raise RuntimeError('private-secret')
    monkeypatch.setattr(synthetic_case_source, 'seed_synthetic_cases', seed)
    assert cli_module()['main']([*cli_args(), '--apply']) == 4
    output = capsys.readouterr().out
    assert calls == [(8, 1)]
    assert 'private-secret' not in output
    assert json.loads(output)['error'] == 'synthetic_seed_runtime_error'


@pytest.mark.parametrize('role', ['ai_operator', 'admin'])
def test_seed_operator_roles_reach_duplicate_guard_without_writes(role, monkeypatch):
    from unittest.mock import MagicMock
    case, raw = case_fixture()
    numeric = service()._numeric(raw)
    db = MagicMock()
    db.get_bind.return_value.url = make_url('postgresql://localhost/app_test')
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = SimpleNamespace(role=role)
    db.query.return_value.filter.return_value.first.return_value = case
    db.__enter__.return_value = db
    monkeypatch.setattr(service(), 'load_synthetic_case_package', lambda *args: [(None, numeric)])
    with pytest.raises(service().SyntheticCaseSourceError, match='synthetic_subject_already_imported'):
        service().seed_synthetic_cases(lambda: db, Path('.'), 8, ['subject'])
    db.add.assert_not_called()
    assert db.begin.return_value.__exit__.call_args.args[0] is service().SyntheticCaseSourceError


def test_manifest_requires_explicit_false_clinical_claim(tmp_path):
    directory, subject = package_fixture(tmp_path)
    path = directory / 'manifest.json'
    manifest = json.loads(path.read_bytes())
    manifest['clinical_validity_claim'] = 0
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(service().SyntheticCaseSourceError):
        service().load_synthetic_case_package(directory, [subject], trusted_root=tmp_path)


@pytest.mark.parametrize('variable', ['PGHOSTADDR', 'PGSERVICE'])
def test_isolation_rejects_libpq_environment_redirects(variable, monkeypatch):
    monkeypatch.setenv(variable, 'redirected-private-target')
    with pytest.raises(service().SyntheticCaseSourceError, match='isolated_test_database_required'):
        service().require_isolated_test_database(make_url('postgresql://localhost/app_test'))


@pytest.mark.parametrize('variable', ['PGHOSTADDR', 'PGSERVICE'])
def test_cli_apply_rejects_environment_redirect_before_engine(variable, monkeypatch, capsys):
    import sqlalchemy
    monkeypatch.setenv('TEST_DATABASE_URL', 'postgresql://localhost/app_test')
    monkeypatch.setenv(variable, 'redirected-private-target')
    monkeypatch.setattr(sqlalchemy, 'create_engine', lambda *a, **kw: pytest.fail('unexpected_engine_creation'))
    assert cli_module()['main']([*cli_args(), '--apply']) == 2
    output = capsys.readouterr().out
    assert json.loads(output)['error'] == 'isolated_test_database_required'
    assert 'redirected-private-target' not in output


def test_isolation_accepts_empty_redirect_variables_and_servicefile_only(monkeypatch):
    monkeypatch.setenv('PGHOSTADDR', '')
    monkeypatch.setenv('PGSERVICE', '')
    monkeypatch.setenv('PGSERVICEFILE', 'unused-service-file')
    service().require_isolated_test_database(make_url('postgresql://localhost/app_test'))
