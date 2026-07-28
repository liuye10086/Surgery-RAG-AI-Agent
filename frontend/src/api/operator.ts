import request from './request'

export interface ReportListItem {
  id: number
  user_id: number
  title: string | null
  query: string
  department_ids: number[]
  status: string
  error_message: string | null
  download_count: number
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

function parseOperatorSSE(raw: string, callbacks: ReportStreamCallbacks) {
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
