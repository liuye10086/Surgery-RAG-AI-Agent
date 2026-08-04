import request from './request'

// ===== 预测分析类型 =====
export interface IndicatorInput {
  name: string
  value: number
  unit: string
}

export interface Disease {
  id: number
  name: string
  description: string | null
  case_count: number
  created_at: string
}

export interface CaseRecord {
  id: number
  disease_id: number
  patient_label: string | null
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

export interface PredictionResult {
  score: number
  band: string
  probability_range: number[]
  abnormal_count: number
  sample_size: number
  insufficient_sample: boolean
}

export interface IndicatorAnalysis {
  name: string
  value: number
  unit: string
  lower: number | null
  upper: number | null
  lower_inclusive: boolean
  upper_inclusive: boolean
  is_abnormal: boolean
  deviation_pct: number
  present_rate_in_cases: number
  abnormal_rate_in_cases: number
  risk_weight: number
}

export interface OperatorDocument {
  id: number
  title: string | null
  filename: string
  access_scope: string
  status: string
  sync_ready: boolean
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
  indicators: Record<string, unknown>[]
  prediction_result: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ReportDetail extends ReportListItem {
  content: string
  sources: any[]
  retrieval_meta: any
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
  onIndicators?: (analyses: IndicatorAnalysis[], prediction: PredictionResult) => void
}

// ===== 疾病 / 病例 / 参考范围 API =====
export function listDiseases(): Promise<Disease[]> {
  return request.get('/v1/operator/diseases')
}

export function createDisease(data: { name: string; description?: string }): Promise<Disease> {
  return request.post('/v1/operator/diseases', data)
}

export function updateDisease(id: number, data: { name?: string; description?: string }): Promise<Disease> {
  return request.put(`/v1/operator/diseases/${id}`, data)
}

export function deleteDisease(id: number): Promise<void> {
  return request.delete(`/v1/operator/diseases/${id}`)
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

// 返回类型含 dropped：后端 sync_reference_ranges 返回 {inserted, dropped, document_id}
export function syncReferenceRanges(documentId: number): Promise<{ inserted: number; dropped: number; document_id: number }> {
  return request.post('/v1/operator/reference-ranges/sync', { document_id: documentId })
}

export function listReferenceRanges(): Promise<ReferenceRange[]> {
  return request.get('/v1/operator/reference-ranges')
}

// operator 范围文档列表：不能复用 admin 的 listDocuments（ai_operator 无权访问 admin API）
export function listOperatorDocuments(): Promise<OperatorDocument[]> {
  return request.get('/v1/operator/documents')
}

export function listReports(skip = 0, limit = 20): Promise<ReportListOut> {
  return request.get('/v1/operator/reports', { params: { skip, limit } })
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

/**
 * SSE 流式生成报告（POST，使用 fetch + ReadableStream）。
 * 返回 abort 函数用于取消。
 */
export function generateReportStream(
  query: string,
  departmentIds: number[] | null,
  analysisBackend: string,
  callbacks: ReportStreamCallbacks,
): () => void {
  const abortController = new AbortController()
  const token = localStorage.getItem('token')

  const body: Record<string, unknown> = {
    query,
    analysis_backend: analysisBackend,
  }
  if (departmentIds && departmentIds.length > 0) {
    body.department_ids = departmentIds
  }

  fetch('/api/v1/operator/reports', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: token ? `Bearer ${token}` : '',
    },
    body: JSON.stringify(body),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        callbacks.onError(data.detail || `请求失败 (${response.status})`)
        return
      }
      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError('无法读取响应流')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          if (!part.trim()) continue
          parseOperatorSSE(part, callbacks)
        }
      }
      if (buffer.trim()) {
        parseOperatorSSE(buffer, callbacks)
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message || '网络错误')
      }
    })

  return () => abortController.abort()
}

/**
 * SSE 流式生成预测报告（POST，使用 fetch + ReadableStream）。
 * 事件：stage / indicators / delta / sources / done / error。
 * 返回 abort 函数用于取消。
 */
export function generatePredictionStream(
  request: { disease_id: number; indicators: IndicatorInput[]; patient_summary?: string },
  callbacks: PredictionStreamCallbacks,
): () => void {
  const abortController = new AbortController()
  const token = localStorage.getItem('token')

  fetch('/api/v1/operator/reports', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: token ? `Bearer ${token}` : '',
    },
    body: JSON.stringify(request),
    signal: abortController.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const data = await response.json().catch(() => ({}))
        callbacks.onError(data.detail || `请求失败 (${response.status})`)
        return
      }
      const reader = response.body?.getReader()
      if (!reader) {
        callbacks.onError('无法读取响应流')
        return
      }
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''
        for (const part of parts) {
          if (!part.trim()) continue
          parseOperatorSSE(part, callbacks)
        }
      }
      if (buffer.trim()) {
        parseOperatorSSE(buffer, callbacks)
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message || '网络错误')
      }
    })

  return () => abortController.abort()
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
      case 'indicators':
        callbacks.onIndicators?.(payload.indicators || [], payload.probability || {})
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
        callbacks.onError(payload.error || '生成失败')
        break
    }
  } catch {
    // 忽略无法解析的事件
  }
}
