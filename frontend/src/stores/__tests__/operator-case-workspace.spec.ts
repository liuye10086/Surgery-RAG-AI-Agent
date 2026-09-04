import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  saveLongitudinalCase: vi.fn(),
  getLongitudinalCaseReportReadiness: vi.fn(),
  getReport: vi.fn(),
  generateLongitudinalReportStream: vi.fn(),
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
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)
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

  it('does not restore a saved case after a new case session starts', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveSave!: (value: any) => void
    api.saveLongitudinalCase.mockReturnValue(new Promise((resolve) => { resolveSave = resolve }))
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)

    const pendingSave = store.saveLongitudinalCase(3, { age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, visits: [], change_reason: '校正' })
    store.startNewLongitudinalCase()
    resolveSave({ id: 3, anonymous_case_code: 'CASE-OLD' })
    await pendingSave

    expect(store.currentLongitudinalCase).toBeNull()
    expect(store.draft).toBeNull()
    expect(store.readiness).toBeNull()
  })

  it('does not leave a stale save active after switching cases', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveSave!: (value: any) => void
    api.saveLongitudinalCase.mockReturnValue(new Promise((resolve) => { resolveSave = resolve }))
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)

    const pendingSave = store.saveLongitudinalCase(3, { age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, visits: [], change_reason: '校正' })
    store.selectLongitudinalCase({ id: 4, status: 'active' } as any)
    resolveSave({ id: 3, anonymous_case_code: 'CASE-OLD' })
    await pendingSave

    expect(store.currentLongitudinalCase?.id).toBe(4)
    expect(store.saving).toBe(false)
  })

  it('does not restore readiness after a new case session starts', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveReadiness!: (value: any) => void
    api.getLongitudinalCaseReportReadiness.mockReturnValue(new Promise((resolve) => { resolveReadiness = resolve }))
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)

    const pendingReadiness = store.refreshLongitudinalCaseReadiness(3)
    store.startNewLongitudinalCase()
    resolveReadiness({ ready: true, blockers: [], minimum_visits: 3, visit_count: 3 })
    await pendingReadiness

    expect(store.readiness).toBeNull()
  })

  it('does not restore a report fetched before a new case session starts', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveReport!: (value: any) => void
    api.getReport.mockReturnValue(new Promise((resolve) => { resolveReport = resolve }))
    const store = useOperatorStore()

    const pendingReport = store.fetchReport(8)
    store.startNewLongitudinalCase()
    resolveReport({ id: 8, content: '旧报告' })
    await pendingReport

    expect(store.currentReport).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('ignores stale report stream callbacks after a new case session starts', async () => {
    const { useOperatorStore } = await import('../operator')
    let callbacks!: Record<string, (...args: any[]) => void>
    api.generateLongitudinalReportStream.mockImplementation((_caseId: number, value: Record<string, (...args: any[]) => void>) => {
      callbacks = value
      return vi.fn()
    })
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)
    store.generateLongitudinalReport(3)
    store.startNewLongitudinalCase()

    callbacks.onStage('predicting', '旧阶段')
    callbacks.onPrediction({ summary: '旧预测' })
    callbacks.onDone(8)
    callbacks.onError()

    expect(store.currentStage).toBe('')
    expect(store.longitudinalPrediction).toBeNull()
    expect(store.currentReport).toBeNull()
    expect(api.getReport).not.toHaveBeenCalled()
  })
})
