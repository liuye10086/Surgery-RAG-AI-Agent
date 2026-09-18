from datetime import date

import pytest

from test_numeric_prediction import numeric_fixture


def test_confirmed_no_history_abstains_without_zero_fill():
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][1]
    packet['input_observations'] = packet['input_observations'][1:]
    packet.update(history_state='confirmed_none', history_coverage='complete')
    result = project_numeric_history_features(packet)
    assert (result.eligible, result.status, result.reason) == (False, 'abstain', 'history_not_observed')
    assert result.prior_value is None and result.slope_per_day is None
    assert (result.n_pre, result.span_pre_days) == (0, 0)


def test_sorted_actual_day_projection():
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][1]
    packet['input_observations'].reverse()
    result = project_numeric_history_features(packet)
    days = (date(2023, 8, 31) - date(2023, 1, 1)).days
    assert (result.eligible, result.status, result.reason) == (True, 'available', None)
    assert (result.anchor_value, result.prior_value, result.n_pre, result.span_pre_days) == (22, 24, 1, days)
    assert result.slope_per_day == -2 / days


@pytest.mark.parametrize('reason', ['anchor_unavailable', 'population_not_confirmed',
                                    'population_not_known_at_anchor', 'conflicting_history'])
def test_input_reason_is_preserved(reason):
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][1]
    packet.update(input_status='unavailable', input_reason=reason)
    if reason == 'anchor_unavailable':
        packet['anchor_observation_id'] = None
        packet['input_observations'] = packet['input_observations'][:1]
    if reason == 'conflicting_history':
        packet.update(history_state='unknown', input_observations=packet['input_observations'][1:])
    result = project_numeric_history_features(packet)
    assert (result.eligible, result.status, result.reason) == (False, 'abstain', reason)


def test_ols_overflow_retains_eligibility():
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture('fatty_liver')['packets'][1]
    for row in packet['input_observations']:
        row['value'] = 1.7e308
    result = project_numeric_history_features(packet)
    assert (result.eligible, result.status, result.reason) == (True, 'error', 'history_calculation_error')
    assert result.prior_value is None and result.slope_per_day is None


@pytest.mark.parametrize('mutation', ['future', 'unit', 'method', 'extra', 'nan'])
def test_invalid_packet_rejected(mutation):
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][1]
    row = packet['input_observations'][0]
    if mutation == 'future': row['known_on'] = '2099-01-01'
    elif mutation == 'unit': row['unit'] = 'U/L'
    elif mutation == 'method': row['method'] = 'other'
    elif mutation == 'extra': packet['outcome'] = 2
    else: row['value'] = float('nan')
    with pytest.raises(ValueError):
        project_numeric_history_features(packet)


@pytest.mark.parametrize('coverage,reason', [('unknown', 'history_coverage_incomplete'), ('complete', 'history_not_observed')])
def test_unknown_history_does_not_become_zero_history(coverage, reason):
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][0]
    packet.update(history_state='unknown', history_coverage=coverage)
    packet['input_observations'] = packet['input_observations'][1:]
    result = project_numeric_history_features(packet)
    assert (result.eligible, result.status, result.reason) == (False, 'abstain', reason)
    assert result.n_pre is None and result.span_pre_days is None


def test_unavailable_population_preserves_observed_anchor_feature():
    from app.services.numeric_history_features import project_numeric_history_features
    packet = numeric_fixture()['packets'][0]
    packet.update(input_status='unavailable', input_reason='population_not_confirmed')
    result = project_numeric_history_features(packet)
    assert result.anchor_value == 22.
    assert result.status == 'abstain' and not result.eligible
