import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listReports: vi.fn(),
  listDiseases: vi.fn(),
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
}))
const validationIssueMap = vi.hoisted(() => vi.fn(() => ({ age: '旧会话校验错误' })))

vi.mock('@/api/operator', async () => {
  const actual = await vi.importActual<typeof import('@/api/operator')>('@/api/operator')
  return { ...actual, ...api }
})

vi.mock('@/api/request', async () => {
  const actual = await vi.importActual<typeof import('@/api/request')>('@/api/request')
  return { ...actual, validationIssueMap }
})

vi.mock('element-plus', async () => {
  const actual = await vi.importActual<typeof import('element-plus')>('element-plus')
  return { ...actual, ElMessage: { success: vi.fn(), error: vi.fn() }, ElMessageBox: { confirm: vi.fn() } }
})

describe('OperatorView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listReports.mockResolvedValue({ reports: [], total: 0 })
    api.listDiseases.mockResolvedValue([])
    api.listLongitudinalCases.mockResolvedValue({ cases: [] })
  })

  it('does not restore validation issues when a stale save rejects after starting a new case', async () => {
    const { useOperatorStore } = await import('@/stores/operator')
    const store = useOperatorStore()
    let rejectCreate!: (reason: Error) => void
    api.createLongitudinalCase.mockReturnValue(new Promise((_resolve, reject) => { rejectCreate = reject }))
    const OperatorView = (await import('../OperatorView.vue')).default
    const wrapper = mount(OperatorView, {
      global: {
        mocks: { $router: { push: vi.fn() } },
        stubs: {
          OperatorSidebar: { template: '<button data-test="new-case" @click="$emit(\'new-longitudinal-case\')">新建</button>' },
          OperatorCaseWorkspace: {
            props: ['validationIssues'],
            template: '<section><button data-test="save" @click="$emit(\'save\', { disease_id: 11, age: 56, sex: \'male\', baseline_stage: \'pre_cirrhosis\', notes: null, visits: [] })">保存</button><output data-test="issues">{{ JSON.stringify(validationIssues) }}</output></section>',
          },
          OperatorCaseList: true,
          LongitudinalPredictionSummary: true,
          LongitudinalReportView: true,
          'el-button': true,
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="save"]').trigger('click')
    await wrapper.get('[data-test="new-case"]').trigger('click')
    rejectCreate(new Error('conflict'))
    await flushPromises()

    expect(store.caseSessionRevision).toBeGreaterThan(0)
    expect(wrapper.get('[data-test="issues"]').text()).not.toContain('旧会话校验错误')
  })
})
