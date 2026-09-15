import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalReportView from '../LongitudinalReportView.vue'
import { syntheticDocument } from './synthetic-report-fixture'

function trainedDocument(disease: 'ad' | 'fatty_liver' = 'ad') {
  const base = syntheticDocument(disease)
  const algorithm = { ...base.prediction.algorithm, model_id: 'ridge:main_anchor', algorithm_version: 'numeric.ridge.main_anchor.v1', bundle_sha256: 'a'.repeat(64) }
  return {
    ...base, schema_version: 'numeric_report_document.v2', template_version: 'numeric_report.zh-CN.v2',
    numeric_input: { ...base.numeric_input, schema_version: 'numeric_input.v1' },
    generation_context: { ...base.generation_context, schema_version: 'numeric_generation_context.v2', algorithm },
    prediction: { ...base.prediction, schema_version: 'numeric_prediction.v2', algorithm, predictions: [...base.prediction.predictions].reverse().map(row => ({ ...row, value: row.horizon_months === 6 ? 12.5 : 13.25 })), baseline_predictions: base.prediction.predictions.map(row => ({ ...row, value: row.horizon_months === 6 ? 10 : 11 })) },
    evidence: { status: 'partial', vector_status: 'failed', fulltext_status: 'complete', items: [{ chunk_id: 42, title: '已保存参考片段', content: '<img src=x onerror=alert(1)>指标观察记录。', source: { source_kind: 'synthetic' } }] },
    narrative: { model: 'deepseek-chat', sections: [{ title: '结果说明', text: '仅依据已保存的输入与计算结果说明。', citation_ids: [42] }], limitations: ['当前结果不能确认临床有效性。'] },
  }
}
function render(document: unknown, extra = {}) {
  return mount(LongitudinalReportView, { props: { report: { id: 7, status: 'completed', analysis_type: 'numeric_prediction', integrity_status: 'valid', report_document: document, ...extra } as never, renderedContent: '<p>LEGACY_RISK_CONTENT</p>' }, global: { stubs: { 'el-button': { template: '<button><slot /></button>' }, ReportArchiveActions: true } } })
}
describe('trained numeric saved report', () => {
  it('formats long predictions for reading without mutating saved precision', () => {
    const doc = trainedDocument()
    doc.prediction.predictions[0]!.value = 23.65382997305097
    const wrapper = render(doc)
    expect(wrapper.text()).toContain('23.6538')
    expect(wrapper.text()).not.toContain('23.65382997305097')
    expect(doc.prediction.predictions[0]!.value).toBe(23.65382997305097)
  })
  it.each(['ad', 'fatty_liver'] as const)('shows %s saved trained values and task-matched baseline in horizon order', disease => {
    const wrapper = render(trainedDocument(disease))
    const rows = wrapper.findAll('[aria-label="6／12月数值结果"] tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows.map(row => row.findAll('td').map(cell => cell.text()))).toEqual([
      [disease === 'ad' ? 'MMSE' : 'ALT', '6 个月', '2026-07-31', '12.5', '10', disease === 'ad' ? '分' : 'U/L', '可用', '—'],
      [disease === 'ad' ? 'MMSE' : 'ALT', '12 个月', '2027-01-31', '13.25', '11', disease === 'ad' ? '分' : 'U/L', '可用', '—'],
    ])
    expect(wrapper.text()).toContain('ridge:main_anchor')
    expect(wrapper.text()).toContain('末次值保持基线')
    expect(wrapper.text()).not.toContain('无拟合基线，仅使用锚点值')
    expect(wrapper.text()).not.toContain('此报告未执行临床标准或参考病例评价')
    expect(wrapper.findAll('svg circle')).toHaveLength(1)
    expect(wrapper.html()).not.toMatch(/合成|工程绑定|test-run|source_kind|LEGACY_RISK_CONTENT/)
  })
  it('renders saved narrative, limitations and escaped reference content linked by citation ID', () => {
    const wrapper = render(trainedDocument())
    expect(wrapper.text()).toContain('仅依据已保存的输入与计算结果说明。')
    expect(wrapper.text()).toContain('当前结果不能确认临床有效性。')
    const link = wrapper.get('a[href="#numeric-reference-42"]')
    expect(link.text()).toBe('[42]')
    const reference = wrapper.get('#numeric-reference-42')
    expect(reference.text()).toContain('已保存参考片段')
    expect(reference.text()).toContain('<img src=x onerror=alert(1)>指标观察记录。')
    expect(reference.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('部分检索结果可用')
  })
  it('shows empty saved evidence without inventing citations', () => {
    const doc = trainedDocument()
    doc.evidence = { ...doc.evidence, status: 'empty', vector_status: 'not_run', fulltext_status: 'not_run', items: [] }
    doc.narrative.sections[0]!.citation_ids = []
    const wrapper = render(doc)
    expect(wrapper.text()).toContain('没有可用的已保存参考片段')
    expect(wrapper.find('a[href^="#numeric-reference-"]').exists()).toBe(false)
  })
  it('preserves unavailable trained and baseline values without filling them', () => {
    const doc = trainedDocument()
    const unavailable = doc.prediction.predictions.map(row => ({ ...row, status: 'unavailable', value: null, reason: 'anchor_unavailable' }))
    const wrapper = render({ ...doc, prediction: { ...doc.prediction, predictions: unavailable, baseline_predictions: unavailable } })
    const rows = wrapper.findAll('[aria-label="6／12月数值结果"] tbody tr')
    expect(rows.map(row => row.findAll('td').slice(3).map(cell => cell.text()))).toEqual([
      ['—', '—', '分', '不可用', '锚点观测不可用'], ['—', '—', '分', '不可用', '锚点观测不可用'],
    ])
  })
  it.each(['failed', 'cancelled'])('shows only verified saved input and trained context for %s', status => {
    const doc = trainedDocument()
    const wrapper = render(null, { status, snapshot_integrity: 'valid', context_integrity: 'valid', input_snapshot: { report_kind: 'numeric_prediction', numeric_input: doc.numeric_input }, generation_context: doc.generation_context })
    expect(wrapper.text()).toContain('ridge:main_anchor')
    expect(wrapper.text()).not.toContain('无拟合基线')
    expect(wrapper.text()).not.toContain('结果说明')
    expect(wrapper.find('[aria-label="6／12月数值结果"]').exists()).toBe(false)
  })
  it.each(['invalid', 'unknown'])('does not expose %s generation context as a confirmed model', state => {
    const doc = trainedDocument()
    if (state === 'unknown') doc.generation_context.schema_version = 'numeric_generation_context.v99'
    const wrapper = render(null, { status: 'failed', snapshot_integrity: 'valid', context_integrity: state === 'invalid' ? 'invalid' : 'valid', input_snapshot: { report_kind: 'numeric_prediction', numeric_input: doc.numeric_input }, generation_context: doc.generation_context })
    expect(wrapper.text()).toContain('未保存可验证的算法身份')
    expect(wrapper.text()).not.toContain('ridge:main_anchor')
    expect(wrapper.text()).not.toContain('无拟合基线')
  })
  it.each(['invalid', 'unsupported'])('blocks %s document content and export', state => {
    const doc = trainedDocument()
    if (state === 'unsupported') doc.schema_version = 'numeric_report_document.v99'
    const wrapper = render(doc, state === 'invalid' ? { integrity_status: 'invalid' } : {})
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.find('.numeric-report').exists()).toBe(false)
    expect(wrapper.find('report-archive-actions-stub').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('LEGACY_RISK_CONTENT')
  })
})
