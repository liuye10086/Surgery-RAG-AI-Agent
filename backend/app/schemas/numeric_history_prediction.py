"""Independent candidate/baseline states for the fixed mixed history model."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.numeric_prediction import PredictionSource
from app.schemas.synthetic_numeric_prediction import (
    CalendarDate, Horizon, Identifier, NumericAlgorithmIdentity, Sha, StrictNumericModel,
)

AbstainReason = Literal['anchor_unavailable', 'population_not_confirmed',
                        'population_not_known_at_anchor', 'conflicting_history',
                        'history_coverage_incomplete', 'history_not_observed', 'comparable_history_required']
ErrorReason = Literal['history_calculation_error', 'standardization_error',
                      'prediction_calculation_error', 'nonfinite_prediction', 'prediction_out_of_bounds']
Number = Annotated[float, Field(strict=True)]
Count = Annotated[int, Field(strict=True, ge=0)]


class HistoryFeatureResult(StrictNumericModel):
    eligible: bool = Field(strict=True)
    status: Literal['available', 'abstain', 'error']
    reason: AbstainReason | Literal['history_calculation_error'] | None
    anchor_value: Number | None
    prior_value: Number | None
    slope_per_day: Number | None
    n_pre: Count | None
    span_pre_days: Count | None

    @model_validator(mode='after')
    def consistent_features(self):
        if self.status == 'available':
            if not self.eligible or self.reason is not None or any(v is None for v in (
                self.anchor_value, self.prior_value, self.slope_per_day, self.n_pre, self.span_pre_days
            )):
                raise ValueError('history_feature_state_mismatch')
        elif (self.prior_value is not None or self.slope_per_day is not None
              or self.eligible != (self.status == 'error')
              or (self.status == 'error') != (self.reason == 'history_calculation_error')
              or self.reason is None):
            raise ValueError('history_feature_state_mismatch')
        if self.eligible and (self.anchor_value is None or not self.n_pre or not self.span_pre_days):
            raise ValueError('history_eligibility_mismatch')
        return self


class MixedNumericAlgorithm(NumericAlgorithmIdentity):
    model_id: Literal['mixed_history'] = 'mixed_history'
    algorithm_version: Literal['numeric.mixed_history.v1'] = 'numeric.mixed_history.v1'
    input_schema_version: Literal['numeric_input.v1'] = 'numeric_input.v1'
    bundle_sha256: Sha


class NumericTaskAlgorithm(StrictNumericModel):
    model_id: Literal['ridge:main_anchor', 'random_forest:history_v1:value_history', 'last_value']
    algorithm_version: Literal['numeric.ridge.main_anchor.v1', 'numeric.random_forest.history_v1.value_history.v1',
                               'numeric.last_value.v1']
    feature_version: Literal['main_anchor', 'history_v1:value_history']
    eligibility_version: Literal['numeric.anchor.v1', 'numeric.history.H.v1']
    feature_names: list[Literal['anchor_value', 'prior_value', 'slope_per_day']]
    parameters_sha256: Sha

    @model_validator(mode='after')
    def fixed_descriptor(self):
        history = self.model_id == 'random_forest:history_v1:value_history'
        version = {'last_value': 'numeric.last_value.v1', 'ridge:main_anchor': 'numeric.ridge.main_anchor.v1',
                   'random_forest:history_v1:value_history': 'numeric.random_forest.history_v1.value_history.v1'}[self.model_id]
        expected = (version, 'history_v1:value_history' if history else 'main_anchor',
                    'numeric.history.H.v1' if history else 'numeric.anchor.v1',
                    ['anchor_value', 'prior_value', 'slope_per_day'] if history else ['anchor_value'])
        if (self.algorithm_version, self.feature_version, self.eligibility_version, self.feature_names) != expected:
            raise ValueError('numeric_history_descriptor_mismatch')
        return self


class NumericTaskPredictionV3(StrictNumericModel):
    task_id: Literal['ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m']
    indicator: Literal['mmse', 'alt']
    unit: Literal['分', 'U/L']
    horizon_months: Horizon
    target_date: CalendarDate
    algorithm: NumericTaskAlgorithm
    status: Literal['available', 'abstain', 'error']
    value: Number | None
    reason: AbstainReason | ErrorReason | None
    raw_prediction: Number | None = None

    @model_validator(mode='after')
    def valid_result(self):
        errors = {'history_calculation_error', 'standardization_error', 'prediction_calculation_error',
                  'nonfinite_prediction', 'prediction_out_of_bounds'}
        if self.status == 'available':
            if self.value is None or self.reason is not None or self.value < 0 or self.indicator == 'mmse' and self.value > 30:
                raise ValueError('numeric_history_result_state_mismatch')
        elif self.value is not None or self.reason is None or (self.status == 'error') != (self.reason in errors):
            raise ValueError('numeric_history_result_state_mismatch')
        if (self.raw_prediction is not None) != (self.reason == 'prediction_out_of_bounds'):
            raise ValueError('numeric_history_raw_prediction_mismatch')
        if self.raw_prediction is not None and not (self.raw_prediction < 0 or self.indicator == 'mmse' and self.raw_prediction > 30):
            raise ValueError('numeric_history_raw_prediction_in_bounds')
        return self


class NumericPredictionV3(StrictNumericModel):
    schema_version: Literal['numeric_prediction.v3'] = 'numeric_prediction.v3'
    disease_code: Literal['ad', 'fatty_liver']
    subject_id: Identifier
    dependency_group_id: Identifier
    anchor_date: CalendarDate
    source: PredictionSource
    input_sha256: Sha
    algorithm: MixedNumericAlgorithm
    predictions: list[NumericTaskPredictionV3] = Field(min_length=2, max_length=2)
    baseline_predictions: list[NumericTaskPredictionV3] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def tasks_and_routes(self):
        from app.services.synthetic_prediction_cases import add_calendar_months

        if self.source.source_kind != 'synthetic':
            raise ValueError('numeric_history_synthetic_required')
        indicator, unit = ('mmse', '分') if self.disease_code == 'ad' else ('alt', 'U/L')
        for rows, baseline in ((self.predictions, False), (self.baseline_predictions, True)):
            if {p.horizon_months for p in rows} != {6, 12}:
                raise ValueError('numeric_history_two_tasks_required')
            for p in rows:
                task = f'{self.disease_code}.{indicator}.{p.horizon_months}m'
                model = 'last_value' if baseline else ('random_forest:history_v1:value_history' if task == 'ad.mmse.12m' else 'ridge:main_anchor')
                if (p.task_id, p.indicator, p.unit, p.target_date, p.algorithm.model_id) != (
                    task, indicator, unit, add_calendar_months(self.anchor_date, p.horizon_months), model
                ):
                    raise ValueError('numeric_history_task_identity_mismatch')
        return self
