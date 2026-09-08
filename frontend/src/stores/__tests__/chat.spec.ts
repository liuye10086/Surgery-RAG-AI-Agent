import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { askStream, createSession, getSession, type AskCallbacks, type SessionDetail } from '@/api/chat'
import { useChatStore } from '../chat'

vi.mock('@/api/chat', () => ({ askStream: vi.fn(), createSession: vi.fn(), getSession: vi.fn(), listSessions: vi.fn(), deleteSession: vi.fn() }))

const session = (id: number): SessionDetail => ({ id, user_id: 1, title: `session ${id}`, created_at: '', updated_at: '', messages: [] })
const streams: { callbacks: AskCallbacks; abort: ReturnType<typeof vi.fn> }[] = []
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setActivePinia(createPinia())
  streams.length = 0
  vi.mocked(askStream).mockImplementation((_id, _content, callbacks) => {
    const abort = vi.fn()
    streams.push({ callbacks, abort })
    return abort
  })
})

describe('chat stream ownership and retries', () => {
  it('cancels active generation on newSession and reuses a cancelled placeholder when retried', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('question')
    const assistant = store.currentSession.messages[1]!
    const key = vi.mocked(askStream).mock.calls[0]![4]
    store.abort()
    store.retryMessage(assistant, 'question')
    expect(store.currentSession.messages).toHaveLength(2)
    expect(vi.mocked(askStream).mock.calls[1]![4]).toBe(key)
    expect(assistant.is_error).toBe(false)
    vi.mocked(createSession).mockResolvedValue(session(2))
    await store.newSession()
    expect(streams[1]!.abort).toHaveBeenCalledOnce()
    streams[1]!.callbacks.onDanger?.('high', 'late')
    streams[1]!.callbacks.onDone('ok', undefined, 12, 11, 'late')
    expect(store.currentSession.title).toBe('session 2')
    expect(store.loading).toBe(false)
    expect(store.dangerState).toBeNull()
  })

  it('preserves a newer send when an earlier session load resolves late', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    const pending = deferred<SessionDetail>()
    vi.mocked(getSession).mockReturnValue(pending.promise)
    const navigation = store.loadSession(2)
    await store.sendMessage('newer action')
    pending.resolve(session(2))
    await navigation
    streams[0]!.callbacks.onDone('ok', undefined, 12, 11)
    expect(store.currentSession.id).toBe(1)
    expect(store.currentSession.messages.map((m) => m.id)).toEqual([11, 12])
    expect(store.loading).toBe(false)
  })

  it('ignores callbacks after a terminal event and keeps completed content when aborted', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('question')
    streams[0]!.callbacks.onDelta('answer')
    streams[0]!.callbacks.onDone('ok', undefined, 12, 11)
    streams[0]!.callbacks.onError('late')
    streams[0]!.callbacks.onDelta('late')
    store.abort()
    expect(store.currentSession.messages[1]?.content).toBe('answer')
    expect(store.currentSession.messages[1]?.is_error).toBe(false)
  })

  it('settles cancellation and prevents old callbacks from ending a subsequent send', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('first')
    const old = streams[0]!
    store.abort()
    expect(store.loading).toBe(false)
    expect(store.currentSession.messages[1]?.is_error).toBe(true)
    await store.sendMessage('second')
    old.callbacks.onDone('ok', undefined, 20, 19, 'stale')
    old.callbacks.onDelta('stale')
    old.callbacks.onError('stale')
    expect(store.loading).toBe('retrieving')
    expect(store.currentSession.title).toBe('session 1')
    expect(store.currentSession.messages[1]?.id).toBeLessThan(0)
    expect(old.abort).toHaveBeenCalledOnce()
    expect(new Set(store.currentSession.messages.map((m) => m.id)).size).toBe(4)
    streams[1]!.callbacks.onDone('ok', undefined, 22, 21)
    expect(store.loading).toBe(false)
  })

  it('cancels on session switch and ignores every late callback from the old session', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    store.sessions = [session(1), session(2)]
    await store.sendMessage('A')
    const previous = store.currentSession.messages[1]!
    vi.mocked(getSession).mockResolvedValue(session(2))
    await store.loadSession(2)
    await store.sendMessage('B')
    const old = streams[0]!
    old.callbacks.onDelta('late')
    old.callbacks.onSources([{ text: 'late' }])
    old.callbacks.onStage?.('generating')
    old.callbacks.onDanger?.('high', 'late')
    old.callbacks.onDone('ok', undefined, 20, 19, 'A title')
    old.callbacks.onError('late', 20, 'A error title')
    expect(old.abort).toHaveBeenCalledOnce()
    expect(store.currentSession.title).toBe('session 2')
    expect(store.dangerState).toBeNull()
    expect(store.loading).toBe('retrieving')
    expect(previous.sources).toEqual([])
    expect(previous.id).toBeLessThan(0)
    expect(previous.content).not.toContain('late')
  })

  it('keeps the latest navigation when earlier loads or creations resolve late', async () => {
    const store = useChatStore()
    const first = deferred<SessionDetail>()
    vi.mocked(getSession).mockReturnValueOnce(first.promise).mockResolvedValueOnce(session(2))
    const oldLoad = store.loadSession(1)
    await store.loadSession(2)
    first.resolve(session(1))
    await oldLoad
    expect(store.currentSession?.id).toBe(2)
    const created = deferred<SessionDetail>()
    vi.mocked(createSession).mockReturnValueOnce(created.promise)
    const oldCreate = store.newSession()
    vi.mocked(getSession).mockResolvedValueOnce(session(3))
    await store.loadSession(3)
    created.resolve(session(4))
    await oldCreate
    expect(store.currentSession?.id).toBe(3)
  })

  it('resends unconfirmed requests with the original idempotency key and migrates both IDs and danger', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('question')
    const [user, assistant] = store.currentSession.messages
    const userId = user!.id
    streams[0]!.callbacks.onError('network')
    store.retryMessage(assistant!, 'question')
    const initial = vi.mocked(askStream).mock.calls[0]!
    const retry = vi.mocked(askStream).mock.calls[1]!
    expect(retry[3]).toBeUndefined()
    expect(retry[4]).toBe(initial[4])
    expect(retry[4]).toBeTruthy()
    streams[1]!.callbacks.onDanger?.('high', 'seek help')
    streams[1]!.callbacks.onDelta('answer')
    streams[1]!.callbacks.onDone('ok', undefined, 12, 11, 'title')
    expect(store.currentSession.messages).toHaveLength(2)
    expect(user!.id).toBe(11)
    expect(assistant!.id).toBe(12)
    expect(assistant!.content).toBe('answer')
    expect(store.dangerByMessageId[11]?.level).toBe('high')
    expect(store.dangerByMessageId[userId]).toBeUndefined()
    expect(store.loading).toBe(false)
  })

  it('retries a server-confirmed error by positive ID while retaining the user association', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('question')
    const [user, assistant] = store.currentSession.messages
    streams[0]!.callbacks.onDanger?.('high', 'advice')
    const temporaryUserId = user!.id
    streams[0]!.callbacks.onError('model failed', 12, undefined, 11)
    expect(user!.id).toBe(11)
    expect(store.dangerByMessageId[temporaryUserId]).toBeUndefined()
    store.retryMessage(assistant!, 'question')
    expect(vi.mocked(askStream).mock.calls[1]![3]).toBe(12)
    expect(vi.mocked(askStream).mock.calls[1]![4]).toBeUndefined()
    streams[1]!.callbacks.onDone('ok', undefined, 12)
    expect(user!.id).toBe(11)
    expect(store.dangerByMessageId[11]?.level).toBe('high')
    expect(store.currentSession.messages).toHaveLength(2)
  })

  it('clears global danger on new sessions while preserving completed message associations', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('question')
    streams[0]!.callbacks.onDanger?.('high', 'advice')
    streams[0]!.callbacks.onDone('ok', undefined, 12, 11)
    vi.mocked(createSession).mockResolvedValue(session(2))
    await store.newSession()
    expect(store.dangerState).toBeNull()
    expect(store.dangerByMessageId[11]?.level).toBe('high')
  })

  it('associates danger from an older retry with A without showing it on the latest question B', async () => {
    const store = useChatStore()
    store.currentSession = session(1)
    await store.sendMessage('A')
    const [userA, assistantA] = store.currentSession.messages
    streams[0]!.callbacks.onError('network')
    await store.sendMessage('B')
    streams[1]!.callbacks.onDone('ok', undefined, 22, 21)
    store.retryMessage(assistantA!, 'A')
    streams[2]!.callbacks.onDanger?.('high', 'A advice')
    expect(store.dangerState).toBeNull()
    expect(store.dangerByMessageId[userA!.id]?.advice).toBe('A advice')
    expect(store.dangerByMessageId[21]).toBeUndefined()
    streams[2]!.callbacks.onDone('ok', undefined, 12, 11)
    expect(store.dangerByMessageId[11]?.advice).toBe('A advice')
  })
})
