"""Leakage and abnormal-score audits for P0-04."""
from __future__ import annotations

from typing import Sequence

from app.schemas.longitudinal_model_training import EvaluationSummary, LeakageAudit, GroupSplit
from app.services.longitudinal_model_training import TrainingRow, _FORBIDDEN


class LeakageBlockedError(ValueError):
    """A hard P0-04 leakage violation."""


def run_input_leakage_audit(rows: Sequence[TrainingRow], split: GroupSplit) -> LeakageAudit:
    development = set(split.development_groups)
    locked = set(split.locked_test_groups)
    overlap = bool(development & locked) or split.group_overlap_check != "passed"
    duplicate_rows = len(rows) - len({(row.sample.identity.group_id, row.sample.identity.as_of) for row in rows})
    hits = sorted({key for row in rows for key in row.values if key.lower() in _FORBIDDEN or any(token in key.lower() for token in ("future", "event_dates", "final_stage", "confirmed"))})
    synthetic = any(row.sample.identity.is_synthetic for row in rows)
    blocked = overlap or duplicate_rows > 0 or bool(hits) or synthetic
    return LeakageAudit(group_overlap=overlap, forbidden_feature_hits=hits, duplicate_rows=duplicate_rows, synthetic_in_formal_metrics=synthetic, status="blocked" if blocked else "passed", leakage_review_required=False)


def review_scores(metrics: EvaluationSummary, audit: LeakageAudit) -> LeakageAudit:
    aggregate = metrics.aggregate or {}
    high = any(isinstance(aggregate.get(key), (float, int)) and aggregate[key] >= 0.95 for key in ("roc_auc", "pr_auc"))
    return audit.model_copy(update={"high_score_warning": high, "leakage_review_required": high or audit.leakage_review_required, "status": "review_required" if high and audit.status == "passed" else audit.status})


def assert_audit_allows_training(audit: LeakageAudit) -> None:
    if audit.status == "blocked" or audit.group_overlap or audit.duplicate_rows or audit.forbidden_feature_hits or audit.test_used_for_selection or audit.synthetic_in_formal_metrics:
        raise LeakageBlockedError("leakage_audit_blocked")
