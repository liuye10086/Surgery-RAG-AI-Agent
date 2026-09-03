import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  saveLongitudinalCase: vi.fn(),
  getLongitudinalCaseReportReadiness: vi.fn(),
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
})
