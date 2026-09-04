import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalPredictionSummary from '@/components/LongitudinalPredictionSummary.vue'

function predictionWithStageStatus(status: string, reasonCode: string) {
  return {
    schema_version: 'longitudinal_prediction.v2',
    disease: { name: '脂肪肝' },
    observation: { visit_count: 2, observation_span_days: 30, indicators: {} },
    outcome_prediction: {
      risk_band: null,
      risk_score: null,
      stage_projection: { status: 'not_estimated', likely_next_stage: null, stage_candidates: [] },
    },
    trend_predictions: [],
    warnings: [],
    model_status: {
      outcome: { artifact_type: 'outcome', status: 'disabled', reason_code: 'lifecycle_not_enabled' },
      stage: { artifact_type: 'stage', status, reason_code: reasonCode },
      trend: { artifact_type: 'trend', status: 'missing', reason_code: 'trend_model_missing' },
    },
  } as any
}

describe('LongitudinalPredictionSummary stage status', () => {
  it.each([
    ['incompatible', 'required_feature_missing', '阶段模型存在，但本次输入缺少必需特征'],
    ['missing', 'stage_model_missing', '当前未配置可用的阶段模型'],
  ])('renders %s stage status with its safe reason', (status, reasonCode, expected) => {
    const wrapper = mount(LongitudinalPredictionSummary, {
      props: { prediction: predictionWithStageStatus(status, reasonCode) },
      global: { stubs: { ElTable: true, ElTableColumn: true } },
    })

    expect(wrapper.text()).toContain(expected)
    expect(wrapper.text()).not.toContain('阶段模型未参与或推理失败')
  })
})
