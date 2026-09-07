import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listReports: vi.fn(),
  listDiseases: vi.fn(),
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  getLongitudinalCaseReportReadiness: vi.fn(),
  listOperatorIndicatorCatalog: vi.fn(),
}))
vi.mock('vue-router',()=>({useRoute:()=>({query:{}}),useRouter:()=>({replace:vi.fn(),push:vi.fn()})}))
vi.mock('@/api/report-history',()=>({listHistory:vi.fn(async()=>({items:[],has_more:false,next_cursor:null}))}))

const validationIssueMap = vi.hoisted(() => vi.fn(() => ({ age: '旧会话校验错误' })))

function existingCase() {
  return {
    id: 3,
    user_id: 7,
    disease_id: 11,
    anonymous_case_code: 'CASE-OLD-VISIBLE',
    age: 56,
    sex: 'male',
    baseline_stage: 'pre_cirrhosis',
    notes: null,
    status: 'active',
    visits: [],
    disease: { id: 11, code: 'fatty_liver', name: '脂肪肝', operator_enabled: true },
  } as any
}

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
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [] })
    api.listOperatorIndicatorCatalog.mockResolvedValue({ disease_code: 'fatty_liver', indicators: [] })
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

  it('removes populated case details when the case-list new entry starts a new case', async () => {
    const selectedCase = existingCase()
    api.listLongitudinalCases.mockResolvedValue({ cases: [selectedCase] })
    const { useOperatorStore } = await import('@/stores/operator')
    const store = useOperatorStore()
    const OperatorView = (await import('../OperatorView.vue')).default
    const wrapper = mount(OperatorView, {
      global: {
        mocks: { $router: { push: vi.fn() } },
        stubs: {
          OperatorSidebar: {
            template: '<button data-test="show-cases" @click="$emit(\'navigate\', \'cases\')">病例库</button>',
          },
          OperatorCaseList: {
            props: ['cases', 'selectedId'],
            template: '<section><output data-test="selected-id">{{ selectedId }}</output><button data-test="case-list-new" @click="$emit(\'new\')">新建</button></section>',
          },
          OperatorCaseWorkspace: {
            props: ['model', 'readiness'],
            template: '<section><output data-test="case-code">{{ model?.anonymous_case_code || \'BLANK-CASE\' }}</output><output data-test="readiness">{{ readiness ? \'OLD-READINESS\' : \'NO-READINESS\' }}</output></section>',
          },
          LongitudinalPredictionSummary: {
            props: ['prediction'],
            template: '<output data-test="prediction">{{ prediction ? \'OLD-PREDICTION\' : \'NO-PREDICTION\' }}</output>',
          },
          LongitudinalReportView: true,
          'el-button': true,
        },
      },
    })
    await flushPromises()
    store.readiness = { ready: true } as any
    store.longitudinalPrediction = { model_status: 'available' } as any
    await nextTick()

    await wrapper.get('[data-test="show-cases"]').trigger('click')
    await nextTick()
    expect(wrapper.get('[data-test="case-code"]').text()).toBe('CASE-OLD-VISIBLE')
    expect(wrapper.get('[data-test="readiness"]').text()).toBe('OLD-READINESS')
    expect(wrapper.get('[data-test="prediction"]').text()).toBe('OLD-PREDICTION')

    await wrapper.get('[data-test="case-list-new"]').trigger('click')
    await nextTick()

    expect(wrapper.get('[data-test="case-code"]').text()).toBe('BLANK-CASE')
    expect(wrapper.get('[data-test="readiness"]').text()).toBe('NO-READINESS')
    expect(wrapper.get('[data-test="prediction"]').text()).toBe('NO-PREDICTION')
    expect(wrapper.text()).not.toContain('CASE-OLD-VISIBLE')
  })

  it('removes a populated historical report when the sidebar starts a new case', async () => {
    const { useOperatorStore } = await import('@/stores/operator')
    const store = useOperatorStore()
    const OperatorView = (await import('../OperatorView.vue')).default
    const wrapper = mount(OperatorView, {
      global: {
        mocks: { $router: { push: vi.fn() } },
        stubs: {
          OperatorSidebar: {
            template: '<button data-test="sidebar-new" @click="$emit(\'new-longitudinal-case\')">新建</button>',
          },
          OperatorCaseWorkspace: {
            props: ['model'],
            template: '<output data-test="workspace-state">{{ model ? model.anonymous_case_code : \'BLANK-WORKSPACE\' }}</output>',
          },
          OperatorCaseList: true,
          LongitudinalPredictionSummary: true,
          LongitudinalReportView: {
            props: ['report', 'predictionResult', 'evidenceSnapshot'],
            template: '<section data-test="report-state">{{ report?.content }} {{ predictionResult ? \'OLD-PREDICTION\' : \'\' }} {{ evidenceSnapshot ? \'OLD-EVIDENCE\' : \'\' }}</section>',
          },
          'el-button': true,
        },
      },
    })
    await flushPromises()
    store.currentReport = { id: 44, content: 'OLD-REPORT-CONTENT' } as any
    store.longitudinalPrediction = { model_status: 'available' } as any
    store.longitudinalEvidence = { version: 'v1' } as any
    await nextTick()
    expect(wrapper.get('[data-test="report-state"]').text()).toContain('OLD-REPORT-CONTENT')

    await wrapper.get('[data-test="sidebar-new"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-test="report-state"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="workspace-state"]').text()).toBe('BLANK-WORKSPACE')
    expect(wrapper.text()).not.toContain('OLD-REPORT-CONTENT')
    expect(store.longitudinalPrediction).toBeNull()
    expect(store.longitudinalEvidence).toBeNull()
  })
})
