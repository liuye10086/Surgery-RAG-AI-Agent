import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportHistoryWorkspace from '../report/ReportHistoryWorkspace.vue'
import LegacyReportSnapshot from '../report/LegacyReportSnapshot.vue'
import { useReportHistoryStore } from '@/stores/report-history'
vi.mock('@/api/report-history', () => ({ listHistory: vi.fn() }))
describe('saved history views', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it('opens saved report identity without a case editor', async () => {
    const store = useReportHistoryStore()
    store.items = [
      {
        id: 17,
        status: 'failed',
        created_at: '2026-09-07T00:00:00Z',
        anonymous_case_code: 'CASE-ABCD-2345',
      },
    ] as never
    const wrapper = mount(ReportHistoryWorkspace, {
      global: { stubs: { 'el-button': true } },
    })
    await wrapper.get('.open-report').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[17]])
    expect(wrapper.text()).toContain('失败')
    expect(wrapper.find('operator-case-workspace').exists()).toBe(false)
  })
  it('preserves zero and false and escapes saved notes', () => {
    const wrapper = mount(LegacyReportSnapshot, {
      props: {
        snapshot: {
          age: 0,
          notes: '<script>private</script>',
          visits: [
            {
              visit_date: '2026-01-01',
              context: { education_adjusted: false },
              indicators: [{ name: 'score', value: 0, unit: '分' }],
            },
          ],
        },
      },
    })
    expect(wrapper.text()).toContain('年龄：0')
    expect(wrapper.text()).toContain('否')
    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.get('tbody').text()).toContain('0')
  })
})
