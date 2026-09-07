import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportHistoryStore } from '@/stores/report-history'
import { listHistory } from '@/api/report-history'
vi.mock('@/api/report-history', () => ({ listHistory: vi.fn() }))

describe('report history', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })
  it('keeps newer history after an older response arrives', async () => {
    const pending: Array<(value: any) => void> = []
    vi.mocked(listHistory).mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    )
    const store = useReportHistoryStore(),
      first = store.refresh(),
      second = store.refresh()
    pending[1]!({ items: [{ id: 2 }], next_cursor: null, has_more: false })
    await second
    pending[0]!({ items: [{ id: 1 }], next_cursor: null, has_more: false })
    await first
    expect(store.items.map((x) => x.id)).toEqual([2])
  })
  it('clears rows and rejects late account responses', async () => {
    let resolve!: (value: any) => void
    vi.mocked(listHistory).mockReturnValue(new Promise((r) => (resolve = r)))
    const store = useReportHistoryStore(),
      pending = store.refresh()
    store.resetForAccount()
    resolve({ items: [{ id: 1 }], next_cursor: 'old', has_more: true })
    await pending
    expect(store.items).toEqual([])
    expect(store.loading).toBe(false)
  })
})
