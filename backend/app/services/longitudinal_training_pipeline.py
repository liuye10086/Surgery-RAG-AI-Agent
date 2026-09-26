"""Shared sklearn candidate construction for stage and trend training."""

from __future__ import annotations

from typing import Sequence

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def _preprocessor(
    numeric_features: Sequence[str],
    categorical_features: Sequence[str],
    *,
    scale_numeric: bool,
):
    numeric_steps = [
        (
            "imputer",
            SimpleImputer(
                strategy="median",
                add_indicator=True,
                keep_empty_features=True,
            ),
        )
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))
    transformers = []
    if numeric_features:
        transformers.append(
            (
                "numeric",
                Pipeline(numeric_steps),
                list(numeric_features),
            )
        )
    if categorical_features:
        transformers.append(
            (
                "categorical",
                Pipeline(
                    [
                        (
                            "imputer",
                            SimpleImputer(strategy="most_frequent"),
                        ),
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                list(categorical_features),
            )
        )
    return ColumnTransformer(transformers, remainder="drop")


def build_training_candidates(
    numeric_features: Sequence[str], categorical_features: Sequence[str], seed: int
):
    return {
        "multinomial_logistic_regression": Pipeline(
            [
                (
                    "preprocess",
                    _preprocessor(
                        numeric_features, categorical_features, scale_numeric=True
                    ),
                ),
                (
                    "classifier",
                    LogisticRegression(
                        max_iter=3000,
                        class_weight="balanced",
                        random_state=seed,
                    ),
                ),
            ]
        ),
        "random_forest": Pipeline(
            [
                (
                    "preprocess",
                    _preprocessor(
                        numeric_features, categorical_features, scale_numeric=False
                    ),
                ),
                (
                    "classifier",
                    RandomForestClassifier(
                        n_estimators=200,
                        max_depth=6,
                        min_samples_leaf=2,
                        class_weight="balanced",
                        random_state=seed,
                        n_jobs=1,
                    ),
                ),
            ]
        ),
    }
