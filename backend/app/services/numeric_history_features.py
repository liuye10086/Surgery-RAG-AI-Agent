"""Source-neutral history eligibility and actual-day OLS projection, without I/O."""

from app.schemas.numeric_prediction import NumericInputPacket
from app.schemas.numeric_history_prediction import HistoryFeatureResult
from app.services.prediction_history_features import _ols_slope


def project_numeric_history_features(packet: NumericInputPacket) -> HistoryFeatureResult:
    packet = NumericInputPacket.model_validate(packet.model_dump(mode='python') if hasattr(packet, 'model_dump') else packet)
    anchor = next((r for r in packet.input_observations if r.observation_id == packet.anchor_observation_id), None)
    prior = sorted((r for r in packet.input_observations if r.measured_on < packet.anchor_date),
                   key=lambda r: (r.measured_on, r.observation_id))
    known = packet.history_coverage == 'complete' and packet.history_state in ('observed', 'confirmed_none')
    n_pre = len(prior) if known else None
    span = (packet.anchor_date - prior[0].measured_on).days if known and prior else (0 if known else None)
    eligible, status, reason = False, 'abstain', None
    prior_value = slope = None
    anchor_value = anchor.value if anchor is not None else None
    if packet.input_status != 'available':
        reason = packet.input_reason
    elif packet.history_coverage != 'complete':
        reason = 'history_coverage_incomplete'
    elif packet.history_state != 'observed':
        reason = 'history_not_observed'
    elif not prior or not span:
        reason = 'comparable_history_required'
    else:
        eligible = True
        try:
            points = [((r.measured_on - packet.anchor_date).days, r.value) for r in prior]
            slope = _ols_slope(points + [(0, anchor_value)])
            prior_value, status = prior[-1].value, 'available'
        except (ArithmeticError, TypeError, ValueError):
            status, reason = 'error', 'history_calculation_error'
    return HistoryFeatureResult(eligible=eligible, status=status, reason=reason, anchor_value=anchor_value,
                                prior_value=prior_value, slope_per_day=slope, n_pre=n_pre, span_pre_days=span)
