import request from './request'
import type { ReportDocumentV1 } from '@/types/report-document'

// ===== 预测分析类型 =====
export interface IndicatorInput {
  name: string
  value: number | null
  unit: string
}

export type VisitSourceType = 'lab' | 'imaging' | 'assessment' | 'clinical' | 'other'

export interface VisitContext {
  source_type?: VisitSourceType | null
  facility_name?: string | null
  device_name?: string | null
  assay_platform?: string | null
  method?: string | null
  specimen?: string | null
  is_baseline?: boolean | null
  treatment_change?: string | null
  diagnosis_change?: string | null
  scale_version?: string | null
  assessment_language?: string | null
  education_years?: number | null
  education_adjusted?: boolean | null
  imaging_type?: string | null
}

export interface OperatorIndicatorCatalogItem {
  code: string
  name_cn: string | null
  name_en: string
  aliases: string[]
  allowed_units: string[]
  default_unit: string | null
  data_type: string
  context_requirements: string[]
}

export interface OperatorIndicatorCatalog {
  disease_code: string
  catalog_version: string
  items: OperatorIndicatorCatalogItem[]
}

export interface Disease {
  id: number
  code: string
  name: string
  description: string | null
  operator_enabled: boolean
  created_at: string
}

export interface ReportIdentityMeta {
  id: number
  user_id: number
  title: string | null
  query: string
  department_ids: number[]
  status: string
  error_message: string | null
  download_count: number
  analysis_type: string
  disease_id: number | null
  operator_case_id: number | null
  anonymous_case_code: string | null
  indicators: Record<string, unknown>[]
    error_stage: string | null
    input_snapshot_sha256: string | null
    generation_batch_id: string | null
    generation_fingerprint: string | null
  created_at: string
  updated_at: string
}

export interface ReportListItem extends ReportIdentityMeta {
  disease_name: string | null
  baseline_stage: string | null
  visit_count: number | null
  model_version_summary: string | null
}

export interface GenerationAuditSummary {
  schema_version: 'generation_audit.v1'
  last_execution_phase: string|null
  failure_phase: string|null
  error_code: string|null
  event_count: number
  note: string
  events: Array<{kind:string;phase:string;task:string|null;result_state:string|null;input_audit:{model_invoked:boolean;fields:Array<{name:string;state:string}>}|null}>
}

export interface ReportDetail extends ReportIdentityMeta {
  publication_status?: 'published'|'not_published'|'invalid'
  snapshot_integrity?: 'valid'|'invalid'|'unverifiable'
  context_integrity?: 'valid'|'invalid'|'unverifiable'
  generation_context?: Record<string,unknown>|null
  generation_audit?: GenerationAuditSummary|null
  report_document?: ReportDocumentV1 | null
  report_document_sha256?: string | null
  generation_fingerprint_version?: string | null
  integrity_status?: 'valid' | 'invalid' | 'unverifiable' | null
  integrity_reason_code?: string | null
  content: string
  sources: LegacyEvidenceSource[]
  retrieval_meta: Record<string, unknown>
  prediction_result: LongitudinalPrediction | null
  input_snapshot: Record<string, unknown> | null
  evidence_snapshot: EvidenceBundleV1 | null
  evidence_snapshot_sha256: string | null
  evidence_status: EvidenceStatus | null
  standard_evidence_status: StandardEvidenceStatus | null
  reference_case_status: ReferenceCaseStatus | null
}

export interface LegacyEvidenceSource {
  source_type?: string
  indicator?: string
  standard_version_id?: number
  standard_rule_id?: number
  anonymous_case_code?: string
  status?: string
  [key: string]: unknown
}

export type EvidenceStatus = 'complete' | 'partial'
export type StandardEvidenceStatus = 'available' | 'context_incomplete' | 'not_applicable' | 'conflict'
export type ReferenceCaseStatus = 'available' | 'no_eligible_cases' | 'insufficient_comparability' | 'reference_query_failed' | 'reference_index_stale'
export interface EvidenceSourceLocator {
  segment_id: number
  section_title: string | null
  paragraph_index: number | null
  table_index: number | null
  row_index: number | null
  column_index: number | null
  page_number: number | null
  raw_text: string
}
export interface StandardRuleEvidence {
  rule_id: number
  indicator: string
  display_name: string
  status: 'calculable' | 'evidence_only' | 'missing_context' | 'not_applicable' | 'conflict'
  machine_actionability: 'calculable' | 'evidence-only' | 'blocked'
  unit: string | null
  lower: number | null
  upper: number | null
  lower_inclusive: boolean
  upper_inclusive: boolean
  latest_value: number | null
  numeric_interpretation: 'within_range' | 'above_range' | 'below_range' | null
  interpretation: string | null
  applicability: Record<string, unknown>
  applicability_hash: string | null
  conditions: { status: 'matched' | 'missing' | 'mismatched'; satisfied: string[]; missing: string[]; mismatched: string[] }
  source: EvidenceSourceLocator
}
export interface ReferenceCaseEvidenceItem {
  anonymous_case_code: string
  features: {
    baseline_stage: string
    prediction_task: string
    age: number | null
    sex: 'male' | 'female' | null
    as_of: string
    visit_count: number
    observation_span_days: number
    feature_summary: Record<string, unknown>
    measurement_context_summary: Record<string, unknown>
  }
  score: { conditional_similarity: number; coverage: number; ranking_score: number; available_weight: number; dimensions: Record<string, number> }
  comparisons: { indicator: string; status: 'comparable' | 'excluded'; score: number | null; reason: string | null }[]
  outcome_status: 'positive' | 'negative' | 'unknown'
  outcome_value: Record<string, unknown>
  outcome_source: string
  outcome_reliability: 'low' | 'medium' | 'high'
  source_trace: Record<string, unknown>
}
export interface EvidenceBundleV1 {
  schema_version: 'longitudinal_evidence_bundle.v1'
  evidence_bundle_id: string
  generation_batch_id: string
  disease_code: 'fatty_liver' | 'ad'
  created_at: string
  standard: {
    status: StandardEvidenceStatus
    document: { document_id: number; title: string; filename: string; content_sha256: string; issuer: string | null; publication_date: string | null; external_identifier: string | null; source_url: string | null }
    version: { version_id: number; version_label: string; content_sha256: string; parser_version: string; approved_at: string | null; effective_from: string | null }
    rules: StandardRuleEvidence[]
    warnings: string[]
  }
  reference_cases: {
    status: ReferenceCaseStatus
    data_release: { logical_dataset: string; dataset_release_id: string | null; data_content_sha256: string | null }
    algorithm_version: 'reference_similarity.v1'
    configuration_hash: string
    pool_statistics: { total_windows: number; eligible_windows: number; comparable_windows: number; returned_windows: number; exclusion_counts: Record<string, number> }
    cases: ReferenceCaseEvidenceItem[]
    warnings: string[]
  }
  warnings: string[]
  integrity: { canonicalization_version: 'v1'; hash_algorithm: 'sha256'; evidence_snapshot_sha256: string | null }
}

export interface LongitudinalVisit {
  id: number
  case_id: number
  visit_date: string
  visit_index: number
  indicators: IndicatorInput[]
  notes?: string | null
  visit_context?: VisitContext
}

export type BaselineStage =
  | 'pre_cirrhosis'
  | 'cirrhosis'
  | 'suspected_cirrhosis'
  | 'hcc'
  | 'normal'
  | 'mci'
  | 'pre_dementia'
  | 'dementia'

export interface LongitudinalCaseDisease {
  id: number
  code: string
  name: string
  operator_enabled: boolean
}

export interface LongitudinalCase {
  id: number
  user_id: number
  disease_id: number
  anonymous_case_code: string | null
  age: number | null
  sex?: 'male' | 'female' | null
  baseline_stage?: BaselineStage | string | null
  notes?: string | null
  status: 'active' | 'archived'
  visits: LongitudinalVisit[]
  created_at?: string
  updated_at?: string
  disease: LongitudinalCaseDisease
}

export interface LongitudinalCaseCreatePayload {
  disease_id: number
  age: number
  sex: 'male' | 'female'
  baseline_stage: BaselineStage
  notes: string | null
  visits: LongitudinalVisitInput[]
}

export interface LongitudinalCaseSavePayload {
  age: number
  sex: 'male' | 'female'
  baseline_stage: BaselineStage
  notes: string | null
  visits: LongitudinalVisitInput[]
  change_reason?: string | null
}

export interface LongitudinalVisitInput {
  visit_date: string
  indicators: IndicatorInput[]
  notes?: string | null
  visit_context?: VisitContext
}

export interface OperatorCaseListParams {
  q?: string
  disease_id?: number
  status?: LongitudinalCaseStatus
  skip?: number
  limit?: number
}

export interface OperatorCaseListOut {
  cases: LongitudinalCase[]
  total: number
  skip: number
  limit: number
}

export interface OperatorCaseReadinessBlocker {
  code: string
  message: string
}

export interface OperatorCaseReportReadiness {
  ready: boolean
  case_ready: boolean
  timeline_ready: boolean
  model_ready: boolean
  visit_count: number
  minimum_visits: number | null
  blockers: OperatorCaseReadinessBlocker[]
}

export type LongitudinalCaseStatus = 'active' | 'archived'

export interface LongitudinalCaseStatusChangePayload {
  expected_status: LongitudinalCaseStatus
  status: LongitudinalCaseStatus
  reason?: string | null
}

export interface LongitudinalRuntimeStatus {
  artifact_type: 'outcome' | 'stage' | 'trend'
  task?: string | null
  status: 'available' | 'missing' | 'incompatible' | 'disabled'
  reason_code: string
  lifecycle_status?: 'candidate' | 'reviewed' | 'enabled' | null
  model_id?: string | null
  model_name?: string | null
  model_version?: string | null
  artifact_sha256?: string | null
  target?: string | null
  horizon_days?: number | null
  feature_version?: string | null
  score_semantics?: string | null
  calibration_status?: string | null
}

export interface LongitudinalStageRuntimeStatus extends LongitudinalRuntimeStatus {
  artifact_type: 'stage'
}

export interface LongitudinalModelStatuses {
  outcome: LongitudinalRuntimeStatus
  stage: LongitudinalStageRuntimeStatus
  trend: LongitudinalRuntimeStatus
}

export interface LongitudinalStageProjection {
  status: 'available' | 'not_estimated'
  likely_next_stage?: string | null
  stage_candidates?: Array<{ stage: string; model_score: number }>
}

export interface LongitudinalOutcomePrediction {
  risk_band?: string | null
  risk_score?: number | null
  score_semantics?: 'model_score'
  stage_projection: LongitudinalStageProjection
  confidence?: Record<string, unknown>
}

export interface LongitudinalObservedIndicator {
  first?: number | null
  last?: number | null
  delta?: number | null
  n_observations?: number
  unit?: string | null
  unit_state?: string | null
  series?: Array<{ visit_date: string; value: number; unit?: string | null }>
}

export interface LongitudinalObservation {
  visit_count?: number
  observation_span_days?: number
  indicators?: Record<string, LongitudinalObservedIndicator>
  [key: string]: unknown
}

export interface LongitudinalTrendPrediction {
  indicator: string
  unit?: string | null
  observed?: LongitudinalObservedIndicator
  reference?: Record<string, unknown>
  forecast: {
    direction?: 'rising' | 'stable' | 'falling' | null
    status: 'direction_only' | 'not_estimable' | 'not_available'
    window?: 'next_followup'
    projected_value?: null
    prediction_interval?: null
    basis?: string | null
  }
  importance?: Record<string, unknown>
}

export interface LongitudinalTrendPredictionV3 extends LongitudinalTrendPrediction {
  model_status: LongitudinalRuntimeStatus
}

export interface LongitudinalReleaseSetIdentity {
  dataset: 'fatty_liver' | 'ad'
  release_set_id: string
  release_set_sha256: string
  data_release_id: string
  split_sha256: string
}

interface LongitudinalPredictionBase {
  disease: Record<string, unknown>
  observation: LongitudinalObservation
  outcome_prediction: LongitudinalOutcomePrediction
  evidence?: Record<string, unknown>
  warnings: string[]
}

export interface LongitudinalPredictionV1 extends LongitudinalPredictionBase {
  schema_version: 'longitudinal_prediction.v1'
  trend_predictions: LongitudinalTrendPrediction[]
}

export interface LongitudinalPredictionV2 extends LongitudinalPredictionBase {
  schema_version: 'longitudinal_prediction.v2'
  trend_predictions: LongitudinalTrendPrediction[]
  model_status: LongitudinalModelStatuses
  progression_signals?: Record<string, any>
}

export interface LongitudinalPredictionV3 extends LongitudinalPredictionBase {
  schema_version: 'longitudinal_prediction.v3'
  release_set: LongitudinalReleaseSetIdentity
  trend_predictions: LongitudinalTrendPredictionV3[]
  model_status: LongitudinalModelStatuses
  progression_signals?: Record<string, any>
}

export type LongitudinalPrediction =
  LongitudinalPredictionV1 | LongitudinalPredictionV2 | LongitudinalPredictionV3

export function listLongitudinalCases(params: OperatorCaseListParams = {}): Promise<OperatorCaseListOut> {
  return request.get('/v1/operator/longitudinal-cases', { params })
}

export function createLongitudinalCase(data: LongitudinalCaseCreatePayload, idempotencyKey: string): Promise<LongitudinalCase> {
  return request.post('/v1/operator/longitudinal-cases', data, {
    headers: { 'Idempotency-Key': idempotencyKey },
  })
}

export function saveLongitudinalCase(id: number, data: LongitudinalCaseSavePayload): Promise<LongitudinalCase> {
  return request.put(`/v1/operator/longitudinal-cases/${id}`, data)
}

export function deleteLongitudinalCase(id: number): Promise<void> {
  return request.delete(`/v1/operator/longitudinal-cases/${id}`)
}

export function getLongitudinalCaseReportReadiness(caseId: number): Promise<OperatorCaseReportReadiness> {
  return request.get(`/v1/operator/longitudinal-cases/${caseId}/report-readiness`)
}

// ===== 疾病 / 病例 / 报告 API =====
export function listDiseases(): Promise<Disease[]> {
  return request.get('/v1/operator/diseases')
}

export function listOperatorIndicatorCatalog(code: string): Promise<OperatorIndicatorCatalog> {
  return request.get(`/v1/operator/diseases/${encodeURIComponent(code)}/indicators`)
}

export function updateLongitudinalCaseStatus(id: number, data: LongitudinalCaseStatusChangePayload): Promise<LongitudinalCase> {
  return request.put(`/v1/operator/longitudinal-cases/${id}/status`, data)
}

export function getReport(reportId: number): Promise<ReportDetail> {
  return request.get(`/v1/operator/reports/${reportId}`)
}

export interface DeleteReportResult {deleted:true;cleanup_state:'complete'|'pending';message?:string}

export function deleteReport(reportId: number): Promise<void | DeleteReportResult> {
  return request.delete(`/v1/operator/reports/${reportId}`)
}

export async function downloadReport(reportId: number, _filename?: string): Promise<void> {
  const {downloadOriginal}=await import('./report-archive')
  await downloadOriginal(reportId)
}
