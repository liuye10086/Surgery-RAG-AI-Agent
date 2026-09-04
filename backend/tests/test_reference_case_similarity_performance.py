"""CPU reranking budget after PostgreSQL narrows a 10k pool to 500 rows."""

from datetime import date
from statistics import quantiles
from time import perf_counter

import pytest

from app.schemas.longitudinal_evidence import (
    ReferenceCaseFeatureProfile,
    ReferenceCaseProfile,
    ReferenceCaseScoreBreakdown,
)
from app.services.reference_case_similarity import MAX_CANDIDATES, rank_reference_cases


@pytest.mark.performance
def test_reference_similarity_ten_thousand_window_rerank_p95_budget():
    current = ReferenceCaseFeatureProfile(
        baseline_stage="pre_cirrhosis",
        prediction_task="fatty_liver.pre_cirrhosis_to_progression",
        age=60, sex="female", as_of=date(2025, 1, 1), visit_count=4,
        observation_span_days=365,
        feature_summary={
            "indicators": {
                "alt": {"last": 20, "unit": "U/L", "time_slope_per_day": 0.01},
                "ast": {"last": 22, "unit": "U/L", "time_slope_per_day": 0.01},
            }
        },
        measurement_context_summary={},
    )
    empty_score = ReferenceCaseScoreBreakdown(
        conditional_similarity=0, coverage=0, ranking_score=0, available_weight=0,
    )
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    candidates = [
        ReferenceCaseProfile(
            anonymous_case_code=(
                "CASE-" + "".join(alphabet[(index // (32 ** power)) % 32] for power in range(4))
                + "-" + "".join(alphabet[((index + 997) // (32 ** power)) % 32] for power in range(4))
            ),
            features=current, score=empty_score, outcome_status="positive",
            outcome_source="explicit_cirrhosis", outcome_reliability="high",
        )
        for index in range(MAX_CANDIDATES)
    ]
    durations = []
    for _ in range(20):  # 20 × 500 = 10,000 scored windows.
        started = perf_counter()
        selection = rank_reference_cases(current, candidates)
        durations.append(perf_counter() - started)
        assert len(selection.cases) == 5

    p95_seconds = quantiles(durations, n=100, method="inclusive")[94]
    assert MAX_CANDIDATES == 500
    assert p95_seconds < 1.0
