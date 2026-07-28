import request from './request'

export interface Session {
  id: number
  user_id: number
  title: string
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  session_id: number
  role: string
  content: string
  sources: any[]
  is_no_knowledge?: boolean
  is_error?: boolean
  created_at: string
}

export interface SessionDetail extends Session {
  messages: Message[]
}

export interface AskCallbacks {
  onDelta: (text: string) => void
  onSources: (sources: any[]) => void
  onStage?: (stage: string) => void
  onDanger?: (level: string, advice: string) => void
  onDone: (status: string, warning?: string, messageId?: number, userMessageId?: number, title?: string, isNoKnowledge?: boolean) => void
  onError: (msg: string, messageId?: number, title?: string) => void
}

export function listSessions(): Promise<Session[]> {
  return request.get('/v1/chat/sessions')
}

export function getSession(sessionId: number): Promise<SessionDetail> {
  return request.get(`/v1/chat/sessions/${sessionId}`)
}

export function createSession(title?: string): Promise<Session> {
  return request.post('/v1/chat/sessions', { title })
}

export function deleteSession(sessionId: number): Promise<void> {
  return request.delete(`/v1/chat/sessions/${sessionId}`)
}

// ---- 文档完整内容（查看完整病例） ----

export interface DocumentChunk {
  id: number
  content: string
  page_number: number | null
  chunk_index: number
}

export interface DocumentContent {
  id: number
  title: string
  file_type: string
  chunks: DocumentChunk[]
}

export function getDocumentContent(documentId: number): Promise<DocumentContent> {
  return request.get(`/v1/documents/${documentId}/content`)
}

export async function getProtectedImage(url: string): Promise<Blob> {
  const normalized = url.startsWith('/uploads/images/')
    ? url.replace('/uploads/images/', '/v1/files/images/')
    : url.replace(/^\/api/, '')
  return request.get(normalized, { responseType: 'blob' })
}

function parseSSEEvent(raw: string, callbacks: AskCallbacks) {
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
    if (event === 'delta') {
      callbacks.onDelta(payload.content || '')
    } else if (event === 'sources') {
      callbacks.onSources(payload.sources || [])
    } else if (event === 'done') {
      callbacks.onDone(payload.status, payload.warning, payload.message_id, payload.user_message_id, payload.title, payload.is_no_knowledge)
    } else if (event === 'stage') {
      callbacks.onStage?.(payload.stage || '')
    } else if (event === 'danger') {
      callbacks.onDanger?.(payload.level || '', payload.advice || '')
    } else if (event === 'error') {
      callbacks.onError(payload.detail || '生成失败', payload.message_id, payload.title)
    }
  } catch {
    // 忽略无法解析的事件
  }
}

export function askStream(
  sessionId: number,
  content: string,
  callbacks: AskCallbacks,
  retryMessageId?: number,
  clientRequestId?: string,
  departmentId?: number | null,
): () => void {
  const abortController = new AbortController()
  const token = localStorage.getItem('token')

  const body: Record<string, unknown> = {
    content,
    retry_message_id: retryMessageId,
    client_request_id: clientRequestId,
  }
  if (departmentId !== undefined && departmentId !== null) {
    body.department_id = departmentId
  }

  fetch(`/api/v1/chat/sessions/${sessionId}/ask`, {
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
          parseSSEEvent(part, callbacks)
        }
      }
      if (buffer.trim()) {
        parseSSEEvent(buffer, callbacks)
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message || '网络错误')
      }
    })

  return () => abortController.abort()
}
