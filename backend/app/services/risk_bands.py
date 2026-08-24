"""Shared risk-band thresholds used by longitudinal prediction only."""

_BANDS = [
    (0.8, "极高", [80, 95]),
    (0.6, "高", [60, 80]),
    (0.4, "中等", [40, 60]),
    (0.2, "低", [20, 40]),
    (0.0, "极低", [0, 20]),
]
