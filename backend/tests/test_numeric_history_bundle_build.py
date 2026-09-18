from copy import deepcopy
import json

import pytest

from test_numeric_history_bundle import rf_fixture


def test_missing_source_fails_without_output(tmp_path, monkeypatch):
    from app.services import numeric_history_bundle_build as build
    monkeypatch.setattr(build, 'OUTPUT_DIR', tmp_path / 'out')
    with pytest.raises(ValueError, match='source_missing'):
        build.preflight_numeric_history_bundle(tmp_path / 'missing', tmp_path / 'b.json', tmp_path / 'out')
    assert not (tmp_path / 'out').exists()


def test_existing_output_rejected_before_sources(tmp_path):
    from app.services.numeric_history_bundle_build import preflight_numeric_history_bundle
    with pytest.raises(FileExistsError):
        preflight_numeric_history_bundle(tmp_path / 'missing', tmp_path / 'b.json', tmp_path)


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}'])
def test_strict_json_rejects_ambiguous_numbers_and_keys(tmp_path, text):
    from app.services.numeric_history_bundle_build import _read_json
    path = tmp_path / 'x.json'
    path.write_text(text)
    with pytest.raises(ValueError):
        _read_json(path)


def test_prediction_difference_cannot_hide_behind_equal_mean():
    from app.services.numeric_history_bundle_build import _compare_prediction
    left = dict(sample_id='a', task_id='ad.mmse.12m', model_id='random_forest:history_v1:value_history', status='valid', reason=None, value=19.)
    right = {**left, 'status': 'available', 'value': 20.}
    with pytest.raises(ValueError, match='prediction_replay_mismatch'):
        _compare_prediction(left, right)


@pytest.mark.parametrize('field', ['sample_id', 'task_id', 'model_id', 'status', 'reason'])
def test_prediction_identity_and_state_are_checked(field):
    from app.services.numeric_history_bundle_build import _compare_prediction
    left = dict(sample_id='a', task_id='ad.mmse.12m', model_id='random_forest:history_v1:value_history', status='valid', reason=None, value=19.)
    right = {**left, 'status': 'available', field: 'wrong'}
    with pytest.raises(ValueError, match='prediction_replay_mismatch'):
        _compare_prediction(left, right)


def test_tree_export_matches_tiny_synthetic_forest():
    import numpy as np
    from sklearn.ensemble import RandomForestRegressor
    from app.schemas.numeric_history_bundle import RfParameters
    from app.services.numeric_history_bundle import predict_forest_json
    from app.services.numeric_history_bundle_build import _export_trees
    x = np.asarray([[float(i), float(i % 3), float(i % 2)] for i in range(15)])
    estimator = RandomForestRegressor(**RfParameters().model_dump()).fit(x, np.arange(15.) + 5)
    model = rf_fixture()
    model.update(std=[1., 1., 1.], trees=_export_trees(estimator))
    from test_numeric_history_bundle import rehash_model
    rehash_model(model)
    assert [predict_forest_json(row.tolist(), model) for row in x] == estimator.predict(x).tolist()


def test_verify_missing_artifact_does_not_fit(tmp_path, monkeypatch):
    from app.services import numeric_history_bundle_build as build
    monkeypatch.setattr(build, '_fit_selected', lambda *a: pytest.fail('verify must not fit'))
    with pytest.raises(ValueError):
        build.verify_numeric_history_bundle(tmp_path)


@pytest.fixture(scope='module')
def fictional_data():
    """Small, explicitly fictional source behind a monkeypatched trust boundary."""
    import numpy as np
    from app.services import numeric_history_bundle_build as build
    from app.services.numeric_history_bundle import predict_forest_json
    from app.services.prediction_history_features import project_history_features
    from app.schemas.numeric_model_bundle import NumericModelBundle, json_sha256
    from app.schemas.numeric_history_bundle import RfParameters
    from test_numeric_model_bundle import bundle_fixture
    from test_numeric_prediction import numeric_fixture
    from test_numeric_history_bundle import evidence_fixture
    packets, samples, features = {}, {}, {}
    for disease in ('ad', 'fatty_liver'):
        for number in range(6):
            numeric = numeric_fixture(disease)
            subject = f'fictional-{disease}-{number}'
            role = build.ROLES[number // 2]
            for packet in numeric['packets']:
                packet.update(subject_id=subject, dependency_group_id=subject,
                              sample_id=f"{subject}:{packet['horizon_months']}m")
                packet['source'] = dict(source_kind='synthetic', is_synthetic=True,
                                        generator_version='synthetic-prediction.v1', run_id=None)
                for row in packet['input_observations']:
                    row['value'] += number / 10
                packets[packet['sample_id']] = packet
                feature = project_history_features([packet])[0]
                feature.update(evaluation_role=role, pool='challenge_pool' if role == 'challenge' else 'development_pool')
                features[packet['sample_id']] = feature
                samples[packet['sample_id']] = dict(feature, anchor_status='eligible', label_status='valid', actual=20. + number / 10)
    train = [samples[k] for k in sorted(samples) if samples[k]['evaluation_role'] == 'training' and samples[k]['task_id'] == build.SELECTION['task_id']]
    identity = [{k: row[k] for k in ('sample_id', 'subject_id', 'dependency_group_id')} for row in train]
    x = [[features[row['sample_id']][name] for name in build.FEATURE_NAMES] for row in train]
    y = [row['actual'] for row in train]
    matrix = np.asarray(x)
    mean, std = matrix.mean(axis=0), matrix.std(axis=0)
    record = dict(training_sample_ids=[r['sample_id'] for r in train], training_subject_ids=[r['subject_id'] for r in train],
                  training_dependency_groups=sorted({r['dependency_group_id'] for r in train}),
                  training_identity_sha256=json_sha256(identity), training_target_sha256=json_sha256(y),
                  training_data_sha256=json_sha256(dict(identity=identity, feature_names=build.FEATURE_NAMES, X=x, y=y)),
                  mean=mean.tolist(), std=std.tolist(), scale=np.where(std == 0, 1., std).tolist(),
                  constant_columns=[name for name, sigma in zip(build.FEATURE_NAMES, std) if sigma == 0],
                  parameters=RfParameters().model_dump(mode='json'))
    data = dict(packets=packets, features=features, samples=samples, record=record,
                legacy=NumericModelBundle.model_validate(bundle_fixture()),
                snapshot=dict(files={'seed-20260914/cohort.json': {'sha256': 'a' * 64, 'bytes': 0}}))
    model = build._fit_selected(data)
    data['predictions'] = [dict(sample_id=k, task_id=row['task_id'], model_id=build.SELECTION['model_id'],
        status='valid', reason=None, value=predict_forest_json([row[name] for name in build.FEATURE_NAMES], model))
        for k, row in features.items() if row['task_id'] == build.SELECTION['task_id']]
    evidence = evidence_fixture(model.model_dump(mode='json'))
    data.update(comparisons=evidence['comparisons'], aggregates=evidence['aggregates'])
    return data


@pytest.fixture
def trusted_fixture(fictional_data, monkeypatch, tmp_path):
    from app.services import numeric_history_bundle_build as build
    data = deepcopy(fictional_data)
    monkeypatch.setattr(build, 'OUTPUT_DIR', tmp_path / 'new')
    monkeypatch.setattr(build, '_load_sources', lambda *a: deepcopy(data))
    monkeypatch.setattr(build, '_source_snapshot', lambda *a: (deepcopy(data['snapshot']), data['legacy']))
    # The old fixture bundle deliberately has fictional source/runtime identities.
    monkeypatch.setattr(build, 'verify_numeric_history_runtime', lambda *a: None)
    return build, data


def test_tiny_build_then_independent_verification_without_fit(trusted_fixture, tmp_path, monkeypatch):
    build, _ = trusted_fixture
    original = build._fit_selected
    calls = []
    def fit(data):
        calls.append(1)
        return original(data)
    monkeypatch.setattr(build, '_fit_selected', fit)
    destination = tmp_path / 'new'
    result = build.build_numeric_history_bundle(tmp_path / 'source', tmp_path / 'old', destination)
    assert calls == [1]
    assert result['replay']['projection']['rows'] == 24
    assert {role: count['rows'] for role, count in result['replay']['roles'].items()} == dict(training=2, internal_validation=2, challenge=2)
    assert all(row['rows'] == 6 for row in result['replay']['legacy'].values())
    monkeypatch.setattr(build, '_fit_selected', lambda *a: pytest.fail('verification must never fit'))
    assert build.verify_numeric_history_bundle(destination)['replay'] == result['replay']
    assert set(p.name for p in destination.iterdir()) == {'bundle.json', 'manifest.json', 'replay.json'}


def test_preflight_never_fits_or_creates_directory(trusted_fixture, tmp_path, monkeypatch):
    build, _ = trusted_fixture
    monkeypatch.setattr(build, '_fit_selected', lambda *a: pytest.fail('preflight must not fit'))
    output = tmp_path / 'absent-parent' / 'new'
    monkeypatch.setattr(build, 'OUTPUT_DIR', output)
    assert build.preflight_numeric_history_bundle(tmp_path, tmp_path, output)['fitted_models'] == 0
    assert not output.parent.exists()


@pytest.mark.parametrize('key', ['training_identity_sha256', 'training_target_sha256', 'training_data_sha256', 'mean', 'std', 'scale', 'training_sample_ids'])
def test_training_identity_drift_fails_before_fit(fictional_data, key):
    from app.services.numeric_history_bundle_build import _training
    data = deepcopy(fictional_data)
    data['record'][key] = [] if isinstance(data['record'][key], list) else '0' * 64
    with pytest.raises(ValueError, match='training_identity_mismatch'):
        _training(data)


def test_history_calculation_error_not_dropped(fictional_data):
    from app.services.numeric_history_bundle_build import _training
    data = deepcopy(fictional_data)
    data['features'][data['record']['training_sample_ids'][0]]['history_status'] = 'error'
    with pytest.raises(ValueError, match='history_training_calculation_error'):
        _training(data)


def test_dependency_group_cannot_cross_roles(fictional_data):
    from app.services.numeric_history_bundle_build import _validate_partitions
    data = deepcopy(fictional_data)
    rows = list(data['features'].values())
    train = next(r for r in rows if r['evaluation_role'] == 'training')
    challenge = next(r for r in rows if r['evaluation_role'] == 'challenge')
    challenge['dependency_group_id'] = train['dependency_group_id']
    with pytest.raises(ValueError, match='dependency_crosses_partitions'):
        _validate_partitions(rows, list(data['samples'].values()))


def test_prediction_mismatch_leaves_no_output(trusted_fixture, tmp_path):
    build, data = trusted_fixture
    data['predictions'][0]['value'] += 0.01
    output = tmp_path / 'new'
    with pytest.raises(ValueError, match='prediction_replay_mismatch'):
        build.build_numeric_history_bundle(tmp_path, tmp_path, output)
    assert list(tmp_path.iterdir()) == []


def test_source_changes_during_build_leave_no_complete_artifact(trusted_fixture, tmp_path, monkeypatch):
    build, data = trusted_fixture
    monkeypatch.setattr(build, '_source_snapshot', lambda *a: ({'changed': True}, data['legacy']))
    with pytest.raises(ValueError, match='source_changed_during_build'):
        build.build_numeric_history_bundle(tmp_path, tmp_path, tmp_path / 'new')
    assert list(tmp_path.iterdir()) == []


def test_tampered_model_with_rehashed_receipts_still_fails_replay(trusted_fixture, tmp_path):
    build, _ = trusted_fixture
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    from test_numeric_history_bundle import rehash_model
    output = tmp_path / 'new'
    build.build_numeric_history_bundle(tmp_path, tmp_path, output)
    raw = json.loads((output / 'bundle.json').read_text(encoding='utf8'))
    # A change to one leaf is not authenticated merely by regenerating all hashes.
    raw['history_model']['trees'][0]['nodes'][0]['value'] += 1.
    rehash_model(raw['history_model'])
    raw['history_evidence']['parameters_sha256'] = raw['history_model']['parameters_sha256']
    (output / 'bundle.json').write_text(json.dumps(raw), encoding='utf8')
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf8'))
    manifest.update(parameters_sha256=raw['history_model']['parameters_sha256'],
                    bundle_sha256=build.history_bundle_sha256(NumericHistoryBundle.model_validate(raw)))
    manifest['files']['bundle.json'] = build._record(output / 'bundle.json')
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='prediction_replay_mismatch'):
        build.verify_numeric_history_bundle(output)


@pytest.mark.parametrize('key,value', [('clinical_validity_claim', True), ('source_kind', 'real'),
    ('clinical_status', 'passed'), ('production_enabled', True), ('fitted_models', True), ('unrecognized', 1)])
def test_manifest_claims_and_shape_are_verified(trusted_fixture, tmp_path, key, value):
    build, _ = trusted_fixture
    output = tmp_path / 'new'
    build.build_numeric_history_bundle(tmp_path, tmp_path, output)
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf8'))
    manifest[key] = value
    (output / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    with pytest.raises(ValueError, match='invalid_build_manifest'):
        build.verify_numeric_history_bundle(output)


def test_stage_cleanup_rejects_wrong_parent(tmp_path):
    from app.services.numeric_history_bundle_build import _validate_stage
    with pytest.raises(ValueError, match='unsafe_stage_path'):
        _validate_stage(tmp_path / '.numeric-history-wrong', tmp_path / 'other' / 'output')


@pytest.fixture
def sealed_fixture(tmp_path, monkeypatch):
    from app.services import numeric_history_bundle_build as build
    from test_numeric_model_bundle import bundle_fixture
    history = tmp_path / 'fictional-source'
    history.mkdir()
    legacy = tmp_path / 'fictional-legacy.json'
    legacy.write_text(json.dumps(bundle_fixture()), encoding='utf8')
    source_name = 'backend/app/services/prediction_history_features.py'
    protocol = dict(runtime=build._runtime(), protocol={'is_test_fixture': True},
                    code_sha256={source_name: build._record(build.ROOT / source_name)['sha256']})
    (history / 'protocol.json').write_text(json.dumps(protocol), encoding='utf8')
    records = {'protocol.json': build._record(history / 'protocol.json')}
    # All frozen constants are replaced explicitly, only at this test trust boundary.
    # Production has no flag or configuration capable of doing this.
    manifest = dict(status='passed', run_id='fictional-sealed-unit-source', is_test_fixture=False,
                    files=records, data_content_sha256=build.json_sha256(records),
                    protocol_identity_sha256=build.json_sha256(protocol))
    (history / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    monkeypatch.setattr(build, 'HISTORY_DIR', history)
    monkeypatch.setattr(build, 'LEGACY_PATH', legacy)
    monkeypatch.setattr(build, 'MANIFEST_SHA', build._record(history / 'manifest.json')['sha256'])
    monkeypatch.setattr(build, 'DATA_SHA', manifest['data_content_sha256'])
    monkeypatch.setattr(build, 'PROTOCOL_SHA', manifest['protocol_identity_sha256'])
    monkeypatch.setattr(build, 'RUN_ID', manifest['run_id'])
    monkeypatch.setattr(build, 'LEGACY_SHA', build.bundle_sha256(build.load_numeric_model_bundle(legacy)))
    monkeypatch.setattr(build, 'verify_numeric_bundle_runtime', lambda *a: None)
    return build, history, legacy


def test_source_snapshot_checks_all_frozen_identities(sealed_fixture):
    build, history, legacy = sealed_fixture
    snapshot, _ = build._source_snapshot(history, legacy)
    assert snapshot['manifest']['sha256'] == build.MANIFEST_SHA
    assert snapshot['files'] == json.loads((history / 'manifest.json').read_text())['files']


@pytest.mark.parametrize('mutation,code', [('manifest', 'manifest_identity_mismatch'),
    ('file', 'source_file_changed'), ('legacy', 'legacy_identity_mismatch'),
    ('runtime', 'runtime_changed'), ('code', 'source_code_changed'), ('extra', 'source_file_set_changed')])
def test_source_snapshot_rejects_drift(sealed_fixture, monkeypatch, mutation, code):
    build, history, legacy = sealed_fixture
    if mutation == 'manifest':
        with (history / 'manifest.json').open('a') as stream:
            stream.write(' ')
    elif mutation == 'file':
        with (history / 'protocol.json').open('a') as stream:
            stream.write(' ')
    elif mutation == 'legacy':
        monkeypatch.setattr(build, 'LEGACY_SHA', '0' * 64)
    elif mutation == 'runtime':
        monkeypatch.setattr(build, '_runtime', lambda: {'python': 'drift'})
    elif mutation == 'code':
        record = build._record
        def changed(path):
            if path == build.ROOT / 'backend/app/services/prediction_history_features.py':
                return {'sha256': '0' * 64, 'bytes': 0}
            return record(path)
        monkeypatch.setattr(build, '_record', changed)
    else:
        (history / 'extra.json').write_text('{}')
    with pytest.raises(ValueError, match=code):
        build._source_snapshot(history, legacy)


def test_write_failure_cleans_own_stage(trusted_fixture, tmp_path, monkeypatch):
    build, _ = trusted_fixture
    def failure(*a):
        raise OSError('test write failure')
    monkeypatch.setattr(build, '_write', failure)
    with pytest.raises(OSError):
        build.build_numeric_history_bundle(tmp_path, tmp_path, tmp_path / 'new')
    assert list(tmp_path.iterdir()) == []
