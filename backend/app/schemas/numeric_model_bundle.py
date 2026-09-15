"""Strict, self-contained JSON parameters for four fixed engineering tasks."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from app.schemas.numeric_prediction import NumericAlgorithm, NumericPrediction
from app.schemas.synthetic_numeric_prediction import (
    Horizon, Identifier, NumericTaskPrediction, Sha, StrictNumericModel,
)


TASKS = ('ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m')
FiniteNumber = Annotated[float, Field(strict=True)]


def json_sha256(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class NumericBundleSourceItem(StrictNumericModel):
    run_id: Identifier
    data_content_sha256: Sha


class NumericBundleSource(StrictNumericModel):
    cases: NumericBundleSourceItem
    calculation: NumericBundleSourceItem


class NumericRidgeTask(StrictNumericModel):
    task_id: Literal['ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m']
    indicator: Literal['mmse', 'alt']
    unit: Literal['分', 'U/L']
    horizon_months: Horizon
    feature_names: list[Literal['anchor_value']] = Field(min_length=1, max_length=1)
    mean: list[FiniteNumber] = Field(min_length=1, max_length=1)
    std: list[Annotated[float, Field(strict=True, ge=0)]] = Field(min_length=1, max_length=1)
    scale: list[Annotated[float, Field(strict=True, gt=0)]] = Field(min_length=1, max_length=1)
    coef: list[FiniteNumber] = Field(min_length=1, max_length=1)
    intercept: FiniteNumber
    training_sample_ids: list[Identifier] = Field(min_length=2)
    training_subject_ids: list[Identifier] = Field(min_length=2)
    training_dependency_groups: list[Identifier] = Field(min_length=2)
    training_identity_sha256: Sha
    training_data_sha256: Sha
    parameters_sha256: Sha

    @model_validator(mode='after')
    def valid_task_parameters(self):
        disease = 'ad' if self.indicator == 'mmse' else 'fatty_liver'
        if (self.task_id != f'{disease}.{self.indicator}.{self.horizon_months}m'
                or self.unit != ('分' if self.indicator == 'mmse' else 'U/L')):
            raise ValueError('numeric_model_task_mismatch')
        if self.scale != [1.0 if self.std[0] == 0 else self.std[0]]:
            raise ValueError('numeric_model_scale_mismatch')
        if (len(self.training_sample_ids) != len(self.training_subject_ids)
                or any(len(values) != len(set(values)) for values in
                       (self.training_sample_ids, self.training_subject_ids, self.training_dependency_groups))):
            raise ValueError('numeric_model_training_identity_mismatch')
        if self.parameters_sha256 != json_sha256(self.model_dump(mode='json', exclude={'parameters_sha256'})):
            raise ValueError('numeric_model_parameters_mismatch')
        return self


class TrainedNumericAlgorithm(NumericAlgorithm):
    model_id: Literal['ridge:main_anchor'] = 'ridge:main_anchor'
    algorithm_version: Literal['numeric.ridge.main_anchor.v1'] = 'numeric.ridge.main_anchor.v1'
    bundle_sha256: Sha


class NumericModelBundle(StrictNumericModel):
    schema_version: Literal['numeric_model_bundle.v1'] = 'numeric_model_bundle.v1'
    model_id: Literal['ridge:main_anchor'] = 'ridge:main_anchor'
    algorithm_version: Literal['numeric.ridge.main_anchor.v1'] = 'numeric.ridge.main_anchor.v1'
    input_schema_version: Literal['numeric_input.v1'] = 'numeric_input.v1'
    implementation_sha256: Sha
    models: list[NumericRidgeTask] = Field(min_length=4, max_length=4)
    source: NumericBundleSource
    challenge_subject_ids: list[Identifier]
    challenge_dependency_groups: list[Identifier]
    evaluation: dict[str, JsonValue]
    evaluation_sha256: Sha
    clinical_validity_claim: Literal[False] = False
    production_enabled: Literal[False] = False

    @model_validator(mode='before')
    @classmethod
    def engineering_only(cls, value):
        if isinstance(value, dict) and any(value.get(k, False) is not False for k in
                                           ('clinical_validity_claim', 'production_enabled')):
            raise ValueError('engineering_only')
        return value

    @model_validator(mode='after')
    def complete_and_separated(self):
        if {m.task_id for m in self.models} != set(TASKS):
            raise ValueError('numeric_model_four_tasks_required')
        for model in self.models:
            if (set(model.training_subject_ids) & set(self.challenge_subject_ids)
                    or set(model.training_dependency_groups) & set(self.challenge_dependency_groups)):
                raise ValueError('numeric_model_challenge_leakage')
        evaluation = self.evaluation
        if (evaluation.get('schema_version') != 'synthetic_prediction_candidates.v1'
                or evaluation.get('clinical_validity_claim') is not False
                or evaluation.get('clinical_status') != 'not_assessable'
                or evaluation.get('candidate_model_training') != 'executed'
                or not isinstance(evaluation.get('fit_failures'), list)
                or evaluation.get('engineering_status') not in ('passed', 'incomplete')):
            raise ValueError('numeric_model_evaluation_invalid')
        comparisons = evaluation.get('comparisons')
        if not isinstance(comparisons, list) or any(not isinstance(c, dict) for c in comparisons):
            raise ValueError('numeric_model_evaluation_invalid')
        selected = [c for c in comparisons if c.get('model_id') == self.model_id]
        expected = {(task, pool) for task in TASKS for pool in ('development_pool', 'challenge_pool')}
        if len(selected) != 8 or {(c.get('task_id'), c.get('pool')) for c in selected} != expected:
            raise ValueError('numeric_model_evaluation_tasks_mismatch')
        for comparison in selected:
            counts = comparison.get('counts')
            if (not isinstance(counts, dict) or any(type(v) is not int or v < 0 for v in counts.values())
                    or not {'N_patient', 'N_label_valid', 'N_pair_valid'} <= counts.keys()
                    or not counts['N_pair_valid'] <= counts['N_label_valid'] <= counts['N_patient']):
                raise ValueError('numeric_model_evaluation_counts_invalid')
        if self.evaluation_sha256 != json_sha256(evaluation):
            raise ValueError('numeric_model_evaluation_mismatch')
        return self


class TrainedNumericPrediction(NumericPrediction):
    schema_version: Literal['numeric_prediction.v2'] = 'numeric_prediction.v2'
    algorithm: TrainedNumericAlgorithm
    baseline_predictions: list[NumericTaskPrediction] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def baseline_tasks_match(self):
        identity = lambda p: (p.task_id, p.indicator, p.unit, p.horizon_months, p.target_date, p.status, p.reason)
        if ({identity(p) for p in self.baseline_predictions} != {identity(p) for p in self.predictions}
                or len({p.task_id for p in self.baseline_predictions}) != 2):
            raise ValueError('numeric_baseline_task_mismatch')
        return self
