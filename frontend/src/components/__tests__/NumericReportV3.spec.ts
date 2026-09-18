import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalReportView from '../LongitudinalReportView.vue'
import { syntheticDocument } from './synthetic-report-fixture'

function descriptor(model: string) {
  const history = model.startsWith('random_forest')
  return { model_id: model, algorithm_version: history ? 'numeric.random_forest.history_v1.value_history.v1' : `numeric.${model === 'last_value' ? 'last_value' : 'ridge.main_anchor'}.v1`, feature_version: history ? 'history_v1:value_history' : 'main_anchor', eligibility_version: history ? 'numeric.history.H.v1' : 'numeric.anchor.v1', feature_names: history ? ['anchor_value', 'prior_value', 'slope_per_day'] : ['anchor_value'], parameters_sha256: 'a'.repeat(64) }
}

// Saved presentation fixture: no API or active model provides expected values.
function mixedDocument(disease: 'ad' | 'fatty_liver' = 'ad') {
  const base = syntheticDocument(disease)
  const algorithm = { ...base.prediction.algorithm, model_id: 'mixed_history', algorithm_version: 'numeric.mixed_history.v1', bundle_sha256: 'b'.repeat(64) }
  const numericInput = { ...base.numeric_input, schema_version: 'numeric_input.v1', packets: base.numeric_input.packets.map(packet => ({ ...packet, input_observations: packet.input_observations.map(row => ({ ...row, value: 22.0 })) })) }
  const taskAlgorithms = Object.fromEntries(['ad.mmse.6m', 'ad.mmse.12m', 'fatty_liver.alt.6m', 'fatty_liver.alt.12m'].map(task => [task, descriptor(task === 'ad.mmse.12m' ? 'random_forest:history_v1:value_history' : 'ridge:main_anchor')]))
  return {
    ...base, schema_version: 'numeric_report_document.v3', template_version: 'numeric_report.zh-CN.v3', numeric_input: numericInput,
    generation_context: { ...base.generation_context, schema_version: 'numeric_generation_context.v3', numeric_input: numericInput, algorithm, task_algorithms: taskAlgorithms, source_binding_sha256: 'PRIVATE_SOURCE_BINDING' },
    prediction: { ...base.prediction, schema_version: 'numeric_prediction.v3', algorithm,
      predictions: [...base.prediction.predictions].reverse().map(row => ({ ...row, algorithm: taskAlgorithms[row.task_id]!, status: disease === 'ad' && row.horizon_months === 12 ? 'abstain' : 'available', reason: disease === 'ad' && row.horizon_months === 12 ? 'history_not_observed' : null as string | null, value: disease === 'ad' && row.horizon_months === 12 ? null : 14.0, raw_prediction: null as number | null })),
      baseline_predictions: [...base.prediction.predictions].reverse().map(row => ({ ...row, algorithm: descriptor('last_value'), status: 'available', value: 22.0 as number | null, reason: null as string | null, raw_prediction: null })),
    },
    evidence: { status: 'empty', items: [] as { chunk_id: number; title: string; content: string }[] },
    narrative: { model: 'deepseek-chat', response_model: 'saved-model', sections: [{ title: '结果阅读说明', text: '请逐项查看已保存结果。', citation_ids: [] as number[] }, { title: '参考证据说明', text: '缺少指南证据。', citation_ids: [] as number[] }], limitations: ['不能据此判断临床效能。', '未来实测结果仍待随访确认。'] },
  }
}
function render(document: unknown, extra = {}) {
  return mount(LongitudinalReportView, { props: { report: { id: 7, status: 'completed', analysis_type: 'numeric_prediction', integrity_status: 'valid', report_document: document, ...extra } as never, renderedContent: '<p>LEGACY_RISK_CONTENT</p>' }, global: { stubs: { 'el-button': { template: '<button><slot /></button>' }, ReportArchiveActions: true } } })
}
const cells = (wrapper: ReturnType<typeof render>) => wrapper.findAll('tbody tr').map(row => row.findAll('td').map(cell => cell.text()))

describe('mixed history numeric saved report', () => {
  it('orders reversed tasks and retains available baseline when the candidate abstains', () => {
    const doc = mixedDocument()
    const before = JSON.stringify(doc)
    const wrapper = render(doc)
    const rows = cells(wrapper)
    expect(rows.map(row => row[1])).toEqual(['6 个月', '12 个月'])
    expect(rows.map(row => row.slice(3, 5))).toEqual([['14.00', '22.00'], ['—', '22.00']])
    expect(rows[1]!.join(' ')).toContain('历史不足，未预测')
    expect(rows[1]!.join(' ')).toContain('缺少已观察历史')
    expect(rows[1]!.join(' ')).toContain('随机森林')
    expect(rows[1]!.join(' ')).toContain('可用')
    expect(wrapper.text()).not.toMatch(/PRIVATE_SOURCE_BINDING|source_kind|test-run|LEGACY_RISK_CONTENT/)
    const sections = wrapper.findAll('.numeric-report__section')
    expect(sections[sections.length - 1]!.attributes('aria-label')).toBe('算法说明')
    expect(JSON.stringify(doc)).toBe(before)
  })
  it('shows candidate error and independent baseline reason without leaking raw values', () => {
    const doc = mixedDocument()
    Object.assign(doc.prediction.predictions[0]!, { status: 'error', reason: 'prediction_out_of_bounds', raw_prediction: 98765.4321 })
    Object.assign(doc.prediction.baseline_predictions[1]!, { status: 'abstain', reason: 'anchor_unavailable', value: null })
    const wrapper = render(doc)
    const rows = cells(wrapper)
    expect(rows[1]!.slice(3, 5)).toEqual(['—', '22.00'])
    expect(rows[1]!.join(' ')).toContain('计算失败')
    expect(rows[1]!.join(' ')).toContain('结果超出允许范围')
    expect(rows[0]!.slice(3, 5)).toEqual(['14.00', '—'])
    expect(rows[0]!.join(' ')).toContain('锚点观测不可用')
    expect(wrapper.text()).not.toMatch(/98765|raw_prediction/)
  })
  it.each([[1.005, '1.01'], [22.56701016, '22.57'], [0, '0.00']])('rounds %s only in display', (value, expected) => {
    const doc = mixedDocument()
    doc.prediction.predictions[1]!.value = Number(value)
    const before = JSON.stringify(doc)
    expect(cells(render(doc))[0]![3]).toBe(expected)
    expect(JSON.stringify(doc)).toBe(before)
  })
  it('lists only this disease tasks with their saved input features', () => {
    const wrapper = render(mixedDocument('fatty_liver'))
    const version = wrapper.get('[aria-label="算法说明"]').text()
    expect(cells(wrapper).map(row => row[0])).toEqual(['ALT', 'ALT'])
    expect(version.match(/Ridge/g)).toHaveLength(2)
    expect(version).not.toContain('随机森林')
    expect(version).toContain('锚点实测值')
  })
  it.each(['generating', 'failed', 'cancelled'])('routes saved v3 context for %s without showing predictions', status => {
    const doc = mixedDocument()
    const wrapper = render(null, { status, snapshot_integrity: 'valid', context_integrity: 'valid', input_snapshot: { report_kind: 'numeric_prediction', numeric_input: doc.numeric_input }, generation_context: doc.generation_context })
    expect(wrapper.get('[aria-label="算法说明"]').text()).toContain('随机森林')
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('LEGACY_RISK_CONTENT')
    if (status === 'generating') {
      expect(wrapper.text()).toContain('报告正在生成')
      expect(wrapper.text()).not.toContain('报告生成失败')
    }
  })
  it('retains empty evidence and escapes saved reference markup', () => {
    const doc = mixedDocument()
    expect(render(doc).text()).toContain('没有可用的已保存参考片段')
    doc.evidence = { status: 'partial', items: [{ chunk_id: 42, title: '保存参考', content: '<img src=x onerror=alert(1)>参考正文' }] }
    doc.narrative.sections[0]!.citation_ids = [42]
    const wrapper = render(doc)
    expect(wrapper.get('a[href="#numeric-reference-42"]').text()).toBe('[42]')
    expect(wrapper.get('#numeric-reference-42').text()).toContain('<img src=x onerror=alert(1)>参考正文')
    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.text()).toContain('部分检索结果可用')
  })
  it.each(['invalid', 'unsupported'])('blocks %s saved content and export', state => {
    const doc = mixedDocument()
    if (state === 'unsupported') doc.schema_version = 'numeric_report_document.v99'
    const wrapper = render(doc, state === 'invalid' ? { integrity_status: 'invalid' } : {})
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect(wrapper.find('.numeric-report').exists()).toBe(false)
    expect(wrapper.find('report-archive-actions-stub').exists()).toBe(false)
  })
})
