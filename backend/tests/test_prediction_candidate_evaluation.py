import copy

import pytest


TASK = 'ad.mmse.6m'
FAMILIES = ('ridge', 'random_forest')
BRANCHES = ('main_anchor', 'd03_anchor', 'd03_augmented')


def example(pool='development_pool'):
    samples, predictions, baselines = [], [], []
    for i, (actual, last, anchor, augmented) in enumerate(((10., 8., 9., 10.), (20., 17., 18., 19.))):
        sid = f's{i}'
        samples.append(dict(sample_id=sid, subject_id=sid, dependency_group_id=f'g{i}', task_id=TASK,
                            pool=pool, anchor_status='eligible', label_status='valid', actual=actual,
                            n_pre=i, span_pre_days=30*i, anchor_value=last))
        for family in FAMILIES:
            for branch in BRANCHES:
                value = augmented if branch == 'd03_augmented' else anchor
                predictions.append(dict(sample_id=sid, task_id=TASK, model_id=f'{family}:{branch}',
                                        status='valid', value=value, reason=None))
        baselines.append(dict(sample_id=sid, model_id='last_value', status='valid', value=last, reason=None))
    return samples, predictions, baselines


def evaluate(*args):
    from app.services.prediction_candidate_evaluation import evaluate_candidates
    return evaluate_candidates(*args)


def row(result, kind='vs_last', branch='d03_augmented', pool='development_pool'):
    return next(c for c in result['evaluation']['comparisons'] if c['task_id'] == TASK and
                c['family'] == 'ridge' and c['comparison_kind'] == kind and c['branch'] == branch and c['pool'] == pool)


def test_literal_last_value_gain_and_d03_flow_gain_are_distinct():
    result = evaluate(*example())
    main, flow = row(result), row(result, 'd03_flow')
    assert main['statistics']['mae_gain_vs_last'] == 2.0
    assert main['statistics']['mae'] == .5
    assert flow['statistics']['flow_mae_gain'] == 1.0
    assert flow['statistics']['reference_mae'] == 1.5
    assert flow['reference_model_id'] == 'ridge:d03_anchor'
    assert 'mae_gain_vs_last' not in flow['statistics']
    assert main['performance']['status'] == flow['performance']['status'] == 'not_assessable'
    assert len(result['evaluation']['comparisons']) == 64


def test_missing_target_does_not_hide_failed_required_output():
    samples, predictions, baseline = example()
    samples[1]['label_status'], samples[1]['actual'] = 'absent', None
    predictions = [p for p in predictions if not(p['sample_id'] == 's1' and p['model_id'] == 'ridge:d03_augmented')]
    c = row(evaluate(samples, predictions, baseline))
    assert c['counts']['N_branch_eligible'] == 2
    assert c['counts']['N_label_valid'] == c['counts']['N_label_absent'] == 1
    assert c['counts']['N_all_pred_error'] == 1
    assert not c['complete_output']
    assert c['counts']['N_pair_valid'] == 1
    assert 'incomplete_output' in c['performance']['known_failures']


def test_unknown_history_excluded_zero_retained_without_moving_anchor():
    samples, predictions, baseline = example()
    samples[1]['n_pre'], samples[1]['span_pre_days'] = None, None
    for p in predictions:
        if p['sample_id'] == 's1' and ':d03_' in p['model_id']:
            p.update(status='abstain', value=None, reason='history_unknown')
    c = row(evaluate(samples, predictions, baseline))
    assert c['counts']['N_branch_eligible'] == 1
    assert c['counts']['N_branch_not_applicable'] == 1
    assert c['counts']['N_all_pred_abstain'] == 1
    assert c['complete_output']


def test_missing_d03_reference_retains_joint_state_and_negative_gain():
    samples, predictions, baseline = example()
    for p in predictions:
        if p['model_id'] == 'ridge:d03_augmented': p['value'] = 100.
    predictions = [p for p in predictions if not(p['sample_id'] == 's1' and p['model_id'] == 'ridge:d03_anchor')]
    c = row(evaluate(samples, predictions, baseline), 'd03_flow')
    assert c['joint_states']['baseline_unavailable'] == 1
    assert c['statistics']['flow_mae_gain'] == -89.
    assert not c['complete_output']
    assert c['counts']['N_all_reference_error'] == 1


def test_nonfinite_valid_output_is_error_finite_extreme_is_retained():
    samples, predictions, baseline = example()
    for p in predictions:
        if p['model_id'] == 'ridge:d03_augmented': p['value'] = float('nan') if p['sample_id'] == 's0' else -999.
    c = row(evaluate(samples, predictions, baseline))
    assert c['counts']['N_pred_error'] == 1
    assert c['statistics']['mae'] == 1019.


def test_zero_denominators_remain_null_and_state_partitions_close():
    result = evaluate([], [], [])
    for c in result['evaluation']['comparisons']:
        assert c['coverage']['paired']['value'] is None
        assert c['counts']['N_patient'] == 0
        assert c['statistics']['n_patients'] == 0
        assert sum(c['joint_states'].values()) == 0


@pytest.mark.parametrize('mutation', ['duplicate_sample', 'duplicate_subject', 'foreign_prediction', 'wrong_task', 'cross_pool_group'])
def test_invalid_analysis_identity_rejected(mutation):
    samples, predictions, baseline = example()
    if mutation == 'duplicate_sample': samples.append(copy.deepcopy(samples[0]))
    elif mutation == 'duplicate_subject': samples[1]['subject_id'] = samples[0]['subject_id']
    elif mutation == 'foreign_prediction': predictions[0]['sample_id'] = 'foreign'
    elif mutation == 'wrong_task': predictions[0]['task_id'] = 'fatty_liver.alt.6m'
    else:
        samples[1]['pool'] = 'challenge_pool'
        samples[1]['dependency_group_id'] = samples[0]['dependency_group_id']
    with pytest.raises(ValueError): evaluate(samples, predictions, baseline)


def test_real_bootstrap_uses_same_flow_draws_and_renamed_intervals():
    result = evaluate(*example('challenge_pool'))
    c = row(result, 'd03_flow', pool='challenge_pool')
    interval = c['intervals']['flow_mae_gain']
    assert interval['attempted'] == interval['valid'] == 2000
    assert interval['lower'] == interval['upper'] == 1.
    plan = result['bootstrap_plans'][c['comparison_id']]
    assert plan['ordered_groups'] == ['g0', 'g1']
    assert len(plan['draw_indices']) == 2000
    assert all(len(draw) == 2 for draw in plan['draw_indices'])


def test_flow_remains_patient_weighted_with_unequal_dependency_groups():
    samples, predictions, baseline = example('challenge_pool')
    samples.append({**samples[1], 'sample_id': 's2', 'subject_id': 's2', 'anchor_value': 24.})
    for p in list(predictions):
        if p['sample_id'] == 's1':
            predictions.append({**p, 'sample_id': 's2', 'value': 23. if p['model_id'].endswith('d03_augmented') else 22.})
    baseline.append({**baseline[1], 'sample_id': 's2', 'value': 24.})
    result = evaluate(samples, predictions, baseline)
    flow = row(result, 'd03_flow', pool='challenge_pool')
    assert flow['statistics']['flow_mae_gain'] == pytest.approx(1/3)
    assert flow['statistics']['n_patients'] == 3
    assert flow['statistics']['n_groups'] == 2
    assert flow['intervals']['flow_mae_gain']['lower'] == 0.
    assert flow['intervals']['flow_mae_gain']['upper'] == 1.
    assert row(result, pool='challenge_pool')['statistics']['mae_gain_vs_last'] == pytest.approx(5/3)


def test_failed_bootstrap_metric_is_not_replaced_or_redrawn():
    samples, predictions, baseline = example('challenge_pool')
    for p in predictions:
        if p['model_id'] == 'ridge:d03_augmented': p['value'] = -1e200
    c = row(evaluate(samples, predictions, baseline), 'd03_flow', pool='challenge_pool')
    interval = c['intervals']['rmse']
    assert interval['status'] == 'not_estimable'
    assert interval['attempted'] == interval['failed'] == 2000
    assert interval['valid'] == 0 and interval['lower'] is None
    assert c['statistics']['mae'] == 1e200
