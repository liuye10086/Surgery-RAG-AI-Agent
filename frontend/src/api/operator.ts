import request from './request'

// ===== 预测分析类型 =====
export interface IndicatorInput {
  name: string
  value: number | null
  unit: string
}

export interface Disease {
  id: number
  code: string
  name: string
  description: string | null
  operator_enabled: boolean
  created_at: string
}

export interface CaseRecord {
  id: number
  disease_id: number
  patient_label: string | null
  anonymous_case_code: string | null
  indicators: IndicatorInput[]
  confirmed: boolean
  metadata: Record<string, unknown>
  created_at: string
}

export interface ReferenceRange {
  id: number
  indicator_name: string
  name_cn: string | null
  unit: string | null
  lower: number | null
  upper: number | null
  lower_inclusive: boolean
  upper_inclusive: boolean
  category: string | null
}

export interface ReportListItem {
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
  prediction_result: LongitudinalPrediction | null
  created_at: string
  updated_at: string
}

export interface ReportDetail extends ReportListItem {
  content: string
  sources: any[]
  retrieval_meta: any
}

export interface LongitudinalVisit {
  id: number
  case_id: number
  visit_date: string
  visit_index: number
  indicators: IndicatorInput[]
  notes?: string | null
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
  patient_label: string
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
  patient_label?: string
  age: number
  sex?: 'male' | 'female' | null
  baseline_stage?: BaselineStage | null
  notes?: string | null
  visits: Array<{ visit_date: string; indicators: IndicatorInput[]; notes?: string | null }>
}

export interface LongitudinalCaseUpdatePayload {
  age?: number
  sex?: 'male' | 'female' | null
  baseline_stage?: BaselineStage | null
  notes?: string | null
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

export interface LongitudinalModelStatuses {
  outcome: LongitudinalRuntimeStatus
  stage: LongitudinalRuntimeStatus
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

export function listLongitudinalCases(diseaseId?: number, status?: LongitudinalCaseStatus): Promise<{ cases: LongitudinalCase[]; total: number }> {
  return request.get('/v1/operator/longitudinal-cases', { params: { ...(diseaseId ? { disease_id: diseaseId } : {}), ...(status ? { status } : {}) } })
}

export function createLongitudinalCase(data: LongitudinalCaseCreatePayload): Promise<LongitudinalCase> {
  return request.post('/v1/operator/longitudinal-cases', data)
}

export function updateLongitudinalCase(id: number, data: LongitudinalCaseUpdatePayload): Promise<LongitudinalCase> {
  return request.put(`/v1/operator/longitudinal-cases/${id}`, data)
}

export function deleteLongitudinalCase(id: number): Promise<void> {
  return request.delete(`/v1/operator/longitudinal-cases/${id}`)
}

export function addLongitudinalVisit(caseId: number, data: { visit_date: string; indicators: IndicatorInput[]; notes?: string }): Promise<LongitudinalVisit> {
  return request.post(`/v1/operator/longitudinal-cases/${caseId}/visits`, data)
}

export function replaceLongitudinalVisits(caseId: number, visits: Array<{ visit_date: string; indicators: IndicatorInput[]; notes?: string | null }>): Promise<LongitudinalVisit[]> {
  return request.put(`/v1/operator/longitudinal-cases/${caseId}/visits`, { visits })
}

export function updateLongitudinalVisit(caseId: number, visitId: number, data: Record<string, unknown>): Promise<LongitudinalVisit> {
  return request.put(`/v1/operator/longitudinal-cases/${caseId}/visits/${visitId}`, data)
}

export function deleteLongitudinalVisit(caseId: number, visitId: number): Promise<void> {
  return request.delete(`/v1/operator/longitudinal-cases/${caseId}/visits/${visitId}`)
}

export function generateLongitudinalReportStream(caseId: number, callbacks: PredictionStreamCallbacks, modelOptions: Record<string, unknown> = {}): () => void {
  const controller = new AbortController()
  const token = localStorage.getItem('token')
  fetch(`/api/v1/operator/longitudinal-cases/${caseId}/reports`, { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: token ? `Bearer ${token}` : '' }, body: JSON.stringify({ model_options: modelOptions }), signal: controller.signal })
    .then(async (response) => {
      if (!response.ok) { callbacks.onError((await response.json().catch(() => ({}))).detail || `请求失败 (${response.status})`); return }
      const reader = response.body?.getReader()
      if (!reader) { callbacks.onError('无法读取响应流'); return }
      const decoder = new TextDecoder(); let buffer = ''
      while (true) { const { done, value } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true }); const parts = buffer.split('\n\n'); buffer = parts.pop() || ''; for (const part of parts) if (part.trim()) parseOperatorSSE(part, callbacks) }
      if (buffer.trim()) parseOperatorSSE(buffer, callbacks)
    })
    .catch((error) => { if (error.name !== 'AbortError') callbacks.onError(error.message || '网络错误') })
  return () => controller.abort()
}

export interface ReportListOut {
  reports: ReportListItem[]
  total: number
}

export interface ReportStreamCallbacks {
  onStage: (stage: string, message: string) => void
  onDelta: (content: string) => void
  onSources: (sources: any[]) => void
  onDone: (reportId: number) => void
  onError: (error: string) => void
}

export interface PredictionStreamCallbacks extends ReportStreamCallbacks {
  onPrediction?: (prediction: LongitudinalPrediction) => void
}

// ===== 疾病 / 病例 / 参考范围 API =====
export function listDiseases(): Promise<Disease[]> {
  return request.get('/v1/operator/diseases')
}

export function updateLongitudinalCaseStatus(id: number, data: LongitudinalCaseStatusChangePayload): Promise<LongitudinalCase> {
  return request.put(`/v1/operator/longitudinal-cases/${id}/status`, data)
}

export function listCases(diseaseId?: number): Promise<{ total: number; items: CaseRecord[] }> {
  return request.get('/v1/operator/cases', { params: { disease_id: diseaseId } })
}

export function createCase(data: unknown): Promise<CaseRecord> {
  return request.post('/v1/operator/cases', data)
}

export function updateCase(id: number, data: unknown): Promise<CaseRecord> {
  return request.put(`/v1/operator/cases/${id}`, data)
}

export function deleteCase(id: number): Promise<void> {
  return request.delete(`/v1/operator/cases/${id}`)
}

export function listReferenceRanges(): Promise<ReferenceRange[]> {
  return request.get('/v1/operator/reference-ranges')
}

export function listReports(skip = 0, limit = 20, analysisType?: string): Promise<ReportListOut> {
  return request.get('/v1/operator/reports', { params: { skip, limit, analysis_type: analysisType } })
}

export function getReport(reportId: number): Promise<ReportDetail> {
  return request.get(`/v1/operator/reports/${reportId}`)
}

export function deleteReport(reportId: number): Promise<void> {
  return request.delete(`/v1/operator/reports/${reportId}`)
}

export async function downloadReport(reportId: number, filename?: string): Promise<void> {
  const token = localStorage.getItem('token')
  const response = await fetch(`/api/v1/operator/reports/${reportId}/download`, {
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
    },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `下载失败 (${response.status})`)
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || `report-${reportId}.pdf`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function parseOperatorSSE(raw: string, callbacks: PredictionStreamCallbacks) {
  const lines = raw.split('\n')
  let event = ''
  let data = ''
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data = line.slice(5).trim()
    }
  }
  if (!event || !data) return
  try {
    const payload = JSON.parse(data)
    switch (event) {
      case 'stage':
        callbacks.onStage(payload.stage || '', payload.message || '')
        break
      case 'prediction':
        callbacks.onPrediction?.(payload as LongitudinalPrediction)
        break
      case 'delta':
        callbacks.onDelta(payload.content || '')
        break
      case 'sources':
        callbacks.onSources(payload.sources || [])
        break
      case 'done':
        callbacks.onDone(payload.report_id || 0)
        break
      case 'error':
        callbacks.onError(payload.error || payload.message || '生成失败')
        break
    }
  } catch {
    // 忽略无法解析的事件
  }
}
