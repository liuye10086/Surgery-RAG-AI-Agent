import math
import time

import pytest

from app.schemas.longitudinal_evidence import ReferenceCaseFeatureProfile
from app.services.reference_case_similarity import score_reference_case


@pytest.mark.performance
def test_reference_similarity_ten_thousand_windows_budget():
    current = ReferenceCaseFeatureProfile(
        baseline_stage="mci", prediction_task="progression", age=60, sex="female",
        as_of="2025-01-01", visit_count=3, observation_span_days=100,
        feature_summary={"indicators": {"alt": {"last": 20, "time_slope_per_day": 0.1}}},
        measurement_context_summary={"values": {"assay_platform": ["A"]}},
    )
    candidate = current.model_copy()
    samples = []
    for _ in range(10_000):
        samples.append(score_reference_case(current, candidate))
    assert len(samples) == 10_000
    assert math.isfinite(samples[-1].ranking_score)

