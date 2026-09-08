import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { askStream, createSession, deleteSession, getSession, listSessions, type Message, type Session, type SessionDetail } from '@/api/chat'

const DANGER_STORAGE_KEY = 'surgery_rag_danger_state'
const DEPARTMENT_STORAGE_KEY = 'surgery_rag_selected_department_id'

function loadDangerFromStorage(): Record<number, { level: string; advice: string }> {
  try {
    const raw = localStorage.getItem(DANGER_STORAGE_KEY)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

function saveDangerToStorage(data: Record<number, { level: string; advice: string }>) {
  try {
    localStorage.setItem(DANGER_STORAGE_KEY, JSON.stringify(data))
  } catch { /* 忽略存储满等异常 */ }
}

function normalizeDepartmentId(id: unknown): number | null {
  const normalized = Number(id)
  return Number.isFinite(normalized) ? normalized : null
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<Session[]>([])
  const currentSession = ref<SessionDetail | null>(null)
  const loading = ref<string | boolean>(false)
  const currentAbort = ref<(() => void) | null>(null)
  let navigationGeneration = 0
  let temporaryId = -Date.now()
  let activeRequest: { assistantMessage: Message } | null = null
  const requestContexts = new WeakMap<Message, { clientRequestId: string; userMessage: Message; departmentId: number | null }>()
  const dangerState = ref<{ level: string; advice: string } | null>(null)
  // 持久化：messageId → danger 映射，会话历史回访时可恢复
  const dangerByMessageId = ref<Record<number, { level: string; advice: string }>>(loadDangerFromStorage())

  // 科室筛选：持久化到 localStorage
  function _loadDepartmentId(): number | null {
    try {
      const raw = localStorage.getItem(DEPARTMENT_STORAGE_KEY)
      const id = raw ? normalizeDepartmentId(raw) : null
      if (raw && id === null) {
        localStorage.removeItem(DEPARTMENT_STORAGE_KEY)
      }
      return id
    } catch {
      return null
    }
  }
  const selectedDepartmentId = ref<number | null>(_loadDepartmentId())

  function setSelectedDepartmentId(id: number | null | undefined) {
    const normalizedId = normalizeDepartmentId(id)
    selectedDepartmentId.value = normalizedId
    try {
      if (normalizedId === null) {
        localStorage.removeItem(DEPARTMENT_STORAGE_KEY)
      } else {
        localStorage.setItem(DEPARTMENT_STORAGE_KEY, String(normalizedId))
      }
    } catch { /* 忽略 */ }
  }

  async function loadSessions() {
    sessions.value = await listSessions()
  }

  async function loadSession(sessionId: number) {
    const generation = ++navigationGeneration
    abort()
    dangerState.value = null
    const session = await getSession(sessionId)
    if (generation === navigationGeneration) currentSession.value = session
  }

  async function newSession(title?: string) {
    const generation = ++navigationGeneration
    abort()
    dangerState.value = null
    const session = await createSession(title)
    sessions.value.unshift(session)
    if (generation === navigationGeneration) currentSession.value = { ...session, messages: [] }
    return session
  }

  async function sendMessage(content: string) {
    if (!currentSession.value) return
    ++navigationGeneration
    abort()
    dangerState.value = null
    const sessionId = currentSession.value.id

    const clientRequestId = crypto.randomUUID()
    const userMessage = reactive<Message>({
      id: temporaryId--,
      session_id: sessionId,
      role: 'user',
      content,
      sources: [],
      is_no_knowledge: false,
      is_error: false,
      created_at: new Date().toISOString(),
    })
    currentSession.value.messages.push(userMessage)

    // 预占一条 assistant 消息用于流式渲染，必须使用 reactive 对象才能让后续 onDelta 更新触发 UI
    const assistantMessage = reactive<Message>({
      id: temporaryId--,
      session_id: sessionId,
      role: 'assistant',
      content: '',
      sources: [],
      is_no_knowledge: false,
      is_error: false,
      created_at: new Date().toISOString(),
    })
    currentSession.value.messages.push(assistantMessage)

    requestContexts.set(assistantMessage, { clientRequestId, userMessage, departmentId: selectedDepartmentId.value })
    startRequest(assistantMessage, content)

    // 会话标题由后端 LLM 自动生成，通过 SSE done 事件回传更新
  }

  function retryMessage(assistantMessage: Message, userContent: string) {
    if (!currentSession.value || assistantMessage.session_id !== currentSession.value.id
      || !currentSession.value.messages.includes(assistantMessage)) return
    if (assistantMessage.id <= 0 && !requestContexts.has(assistantMessage)) return
    ++navigationGeneration
    abort()

    // 重置错误状态，复用同一个占位消息
    assistantMessage.content = ''
    assistantMessage.sources = []
    assistantMessage.is_no_knowledge = false
    assistantMessage.is_error = false
    startRequest(assistantMessage, userContent)
  }

  function startRequest(assistantMessage: Message, content: string) {
    const context = requestContexts.get(assistantMessage)
    const index = currentSession.value!.messages.indexOf(assistantMessage)
    const previous = currentSession.value!.messages[index - 1]
    const userMessage = context?.userMessage ?? (previous?.role === 'user' ? previous : undefined)
    const request = { assistantMessage }
    activeRequest = request
    loading.value = 'retrieving'
    const cancel = askStream(
      assistantMessage.session_id,
      content,
      buildCallbacks(assistantMessage, request, userMessage),
      assistantMessage.id > 0 ? assistantMessage.id : undefined,
      assistantMessage.id > 0 ? undefined : context?.clientRequestId,
      context ? context.departmentId : selectedDepartmentId.value,
    )
    // A synchronous terminal callback must not leave a stale cancellation handle.
    if (activeRequest === request) currentAbort.value = cancel
  }

  function abort() {
    const request = activeRequest
    activeRequest = null
    const cancel = currentAbort.value
    currentAbort.value = null
    loading.value = false
    if (request) {
      request.assistantMessage.is_error = true
      if (!request.assistantMessage.content) request.assistantMessage.content = '生成已取消，可重试。'
    }
    cancel?.()
  }

  async function removeSession(sessionId: number) {
    await deleteSession(sessionId)
    // 从会话列表中移除
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    // 如果删除的是当前会话，清空当前会话
    if (currentSession.value?.id === sessionId) {
      ++navigationGeneration
      abort()
      dangerState.value = null
      currentSession.value = null
    }
  }

  function buildCallbacks(assistantMessage: Message, request: { assistantMessage: Message }, userMessage?: Message) {
    const sessionId = assistantMessage.session_id
    const isCurrent = () => activeRequest === request && currentSession.value?.id === sessionId
    function applyUserMessageId(userMessageId?: number) {
      if (!userMessage || !userMessageId) return
      const previousId = userMessage.id
      userMessage.id = userMessageId
      const danger = dangerByMessageId.value[previousId]
      if (danger) {
        const updated = { ...dangerByMessageId.value }
        delete updated[previousId]
        updated[userMessageId] = danger
        dangerByMessageId.value = updated
        saveDangerToStorage(updated)
      }
    }
    function applyTitle(title: string) {
      if (!title) return
      if (currentSession.value?.id === sessionId) {
        currentSession.value.title = title
      }
      if (sessionId != null) {
        const idx = sessions.value.findIndex((s) => s.id === sessionId)
        if (idx >= 0) sessions.value[idx].title = title
      }
    }

    return {
      onDelta: (text: string) => {
        if (!isCurrent()) return
        assistantMessage.content += text
      },
      onSources: (sources: any[]) => {
        if (!isCurrent()) return
        assistantMessage.sources = sources
      },
      onStage: (stage: string) => {
        if (!isCurrent()) return
        if (stage === 'generating') {
          loading.value = 'generating'
        }
      },
      onDanger: (level: string, advice: string) => {
        if (!isCurrent()) return
        const latestUser = [...(currentSession.value?.messages ?? [])].reverse().find((message) => message.role === 'user')
        if (userMessage && latestUser === userMessage) dangerState.value = { level, advice }
        // 持久化到 localStorage，确保会话历史回访时警告仍可见
        if (userMessage) {
          dangerByMessageId.value = { ...dangerByMessageId.value, [userMessage.id]: { level, advice } }
          saveDangerToStorage(dangerByMessageId.value)
        }
      },
      onDone: (status: string, warning?: string, messageId?: number, userMessageId?: number, title?: string, isNoKnowledge?: boolean) => {
        if (!isCurrent()) return
        if (status === 'no_knowledge' || isNoKnowledge) {
          assistantMessage.is_no_knowledge = true
          assistantMessage.content = warning || '当前知识库中未找到足够依据，无法回答该问题。'
        }
        if (messageId) {
          assistantMessage.id = messageId
        }
        applyUserMessageId(userMessageId)
        if (title) {
          applyTitle(title)
        }
        loading.value = false
        currentAbort.value = null
        activeRequest = null
      },
      onError: (msg: string, messageId?: number, title?: string, userMessageId?: number) => {
        if (!isCurrent()) return
        assistantMessage.content = `出错了：${msg}`
        assistantMessage.is_error = true
        if (messageId) {
          assistantMessage.id = messageId
        }
        applyUserMessageId(userMessageId)
        if (title) {
          applyTitle(title)
        }
        loading.value = false
        currentAbort.value = null
        activeRequest = null
      },
    }
  }

  return {
    sessions,
    currentSession,
    loading,
    dangerState,
    dangerByMessageId,
    selectedDepartmentId,
    setSelectedDepartmentId,
    loadSessions,
    loadSession,
    newSession,
    sendMessage,
    retryMessage,
    removeSession,
    abort,
  }
})
