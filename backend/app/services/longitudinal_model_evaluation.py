"""Audited binary evaluation helpers for P0-04."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from app.schemas.longitudinal_model_training import BinaryMetrics
from app.schemas.longitudinal_model_suite import MulticlassMetrics


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    method: str


@dataclass(frozen=True)
class ConfidenceInterval:
    unit: str
    lower: float | None
    upper: float | None
    unstable: bool


def compute_binary_metrics(labels: Sequence[int], probabilities: Sequence[float], threshold: float) -> BinaryMetrics:
    y = np.asarray(labels, dtype=int)
    p = np.asarray(probabilities, dtype=float)
    predicted = (p >= threshold).astype(int)
    unavailable: list[str] = []
    pr_auc = float(average_precision_score(y, p)) if len(set(y)) == 2 else None
    roc_auc = float(roc_auc_score(y, p)) if len(set(y)) == 2 else None
    if pr_auc is None:
        unavailable.extend(["pr_auc", "roc_auc"])
    matrix = confusion_matrix(y, predicted, labels=[0, 1]).tolist()
    tn, fp, fn, tp = matrix[0][0], matrix[0][1], matrix[1][0], matrix[1][1]
    return BinaryMetrics(
        pr_auc=pr_auc,
        roc_auc=roc_auc,
        brier_score=float(brier_score_loss(y, p)) if len(y) else None,
        sensitivity=float(recall_score(y, predicted, zero_division=0)) if tp + fn else None,
        specificity=float(tn / (tn + fp)) if tn + fp else None,
        ppv=float(precision_score(y, predicted, zero_division=0)) if tp + fp else None,
        npv=float(tn / (tn + fn)) if tn + fn else None,
        f1=float(f1_score(y, predicted, zero_division=0)) if len(y) else None,
        confusion_matrix=matrix,
        unavailable_metrics=unavailable,
    )


def select_oof_f1_threshold(labels: Sequence[int], probabilities: Sequence[float]) -> ThresholdResult:
    candidates = sorted({0.5, *[float(value) for value in probabilities]})
    best = max(candidates, key=lambda threshold: (f1_score(labels, np.asarray(probabilities) >= threshold, zero_division=0), -threshold))
    return ThresholdResult(threshold=float(best), method="oof_f1")


def patient_bootstrap_ci(labels_by_group: Mapping[str, Sequence[int]], probabilities_by_group: Mapping[str, Sequence[float]], threshold: float, *, seed: int, iterations: int) -> ConfidenceInterval:
    groups = sorted(set(labels_by_group) & set(probabilities_by_group))
    if len(groups) < 2:
        return ConfidenceInterval("group_id", None, None, True)
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(iterations):
        chosen = rng.choice(groups, size=len(groups), replace=True)
        labels = [item for group in chosen for item in labels_by_group[group]]
        probabilities = [item for group in chosen for item in probabilities_by_group[group]]
        values.append(compute_binary_metrics(labels, probabilities, threshold).f1 or 0.0)
    lower, upper = np.percentile(values, [2.5, 97.5]).tolist()
    return ConfidenceInterval("group_id", float(lower), float(upper), False)


def compute_multiclass_metrics(
    labels: Sequence[str],
    predictions: Sequence[str],
    class_order: Sequence[str],
) -> MulticlassMetrics:
    fixed_order = list(class_order)
    if not fixed_order or len(fixed_order) != len(set(fixed_order)):
        raise ValueError("class_order_invalid")
    if len(labels) != len(predictions):
        raise ValueError("label_prediction_length_mismatch")
    allowed = set(fixed_order)
    if any(value not in allowed for value in labels) or any(
        value not in allowed for value in predictions
    ):
        raise ValueError("unknown_class")
    support = {name: sum(value == name for value in labels) for name in fixed_order}
    unavailable: list[str] = []
    if not labels:
        macro_f1 = None
        balanced = None
        unavailable.extend(["macro_f1", "balanced_accuracy"])
    else:
        macro_f1 = float(
            f1_score(
                labels,
                predictions,
                labels=fixed_order,
                average="macro",
                zero_division=0,
            )
        )
        present_classes = {value for value in labels}
        if len(present_classes) < 2:
            balanced = None
            unavailable.append("balanced_accuracy")
        else:
            balanced = float(balanced_accuracy_score(labels, predictions))
    return MulticlassMetrics(
        class_order=fixed_order,
        class_support=support,
        macro_f1=macro_f1,
        balanced_accuracy=balanced,
        confusion_matrix=confusion_matrix(
            labels,
            predictions,
            labels=fixed_order,
        ).tolist(),
        unavailable_metrics=unavailable,
    )
