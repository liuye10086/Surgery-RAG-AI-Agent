from app.services.longitudinal_model_evaluation import (
    compute_binary_metrics,
    patient_bootstrap_ci,
    select_oof_f1_threshold,
)


def test_metrics_include_pr_auc_roc_auc_brier_and_threshold_metrics():
    metrics = compute_binary_metrics([0, 1, 0, 1], [0.1, 0.8, 0.2, 0.7], 0.5)
    assert metrics.pr_auc is not None
    assert metrics.roc_auc is not None
    assert metrics.brier_score is not None
    assert metrics.confusion_matrix == [[2, 0], [0, 2]]


def test_missing_class_marks_auc_unestimable():
    metrics = compute_binary_metrics([0, 0], [0.1, 0.2], 0.5)
    assert metrics.pr_auc is None
    assert metrics.roc_auc is None
    assert {"pr_auc", "roc_auc"}.issubset(metrics.unavailable_metrics)


def test_threshold_is_selected_from_oof_only():
    result = select_oof_f1_threshold([0, 1, 1, 0], [0.2, 0.55, 0.8, 0.4])
    assert result.method == "oof_f1"
    assert 0.0 < result.threshold < 1.0


def test_bootstrap_resamples_groups_not_rows():
    ci = patient_bootstrap_ci({"g1": [1, 0], "g2": [0, 0]}, {"g1": [0.8, 0.7], "g2": [0.1, 0.2]}, 0.5, seed=42, iterations=100)
    assert ci.unit == "group_id"
