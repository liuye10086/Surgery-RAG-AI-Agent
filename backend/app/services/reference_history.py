"""Reference comparison needs units; model feature vectors remain unchanged."""

from app.services.longitudinal_features import (
    summarize_fixed_window_history,
    summarize_observation,
)


def summarize_reference_history(visits):
    rows = list(visits)
    summary = summarize_fixed_window_history(rows)
    observed = summarize_observation(rows)["indicators"]
    for name, features in summary["indicators"].items():
        record = observed.get(name, {})
        features["unit"] = record.get("unit")
        features["unit_state"] = record.get("unit_state", "missing")
    return summary
