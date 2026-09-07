import json

from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_prediction import run_longitudinal_prediction


def test_ad_mmse_moca_signals_survive_without_outcome_model():
    visits = [
        {
            "visit_date": visit_date,
            "indicators": [
                {"name": "MMSE", "value": mmse, "unit": "分"},
                {"name": "MoCA", "value": moca, "unit": "分"},
            ],
        }
        for visit_date, mmse, moca in [
            ("2024-01-01", 28, 25),
            ("2024-06-01", 25, 22),
            ("2024-12-31", 22, 18),
        ]
    ]

    result = run_longitudinal_prediction(
        {"baseline_stage": "mci"}, visits, AD_ADAPTER, {}
    )

    names = {item.indicator for item in result.progression_signals.signals}
    assert {"mmse", "moca"}.issubset(names)
    assert all(
        item.used_by_outcome_model is False
        for item in result.progression_signals.signals
    )


def test_signal_provenance_and_limitations_do_not_leak_sensitive_values():
    visits = [
        {
            "visit_date": visit_date,
            "indicators": [{"name": "ALT", "value": value, "unit": "U/L"}],
        }
        for visit_date, value in [
            ("2024-01-01", 20),
            ("2024-06-01", 35),
            ("2024-12-31", 60),
        ]
    ]
    result = run_longitudinal_prediction(
        {"baseline_stage": None}, visits, FATTY_LIVER_ADAPTER, {}
    )
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)

    for secret in (
        "postgresql://",
        "password",
        "Traceback",
        "C:\\Users\\",
        "P001",
    ):
        assert secret not in serialized
