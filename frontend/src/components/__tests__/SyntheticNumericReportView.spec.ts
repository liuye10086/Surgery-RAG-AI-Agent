import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalReportView from '../LongitudinalReportView.vue'
import { syntheticDocument } from './synthetic-report-fixture'

const global = { stubs: { 'el-button': { template: '<button><slot /></button>' }, ReportArchiveActions: true } }
function render(document: unknown, extra = {}) {
  return mount(LongitudinalReportView, { props: { report: { id: 7, status: 'completed', analysis_type: 'synthetic_numeric', integrity_status: 'valid', report_document: document, ...extra } as never, renderedContent: '<p>LEGACY_RISK_CONTENT</p>' }, global })
}
describe('synthetic numeric report dispatch', () => {
  it.each(['synthetic', 'real'] as const)('renders the same numeric view for %s source', sourceKind => {
    const doc = structuredClone(syntheticDocument()) as any
    doc.schema_version = 'numeric_report_document.v1'
    doc.numeric_input.schema_version = 'numeric_input.v1'
    doc.numeric_input.source.source_kind = sourceKind
    doc.numeric_input.source.is_synthetic = sourceKind === 'synthetic'
    doc.prediction.source.source_kind = sourceKind
    doc.prediction.source.is_synthetic = sourceKind === 'synthetic'
    doc.generation_context.schema_version = 'numeric_generation_context.v1'
    const wrapper = render(doc, { analysis_type: 'numeric_prediction', title: '合成数值报告' })
    expect(wrapper.get('#longitudinal-report-title').text()).toContain('数值预测报告')
    expect(wrapper.findAll('[aria-label="6／12月数值结果"] tbody tr')).toHaveLength(2)
    expect(wrapper.text()).not.toMatch(/合成|工程|test-run|来源批次/)
  })
  it('keeps separate observation series without exposing source-coded methods', () => {
    const doc = syntheticDocument()
    const first = doc.numeric_input.packets[0]!.input_observations[0]!
    doc.numeric_input.packets[0]!.input_observations.push({ ...first, observation_id: 'second-observation', method: 'synthetic_fixture_alt' })
    const wrapper = render(doc)
    expect(wrapper.findAll('.document-charts figure')).toHaveLength(2)
    expect(wrapper.get('.document-charts').text()).toContain('序列 1')
    expect(wrapper.get('.document-charts').text()).toContain('序列 2')
    expect(wrapper.text()).not.toContain('synthetic_fixture')
    expect(wrapper.html()).not.toContain('synthetic_fixture')
  })
  it('discloses unrequested clinical evidence and numeric results in the audit', () => {
    const wrapper = render(syntheticDocument(), { generation_audit: { schema_version: 'generation_audit.v1', last_execution_phase: 'standard_evidence', events: [
      { kind: 'task_finished', phase: 'prediction', task: 'ad.mmse.6m', result_state: 'available', input_audit: null },
      { kind: 'evidence_resolved', phase: 'standard_evidence', task: null, result_state: 'not_requested', input_audit: null },
    ] } })
    const audit = wrapper.get('[aria-label="生成审计记录"]')
    expect(audit.text()).toContain('未执行临床标准或参考病例评价')
    expect(audit.text()).toContain('结果：可用')
    expect(audit.text()).not.toContain('证据查询完成')
  })
  it('refuses failed synthetic snapshots whose integrity is invalid', () => {
    const wrapper = render(null, { status: 'failed', snapshot_integrity: 'invalid', input_snapshot: { numeric_input: syntheticDocument().numeric_input } })
    expect(wrapper.text()).toContain('数值输入快照无法验证')
    expect(wrapper.text()).not.toContain('2026-01-31')
    expect(wrapper.find('svg').exists()).toBe(false)
  })
  it.each(['ad', 'fatty_liver'] as const)('renders both %s horizons, measured-only chart and saved source', disease => {
    const wrapper = render(syntheticDocument(disease))
    expect(wrapper.text()).toContain('末次值保持')
    expect(wrapper.text()).not.toMatch(/合成数据|工程绑定|来源批次|test-run/)
    expect(wrapper.text()).toContain('CASE-TEST-2345')
    const rows = wrapper.findAll('[aria-label="6／12月数值结果"] tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows.map(row => row.text())).toEqual([
      expect.stringContaining('6 个月2026-07-31'), expect.stringContaining('12 个月2027-01-31'),
    ])
    rows.forEach(row => expect(row.text()).toContain(disease === 'ad' ? '0分可用' : '0U/L可用'))
    expect(wrapper.findAll('svg circle')).toHaveLength(1)
    expect(wrapper.text()).toContain('已确认无锚点前历史')
    expect(wrapper.text()).not.toMatch(/LEGACY_RISK_CONTENT|未来 365 天|风险分数|完整证据/)
  })
  it('shows unavailable reasons and unknown history without filling missing values', () => {
    const doc = syntheticDocument()
    doc.numeric_input.packets.forEach(packet => { packet.input_status = 'unavailable'; packet.input_reason = 'anchor_unavailable'; packet.input_observations = []; packet.history_state = 'unknown' })
    doc.prediction.predictions.forEach(row => { row.status = 'unavailable'; row.value = null; row.reason = 'anchor_unavailable' })
    const wrapper = render(doc)
    expect(wrapper.text()).toContain('锚点观测不可用')
    expect(wrapper.text()).toContain('历史覆盖未知')
    expect(wrapper.findAll('[aria-label="6／12月数值结果"] tbody tr').map(row => row.text())).toEqual([expect.stringContaining('—分不可用'), expect.stringContaining('—分不可用')])
    expect(wrapper.find('svg').exists()).toBe(false)
  })
  it.each([{ schema_version: 'synthetic_numeric_report_document.v99' }, null])('refuses unsupported or missing synthetic documents instead of legacy fallback', doc => {
    const wrapper = render(doc)
    expect(wrapper.text()).toContain('报告文档版本无法识别或缺失')
    expect(wrapper.text()).not.toContain('LEGACY_RISK_CONTENT')
    expect(wrapper.find('report-archive-actions-stub').exists()).toBe(false)
  })
  it.each(['failed', 'cancelled'])('renders preserved synthetic inputs for %s without legacy evidence', status => {
    const doc = syntheticDocument()
    const wrapper = render(null, { status, snapshot_integrity: 'valid', input_snapshot: { report_kind: 'synthetic_numeric', numeric_input: doc.numeric_input }, generation_context: doc.generation_context })
    expect(wrapper.text()).toContain('末次值保持')
    expect(wrapper.text()).not.toMatch(/合成数据|工程绑定|来源批次|test-run/)
    expect(wrapper.text()).toContain('2026-01-31')
    expect(wrapper.text()).not.toContain('LEGACY_RISK_CONTENT')
    expect(wrapper.find('[aria-label="6／12月数值结果"]').exists()).toBe(false)
  })
})
