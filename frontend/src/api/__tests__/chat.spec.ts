import { afterEach, describe, expect, it, vi } from 'vitest'
import { askStream } from '../chat'

afterEach(() => vi.unstubAllGlobals())

describe('chat SSE error transport', () => {
  it('forwards the persisted user ID from a server error event', async () => {
    const payload = { detail: 'model failed', message_id: 12, title: 'question', user_message_id: 11 }
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      body: new ReadableStream({ start(controller) {
        controller.enqueue(new TextEncoder().encode(`event: error\ndata: ${JSON.stringify(payload)}\n\n`))
        controller.close()
      } }),
    })))
    const onError = vi.fn()
    askStream(1, 'question', { onDelta: vi.fn(), onSources: vi.fn(), onDone: vi.fn(), onError })
    await vi.waitFor(() => expect(onError).toHaveBeenCalledOnce())
    expect(onError).toHaveBeenCalledWith('model failed', 12, 'question', 11)
  })
})
