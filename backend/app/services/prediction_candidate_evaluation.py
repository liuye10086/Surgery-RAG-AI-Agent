"""Fixed synthetic candidates and explicitly separate D03 paired comparisons."""

from collections import Counter
import math

from app.services.prediction_calculation import TASKS, POOLS, THRESHOLDS
from app.services.prediction_calculation_metrics import paired_statistics, paired_bootstrap, performance_decision


MISSING = {'status': 'error', 'value': None, 'reason': 'prediction_record_missing'}
STATES = ('valid', 'abstain', 'error')
JOINT_STATES = ('both_valid', 'candidate_unavailable', 'baseline_unavailable', 'both_unavailable')


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _ratio(numerator, denominator):
    return {'value': numerator / denominator if denominator else None, 'numerator': numerator,
            'denominator': denominator, 'reason': None if denominator else 'zero_denominator'}


def _samples_index(samples):
    result, subjects, groups, identities = {}, {}, {}, set()
    for row in samples:
        sid, subject, group = row['sample_id'], row['subject_id'], row['dependency_group_id']
        task, pool = row['task_id'], row['pool']
        if (sid in result or (subject, task) in identities or task not in TASKS or pool not in POOLS
                or row['anchor_status'] not in {'eligible', 'ineligible', 'pending'}
                or row['label_status'] not in {'valid', 'absent', 'pending', 'not_applicable'}):
            raise ValueError('invalid_analysis_identity')
        if ((subject in subjects and subjects[subject] != (group, pool))
                or (group in groups and groups[group] != pool)):
            raise ValueError('dependency_crosses_pools')
        if row['label_status'] == 'valid' and not _finite(row['actual']):
            raise ValueError('invalid_analysis_target')
        identities.add((subject, task))
        subjects[subject], groups[group], result[sid] = (group, pool), pool, row
    return result


def _prediction_index(predictions, samples, allowed):
    indexed = {}
    for row in predictions:
        sid, model_id = row['sample_id'], row['model_id']
        key = (sid, model_id)
        if (key in indexed or sid not in samples or model_id not in allowed
                or row.get('task_id', samples[sid]['task_id']) != samples[sid]['task_id']):
            raise ValueError('invalid_prediction_identity')
        if row['status'] not in STATES:
            raise ValueError('invalid_prediction_status')
        if row['status'] == 'valid' and not _finite(row['value']):
            row = {**row, 'status': 'error', 'value': None, 'reason': 'nonfinite_prediction'}
        indexed[key] = row
    return indexed


def _joint(candidate, reference):
    a, b = candidate['status'] == 'valid', reference['status'] == 'valid'
    return 'both_valid' if a and b else ('candidate_unavailable' if b else
                                      ('baseline_unavailable' if a else 'both_unavailable'))


def _renamed(values, flow):
    names = {'baseline_mae': 'reference_mae' if flow else 'last_value_mae',
             'mae_gain': 'flow_mae_gain' if flow else 'mae_gain_vs_last'}
    renamed = {names.get(k, k): v for k, v in values.items()}
    if 'unavailable' in renamed:
        renamed['unavailable'] = [names.get(x.split(':', 1)[0], x.split(':', 1)[0]) +
                                  (':' + x.split(':', 1)[1] if ':' in x else '') for x in renamed['unavailable']]
    return renamed


def evaluate_candidates(samples, predictions, baseline_predictions):
    """Keep all denominators and never substitute flow gain for gain vs last value."""
    from app.services.prediction_candidate_training import FAMILIES, BRANCH_FEATURES, candidate_model_id

    smap = _samples_index(samples)
    allowed = {candidate_model_id(family, branch) for family in FAMILIES for branch in BRANCH_FEATURES}
    pmap = _prediction_index(predictions, smap, allowed)
    bmap = _prediction_index(baseline_predictions, smap, {'last_value', 'history_trend'})
    comparisons, paired_rows, plans = [], [], {}
    for task in TASKS:
        for pool in POOLS:
            selected = sorted((s for s in samples if s['task_id'] == task and s['pool'] == pool), key=lambda s: s['sample_id'])
            eligible = [s for s in selected if s['anchor_status'] == 'eligible']
            d03 = [s for s in eligible if s['n_pre'] is not None and s['span_pre_days'] is not None]
            for family in FAMILIES:
                specs = [('vs_last', branch, 'last_value') for branch in BRANCH_FEATURES]
                specs.append(('d03_flow', 'd03_augmented', candidate_model_id(family, 'd03_anchor')))
                for kind, branch, reference_id in specs:
                    flow = kind == 'd03_flow'
                    model_id = candidate_model_id(family, branch)
                    key = f'{task}:{pool}:{family}:{branch}:{kind}'
                    branch_rows = eligible if branch == 'main_anchor' else d03
                    valid = [s for s in branch_rows if s['label_status'] == 'valid']
                    references = pmap if flow else bmap
                    output = lambda s: pmap.get((s['sample_id'], model_id), MISSING)
                    reference = lambda s: references.get((s['sample_id'], reference_id), MISSING)
                    all_counts = Counter(output(s)['status'] for s in selected)
                    reference_counts = Counter(reference(s)['status'] for s in selected)
                    complete = (all((s['sample_id'], model_id) in pmap and
                                    (s['sample_id'], reference_id) in references for s in selected)
                                and all(output(s)['status'] == reference(s)['status'] == 'valid' for s in branch_rows)
                                and not all_counts['error'] and not reference_counts['error'])
                    joint, counts, pairs = Counter(), Counter(), []
                    for s in valid:
                        p, r = output(s), reference(s)
                        counts[p['status']] += 1
                        state = _joint(p, r)
                        joint[state] += 1
                        if state == 'both_valid':
                            values = {'subject_id': s['subject_id'], 'dependency_group_id': s['dependency_group_id'],
                                      'actual': s['actual'], 'prediction': p['value'], 'baseline': r['value']}
                            pairs.append(values)
                            paired_rows.append({k: v for k, v in values.items() if k != 'baseline'} |
                                               {'comparison_id': key, 'sample_id': s['sample_id'], 'reference': r['value'],
                                                'reference_model_id': reference_id, 'last_value': bmap.get(
                                                    (s['sample_id'], 'last_value'), MISSING)['value']})
                    stats = paired_statistics(pairs)
                    intervals = {}
                    if pool == 'challenge_pool':
                        boot = paired_bootstrap(pairs)
                        intervals = boot['intervals']
                        plans[key] = {k: v for k, v in boot.items() if k != 'intervals'}
                    totals = {'N_patient': len(selected), 'N_anchor_eligible': len(eligible),
                              'N_anchor_ineligible': sum(s['anchor_status'] == 'ineligible' for s in selected),
                              'N_anchor_pending': sum(s['anchor_status'] == 'pending' for s in selected),
                              'N_branch_eligible': len(branch_rows), 'N_branch_not_applicable': len(eligible)-len(branch_rows),
                              'N_label_valid': len(valid),
                              'N_label_absent': sum(s['label_status'] == 'absent' for s in branch_rows),
                              'N_label_pending': sum(s['label_status'] == 'pending' for s in branch_rows),
                              'N_pair_valid': len(pairs), 'N_d03_eligible': len(d03),
                              'N_d03_unknown_history': len(eligible)-len(d03),
                              'N_dependency_groups': len({s['dependency_group_id'] for s in selected})}
                    for state in STATES:
                        totals['N_pred_' + state] = counts[state]
                        totals['N_all_pred_' + state] = all_counts[state]
                        totals['N_all_reference_' + state] = reference_counts[state]
                    performance = ({'status': 'not_assessable',
                                    'missing': ['prerequisites', 'clinical_flow_criterion_not_defined'],
                                    'known_failures': [] if complete else ['incomplete_output']} if flow else
                                   performance_decision(stats, intervals, THRESHOLDS,
                                                        prerequisites=False, complete_output=complete))
                    comparisons.append({'comparison_id': key, 'task_id': task, 'pool': pool, 'family': family,
                        'branch': branch, 'comparison_kind': kind, 'model_id': model_id, 'reference_model_id': reference_id,
                        'counts': totals, 'joint_states': {k: joint[k] for k in JOINT_STATES},
                        'coverage': {'label_support': _ratio(len(valid), len(branch_rows)),
                                     'output': _ratio(counts['valid'], len(valid)), 'paired': _ratio(len(pairs), len(valid)),
                                     'end_to_end': _ratio(len(pairs), len(branch_rows))},
                        'complete_output': bool(complete), 'statistics': _renamed(stats, flow),
                        'intervals': _renamed(intervals, flow), 'performance': performance,
                        'thresholds': None if flow else dict(THRESHOLDS),
                        'uncertainty_scope': 'synthetic_fixed_challenge' if pool == 'challenge_pool' else 'training_descriptive_only'})
    return {'evaluation': {'schema_version': 'synthetic_prediction_candidates.v1', 'clinical_validity_claim': False,
                           'clinical_status': 'not_assessable', 'comparisons': comparisons,
                           'candidate_model_training': 'executed', 'd03_model_comparison': 'executed'},
            'paired_rows': paired_rows, 'bootstrap_plans': plans}
