"""Strict JSON-only parameters and provenance for one fixed history candidate."""

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.numeric_model_bundle import NumericModelBundle, TASKS, json_sha256
from app.schemas.numeric_history_prediction import Count, Number
from app.schemas.synthetic_numeric_prediction import Identifier, Sha, StrictNumericModel

HISTORY_MODEL_ID = 'random_forest:history_v1:value_history'
FEATURE_NAMES = ['anchor_value', 'prior_value', 'slope_per_day']


class RfBranch(StrictNumericModel):
    kind: Literal['branch']
    feature_index: Annotated[int, Field(strict=True, ge=0, le=2)]
    threshold: Number
    left: Count
    right: Count


class RfLeaf(StrictNumericModel):
    kind: Literal['leaf']
    value: Number


class RfTree(StrictNumericModel):
    nodes: list[Annotated[RfBranch | RfLeaf, Field(discriminator='kind')]] = Field(min_length=1, max_length=31)

    @model_validator(mode='after')
    def valid_structure(self):
        seen, pending = set(), [(0, 0)]
        while pending:
            index, depth = pending.pop()
            if index >= len(self.nodes) or index in seen or depth > 4:
                raise ValueError('numeric_history_tree_structure_invalid')
            seen.add(index)
            node = self.nodes[index]
            if node.kind == 'branch':
                pending.extend(((node.left, depth + 1), (node.right, depth + 1)))
        if len(seen) != len(self.nodes):
            raise ValueError('numeric_history_tree_orphan')
        return self


class RfParameters(StrictNumericModel):
    n_estimators: Annotated[int, Field(strict=True)] = 200
    criterion: Literal['squared_error'] = 'squared_error'
    max_depth: Annotated[int, Field(strict=True)] = 4
    min_samples_split: Annotated[int, Field(strict=True)] = 2
    min_samples_leaf: Annotated[int, Field(strict=True)] = 3
    min_weight_fraction_leaf: Number = 0.0
    max_features: Number = 1.0
    max_leaf_nodes: None = None
    min_impurity_decrease: Number = 0.0
    bootstrap: bool = Field(default=True, strict=True)
    oob_score: bool = Field(default=False, strict=True)
    n_jobs: Annotated[int, Field(strict=True)] = 1
    random_state: Annotated[int, Field(strict=True)] = 20260914
    verbose: Annotated[int, Field(strict=True)] = 0
    warm_start: bool = Field(default=False, strict=True)
    ccp_alpha: Number = 0.0
    max_samples: None = None
    monotonic_cst: None = None

    @model_validator(mode='after')
    def frozen_configuration(self):
        if any(getattr(self, key) != field.default for key, field in type(self).model_fields.items()):
            raise ValueError('numeric_history_rf_configuration_changed')
        return self


class NumericHistoryRfModel(StrictNumericModel):
    task_id: Literal['ad.mmse.12m'] = 'ad.mmse.12m'
    model_id: Literal['random_forest:history_v1:value_history'] = HISTORY_MODEL_ID
    feature_names: list[Literal['anchor_value', 'prior_value', 'slope_per_day']] = Field(min_length=3, max_length=3)
    mean: list[Number] = Field(min_length=3, max_length=3)
    std: list[Annotated[float, Field(strict=True, ge=0)]] = Field(min_length=3, max_length=3)
    scale: list[Annotated[float, Field(strict=True, gt=0)]] = Field(min_length=3, max_length=3)
    parameters: RfParameters
    trees: list[RfTree] = Field(min_length=200, max_length=200)
    source_seed: Annotated[int, Field(strict=True)] = 20260914
    training_sample_ids: list[Identifier] = Field(min_length=2)
    training_subject_ids: list[Identifier] = Field(min_length=2)
    training_dependency_groups: list[Identifier] = Field(min_length=1)
    training_identity_sha256: Sha
    training_data_sha256: Sha
    training_target_sha256: Sha
    parameters_sha256: Sha

    @model_validator(mode='after')
    def valid_parameters(self):
        if self.feature_names != FEATURE_NAMES or self.source_seed != 20260914:
            raise ValueError('numeric_history_model_selection_mismatch')
        if self.scale != [1.0 if std == 0 else std for std in self.std]:
            raise ValueError('numeric_history_scale_mismatch')
        if (self.training_sample_ids != sorted(self.training_sample_ids)
                or len(self.training_sample_ids) != len(self.training_subject_ids)
                or any(len(values) != len(set(values)) for values in
                       (self.training_sample_ids, self.training_subject_ids, self.training_dependency_groups))):
            raise ValueError('numeric_history_training_identity_mismatch')
        if self.parameters_sha256 != json_sha256(self.model_dump(mode='json', exclude={'parameters_sha256'})):
            raise ValueError('numeric_history_parameters_mismatch')
        return self


class NumericHistoryTaskAssignment(StrictNumericModel):
    task_id: Literal['ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m']
    provider: Literal['legacy_ridge', 'history_rf']


class HistoryEvidenceModel(StrictNumericModel):
    @model_validator(mode="before")
    @classmethod
    def strict_literal_types(cls, value):
        if isinstance(value, dict):
            for key in ("seed", "source_seed", "n_valid", "n_invalid", "n_present_seeds", "n_effective_seeds"):
                if key in value and type(value[key]) is not int:
                    raise ValueError("integer_evidence_field_required")
            for key in ("complete_output", "common_scope_limited", "clinical_validity_claim", "complete", "incomplete"):
                if key in value and type(value[key]) is not bool:
                    raise ValueError("boolean_evidence_field_required")
            for key in ("seeds", "expected_seeds", "effective_seeds", "missing_seeds"):
                if key in value and any(type(item) is not int for item in value[key]):
                    raise ValueError("integer_seed_required")
        return value


Role = Literal["training", "internal_validation", "challenge"]
Scope = Literal["original", "common_complete"]
ComparisonName = Literal[
    "value_history_vs_last_value", "value_history_vs_anchor_history"
]


class NumericHistorySelection(HistoryEvidenceModel):
    schema_version: Literal["numeric_history_selection.v1"]
    seed: Literal[20260914]
    task_id: Literal["ad.mmse.12m"]
    model_id: Literal["random_forest:history_v1:value_history"]


class EvidenceRatio(HistoryEvidenceModel):
    value: Number | None
    numerator: Count
    denominator: Count
    reason: Literal["zero_denominator"] | None

    @model_validator(mode="after")
    def ratio_is_exact(self):
        if self.numerator > self.denominator:
            raise ValueError("ratio_numerator_exceeds_denominator")
        if self.denominator == 0:
            if self.value is not None or self.reason != "zero_denominator":
                raise ValueError("invalid_zero_denominator_ratio")
        elif (self.reason is not None or self.value is None
              or not math.isclose(self.value, self.numerator / self.denominator,
                                  rel_tol=0.0, abs_tol=1e-15)):
            raise ValueError("invalid_ratio")
        return self


class EvidenceCoverage(HistoryEvidenceModel):
    label_support: EvidenceRatio
    paired: EvidenceRatio
    end_to_end: EvidenceRatio


class EvidenceJointStates(HistoryEvidenceModel):
    both_valid: Count
    candidate_unavailable: Count
    reference_unavailable: Count
    both_unavailable: Count


class EvidenceCounts(HistoryEvidenceModel):
    N_patient: Count
    N_anchor_eligible: Count
    N_anchor_ineligible: Count
    N_anchor_pending: Count
    N_history_eligible: Count
    N_history_unavailable: Count
    N_branch_eligible: Count
    N_original_eligible: Count
    N_common_complete: Count
    N_common_excluded: Count
    N_common_excluded_due_to_output: Count
    N_label_valid: Count
    N_label_absent: Count
    N_label_pending: Count
    N_label_not_applicable: Count
    N_pair_valid: Count
    N_dependency_groups: Count
    N_candidate_out_of_range: Count
    N_reference_out_of_range: Count
    N_all_candidate_out_of_range: Count
    N_all_reference_out_of_range: Count
    N_pred_valid: Count
    N_pred_abstain: Count
    N_pred_error: Count
    N_reference_valid: Count
    N_reference_abstain: Count
    N_reference_error: Count
    N_original_pred_valid: Count
    N_original_pred_abstain: Count
    N_original_pred_error: Count
    N_original_reference_valid: Count
    N_original_reference_abstain: Count
    N_original_reference_error: Count
    N_all_pred_valid: Count
    N_all_pred_abstain: Count
    N_all_pred_error: Count
    N_all_reference_valid: Count
    N_all_reference_abstain: Count
    N_all_reference_error: Count


class EvidenceStatistics(HistoryEvidenceModel):
    mae: Number | None
    rmse: Number | None
    bias: Number | None
    reference_mae: Number | None
    mae_gain_reference_minus_candidate: Number | None
    alpha: Number | None
    beta: Number | None
    n_patients: Count
    n_groups: Count
    unavailable: list[Identifier]

    @model_validator(mode='after')
    def metric_bounds(self):
        for value in (self.mae, self.rmse, self.reference_mae):
            if value is not None and value < 0:
                raise ValueError('negative_error_metric')
        if self.mae is not None:
            if self.rmse is not None and self.rmse < self.mae and not math.isclose(self.rmse, self.mae, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError('rmse_below_mae')
            if self.bias is not None and abs(self.bias) > self.mae and not math.isclose(abs(self.bias), self.mae, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError('bias_exceeds_mae')
            if self.reference_mae is not None and self.mae_gain_reference_minus_candidate is not None and not math.isclose(
                self.mae_gain_reference_minus_candidate, self.reference_mae - self.mae, rel_tol=1e-12, abs_tol=1e-12
            ):
                raise ValueError('metric_gain_mismatch')
        return self


class EvidenceInterval(HistoryEvidenceModel):
    status: Literal["estimated", "unavailable"]
    reason: Identifier | None
    lower: Number | None
    upper: Number | None
    width: Number | None
    attempted: Count
    valid: Count
    failed: Count

    @model_validator(mode="after")
    def interval_is_consistent(self):
        if self.valid + self.failed != self.attempted:
            raise ValueError("invalid_interval_attempt_counts")
        if self.status == "estimated":
            if (self.reason is not None or self.lower is None or self.upper is None
                    or self.width is None or self.lower > self.upper
                    or not math.isclose(self.width, self.upper - self.lower,
                                        rel_tol=1e-12, abs_tol=1e-12)):
                raise ValueError("invalid_estimated_interval")
        elif any(value is not None for value in (self.lower, self.upper, self.width)):
            raise ValueError("invalid_unavailable_interval")
        return self


class EvidenceIntervals(HistoryEvidenceModel):
    bias: EvidenceInterval
    mae: EvidenceInterval
    mae_gain_reference_minus_candidate: EvidenceInterval
    reference_mae: EvidenceInterval
    rmse: EvidenceInterval

    @model_validator(mode='after')
    def nonnegative_error_intervals(self):
        if any(value.lower is not None and value.lower < 0 for value in (self.mae, self.rmse, self.reference_mae)):
            raise ValueError('negative_error_interval')
        return self


class EmptyEvidenceIntervals(HistoryEvidenceModel):
    """Serializes as the source artifact's exact `{}` for descriptive roles."""


class NumericHistoryComparisonEvidence(HistoryEvidenceModel):
    seed: Literal[20260914]  # wrapper addition; source row itself has no seed
    comparison_id: Identifier
    task_id: Literal["ad.mmse.12m"]
    pool: Literal["development_pool", "challenge_pool"]
    evaluation_role: Role
    family: Literal["random_forest"]
    comparison_name: ComparisonName
    scope: Scope
    candidate_model_id: Literal["random_forest:history_v1:value_history"]
    reference_model_id: Literal[
        "last_value", "random_forest:history_v1:anchor_history"
    ]
    gain_name: Literal["mae_gain_reference_minus_candidate"]
    unit: Literal["分"]
    counts: EvidenceCounts
    joint_states: EvidenceJointStates
    coverage: EvidenceCoverage
    complete_output: Literal[True]
    statistics: EvidenceStatistics
    intervals: EvidenceIntervals | EmptyEvidenceIntervals
    common_scope_limited: Literal[False]
    bootstrap_plan_id: Identifier | None
    uncertainty_scope: Literal[
        "descriptive_only", "synthetic_fixed_challenge_group_bootstrap"
    ]
    clinical_status: Literal["not_assessable"]

    @model_validator(mode="after")
    def closed_semantics(self):
        expected_pool = "challenge_pool" if self.evaluation_role == "challenge" else "development_pool"
        expected_ref = ("last_value" if self.comparison_name == "value_history_vs_last_value"
                        else "random_forest:history_v1:anchor_history")
        expected_id = (f"ad.mmse.12m:{self.evaluation_role}:random_forest:"
                       f"{self.comparison_name}:{self.scope}")
        if self.pool != expected_pool or self.reference_model_id != expected_ref or self.comparison_id != expected_id:
            raise ValueError("comparison_identity_mismatch")
        challenge = self.evaluation_role == "challenge"
        if (challenge != isinstance(self.intervals, EvidenceIntervals)
                or challenge != (self.bootstrap_plan_id is not None)):
            raise ValueError("comparison_interval_role_mismatch")
        if self.uncertainty_scope != ("synthetic_fixed_challenge_group_bootstrap" if challenge
                                     else "descriptive_only"):
            raise ValueError("comparison_uncertainty_scope_mismatch")
        c, j, s = self.counts, self.joint_states, self.statistics
        if c.N_patient != c.N_anchor_eligible + c.N_anchor_ineligible + c.N_anchor_pending:
            raise ValueError("patient_count_mismatch")
        if c.N_history_eligible + c.N_history_unavailable != c.N_anchor_eligible:
            raise ValueError("history_count_mismatch")
        if c.N_common_complete + c.N_common_excluded != c.N_original_eligible:
            raise ValueError("common_count_mismatch")
        if (c.N_original_eligible != c.N_history_eligible
                or c.N_common_excluded_due_to_output > c.N_common_excluded
                or c.N_dependency_groups > c.N_branch_eligible):
            raise ValueError('evidence_subset_count_mismatch')
        expected_branch = c.N_original_eligible if self.scope == "original" else c.N_common_complete
        if c.N_branch_eligible != expected_branch:
            raise ValueError("branch_count_mismatch")
        if c.N_label_valid + c.N_label_absent + c.N_label_pending + c.N_label_not_applicable != c.N_branch_eligible:
            raise ValueError("label_count_mismatch")
        if sum((j.both_valid, j.candidate_unavailable, j.reference_unavailable,
                j.both_unavailable)) != c.N_label_valid:
            raise ValueError("joint_count_mismatch")
        if c.N_pair_valid != j.both_valid or c.N_pair_valid != s.n_patients or s.n_patients != s.n_groups:
            raise ValueError("paired_count_mismatch")
        for prefix, denominator in (("N_pred_", c.N_branch_eligible),
                                    ("N_reference_", c.N_branch_eligible),
                                    ("N_original_pred_", c.N_original_eligible),
                                    ("N_original_reference_", c.N_original_eligible),
                                    ("N_all_pred_", c.N_patient),
                                    ("N_all_reference_", c.N_patient)):
            if sum(getattr(c, prefix + state) for state in ("valid", "abstain", "error")) != denominator:
                raise ValueError("prediction_state_count_mismatch")
        for branch, original, all_rows in (('N_pred_', 'N_original_pred_', 'N_all_pred_'),
                                           ('N_reference_', 'N_original_reference_', 'N_all_reference_')):
            if any(not getattr(c, branch + state) <= getattr(c, original + state) <= getattr(c, all_rows + state)
                   for state in ('valid', 'abstain', 'error')):
                raise ValueError('prediction_state_subset_mismatch')
        if (c.N_pair_valid > min(c.N_pred_valid, c.N_reference_valid)
                or c.N_candidate_out_of_range > c.N_pair_valid
                or c.N_reference_out_of_range > c.N_pair_valid
                or not c.N_candidate_out_of_range <= c.N_all_candidate_out_of_range <= c.N_all_pred_valid
                or not c.N_reference_out_of_range <= c.N_all_reference_out_of_range <= c.N_all_reference_valid):
            raise ValueError('out_of_range_denominator_mismatch')
        # These are the source evaluator's exact complete_output conditions.
        if (c.N_original_pred_error or c.N_original_reference_error or c.N_all_pred_error
                or c.N_all_reference_error or c.N_original_pred_abstain or c.N_original_reference_abstain
                or self.scope == 'common_complete' and c.N_common_excluded_due_to_output):
            raise ValueError('complete_output_count_mismatch')
        expected_ratios = ((self.coverage.label_support, c.N_label_valid, c.N_branch_eligible),
                           (self.coverage.paired, c.N_pair_valid, c.N_label_valid),
                           (self.coverage.end_to_end, c.N_pair_valid, c.N_branch_eligible))
        if any(r.numerator != n or r.denominator != d for r, n, d in expected_ratios):
            raise ValueError("coverage_count_mismatch")
        return self


class AggregateValue(HistoryEvidenceModel):
    mean: Number
    min: Number
    max: Number
    n_valid: Literal[3]
    n_invalid: Literal[0]

    @model_validator(mode="after")
    def ordered(self):
        if not self.min <= self.mean <= self.max:
            raise ValueError("invalid_aggregate_order")
        return self


class AggregateMetric(AggregateValue):
    missing_seeds: list[Literal[20260914, 20260915, 20260916]] = Field(max_length=0)


class AggregateMetrics(HistoryEvidenceModel):
    bias: AggregateMetric
    mae: AggregateMetric
    mae_gain_reference_minus_candidate: AggregateMetric
    reference_mae: AggregateMetric
    rmse: AggregateMetric

    @model_validator(mode='after')
    def nonnegative_errors(self):
        if any(value.min < 0 for value in (self.mae, self.rmse, self.reference_mae)):
            raise ValueError('negative_aggregate_error_metric')
        return self


class AggregateCounts(HistoryEvidenceModel):
    N_label_valid: AggregateValue
    N_pair_valid: AggregateValue

    @model_validator(mode='after')
    def nonnegative_integer_extrema(self):
        for value in (self.N_label_valid, self.N_pair_valid):
            if value.min < 0 or not value.min.is_integer() or not value.max.is_integer():
                raise ValueError('invalid_aggregate_counts')
        return self


class NumericHistoryAggregateEvidence(HistoryEvidenceModel):
    evaluation_role: Role
    task_id: Literal["ad.mmse.12m"]
    family: Literal["random_forest"]
    comparison_name: ComparisonName
    scope: Scope
    candidate_model_id: Literal["random_forest:history_v1:value_history"]
    reference_model_id: Literal[
        "last_value", "random_forest:history_v1:anchor_history"
    ]
    gain_name: Literal["mae_gain_reference_minus_candidate"]
    unit: Literal["分"]
    expected_seeds: tuple[Literal[20260914], Literal[20260915], Literal[20260916]]
    seeds: tuple[Literal[20260914], Literal[20260915], Literal[20260916]]
    missing_seeds: list[Literal[20260914, 20260915, 20260916]] = Field(max_length=0)
    n_present_seeds: Literal[3]
    effective_seeds: tuple[Literal[20260914], Literal[20260915], Literal[20260916]]
    n_effective_seeds: Literal[3]
    complete: Literal[True]
    incomplete: Literal[False]
    gain_direction: Literal['positive', 'negative', 'zero', 'mixed']
    metrics: AggregateMetrics
    counts: AggregateCounts
    source_kind: Literal["synthetic"]
    clinical_validity_claim: Literal[False]
    clinical_status: Literal["not_assessable"]

    @model_validator(mode="after")
    def identity_matches(self):
        expected = ("last_value" if self.comparison_name == "value_history_vs_last_value"
                    else "random_forest:history_v1:anchor_history")
        if self.reference_model_id != expected:
            raise ValueError("aggregate_reference_mismatch")
        gain = self.metrics.mae_gain_reference_minus_candidate
        direction = ('positive' if gain.min > 0 else 'negative' if gain.max < 0
                     else 'zero' if gain.min == gain.max == 0 else 'mixed')
        if self.gain_direction != direction:
            raise ValueError('aggregate_gain_direction_mismatch')
        return self


class NumericHistoryEvidence(HistoryEvidenceModel):
    schema_version: Literal["numeric_history_evidence.v1"]
    source_kind: Literal["synthetic"]
    clinical_status: Literal["not_assessable"]
    clinical_validity_claim: Literal[False]
    # S1 validates shape. S2 pins this to hist-fa171097693d166e and exact hashes.
    run_id: Identifier
    manifest_sha256: Sha
    data_content_sha256: Sha
    protocol_identity_sha256: Sha
    selection: NumericHistorySelection
    source_seed: Literal[20260914]
    model_id: Literal["random_forest:history_v1:value_history"]
    training_identity_sha256: Sha
    parameters_sha256: Sha
    # S1 permits compact self-consistent fixtures; S2 requires the exact 400-entry sets.
    challenge_subject_ids: list[Identifier] = Field(min_length=1)
    challenge_dependency_groups: list[Identifier] = Field(min_length=1)
    comparisons: list[NumericHistoryComparisonEvidence] = Field(min_length=12, max_length=12)
    aggregates: list[NumericHistoryAggregateEvidence] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def complete_catalog(self):
        expected = {
            (role, name, scope)
            for role in ("training", "internal_validation", "challenge")
            for name in ("value_history_vs_last_value", "value_history_vs_anchor_history")
            for scope in ("original", "common_complete")
        }
        comparison_keys = [(x.evaluation_role, x.comparison_name, x.scope) for x in self.comparisons]
        aggregate_keys = [(x.evaluation_role, x.comparison_name, x.scope) for x in self.aggregates]
        if set(comparison_keys) != expected or len(set(comparison_keys)) != 12:
            raise ValueError("incomplete_or_duplicate_comparison_catalog")
        if set(aggregate_keys) != expected or len(set(aggregate_keys)) != 12:
            raise ValueError("incomplete_or_duplicate_aggregate_catalog")
        if (len(set(self.challenge_subject_ids)) != len(self.challenge_subject_ids)
                or len(set(self.challenge_dependency_groups)) != len(self.challenge_dependency_groups)
                or len(self.challenge_subject_ids) != len(self.challenge_dependency_groups)):
            raise ValueError("duplicate_challenge_identity")
        by_key = dict(zip(comparison_keys, self.comparisons))
        for key, aggregate in zip(aggregate_keys, self.aggregates):
            comparison = by_key[key]
            for name in type(aggregate.metrics).model_fields:
                _validate_aggregate_member(getattr(aggregate.metrics, name), getattr(comparison.statistics, name))
            for name in type(aggregate.counts).model_fields:
                _validate_aggregate_member(getattr(aggregate.counts, name), getattr(comparison.counts, name))
        return self


def _validate_aggregate_member(summary, member):
    """A saved selected seed must be a possible member of its three-seed summary."""
    if member is None or not summary.min <= member <= summary.max:
        raise ValueError('aggregate_selected_member_mismatch')
    # Both reported extrema must be attained among exactly three seeds. If the
    # selected value is interior, the other two are necessarily min and max.
    required = [value for value in {summary.min, summary.max} if value != member]
    remaining = 2 - len(required)
    lower = math.fsum([member / 3, *(value / 3 for value in required), *([summary.min / 3] * remaining)])
    upper = math.fsum([member / 3, *(value / 3 for value in required), *([summary.max / 3] * remaining)])
    if ((summary.mean < lower and not math.isclose(summary.mean, lower, rel_tol=1e-12, abs_tol=1e-12))
            or (summary.mean > upper and not math.isclose(summary.mean, upper, rel_tol=1e-12, abs_tol=1e-12))):
        raise ValueError('aggregate_selected_mean_infeasible')


class NumericHistoryBundle(HistoryEvidenceModel):
    schema_version: Literal['numeric_model_bundle.v2'] = 'numeric_model_bundle.v2'
    selection_version: Literal['numeric_history_selection.v1'] = 'numeric_history_selection.v1'
    input_schema_version: Literal['numeric_input.v1'] = 'numeric_input.v1'
    implementation_sha256: Sha
    clinical_validity_claim: Literal[False] = False
    production_enabled: bool = Field(default=False, strict=True)
    legacy_bundle: NumericModelBundle
    legacy_bundle_sha256: Sha
    history_model: NumericHistoryRfModel
    task_assignments: list[NumericHistoryTaskAssignment] = Field(min_length=4, max_length=4)
    history_evidence: NumericHistoryEvidence

    @model_validator(mode='after')
    def validate_bundle(self):
        if self.production_enabled:
            raise ValueError('numeric_history_engineering_only')
        routes = {row.task_id: row.provider for row in self.task_assignments}
        expected = {task: 'history_rf' if task == 'ad.mmse.12m' else 'legacy_ridge' for task in TASKS}
        if routes != expected:
            raise ValueError('numeric_history_routes_mismatch')
        legacy = self.legacy_bundle.model_dump(mode='json')
        legacy['models'].sort(key=lambda row: row['task_id'])
        if json_sha256(legacy) != self.legacy_bundle_sha256:
            raise ValueError('numeric_history_legacy_hash_mismatch')
        model, evidence = self.history_model, self.history_evidence
        if (evidence.parameters_sha256, evidence.training_identity_sha256, evidence.source_seed, evidence.model_id) != (
            model.parameters_sha256, model.training_identity_sha256, model.source_seed, model.model_id
        ):
            raise ValueError('numeric_history_evidence_model_mismatch')
        if (set(model.training_subject_ids) & set(evidence.challenge_subject_ids)
                or set(model.training_dependency_groups) & set(evidence.challenge_dependency_groups)):
            raise ValueError('numeric_history_challenge_leakage')
        return self
