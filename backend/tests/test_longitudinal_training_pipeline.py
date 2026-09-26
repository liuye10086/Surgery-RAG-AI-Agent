"""Behavior contracts shared by stage and trend candidate constructors."""

from importlib import import_module

import numpy as np
import pandas as pd
import pytest


@pytest.fixture(params=["stage", "trend"])
def candidates(request):
    module = import_module(f"app.services.longitudinal_{request.param}_training")
    def build(numeric, categorical, seed=17):
        return module.build_training_candidates(numeric, categorical, seed)

    return build


def _training_frame():
    return pd.DataFrame(
        {
            "stage": ["mci", "normal", "mci", "normal"],
            "first": [1.0, 3.0, np.nan, 7.0],
            "sex": ["f", "m", np.nan, "f"],
            "empty": [np.nan] * 4,
            "second": [10.0, np.nan, 30.0, 50.0],
            "ignored": [99] * 4,
        }
    )


def _dense(matrix):
    return matrix.toarray() if hasattr(matrix, "toarray") else matrix


@pytest.mark.parametrize("seed", [17, 43])
def test_candidate_order_steps_and_parameters(candidates, seed):
    models = candidates(("second", "empty", "first"), ("sex", "stage"), seed)
    assert list(models) == ["multinomial_logistic_regression", "random_forest"]
    for name, model in models.items():
        assert list(model.named_steps) == ["preprocess", "classifier"]
        preprocess = model.named_steps["preprocess"]
        assert preprocess.remainder == "drop"
        assert [item[0] for item in preprocess.transformers] == ["numeric", "categorical"]
        numeric, categorical = preprocess.transformers
        assert numeric[2] == ["second", "empty", "first"]
        assert categorical[2] == ["sex", "stage"]
        assert list(numeric[1].named_steps) == (
            ["imputer", "scaler"] if name == "multinomial_logistic_regression" else ["imputer"]
        )
        imputer = numeric[1].named_steps["imputer"]
        assert (imputer.strategy, imputer.add_indicator, imputer.keep_empty_features) == (
            "median", True, True
        )
        assert list(categorical[1].named_steps) == ["imputer", "onehot"]
        assert categorical[1].named_steps["imputer"].strategy == "most_frequent"
        assert categorical[1].named_steps["onehot"].handle_unknown == "ignore"
        classifier = model.named_steps["classifier"]
        assert classifier.random_state == seed
        assert classifier.class_weight == "balanced"
        if name == "multinomial_logistic_regression":
            assert classifier.max_iter == 3000
        else:
            assert (classifier.n_estimators, classifier.max_depth, classifier.min_samples_leaf,
                    classifier.n_jobs) == (200, 6, 2, 1)


def test_missing_empty_numeric_unknown_category_and_column_order(candidates):
    numeric = np.array([
        [10, 0, 1, 0, 1, 0],
        [30, 0, 3, 1, 1, 0],
        [30, 0, 3, 0, 1, 1],
        [50, 0, 7, 0, 1, 0],
    ], dtype=float)
    categorical = np.array([[1, 0, 1, 0], [0, 1, 0, 1], [1, 0, 1, 0], [1, 0, 0, 1]])
    probe = pd.DataFrame({
        "first": [np.nan], "empty": [np.nan], "second": [np.nan],
        "stage": ["unknown"], "sex": ["unknown"], "ignored": [999],
    })
    numeric_probe = np.array([[30, 0, 3, 1, 1, 1]], dtype=float)
    for name, model in candidates(("second", "empty", "first"), ("sex", "stage")).items():
        preprocess = model.named_steps["preprocess"]
        actual = _dense(preprocess.fit_transform(_training_frame()))
        transformed_probe = _dense(preprocess.transform(probe))
        expected_numeric, expected_probe = numeric, numeric_probe
        if name == "multinomial_logistic_regression":
            scale = numeric.std(axis=0)
            scale[scale == 0] = 1
            expected_numeric = (numeric - numeric.mean(axis=0)) / scale
            expected_probe = (numeric_probe - numeric.mean(axis=0)) / scale
        np.testing.assert_allclose(actual, np.column_stack([expected_numeric, categorical]))
        np.testing.assert_allclose(transformed_probe, np.column_stack([expected_probe, np.zeros((1, 4))]))
        assert preprocess.get_feature_names_out().tolist() == [
            "numeric__second", "numeric__empty", "numeric__first",
            "numeric__missingindicator_second", "numeric__missingindicator_empty",
            "numeric__missingindicator_first", "categorical__sex_f", "categorical__sex_m",
            "categorical__stage_mci", "categorical__stage_normal",
        ]


@pytest.mark.parametrize("numeric,categorical,branches,width", [
    (("first",), (), ["numeric"], 2),
    ((), ("sex",), ["categorical"], 2),
    ((), (), [], 0),
])
def test_empty_feature_branches(candidates, numeric, categorical, branches, width):
    for model in candidates(numeric, categorical).values():
        preprocess = model.named_steps["preprocess"]
        assert [item[0] for item in preprocess.transformers] == branches
        transformed = _dense(preprocess.fit_transform(_training_frame()))
        assert transformed.shape == (4, width)


def test_each_call_and_each_candidate_owns_independent_estimators(candidates):
    first = candidates(("first",), ("sex",))
    second = candidates(("first",), ("sex",))
    objects = []
    for models in (first, second):
        for model in models.values():
            objects.extend(value for value in model.get_params(deep=True).values()
                           if hasattr(value, "fit"))
    assert len({id(value) for value in objects}) == len(objects)
    first["multinomial_logistic_regression"].fit(_training_frame(), [0, 1, 0, 1])
    assert not hasattr(second["multinomial_logistic_regression"].named_steps["classifier"], "classes_")
    assert not hasattr(first["random_forest"].named_steps["classifier"], "classes_")
