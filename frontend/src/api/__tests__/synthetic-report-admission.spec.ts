import {afterEach, expect, it, vi} from 'vitest'
import request from '../request'
import {submitReportJob} from '../report-generation'
import {getLongitudinalCaseReportReadiness} from '../operator'

afterEach(() => vi.restoreAllMocks())

it('keeps the old request body and sends an explicit numeric kind', async () => {
  const post = vi.spyOn(request, 'post').mockResolvedValue({report_id: 9})
  await submitReportJob(2, 'old-key')
  await submitReportJob(2, 'numeric-key', 'synthetic_numeric')
  expect(post.mock.calls).toEqual([
    ['/v1/operator/longitudinal-cases/2/report-jobs', {model_options: {}}, {headers: {'Idempotency-Key': 'old-key'}}],
    ['/v1/operator/longitudinal-cases/2/report-jobs', {model_options: {}, report_kind: 'synthetic_numeric'}, {headers: {'Idempotency-Key': 'numeric-key'}}],
  ])
})

it('requests readiness for the selected report kind', async () => {
  const get = vi.spyOn(request, 'get').mockResolvedValue({ready: true})
  await getLongitudinalCaseReportReadiness(2, 'synthetic_numeric')
  expect(get).toHaveBeenCalledWith('/v1/operator/longitudinal-cases/2/report-readiness', {params: {report_kind: 'synthetic_numeric'}})
})

it('submits unified numeric requests explicitly', async () => {
  const post = vi.spyOn(request, 'post').mockResolvedValue({report_id: 9})
  await submitReportJob(2, 'numeric-key', 'numeric_prediction')
  expect(post).toHaveBeenCalledWith('/v1/operator/longitudinal-cases/2/report-jobs', {model_options: {}, report_kind: 'numeric_prediction'}, {headers: {'Idempotency-Key': 'numeric-key'}})
})
