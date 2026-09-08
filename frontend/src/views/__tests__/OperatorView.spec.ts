import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

const api = vi.hoisted(() => ({
  listDiseases: vi.fn(),
  listLongitudinalCases: vi.fn(),
  createLongitudinalCase: vi.fn(),
  deleteLongitudinalCase: vi.fn(),
  updateLongitudinalCaseStatus: vi.fn(),
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
  return { ...actual, ElMessage: { success: vi.fn(), error: vi.fn() }, ElMessageBox: { confirm: vi.fn(), prompt: vi.fn() } }
})

describe('OperatorView', () => {
  async function mountCases() {
    api.listLongitudinalCases.mockResolvedValue({ cases: [existingCase()] })
    const OperatorView = (await import('../OperatorView.vue')).default
    const wrapper = mount(OperatorView, { global: { mocks: { $router: { push: vi.fn() } }, stubs: { OperatorSidebar: true, LongitudinalReportView: true, 'el-button': { template: '<button><slot /></button>' } } } })
    await flushPromises()
    return wrapper
  }

  it('loads readiness and indicators when initially selecting a saved case', async () => {
    const wrapper = await mountCases()
    expect(wrapper.get('h1').text()).toBe('病例详情')
    expect(api.getLongitudinalCaseReportReadiness).toHaveBeenCalledWith(3)
    expect(api.listOperatorIndicatorCatalog).toHaveBeenCalledWith('fatty_liver')
    wrapper.unmount()
  })

  it('preserves a new draft while searching and loads dependencies only after selecting a result', async () => {
    const wrapper = await mountCases()
    const newButton = wrapper.findAll('button').find(button => button.text() === '新建病例')!
    await newButton.trigger('click')
    const age = wrapper.get('.profile-form input[type="number"]')
    await age.setValue('63')
    api.getLongitudinalCaseReportReadiness.mockClear()
    await wrapper.get('input[type="search"]').setValue('CASE-OLD')
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('建立病例')
    expect((age.element as HTMLInputElement).value).toBe('63')
    expect(api.getLongitudinalCaseReportReadiness).not.toHaveBeenCalled()
    await wrapper.get('.case-list__item').trigger('click')
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('病例详情')
    expect(api.getLongitudinalCaseReportReadiness).toHaveBeenCalledWith(3)
    wrapper.unmount()
  })

  it.each([true, false])('does not replace a draft when the initial list arrives late (new button: %s)', async (clickNew) => {
    let resolveList!: (value: any) => void
    api.listLongitudinalCases.mockReturnValue(new Promise(resolve => { resolveList = resolve }))
    const OperatorView = (await import('../OperatorView.vue')).default
    const wrapper = mount(OperatorView, { global: { mocks: { $router: { push: vi.fn() } }, stubs: { OperatorSidebar: true, LongitudinalReportView: true, 'el-button': true } } })
    if (clickNew) {
      const newButton = wrapper.findAll('button').find(button => button.text() === '新建病例')!
      await newButton.trigger('click')
    }
    const age = wrapper.get('.profile-form input[type="number"]')
    await age.setValue('63')
    resolveList({ cases: [existingCase()] })
    await flushPromises()
    expect(wrapper.get('h1').text()).toBe('建立病例')
    expect((age.element as HTMLInputElement).value).toBe('63')
    expect(api.getLongitudinalCaseReportReadiness).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('requests searched and archived cases from list controls', async () => {
    const wrapper = await mountCases()
    expect(api.listLongitudinalCases).toHaveBeenCalledWith({ status: 'active' })
    await wrapper.get('input[type="search"]').setValue('CASE-FIND')
    await flushPromises()
    expect(api.listLongitudinalCases).toHaveBeenLastCalledWith({ q: 'CASE-FIND', status: 'active' })
    await wrapper.get('[aria-label="病例状态筛选"]').setValue('archived')
    await flushPromises()
    expect(api.listLongitudinalCases).toHaveBeenLastCalledWith({ q: 'CASE-FIND', status: 'archived' })
    await wrapper.get('input[type="search"]').setValue('   ')
    await flushPromises()
    expect(api.listLongitudinalCases).toHaveBeenLastCalledWith({ status: 'archived' })
    wrapper.unmount()
  })

  it('confirms deletion while preserving historical reports, and never deletes a replacement selection', async () => {
    const wrapper = await mountCases()
    const { ElMessageBox } = await import('element-plus')
    let confirm!: () => void
    vi.mocked(ElMessageBox.confirm).mockReturnValue(new Promise(resolve => { confirm = () => resolve('confirm') }) as any)
    await wrapper.get('[data-test="delete-case"]').trigger('click')
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(expect.stringContaining('历史报告仍会保留'), expect.any(String), expect.any(Object))
    const { useOperatorStore } = await import('@/stores/operator')
    useOperatorStore().selectLongitudinalCase({ ...existingCase(), id: 4 })
    confirm()
    await flushPromises()
    expect(api.deleteLongitudinalCase).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('archives and restores a selected case through status API', async () => {
    const wrapper = await mountCases()
    const { ElMessageBox } = await import('element-plus')
    vi.mocked(ElMessageBox.prompt).mockResolvedValueOnce({ value: '资料暂不维护' } as any).mockResolvedValueOnce({ value: '恢复继续随访' } as any)
    api.updateLongitudinalCaseStatus.mockResolvedValueOnce({ ...existingCase(), status: 'archived' }).mockResolvedValueOnce(existingCase())
    await wrapper.get('[data-test="case-status"]').trigger('click')
    await flushPromises()
    expect(api.updateLongitudinalCaseStatus).toHaveBeenLastCalledWith(3, { expected_status: 'active', status: 'archived', reason: '资料暂不维护' })
    expect(wrapper.get('[data-test="case-status"]').text()).toContain('恢复病例')
    await wrapper.get('[data-test="case-status"]').trigger('click')
    await flushPromises()
    expect(api.updateLongitudinalCaseStatus).toHaveBeenLastCalledWith(3, { expected_status: 'archived', status: 'active', reason: '恢复继续随访' })
    wrapper.unmount()
  })

  it('deletes only after confirmation and disables duplicate operations until completion', async () => {
    const wrapper = await mountCases()
    const { ElMessageBox, ElMessage } = await import('element-plus')
    let confirm!: () => void
    vi.mocked(ElMessageBox.confirm).mockReturnValue(new Promise(resolve => { confirm = () => resolve('confirm') }) as any)
    api.deleteLongitudinalCase.mockResolvedValue(undefined)
    await wrapper.get('[data-test="delete-case"]').trigger('click')
    expect(wrapper.get('[data-test="delete-case"]').attributes('disabled')).toBeDefined()
    expect(api.deleteLongitudinalCase).not.toHaveBeenCalled()
    confirm()
    await flushPromises()
    expect(api.deleteLongitudinalCase).toHaveBeenCalledWith(3)
    expect(ElMessage.success).toHaveBeenCalledWith('病例已删除，历史报告仍会保留')
    const { useOperatorStore } = await import('@/stores/operator')
    expect(useOperatorStore().currentLongitudinalCase).toBeNull()
    wrapper.unmount()
  })

  it('cancels deletion without a request and reports rejected status changes', async () => {
    const wrapper = await mountCases()
    const { ElMessageBox, ElMessage } = await import('element-plus')
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    vi.mocked(ElMessageBox.prompt).mockResolvedValueOnce({ value: '归档原因' } as any)
    await wrapper.get('[data-test="delete-case"]').trigger('click')
    await flushPromises()
    expect(api.deleteLongitudinalCase).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
    api.updateLongitudinalCaseStatus.mockRejectedValue(new Error('病例已发生变化，请刷新'))
    await wrapper.get('[data-test="case-status"]').trigger('click')
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('病例已发生变化，请刷新')
    expect(wrapper.get('[data-test="case-status"]').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })

  it('does not archive a replacement selection when the confirmation resolves', async () => {
    const wrapper = await mountCases()
    const { ElMessageBox } = await import('element-plus')
    let confirm!: () => void
    vi.mocked(ElMessageBox.prompt).mockReturnValue(new Promise(resolve => { confirm = () => resolve({ value: '归档原因' }) }) as any)
    await wrapper.get('[data-test="case-status"]').trigger('click')
    const { useOperatorStore } = await import('@/stores/operator')
    useOperatorStore().selectLongitudinalCase({ ...existingCase(), id: 4 })
    confirm()
    await flushPromises()
    expect(api.updateLongitudinalCaseStatus).not.toHaveBeenCalled()
    wrapper.unmount()
  })
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listDiseases.mockResolvedValue([])
    api.listLongitudinalCases.mockResolvedValue({ cases: [] })
    api.getLongitudinalCaseReportReadiness.mockResolvedValue({ ready: false, blockers: [] })
    api.listOperatorIndicatorCatalog.mockResolvedValue({ disease_code: 'fatty_liver', items: [] })
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
          LongitudinalReportView: true,
          'el-button': true,
        },
      },
    })
    await flushPromises()
    store.readiness = { ready: true } as any
    await nextTick()

    await wrapper.get('[data-test="show-cases"]').trigger('click')
    await nextTick()
    expect(wrapper.get('[data-test="case-code"]').text()).toBe('CASE-OLD-VISIBLE')
    expect(wrapper.get('[data-test="readiness"]').text()).toBe('OLD-READINESS')

    await wrapper.get('[data-test="case-list-new"]').trigger('click')
    await nextTick()

    expect(wrapper.get('[data-test="case-code"]').text()).toBe('BLANK-CASE')
    expect(wrapper.get('[data-test="readiness"]').text()).toBe('NO-READINESS')
    expect(wrapper.text()).not.toContain('CASE-OLD-VISIBLE')
  })

  it('removes a populated historical report when the sidebar starts a new case', async () => {
    const { useReportGenerationStore } = await import('@/stores/report-generation')
    const generation = useReportGenerationStore()
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
          LongitudinalReportView: {
            props: ['report'],
            template: '<section data-test="report-state">{{ report?.content }}</section>',
          },
          'el-button': true,
        },
      },
    })
    await flushPromises()
    generation.reportId = 44
    generation.viewState = 'completed'
    generation.report = { id: 44, content: 'OLD-REPORT-CONTENT' } as any
    await nextTick()
    expect(wrapper.get('[data-test="report-state"]').text()).toContain('OLD-REPORT-CONTENT')

    await wrapper.get('[data-test="sidebar-new"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-test="report-state"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="workspace-state"]').text()).toBe('BLANK-WORKSPACE')
    expect(wrapper.text()).not.toContain('OLD-REPORT-CONTENT')
    expect(generation.report).toBeNull()
    expect(generation.viewState).toBe('idle')
  })

  it('allows archiving a disabled disease but blocks restore and unknown statuses', async () => {
    const wrapper = await mountCases()
    const { useOperatorStore } = await import('@/stores/operator')
    const store = useOperatorStore()
    store.selectLongitudinalCase({ ...existingCase(), disease: { ...existingCase().disease, operator_enabled: false } })
    await nextTick()
    expect(wrapper.get('[data-test="case-status"]').attributes('disabled')).toBeUndefined()
    store.selectLongitudinalCase({ ...existingCase(), status: 'archived', disease: { ...existingCase().disease, operator_enabled: false } })
    await nextTick()
    expect(wrapper.get('[data-test="case-status"]').attributes('disabled')).toBeDefined()
    store.selectLongitudinalCase({ ...existingCase(), status: 'unexpected' })
    await nextTick()
    expect(wrapper.get('[data-test="case-status"]').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
})
