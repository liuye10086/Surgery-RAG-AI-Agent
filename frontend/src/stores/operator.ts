import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listReports,
  getReport,
  deleteReport,
  listLongitudinalCases,
  createLongitudinalCase,
  saveLongitudinalCase as saveLongitudinalCaseRequest,
  deleteLongitudinalCase,
  updateLongitudinalCaseStatus,
  getLongitudinalCaseReportReadiness,
  generateLongitudinalReportStream,
  listDiseases,
  listOperatorIndicatorCatalog,
  type ReportListItem,
  type ReportDetail,
  type Disease,
  type LongitudinalCase,
  type LongitudinalCaseCreatePayload,
  type LongitudinalCaseSavePayload,
  type LongitudinalCaseStatus,
  type OperatorCaseListParams,
  type OperatorCaseReportReadiness,
  type LongitudinalPrediction,
  type OperatorIndicatorCatalog,
} from '@/api/operator'

export const useOperatorStore = defineStore('operator', () => {
  const reports = ref<ReportListItem[]>([])
  const total = ref(0)
  const currentReport = ref<ReportDetail | null>(null)
  const loading = ref(false)
  const caseListLoading = ref(false)
  const saving = ref(false)
  const readinessLoading = ref(false)
  const generating = ref(false)
  const currentStage = ref('')
  const stageMessage = ref('')
  const currentSources = ref<any[]>([])
  const diseases = ref<Disease[]>([])
  const indicatorCatalogs = ref<Record<string, OperatorIndicatorCatalog>>({})
  const indicatorCatalogLoading = ref<Record<string, boolean>>({})
  const longitudinalCases = ref<LongitudinalCase[]>([])
  const currentLongitudinalCase = ref<LongitudinalCase | null>(null)
  const draft = ref<LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload | null>(null)
  const readiness = ref<OperatorCaseReportReadiness | null>(null)
  const longitudinalCaseStatusFilter = ref<LongitudinalCaseStatus | undefined>(undefined)
  const longitudinalPrediction = ref<LongitudinalPrediction | null>(null)
  const longitudinalReportContent = ref('')

  let cancelFn: (() => void) | null = null
  let createIdempotencyKey: string | null = null

  async function fetchReports(skip = 0, limit = 20, append = false) {
    loading.value = true
    try {
      const res = await listReports(skip, limit, 'longitudinal_predictive')
      reports.value = append
        ? [...reports.value, ...res.reports.filter((item) => !reports.value.some((existing) => existing.id === item.id))]
        : res.reports
      total.value = res.total
    } finally {
      loading.value = false
    }
  }

  async function fetchReport(reportId: number) {
    loading.value = true
    try {
      currentReport.value = await getReport(reportId)
    } finally {
      loading.value = false
    }
  }

  async function loadSavedReport(reportId: number) {
    cancelGeneration()
    longitudinalPrediction.value = null
    longitudinalReportContent.value = ''
    currentSources.value = []
    return fetchReport(reportId)
  }

  async function removeReport(reportId: number) {
    await deleteReport(reportId)
    reports.value = reports.value.filter((r) => r.id !== reportId)
    total.value = Math.max(0, total.value - 1)
    if (currentReport.value?.id === reportId) {
      currentReport.value = null
      longitudinalReportContent.value = ''
    }
  }

  async function fetchDiseases() {
    diseases.value = await listDiseases()
  }

  async function fetchOperatorIndicatorCatalog(code: string, force = false) {
    if (!force && indicatorCatalogs.value[code]) return indicatorCatalogs.value[code]
    indicatorCatalogLoading.value = { ...indicatorCatalogLoading.value, [code]: true }
    try {
      const catalog = await listOperatorIndicatorCatalog(code)
      indicatorCatalogs.value = { ...indicatorCatalogs.value, [code]: catalog }
      return catalog
    } finally {
      indicatorCatalogLoading.value = { ...indicatorCatalogLoading.value, [code]: false }
    }
  }

  function cancelGeneration() {
    if (cancelFn) {
      cancelFn()
      cancelFn = null
    }
    generating.value = false
    currentStage.value = 'cancelled'
  }

  async function fetchLongitudinalCases(params: OperatorCaseListParams = {}) {
    longitudinalCaseStatusFilter.value = params.status
    caseListLoading.value = true
    try {
      const result = await listLongitudinalCases(params)
      longitudinalCases.value = result.cases
      if (!currentLongitudinalCase.value && result.cases.length) currentLongitudinalCase.value = result.cases[0]
      return result
    } finally {
      caseListLoading.value = false
    }
  }

  async function saveLongitudinalCase(id: number, data: LongitudinalCaseSavePayload): Promise<LongitudinalCase>
  async function saveLongitudinalCase(data: LongitudinalCaseCreatePayload): Promise<LongitudinalCase>
  async function saveLongitudinalCase(idOrData: number | LongitudinalCaseCreatePayload, maybeData?: LongitudinalCaseSavePayload) {
    const isCreate = typeof idOrData !== 'number'
    const id = isCreate ? undefined : idOrData
    const data = (isCreate ? idOrData : maybeData) as LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload
    draft.value = data
    saving.value = true
    try {
      let saved: LongitudinalCase
      if (isCreate) {
        createIdempotencyKey ||= crypto.randomUUID()
        saved = await createLongitudinalCase(data as LongitudinalCaseCreatePayload, createIdempotencyKey)
        createIdempotencyKey = null
      } else {
        saved = await saveLongitudinalCaseRequest(id as number, data as LongitudinalCaseSavePayload)
      }
      currentLongitudinalCase.value = saved
      draft.value = null
      longitudinalCases.value = [saved, ...longitudinalCases.value.filter((item) => item.id !== saved.id)]
      await refreshLongitudinalCaseReadiness(saved.id)
      return saved
    } finally {
      saving.value = false
    }
  }

  async function refreshLongitudinalCaseReadiness(caseId: number) {
    readinessLoading.value = true
    try {
      readiness.value = await getLongitudinalCaseReportReadiness(caseId)
      return readiness.value
    } finally {
      readinessLoading.value = false
    }
  }

  async function changeLongitudinalCaseStatus(status: LongitudinalCaseStatus, reason?: string) {
    const current = currentLongitudinalCase.value
    if (!current) throw new Error('请先选择病例')
    const saved = await updateLongitudinalCaseStatus(current.id, {
      expected_status: current.status,
      status,
      reason: reason || null,
    })
    currentLongitudinalCase.value = saved
    longitudinalCases.value = longitudinalCases.value.map((item) => item.id === saved.id ? saved : item)
    await refreshLongitudinalCaseReadiness(saved.id)
    return saved
  }

  async function removeLongitudinalCase() {
    if (currentLongitudinalCase.value && currentLongitudinalCase.value.status !== 'active') throw new Error(currentLongitudinalCase.value.status === 'archived' ? '病例已归档，请先恢复病例' : '病例状态未知，已停止写入操作')
    const current = currentLongitudinalCase.value
    if (!current) throw new Error('请先选择病例')
    await deleteLongitudinalCase(current.id)
    try {
      await fetchLongitudinalCases({ status: longitudinalCaseStatusFilter.value })
    } catch {
      throw new Error('病例已删除，但病例列表刷新失败，请重新加载页面')
    } finally {
      currentLongitudinalCase.value = null
      longitudinalPrediction.value = null
      longitudinalReportContent.value = ''
    }
  }

  function generateLongitudinalReport(caseId: number) {
    generating.value = true
    longitudinalPrediction.value = null
    longitudinalReportContent.value = ''
    cancelFn = generateLongitudinalReportStream(caseId, {
      onStage: (stage, message) => { currentStage.value = stage; stageMessage.value = message },
      onPrediction: (prediction) => { longitudinalPrediction.value = prediction },
      onDelta: (content) => { longitudinalReportContent.value += content },
      onSources: (sources) => { currentSources.value = sources },
      onDone: (id) => { generating.value = false; fetchReports(); fetchReport(id) },
      onError: () => { generating.value = false; currentStage.value = 'error'; fetchReports() },
    })
    return cancelFn
  }

  function clearCurrent() {
    currentReport.value = null
    longitudinalReportContent.value = ''
    currentStage.value = ''
    stageMessage.value = ''
    currentSources.value = []
  }

  return {
    reports,
    total,
    currentReport,
    loading,
    generating,
    currentStage,
    stageMessage,
    currentSources,
    diseases,
    indicatorCatalogs,
    indicatorCatalogLoading,
    caseListLoading,
    saving,
    readinessLoading,
    longitudinalCases,
    currentLongitudinalCase,
    draft,
    readiness,
    longitudinalCaseStatusFilter,
    longitudinalPrediction,
    longitudinalReportContent,

    fetchReports,
    fetchReport,
    loadSavedReport,
    removeReport,
    fetchDiseases,
    fetchOperatorIndicatorCatalog,
    cancelGeneration,
    clearCurrent,
    fetchLongitudinalCases,
    saveLongitudinalCase,
    refreshLongitudinalCaseReadiness,
    changeLongitudinalCaseStatus,
    removeLongitudinalCase,
    generateLongitudinalReport,
  }
})
