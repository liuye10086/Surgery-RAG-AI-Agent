import pytest

from app.services.longitudinal_model_audit import (
    LeakageBlockedError,
    assert_audit_allows_training,
    review_scores,
    run_input_leakage_audit,
)
from app.services.longitudinal_model_training import TrainingRow
from app.schemas.longitudinal_model_training import EvaluationSummary, LeakageAudit


def _row(group: str) -> TrainingRow:
    from backend.tests.test_longitudinal_model_training import _sample
    return TrainingRow(_sample(label=1, group=group), {"age": 60, "sex": "female"})


def _split(**overrides):
    from app.schemas.longitudinal_model_training import GroupSplit
    payload = dict(development_groups=["patient.v1." + "a" * 64], locked_test_groups=["patient.v1." + "b" * 64], development_indices=[0], locked_test_indices=[1], seed=42, test_fraction=0.2, group_overlap_check="passed")
    payload.update(overrides)
    return GroupSplit(**payload)


def test_group_overlap_blocks_training():
    split = _split(locked_test_groups=["patient.v1." + "a" * 64], group_overlap_check="failed")
    audit = run_input_leakage_audit([_row("a")], split)
    assert audit.group_overlap is True
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_forbidden_feature_blocks_training():
    row = _row("a")
    bad = TrainingRow(row.sample, {"final_stage": "hcc"})
    audit = run_input_leakage_audit([bad], _split())
    assert "final_stage" in audit.forbidden_feature_hits
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_abnormal_auc_sets_review_required():
    metrics = EvaluationSummary(split_method="StratifiedGroupKFold", requested_fold_count=5, aggregate={"roc_auc": 0.99, "pr_auc": 0.99})
    audit = review_scores(metrics, LeakageAudit())
    assert audit.leakage_review_required is True
    assert audit.high_score_warning is True


def test_test_selection_or_synthetic_usage_blocks_training():
    audit = LeakageAudit(test_used_for_selection=True, synthetic_in_formal_metrics=True)
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_cross_task_split_mismatch_blocks_training():
    audit = LeakageAudit(cross_task_split_mismatch=True, status="blocked")
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_source_family_crosses_partitions_blocks_training():
    audit = LeakageAudit(source_family_overlap=True, status="blocked")
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)
