from copy import deepcopy

import pytest

from test_numeric_model_bundle import bundle_fixture, digest


def rf_fixture(values=None):
    from app.schemas.numeric_history_bundle import RfParameters
    raw = dict(task_id='ad.mmse.12m', model_id='random_forest:history_v1:value_history',
               feature_names=['anchor_value', 'prior_value', 'slope_per_day'], mean=[0., 0., 0.],
               std=[0., 1., 1.], scale=[1., 1., 1.], parameters=RfParameters().model_dump(mode='json'),
               trees=[{'nodes': [{'kind': 'leaf', 'value': v}]} for v in (values or [19.] * 200)],
               source_seed=20260914, training_sample_ids=['fixture-a', 'fixture-b'],
               training_subject_ids=['fixture-a', 'fixture-b'], training_dependency_groups=['fixture-a', 'fixture-b'],
               training_identity_sha256='1' * 64, training_data_sha256='2' * 64, training_target_sha256='3' * 64)
    raw['parameters_sha256'] = digest(raw)
    return raw


def rehash_model(raw):
    raw['parameters_sha256'] = digest({k: v for k, v in raw.items() if k != 'parameters_sha256'})
    return raw


def evidence_fixture(model):
    # Deliberately tiny fictional evidence, never represented as a sealed artifact.
    comparisons, aggregates = [], []
    for role in ('training', 'internal_validation', 'challenge'):
        for name in ('value_history_vs_last_value', 'value_history_vs_anchor_history'):
            for scope in ('original', 'common_complete'):
                identity = dict(evaluation_role=role, task_id='ad.mmse.12m', family='random_forest',
                                comparison_name=name, scope=scope, candidate_model_id='random_forest:history_v1:value_history',
                                reference_model_id='last_value' if name.endswith('last_value') else 'random_forest:history_v1:anchor_history',
                                gain_name='mae_gain_reference_minus_candidate', unit='分')
                count = dict(N_patient=2, N_anchor_eligible=2, N_anchor_ineligible=0, N_anchor_pending=0,
                             N_history_eligible=2, N_history_unavailable=0, N_branch_eligible=2,
                             N_original_eligible=2, N_common_complete=2, N_common_excluded=0,
                             N_common_excluded_due_to_output=0, N_label_valid=2, N_label_absent=0,
                             N_label_pending=0, N_label_not_applicable=0, N_pair_valid=2, N_dependency_groups=2,
                             N_candidate_out_of_range=0, N_reference_out_of_range=0,
                             N_all_candidate_out_of_range=0, N_all_reference_out_of_range=0)
                for prefix in ('N_pred_', 'N_reference_', 'N_original_pred_', 'N_original_reference_', 'N_all_pred_', 'N_all_reference_'):
                    count.update({prefix + 'valid': 2, prefix + 'abstain': 0, prefix + 'error': 0})
                metrics = dict(mae=1., rmse=1., bias=0., reference_mae=2., mae_gain_reference_minus_candidate=1.)
                interval = dict(status='estimated', reason=None, lower=0., upper=2., width=2., attempted=2, valid=2, failed=0)
                comparisons.append(dict(**identity, seed=20260914,
                    comparison_id=f'ad.mmse.12m:{role}:random_forest:{name}:{scope}',
                    pool='challenge_pool' if role == 'challenge' else 'development_pool',
                    counts=count, joint_states=dict(both_valid=2, candidate_unavailable=0, reference_unavailable=0, both_unavailable=0),
                    coverage={key: dict(value=1., numerator=2, denominator=2, reason=None)
                              for key in ('label_support', 'paired', 'end_to_end')},
                    complete_output=True, statistics=dict(**metrics, alpha=0., beta=1., n_patients=2, n_groups=2, unavailable=[]),
                    intervals={key: deepcopy(interval) for key in metrics} if role == 'challenge' else {},
                    common_scope_limited=False, bootstrap_plan_id='fictional-bootstrap' if role == 'challenge' else None,
                    uncertainty_scope='synthetic_fixed_challenge_group_bootstrap' if role == 'challenge' else 'descriptive_only',
                    clinical_status='not_assessable'))
                def summary(value): return dict(mean=value, min=value, max=value, n_valid=3, n_invalid=0)
                aggregates.append(dict(**identity, expected_seeds=[20260914, 20260915, 20260916],
                    seeds=[20260914, 20260915, 20260916], missing_seeds=[], n_present_seeds=3,
                    effective_seeds=[20260914, 20260915, 20260916], n_effective_seeds=3,
                    complete=True, incomplete=False, gain_direction='positive',
                    metrics={key: dict(**summary(value), missing_seeds=[]) for key, value in metrics.items()},
                    counts={key: summary(2.) for key in ('N_label_valid', 'N_pair_valid')},
                    source_kind='synthetic', clinical_validity_claim=False, clinical_status='not_assessable'))
    return dict(schema_version='numeric_history_evidence.v1', source_kind='synthetic', clinical_status='not_assessable',
                clinical_validity_claim=False, run_id='fictional-unit-fixture', manifest_sha256='4' * 64,
                data_content_sha256='5' * 64, protocol_identity_sha256='6' * 64,
                selection=dict(schema_version='numeric_history_selection.v1', seed=20260914, task_id='ad.mmse.12m',
                               model_id='random_forest:history_v1:value_history'),
                source_seed=20260914, model_id='random_forest:history_v1:value_history',
                training_identity_sha256=model['training_identity_sha256'], parameters_sha256=model['parameters_sha256'],
                challenge_subject_ids=['challenge-a', 'challenge-b'], challenge_dependency_groups=['challenge-a', 'challenge-b'],
                comparisons=comparisons, aggregates=aggregates)


def history_bundle_fixture():
    from app.schemas.numeric_model_bundle import NumericModelBundle
    old = NumericModelBundle.model_validate(bundle_fixture()).model_dump(mode='json')
    old['models'].sort(key=lambda row: row['task_id'])
    model = rf_fixture()
    return dict(schema_version='numeric_model_bundle.v2', selection_version='numeric_history_selection.v1',
                input_schema_version='numeric_input.v1', implementation_sha256='7' * 64,
                clinical_validity_claim=False, production_enabled=False, legacy_bundle=old, legacy_bundle_sha256=digest(old),
                history_model=model, task_assignments=[dict(task_id=row['task_id'], provider='history_rf' if row['task_id'] == 'ad.mmse.12m' else 'legacy_ridge') for row in old['models']],
                history_evidence=evidence_fixture(model))


def split_tree():
    return {'nodes': [
        {'kind': 'branch', 'feature_index': 0, 'threshold': 1 + 2**-26, 'left': 1, 'right': 2},
        {'kind': 'leaf', 'value': 10.0}, {'kind': 'leaf', 'value': 20.0},
    ]}


def test_float32_features_and_double_threshold():
    from app.services.numeric_history_bundle import predict_tree_json
    assert predict_tree_json(split_tree(), (1 + 2**-25, 0.0, 0.0)) == 10.0
    assert predict_tree_json(split_tree(), (1 + 2**-22, 0.0, 0.0)) == 20.0


@pytest.mark.parametrize('mutation', ['cycle', 'multiple_parents', 'orphan', 'index', 'bool', 'nan', 'extra'])
def test_malformed_tree_rejected(mutation):
    from app.schemas.numeric_history_bundle import RfTree
    raw = split_tree()
    if mutation == 'cycle': raw['nodes'][0]['left'] = 0
    elif mutation == 'multiple_parents': raw['nodes'][0]['right'] = 1
    elif mutation == 'orphan': raw['nodes'].append({'kind': 'leaf', 'value': 1.0})
    elif mutation == 'index': raw['nodes'][0]['right'] = 3
    elif mutation == 'bool': raw['nodes'][0]['feature_index'] = True
    elif mutation == 'nan': raw['nodes'][1]['value'] = float('nan')
    else: raw['nodes'][1]['left'] = 0
    with pytest.raises(ValueError): RfTree.model_validate(raw)


def test_repeated_feature_and_single_leaf_are_legal():
    from app.services.numeric_history_bundle import predict_tree_json
    assert predict_tree_json({'nodes': [{'kind': 'leaf', 'value': 7.0}]}, (0., 0., 0.)) == 7
    raw = split_tree()
    raw['nodes'][1] = {'kind': 'branch', 'feature_index': 0, 'threshold': 0., 'left': 3, 'right': 4}
    raw['nodes'] += [{'kind': 'leaf', 'value': 8.}, {'kind': 'leaf', 'value': 9.}]
    assert predict_tree_json(raw, (0., 0., 0.)) == 8


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 1e40, True])
def test_invalid_or_overflow_features_rejected(value):
    from app.services.numeric_history_bundle import predict_tree_json
    with pytest.raises((ValueError, ArithmeticError)):
        predict_tree_json(split_tree(), (value, 0., 0.))


def test_depth_above_four_rejected():
    from app.schemas.numeric_history_bundle import RfTree
    nodes = [{'kind': 'leaf', 'value': 1.}]
    for _ in range(5):
        shifted = deepcopy(nodes)
        for node in shifted:
            if node['kind'] == 'branch':
                node['left'] += 1
                node['right'] += 1
        nodes = [{'kind': 'branch', 'feature_index': 0, 'threshold': 0., 'left': 1, 'right': len(nodes) + 1},
                 *shifted, {'kind': 'leaf', 'value': 1.}]
    with pytest.raises(ValueError): RfTree(nodes=nodes)


def test_forest_preserves_double_order_and_constant_column():
    from app.services.numeric_history_bundle import predict_forest_json
    # fsum would give 1/200; ordinary ordered reduction gives zero.
    assert predict_forest_json([22., 24., -0.01], rf_fixture([1e16, 1., -1e16] + [0.] * 197)) == 0.
    assert predict_forest_json([22., 24., -0.01], rf_fixture()) == 19.


def test_standardize_in_double_before_float32():
    from app.services.numeric_history_bundle import predict_forest_json
    model = rf_fixture()
    model['mean'][0] = 1e20
    model['trees'] = [split_tree()] * 200
    assert predict_forest_json([1e20, 0., 0.], rehash_model(model)) == 10.


@pytest.mark.parametrize('mutation', ['trees', 'scale', 'features', 'seed', 'config', 'hash', 'bool'])
def test_invalid_rf_model_rejected(mutation):
    from app.schemas.numeric_history_bundle import NumericHistoryRfModel
    model = rf_fixture()
    if mutation == 'trees': model['trees'].pop()
    elif mutation == 'scale': model['scale'][0] = 0.
    elif mutation == 'features': model['feature_names'].reverse()
    elif mutation == 'seed': model['source_seed'] = 20260915
    elif mutation == 'config': model['parameters']['max_depth'] = 5
    elif mutation == 'hash': model['trees'][0]['nodes'][0]['value'] += 1
    else: model['parameters']['n_jobs'] = True
    if mutation != 'hash': rehash_model(model)
    with pytest.raises(ValueError): NumericHistoryRfModel.model_validate(model)


def test_mutated_model_instance_is_revalidated():
    from app.schemas.numeric_history_bundle import NumericHistoryRfModel
    from app.services.numeric_history_bundle import predict_forest_json
    model = NumericHistoryRfModel.model_validate(rf_fixture())
    model.trees[0].nodes[0].value = 17.
    with pytest.raises(ValueError): predict_forest_json([0., 0., 0.], model)


@pytest.mark.parametrize('mutation', ['route', 'duplicate', 'missing', 'legacy_hash', 'model_hash', 'evidence_hash',
                                    'extra_evidence', 'extra_counts', 'counts', 'seed', 'flag', 'leak', 'aggregate'])
def test_invalid_mixed_bundle_is_rejected(mutation):
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    raw = history_bundle_fixture()
    if mutation == 'route': raw['task_assignments'][0]['provider'] = 'history_rf' if raw['task_assignments'][0]['provider'] == 'legacy_ridge' else 'legacy_ridge'
    elif mutation == 'duplicate': raw['task_assignments'][1] = deepcopy(raw['task_assignments'][0])
    elif mutation == 'missing': raw['task_assignments'].pop()
    elif mutation == 'legacy_hash': raw['legacy_bundle_sha256'] = '0' * 64
    elif mutation == 'model_hash': raw['history_model']['trees'][0]['nodes'][0]['value'] = 10.
    elif mutation == 'evidence_hash': raw['history_evidence']['parameters_sha256'] = '0' * 64
    elif mutation == 'extra_evidence': raw['history_evidence']['arbitrary'] = {}
    elif mutation == 'extra_counts': raw['history_evidence']['comparisons'][0]['counts']['anything'] = 1
    elif mutation == 'counts': raw['history_evidence']['comparisons'][0]['counts']['N_pair_valid'] = 3
    elif mutation == 'seed': raw['history_evidence']['source_seed'] = 20260915
    elif mutation == 'flag': raw['clinical_validity_claim'] = 0
    elif mutation == 'leak': raw['history_evidence']['challenge_subject_ids'][0] = 'fixture-a'
    else: raw['history_evidence']['aggregates'][0] = deepcopy(raw['history_evidence']['aggregates'][1])
    with pytest.raises(ValueError): NumericHistoryBundle.model_validate(raw)


def test_roundtrip_complete_legacy_and_ordered_hash(tmp_path):
    import json
    from app.services.numeric_history_bundle import load_numeric_history_bundle, history_bundle_sha256
    raw = history_bundle_fixture()
    path = tmp_path / 'bundle.json'
    path.write_text(json.dumps(raw), encoding='utf-8')
    loaded = load_numeric_history_bundle(path)
    assert loaded.legacy_bundle.model_dump(mode='json') == raw['legacy_bundle']
    digest_before = history_bundle_sha256(raw)
    raw['task_assignments'].reverse()
    assert history_bundle_sha256(raw) == digest_before
    assert history_bundle_sha256(loaded) == digest_before


@pytest.mark.parametrize('contents', ['{}', '{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"schema_version":"unknown"}'])
def test_loader_rejects_invalid_json(tmp_path, contents):
    from app.services.numeric_history_bundle import load_numeric_history_bundle
    path = tmp_path / 'bundle.json'
    path.write_text(contents, encoding='utf-8')
    with pytest.raises(ValueError): load_numeric_history_bundle(path)


def test_loader_enforces_file_size_limit(tmp_path):
    from app.services.numeric_history_bundle import MAX_BUNDLE_BYTES, load_numeric_history_bundle
    path = tmp_path / 'bundle.json'
    path.write_bytes(b' ' * (MAX_BUNDLE_BYTES + 1))
    with pytest.raises(ValueError, match='file_too_large'): load_numeric_history_bundle(path)


@pytest.mark.parametrize('mutation', ['replace', 'delete'])
def test_runtime_rejects_replaced_or_deleted_function(monkeypatch, mutation):
    from app.services import numeric_history_bundle as service, numeric_model_bundle
    raw = history_bundle_fixture()
    raw['implementation_sha256'] = service.history_implementation_sha256(raw['legacy_bundle']['implementation_sha256'])
    # A fictional legacy identity needs a stubbed old gate; new runtime checks remain real.
    monkeypatch.setattr(numeric_model_bundle, 'verify_numeric_bundle_runtime', lambda bundle: None)
    if mutation == 'replace': monkeypatch.setattr(service, '_tree_value', lambda *args: 19.)
    else: monkeypatch.delattr(service, '_tree_value')
    with pytest.raises(ValueError, match='loaded_code_mismatch'): service.verify_numeric_history_runtime(raw)


def test_runtime_accepts_loaded_code_then_rejects_detached_ols_alias(monkeypatch):
    from app.services import numeric_history_bundle as service, numeric_model_bundle, numeric_history_features
    raw = history_bundle_fixture()
    raw['implementation_sha256'] = service.history_implementation_sha256(raw['legacy_bundle']['implementation_sha256'])
    monkeypatch.setattr(numeric_model_bundle, 'verify_numeric_bundle_runtime', lambda bundle: None)
    service.verify_numeric_history_runtime(raw)
    monkeypatch.setattr(numeric_history_features, '_ols_slope', lambda points: 0.)
    with pytest.raises(ValueError, match='loaded_code_mismatch'): service.verify_numeric_history_runtime(raw)


def test_evidence_direction_tracks_data_without_positive_score_gate():
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    raw = history_bundle_fixture()
    aggregate = raw['history_evidence']['aggregates'][0]
    aggregate['gain_direction'] = 'negative'
    aggregate['metrics']['mae_gain_reference_minus_candidate'].update(mean=-1., min=-1., max=-1.)
    raw['history_evidence']['comparisons'][0]['statistics'].update(mae=3., rmse=3., mae_gain_reference_minus_candidate=-1.)
    for name in ('mae', 'rmse'): aggregate['metrics'][name].update(mean=3., min=3., max=3.)
    assert NumericHistoryBundle.model_validate(raw).history_evidence.aggregates[0].gain_direction == 'negative'
    aggregate['gain_direction'] = 'positive'
    with pytest.raises(ValueError): NumericHistoryBundle.model_validate(raw)
    raw = history_bundle_fixture()
    aggregate = raw['history_evidence']['aggregates'][0]
    aggregate['gain_direction'] = 'mixed'
    aggregate['metrics']['mae_gain_reference_minus_candidate'].update(mean=0., min=-1., max=1.)
    assert NumericHistoryBundle.model_validate(raw).history_evidence.aggregates[0].gain_direction == 'mixed'


@pytest.mark.parametrize('mutation', ['negative_mae', 'negative_rmse', 'negative_reference_mae',
    'paired_out_of_range', 'all_out_of_range', 'dependency_groups', 'excluded_output',
    'aggregate_member', 'aggregate_mean', 'aggregate_count', 'aggregate_interior_mean'])
def test_evidence_rejects_impossible_statistics_counts_and_aggregate_members(mutation):
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    raw = history_bundle_fixture()
    row, aggregate = raw['history_evidence']['comparisons'][0], raw['history_evidence']['aggregates'][0]
    if mutation.startswith('negative_'): row['statistics'][mutation.removeprefix('negative_')] = -5.
    elif mutation == 'paired_out_of_range': row['counts']['N_candidate_out_of_range'] = 999
    elif mutation == 'all_out_of_range': row['counts']['N_all_reference_out_of_range'] = 999
    elif mutation == 'dependency_groups': row['counts']['N_dependency_groups'] = 999
    elif mutation == 'excluded_output': row['counts']['N_common_excluded_due_to_output'] = 999
    elif mutation == 'aggregate_member': aggregate['metrics']['mae'].update(min=50., mean=50., max=50.)
    elif mutation == 'aggregate_mean': aggregate['metrics']['mae'].update(min=1., mean=1.1, max=10.)
    elif mutation == 'aggregate_interior_mean': aggregate['metrics']['mae'].update(min=0., mean=1., max=10.)
    else: aggregate['counts']['N_pair_valid'].update(min=50., mean=50., max=50.)
    with pytest.raises(ValueError): NumericHistoryBundle.model_validate(raw)


@pytest.mark.parametrize('name', ['project_numeric_history_features', 'add_calendar_months', 'json_sha256'])
@pytest.mark.parametrize('mutation', ['replace', 'delete'])
def test_runtime_rejects_detached_inference_imports(monkeypatch, name, mutation):
    from app.services import numeric_history_bundle as service, numeric_model_bundle
    raw = history_bundle_fixture()
    raw['implementation_sha256'] = service.history_implementation_sha256(raw['legacy_bundle']['implementation_sha256'])
    monkeypatch.setattr(numeric_model_bundle, 'verify_numeric_bundle_runtime', lambda bundle: None)
    if mutation == 'replace': monkeypatch.setattr(service, name, lambda *args: None)
    else: monkeypatch.delattr(service, name)
    with pytest.raises(ValueError, match='loaded_code_mismatch'): service.verify_numeric_history_runtime(raw)


@pytest.mark.parametrize('metric', ['mae', 'rmse', 'reference_mae'])
def test_nonnegative_error_interval_bounds(metric):
    from app.schemas.numeric_history_bundle import NumericHistoryBundle
    raw = history_bundle_fixture()
    row = next(row for row in raw['history_evidence']['comparisons'] if row['evaluation_role'] == 'challenge')
    row['intervals'][metric].update(lower=-1., upper=2., width=3.)
    with pytest.raises(ValueError): NumericHistoryBundle.model_validate(raw)
