import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportArchiveStore } from '@/stores/report-archive'
import { useAuthStore } from '@/stores/auth'
import * as api from '@/api/report-archive'
import { ApiRequestError } from '@/api/request'
vi.mock('@/api/report-archive', () => ({
  readArchive: vi.fn(),
  prepareArchive: vi.fn(),
  downloadOriginal: vi.fn(),
}))
const status = (state: string, extra = {}) => ({
  report_id: 1,
  state,
  revision: 1,
  message: '',
  can_retry: false,
  ...extra,
})
describe('archive actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.useFakeTimers()
    useAuthStore().user = { id: 7 } as any
  })
  afterEach(() => vi.useRealTimers())
  it('observes with GET only and prepares once on double click', async () => {
    vi.mocked(api.readArchive).mockResolvedValue(status('not_requested') as any)
    vi.mocked(api.prepareArchive).mockResolvedValue(status('queued') as any)
    const store = useReportArchiveStore()
    await store.observe(1)
    expect(api.prepareArchive).not.toHaveBeenCalled()
    await Promise.all([store.prepare(), store.prepare()])
    expect(api.prepareArchive).toHaveBeenCalledTimes(1)
    store.detach()
  })
  it('reuses the key after an uncertain response, never automatically posts', async () => {
    vi.mocked(api.readArchive).mockResolvedValue(status('not_requested') as any)
    vi.mocked(api.prepareArchive)
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValue(status('queued') as any)
    const store = useReportArchiveStore()
    await store.observe(1)
    await store.prepare()
    await store.refreshConnection()
    expect(api.prepareArchive).toHaveBeenCalledTimes(1)
    await store.prepare()
    expect(vi.mocked(api.prepareArchive).mock.calls[0]![1]).toBe(
      vi.mocked(api.prepareArchive).mock.calls[1]![1],
    )
    store.detach()
  })
  it('does not accept another account’s late response', async () => {
    let resolve!: (value: any) => void
    vi.mocked(api.readArchive).mockReturnValue(
      new Promise((r) => (resolve = r)),
    )
    const store = useReportArchiveStore(),
      pending = store.observe(1)
    useAuthStore().user = { id: 8 } as any
    resolve(status('ready'))
    await pending
    expect(store.status).toBeNull()
    expect(store.reportId).toBeNull()
  })
  it('downloads ready originals without prepare and forbids retry for missing', async () => {
    vi.mocked(api.readArchive).mockResolvedValue(status('ready') as any)
    const store = useReportArchiveStore()
    await store.observe(1)
    await store.download()
    await store.download()
    expect(api.downloadOriginal).toHaveBeenCalledTimes(2)
    expect(api.prepareArchive).not.toHaveBeenCalled()
    vi.mocked(api.readArchive).mockResolvedValue(
      status('missing', { revision: 2 }) as any,
    )
    await store.refreshConnection()
    await store.retry()
    expect(api.prepareArchive).not.toHaveBeenCalled()
    store.detach()
  })
  it('honors Retry-After before prepare or refresh, and clears expired authentication', async () => {
    vi.mocked(api.readArchive).mockResolvedValue(status('not_requested') as any)
    vi.mocked(api.prepareArchive).mockRejectedValue(
      new ApiRequestError({
        code: 'pdf_capacity_exceeded',
        message: '稍后重试',
        status: 429,
        retryAfterSeconds: 10,
      }),
    )
    const store = useReportArchiveStore()
    await store.observe(1)
    await store.prepare()
    await store.prepare()
    await store.refreshConnection()
    expect(api.prepareArchive).toHaveBeenCalledTimes(1)
    expect(api.readArchive).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(10000)
    vi.mocked(api.readArchive).mockRejectedValue(
      new ApiRequestError({
        code: 'unauthorized',
        message: '登录已过期',
        status: 401,
      }),
    )
    await store.refreshConnection()
    expect(useAuthStore().user).toBeNull()
    expect(store.reportId).toBeNull()
  })
})
