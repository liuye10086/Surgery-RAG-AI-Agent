import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  saveLongitudinalCase: vi.fn(),
  deleteLongitudinalCase: vi.fn(),
  updateLongitudinalCaseStatus: vi.fn(),
  getLongitudinalCaseReportReadiness: vi.fn(),
  listOperatorIndicatorCatalog: vi.fn(),
}))

vi.mock('@/api/operator', async () => {
  const actual = await vi.importActual<typeof import('@/api/operator')>('@/api/operator')
  return { ...actual, ...api }
})

describe('operator case workspace store', () => {
  it('keeps the latest search results when an earlier request arrives late', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()
    let resolveOld!: (value: any) => void
    api.listLongitudinalCases.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
    api.listLongitudinalCases.mockResolvedValueOnce({ cases: [{ id: 4 }] })
    const old = store.fetchLongitudinalCases({ q: 'OLD' })
    await store.fetchLongitudinalCases({ q: 'NEW' })
    resolveOld({ cases: [{ id: 3 }] })
    await old
    expect(store.longitudinalCases).toEqual([{ id: 4 }])
    expect(store.currentLongitudinalCase).toBeNull()
  })

  it('ignores case results requested by a previous account', async () => {
    const { useAuthStore } = await import('../auth')
    const { useOperatorStore } = await import('../operator')
    const auth = useAuthStore()
    const store = useOperatorStore()
    auth.user = { id: 7 } as any
    let resolveCases!: (value: any) => void
    api.listLongitudinalCases.mockReturnValue(new Promise(resolve => { resolveCases = resolve }))
    const pending = store.fetchLongitudinalCases()
    auth.user = { id: 8 } as any
    resolveCases({ cases: [{ id: 3 }] })
    await pending
    expect(store.longitudinalCases).toEqual([])
    expect(store.currentLongitudinalCase).toBeNull()
  })
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.resetAllMocks()
    api.listLongitudinalCases.mockResolvedValue({ cases: [] })
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [] })
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

  it('starts a new case without retaining selected case state', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()

    store.currentLongitudinalCase = { id: 3, anonymous_case_code: 'CASE-OLD' } as any
    store.readiness = { ready: true, blockers: [], minimum_visits: 3, visit_count: 3 } as any
    store.draft = { disease_id: 11, age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: '旧草稿', visits: [] }

    store.startNewLongitudinalCase()

    expect(store.currentLongitudinalCase).toBeNull()
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

  it('does not restore a created case after a new case session starts', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveCreate!: (value: any) => void
    api.createLongitudinalCase.mockReturnValue(new Promise((resolve) => { resolveCreate = resolve }))
    const store = useOperatorStore()
    const payload = { disease_id: 11, age: 56, sex: 'male' as const, baseline_stage: 'pre_cirrhosis' as const, notes: null, visits: [] }

    const pendingCreate = store.saveLongitudinalCase(payload)
    store.startNewLongitudinalCase()
    resolveCreate({ id: 5, anonymous_case_code: 'CASE-OLD' })
    await pendingCreate

    expect(store.currentLongitudinalCase).toBeNull()
    expect(store.longitudinalCases).not.toContainEqual(expect.objectContaining({ id: 5 }))
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

  it('does not clear a newly selected case when an older deletion finishes', async () => {
    const { useOperatorStore } = await import('../operator')
    let resolveDelete!: () => void
    let resolveRefresh!: (value: any) => void
    api.deleteLongitudinalCase.mockReturnValue(new Promise<void>((resolve) => { resolveDelete = resolve }))
    api.listLongitudinalCases.mockReturnValue(new Promise((resolve) => { resolveRefresh = resolve }))
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)

    const pendingDelete = store.removeLongitudinalCase()
    resolveDelete()
    await Promise.resolve()
    store.selectLongitudinalCase({ id: 4, status: 'active' } as any)
    resolveRefresh({ cases: [] })
    await pendingDelete

    expect(store.currentLongitudinalCase?.id).toBe(4)
  })

  it('refreshes the current filtered list after a status change while keeping the changed case selected', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()
    const activeCase = { id: 3, status: 'active', disease: { operator_enabled: true } }
    const archivedCase = { ...activeCase, status: 'archived' }
    api.listLongitudinalCases.mockResolvedValueOnce({ cases: [activeCase] }).mockResolvedValueOnce({ cases: [] })
    api.updateLongitudinalCaseStatus.mockResolvedValue(archivedCase)
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [] })
    await store.fetchLongitudinalCases({ q: 'CASE-3', status: 'active' })
    store.selectLongitudinalCase(activeCase as any)

    await store.changeLongitudinalCaseStatus('archived', '阶段随访结束')

    expect(api.listLongitudinalCases).toHaveBeenLastCalledWith({ q: 'CASE-3', status: 'active' })
    expect(store.longitudinalCases).toEqual([])
    expect(store.currentLongitudinalCase).toEqual(archivedCase)
  })

  it('refreshes archived search results after creating an active case while keeping the new case selected', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()
    const archivedCase = { id: 9, status: 'archived', anonymous_case_code: 'MATCH-OLD' }
    const createdCase = { id: 10, status: 'active', anonymous_case_code: 'OTHER-NEW' }
    api.listLongitudinalCases.mockResolvedValueOnce({ cases: [archivedCase] }).mockResolvedValueOnce({ cases: [archivedCase] })
    api.createLongitudinalCase.mockResolvedValue(createdCase)
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [] })
    await store.fetchLongitudinalCases({ q: 'MATCH', status: 'archived' })

    await store.saveLongitudinalCase({ disease_id: 11, age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, visits: [] })

    expect(api.listLongitudinalCases).toHaveBeenLastCalledWith({ q: 'MATCH', status: 'archived' })
    expect(store.longitudinalCases).toEqual([archivedCase])
    expect(store.longitudinalCases).toHaveLength(1)
    expect(store.currentLongitudinalCase).toEqual(createdCase)
  })

  it('does not replace a new-case draft when a case-list request completes', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()
    let resolveCases!: (value: any) => void
    api.listLongitudinalCases.mockReturnValue(new Promise(resolve => { resolveCases = resolve }))
    const pending = store.fetchLongitudinalCases({ status: 'active' })
    store.startNewLongitudinalCase()
    store.draft = { disease_id: 11, age: 56, sex: 'male', baseline_stage: 'pre_cirrhosis', notes: null, visits: [] }
    resolveCases({ cases: [{ id: 3 }] })
    await pending
    expect(store.longitudinalCases).toEqual([{ id: 3 }])
    expect(store.currentLongitudinalCase).toBeNull()
    expect(store.draft).toEqual(expect.objectContaining({ disease_id: 11 }))
  })

  it('clears a deleted selection even when the list refresh fails', async () => {
    const { useOperatorStore } = await import('../operator')
    const store = useOperatorStore()
    store.selectLongitudinalCase({ id: 3, status: 'active' } as any)
    api.deleteLongitudinalCase.mockResolvedValue(undefined)
    api.listLongitudinalCases.mockRejectedValue(new Error('network'))
    await expect(store.removeLongitudinalCase()).rejects.toThrow('病例已删除，但病例列表刷新失败')
    expect(store.currentLongitudinalCase).toBeNull()
    expect(store.readiness).toBeNull()
  })

})
