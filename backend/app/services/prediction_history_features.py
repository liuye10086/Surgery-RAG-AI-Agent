"""History-value feature projection for the synthetic offline experiment."""

from datetime import date
import math

from app.schemas.synthetic_prediction_cases import PredictionInput
from app.services.prediction_calculation import project_calculation_inputs


def _ols_slope(points):
    x_mean = math.fsum(x for x, _ in points) / len(points)
    y_mean = math.fsum(y for _, y in points) / len(points)
    numerator = math.fsum((x - x_mean) * (y - y_mean) for x, y in points)
    denominator = math.fsum((x - x_mean) ** 2 for x, _ in points)
    slope = numerator / denominator
    if not math.isfinite(slope):
        raise ArithmeticError("nonfinite_history_slope")
    return slope


def project_history_features(packets: list[dict]) -> list[dict]:
    """Validate prediction inputs and add fixed longitudinal numeric features."""
    base_rows = project_calculation_inputs(packets)
    normalized = {
        packet["sample_id"]: packet
        for packet in (PredictionInput.model_validate(raw).model_dump(mode="json") for raw in packets)
    }
    result = []
    for base in base_rows:
        packet = normalized[base["sample_id"]]
        status, reason = "abstain", None
        prior_value = slope_per_day = None

        if base["input_status"] != "available":
            reason = "anchor_not_available"
        elif packet["history_coverage"] != "complete":
            reason = "history_coverage_incomplete"
        elif packet["history_state"] != "observed":
            reason = "history_not_observed"
        else:
            anchor_date = date.fromisoformat(packet["anchor_date"])
            anchor = next(
                observation for observation in packet["input_observations"]
                if observation["observation_id"] == packet["anchor_observation_id"]
            )
            history = sorted(
                (observation for observation in packet["input_observations"]
                 if observation["measured_on"] < packet["anchor_date"]),
                key=lambda observation: (observation["measured_on"], observation["observation_id"]),
            )
            if not history or base["span_pre_days"] <= 0:
                reason = "comparable_history_required"
            else:
                try:
                    points = [
                        ((date.fromisoformat(observation["measured_on"]) - anchor_date).days,
                         observation["value"])
                        for observation in history
                    ]
                    points.append((0, anchor["value"]))
                    slope_per_day = _ols_slope(points)
                    prior_value = history[-1]["value"]
                    status = "available"
                except (ArithmeticError, OverflowError, TypeError, ValueError):
                    status, reason = "error", "history_calculation_error"
                    prior_value = slope_per_day = None

        result.append({
            **base,
            "history_status": status,
            "history_reason": reason,
            "prior_value": prior_value,
            "slope_per_day": slope_per_day,
        })
    return result
