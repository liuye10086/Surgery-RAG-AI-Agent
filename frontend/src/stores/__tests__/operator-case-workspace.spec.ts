import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  saveLongitudinalCase: vi.fn(),
  getLongitudinalCaseReportReadiness: vi.fn(),
  listOperatorIndicatorCatalog: vi.fn(),
}))

vi.mock('@/api/operator', async () => {
  const actual = await vi.importActual<typeof import('@/api/operator')>('@/api/operator')
  return { ...actual, ...api }
})

describe('operator case workspace store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps saving true until aggregate save settles and refreshes readiness', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveSave!: (value: any) => void
    api.saveLongitudinalCase.mockReturnValue(new Promise((resolve) => { resolveSave = resolve }))
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [], minimum_visits: 3, visit_count: 1 })
    const store = useOperatorStore()
    const promise = store.saveLongitudinalCase(3, { age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, visits: [], change_reason: '校正' })

    expect(store.saving).toBe(true)
    resolveSave({ id: 3 })
    await promise
    expect(store.saving).toBe(false)
    expect(api.getLongitudinalCaseReportReadiness).toHaveBeenCalledWith(3)
  })

  it('preserves draft when the aggregate save rejects', async () => {
    const { useOperatorStore } = await import('../operator')
    api.saveLongitudinalCase.mockRejectedValue(new Error('conflict'))
    const store = useOperatorStore()
    const draft = { age: 56, sex: 'male' as const, baseline_stage: 'pre_cirrhosis' as const, notes: 'keep', visits: [], change_reason: '校正' }

    await expect(store.saveLongitudinalCase(3, draft)).rejects.toThrow('conflict')
    expect(store.draft).toEqual(draft)
    expect(store.saving).toBe(false)
  })

  it('reuses a create idempotency key after a failed retry and rotates it after success', async () => {
    const { useOperatorStore } = await import('../operator')
    const payload = { disease_id: 11, age: 56, sex: 'male' as const, baseline_stage: 'pre_cirrhosis' as const, notes: null, visits: [] }
    api.createLongitudinalCase.mockRejectedValueOnce(new Error('network')).mockResolvedValueOnce({ id: 4 })
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [], minimum_visits: 3, visit_count: 1 })
    const store = useOperatorStore()
    await expect(store.saveLongitudinalCase(payload)).rejects.toThrow('network')
    await store.saveLongitudinalCase(payload)
    expect(api.createLongitudinalCase.mock.calls[0][1]).toBe(api.createLongitudinalCase.mock.calls[1][1])
    api.createLongitudinalCase.mockResolvedValueOnce({ id: 5 })
    await store.saveLongitudinalCase(payload)
    expect(api.createLongitudinalCase.mock.calls[2][1]).not.toBe(api.createLongitudinalCase.mock.calls[1][1])
  })

  it('loads and caches each disease indicator catalog', async () => {
    const { useOperatorStore } = await import('../operator')
    const catalog = { disease_code: 'fatty_liver', catalog_version: 'a'.repeat(64), items: [] }
    api.listOperatorIndicatorCatalog.mockResolvedValue(catalog)
    const store = useOperatorStore()

    await store.fetchOperatorIndicatorCatalog('fatty_liver')
    await store.fetchOperatorIndicatorCatalog('fatty_liver')

    expect(store.indicatorCatalogs.fatty_liver).toEqual(catalog)
    expect(api.listOperatorIndicatorCatalog).toHaveBeenCalledTimes(1)
  })

  it('starts a new case without retaining selected case or report state', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()

    store.currentLongitudinalCase = { id: 3, anonymous_case_code: 'CASE-OLD' } as any
    store.currentReport = { id: 8 } as any
    store.longitudinalPrediction = { summary: '旧预测' } as any
    store.longitudinalEvidence = { evidence: [] } as any
    store.readiness = { ready: true, blockers: [], minimum_visits: 3, visit_count: 3 } as any
    store.draft = { disease_id: 11, age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: '旧草稿', visits: [] }

    store.startNewLongitudinalCase()

    expect(store.currentLongitudinalCase).toBeNull()
    expect(store.currentReport).toBeNull()
    expect(store.longitudinalPrediction).toBeNull()
    expect(store.longitudinalEvidence).toBeNull()
    expect(store.readiness).toBeNull()
    expect(store.draft).toBeNull()
  })
})
