import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ReportArchiveActions from '../report/ReportArchiveActions.vue'
import { readArchive } from '@/api/report-archive'
vi.mock('@/api/report-archive', () => ({
  readArchive: vi.fn(),
  prepareArchive: vi.fn(),
  downloadOriginal: vi.fn(),
}))
describe('original health UI', () => {
  beforeEach(() => setActivePinia(createPinia()))
  it.each(['missing', 'corrupt'])(
    'has no render retry for %s',
    async (state) => {
      vi.mocked(readArchive).mockResolvedValue({
        report_id: 1,
        revision: 2,
        state,
        message: '请联系维护人员从备份恢复',
        can_retry: false,
      } as any)
      const wrapper = mount(ReportArchiveActions, {
        props: { reportId: 1 },
        global: { stubs: { 'el-button': true } },
      })
      await flushPromises()
      expect(wrapper.text()).toContain('从备份恢复')
      expect(wrapper.text()).not.toContain('重新准备 PDF')
      wrapper.unmount()
    },
  )
})
