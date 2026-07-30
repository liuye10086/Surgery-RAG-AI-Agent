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
    currentSession.value = await getSession(sessionId)
  }

  async function newSession(title?: string) {
    const session = await createSession(title)
    sessions.value.unshift(session)
    currentSession.value = { ...session, messages: [] }
    return session
  }

  async function sendMessage(content: string) {
    if (!currentSession.value) return
    dangerState.value = null
    const sessionId = currentSession.value.id

    const clientRequestId = crypto.randomUUID()
    const userMessage = reactive<Message>({
      id: -Date.now(),
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
      id: -Date.now(),
      session_id: sessionId,
      role: 'assistant',
      content: '',
      sources: [],
      is_no_knowledge: false,
      is_error: false,
      created_at: new Date().toISOString(),
    })
    currentSession.value.messages.push(assistantMessage)

    loading.value = 'retrieving'

    // 取消上一个正在进行的 SSE 流（如果有）
    currentAbort.value?.()
    currentAbort.value = askStream(
      sessionId,
      content,
      buildCallbacks(assistantMessage, sessionId, userMessage),
      undefined,
      clientRequestId,
      selectedDepartmentId.value,
    )

    // 会话标题由后端 LLM 自动生成，通过 SSE done 事件回传更新
  }

  function retryMessage(assistantMessage: Message, userContent: string) {
    if (!currentSession.value) return

    // 重置错误状态，复用同一个占位消息
    assistantMessage.content = ''
    assistantMessage.sources = []
    assistantMessage.is_no_knowledge = false
    assistantMessage.is_error = false
    loading.value = 'retrieving'

    // 取消上一个正在进行的 SSE 流（如果有）
    currentAbort.value?.()
    currentAbort.value = askStream(
      currentSession.value.id,
      userContent,
      buildCallbacks(assistantMessage, currentSession.value.id),
      assistantMessage.id,
      undefined,
      selectedDepartmentId.value,
    )
  }

  function abort() {
    currentAbort.value?.()
    currentAbort.value = null
  }

  async function removeSession(sessionId: number) {
    await deleteSession(sessionId)
    // 从会话列表中移除
    sessions.value = sessions.value.filter((s) => s.id !== sessionId)
    // 如果删除的是当前会话，清空当前会话
    if (currentSession.value?.id === sessionId) {
      currentSession.value = null
    }
  }

  function buildCallbacks(assistantMessage: Message, sessionId?: number, userMessage?: Message) {
    function applyTitle(title: string) {
      if (!title) return
      if (currentSession.value) {
        currentSession.value.title = title
      }
      if (sessionId != null) {
        const idx = sessions.value.findIndex((s) => s.id === sessionId)
        if (idx >= 0) sessions.value[idx].title = title
      }
    }

    return {
      onDelta: (text: string) => {
        assistantMessage.content += text
      },
      onSources: (sources: any[]) => {
        assistantMessage.sources = sources
      },
      onStage: (stage: string) => {
        if (stage === 'generating') {
          loading.value = 'generating'
        }
      },
      onDanger: (level: string, advice: string) => {
        dangerState.value = { level, advice }
        // 持久化到 localStorage，确保会话历史回访时警告仍可见
        if (userMessage) {
          dangerByMessageId.value = { ...dangerByMessageId.value, [userMessage.id]: { level, advice } }
          saveDangerToStorage(dangerByMessageId.value)
        }
      },
      onDone: (status: string, warning?: string, messageId?: number, userMessageId?: number, title?: string, isNoKnowledge?: boolean) => {
        if (status === 'no_knowledge' || isNoKnowledge) {
          assistantMessage.is_no_knowledge = true
          assistantMessage.content = warning || '当前知识库中未找到足够依据，无法回答该问题。'
        }
        if (messageId) {
          assistantMessage.id = messageId
        }
        if (userMessage && userMessageId) {
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
        if (title) {
          applyTitle(title)
        }
        loading.value = false
        currentAbort.value = null
      },
      onError: (msg: string, messageId?: number, title?: string) => {
        assistantMessage.content = `出错了：${msg}`
        assistantMessage.is_error = true
        if (messageId) {
          assistantMessage.id = messageId
        }
        if (title) {
          applyTitle(title)
        }
        loading.value = false
        currentAbort.value = null
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
