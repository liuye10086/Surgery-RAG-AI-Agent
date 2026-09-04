import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LongitudinalReportView from '@/components/LongitudinalReportView.vue'

describe('LongitudinalReportView evidence placement', () => {
  it('shows live structured evidence once and removes the markdown evidence section', () => {
    const evidence = {
      schema_version: 'longitudinal_evidence_bundle.v1',
      evidence_bundle_id: '00000000-0000-4000-8000-000000000001',
      generation_batch_id: '00000000-0000-4000-8000-000000000002',
      disease_code: 'fatty_liver',
      created_at: '2026-09-04T00:00:00Z',
      standard: { status: 'available', document: { title: '唯一正式标准' }, version: { version_label: 'v1' }, rules: [], warnings: [] },
      reference_cases: { status: 'no_eligible_cases', data_release: { dataset_release_id: 'r1' }, algorithm_version: 'reference_similarity.v1', cases: [], warnings: [] },
      warnings: [],
      integrity: { canonicalization_version: 'v1', hash_algorithm: 'sha256', evidence_snapshot_sha256: null },
    } as any
    const wrapper = mount(LongitudinalReportView, {
      props: {
        renderedContent: '<h2 id="section-8">8. 参考标准和相似病例</h2><p>旧证据内容</p><h2 id="section-9">9. 不确定性与局限性</h2>',
        evidenceSnapshot: evidence,
      },
      global: { stubs: { ElButton: true } },
    })

    expect(wrapper.text()).toContain('唯一正式标准')
    expect(wrapper.text()).not.toContain('旧证据内容')
    expect(wrapper.findAll('#section-8')).toHaveLength(1)
    expect(wrapper.html().indexOf('id="section-8"')).toBeLessThan(wrapper.html().indexOf('id="section-9"'))
  })
})
