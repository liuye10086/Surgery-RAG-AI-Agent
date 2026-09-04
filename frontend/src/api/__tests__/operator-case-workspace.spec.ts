import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
}

vi.mock('../request', () => ({ default: request }))

describe('operator case workspace API', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists owned cases with search, filters and pagination', async () => {
    const { listLongitudinalCases } = await import('../operator')
    request.get.mockResolvedValue({ cases: [], total: 0, skip: 20, limit: 10 })

    await listLongitudinalCases({ q: 'CASE-', disease_id: 11, status: 'active', skip: 20, limit: 10 })

    expect(request.get).toHaveBeenCalledWith('/v1/operator/longitudinal-cases', {
      params: { q: 'CASE-', disease_id: 11, status: 'active', skip: 20, limit: 10 },
    })
  })

  it('sends one idempotency header for create and one aggregate PUT for save', async () => {
    const { createLongitudinalCase, saveLongitudinalCase } = await import('../operator')
    const payload = { disease_id: 11, age: 56, sex: 'male' as const, baseline_stage: 'pre_cirrhosis' as const, notes: null, visits: [] }
    request.post.mockResolvedValue({ id: 3 })
    request.put.mockResolvedValue({ id: 3 })

    await createLongitudinalCase(payload, '00000000-0000-4000-8000-000000000003')
    await saveLongitudinalCase(3, { ...payload, visits: [], change_reason: '校正' })

    expect(request.post).toHaveBeenCalledWith('/v1/operator/longitudinal-cases', payload, {
      headers: { 'Idempotency-Key': '00000000-0000-4000-8000-000000000003' },
    })
    expect(request.put).toHaveBeenCalledTimes(1)
    expect(request.put).toHaveBeenCalledWith('/v1/operator/longitudinal-cases/3', { ...payload, visits: [], change_reason: '校正' })
  })

  it('exposes server readiness blockers and threshold', async () => {
    const { getLongitudinalCaseReportReadiness } = await import('../operator')
    const readiness = { ready: false, case_ready: true, timeline_ready: false, model_ready: true, visit_count: 1, minimum_visits: 3, blockers: [{ code: 'insufficient_visits', message: '需要 3 次' }] }
    request.get.mockResolvedValue(readiness)

    await expect(getLongitudinalCaseReportReadiness(3)).resolves.toEqual(readiness)
    expect(request.get).toHaveBeenCalledWith('/v1/operator/longitudinal-cases/3/report-readiness')
  })

  it('maps structured Chinese validation issues directly to their fields', async () => {
    const { ApiRequestError, validationIssueMap } = await vi.importActual<typeof import('../request')>('../request')
    const error = new ApiRequestError({
      code: 'validation_error',
      message: '输入数据无效',
      issues: [{ code: 'less_than_equal', field: 'age', message: '必须小于或等于 120' }],
      status: 422,
    })

    expect(validationIssueMap(error).age).toBe('必须小于或等于 120')
  })
})
