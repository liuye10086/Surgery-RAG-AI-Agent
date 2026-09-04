import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalEvidenceSection from '@/components/LongitudinalEvidenceSection.vue'

const evidence = (status: string) => ({
  schema_version: 'longitudinal_evidence_bundle.v1',
  disease_code: 'fatty_liver',
  standard: { document: { title: '标准' }, version: { version_label: 'v1' }, rules: [] },
  reference_cases: { status, cases: [] },
  integrity: { evidence_snapshot_sha256: null },
}) as any

describe('LongitudinalEvidenceSection', () => {
  it.each([
    ['no_eligible_cases', '当前没有通过生产准入的参考病例。'],
    ['insufficient_comparability', '存在合格病例，但与当前病例可比信息不足。'],
    ['reference_query_failed', '参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。'],
  ])('renders %s distinctly', (status, copy) => {
    const wrapper = mount(LongitudinalEvidenceSection, { props: { evidence: evidence(status) } })
    expect(wrapper.text()).toContain(copy)
  })

  it('renders the non-causal notice and never exposes patient label', () => {
    const wrapper = mount(LongitudinalEvidenceSection, { props: { evidence: evidence('available') } })
    expect(wrapper.text()).toContain('参考病例结果不代表当前病例将发生相同结局。')
    expect(wrapper.text()).not.toContain('patient_label')
  })
})
