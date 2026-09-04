import { defineStore } from 'pinia'
import { readonly, ref } from 'vue'
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
  type EvidenceBundleV1,
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
  const longitudinalEvidence = ref<EvidenceBundleV1 | null>(null)
  const caseSessionRevision = ref(0)

  let cancelFn: (() => void) | null = null
  let createIdempotencyKey: string | null = null

  function beginCaseSession() {
    caseSessionRevision.value += 1
    return caseSessionRevision.value
  }

  function isCurrentCaseSession(revision: number, caseId?: number) {
    return caseSessionRevision.value === revision
      && (caseId === undefined || currentLongitudinalCase.value?.id === caseId)
  }

  function stopGeneration() {
    if (cancelFn) {
      cancelFn()
      cancelFn = null
    }
    generating.value = false
  }

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

  async function fetchReport(reportId: number, revision = caseSessionRevision.value) {
    loading.value = true
    try {
      const report = await getReport(reportId)
      if (isCurrentCaseSession(revision)) currentReport.value = report
      return report
    } finally {
      if (isCurrentCaseSession(revision)) loading.value = false
    }
  }

  async function loadSavedReport(reportId: number) {
    stopGeneration()
    clearCurrent()
    const revision = caseSessionRevision.value
    longitudinalPrediction.value = null
    longitudinalEvidence.value = null
    longitudinalReportContent.value = ''
    currentSources.value = []
    return fetchReport(reportId, revision)
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
    stopGeneration()
    beginCaseSession()
    currentStage.value = 'cancelled'
  }

  async function fetchLongitudinalCases(params: OperatorCaseListParams = {}) {
    const revision = caseSessionRevision.value
    longitudinalCaseStatusFilter.value = params.status
    caseListLoading.value = true
    try {
      const result = await listLongitudinalCases(params)
      longitudinalCases.value = result.cases
      if (isCurrentCaseSession(revision) && !currentLongitudinalCase.value && result.cases.length) selectLongitudinalCase(result.cases[0])
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
    const revision = caseSessionRevision.value
    const data = (isCreate ? idOrData : maybeData) as LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload
    draft.value = data
    saving.value = true
    try {
      let saved: LongitudinalCase
      if (isCreate) {
        createIdempotencyKey ||= crypto.randomUUID()
        saved = await createLongitudinalCase(data as LongitudinalCaseCreatePayload, createIdempotencyKey)
        if (isCurrentCaseSession(revision)) createIdempotencyKey = null
      } else {
        saved = await saveLongitudinalCaseRequest(id as number, data as LongitudinalCaseSavePayload)
      }
      if (!isCurrentCaseSession(revision, id)) return saved
      currentLongitudinalCase.value = saved
      draft.value = null
      longitudinalCases.value = [saved, ...longitudinalCases.value.filter((item) => item.id !== saved.id)]
      await refreshLongitudinalCaseReadiness(saved.id, revision)
      return saved
    } finally {
      if (isCurrentCaseSession(revision)) saving.value = false
    }
  }

  async function refreshLongitudinalCaseReadiness(caseId: number, revision = caseSessionRevision.value) {
    if (!isCurrentCaseSession(revision, caseId)) return null
    readinessLoading.value = true
    try {
      const nextReadiness = await getLongitudinalCaseReportReadiness(caseId)
      if (isCurrentCaseSession(revision, caseId)) readiness.value = nextReadiness
      return nextReadiness
    } finally {
      if (isCurrentCaseSession(revision, caseId)) readinessLoading.value = false
    }
  }

  async function changeLongitudinalCaseStatus(status: LongitudinalCaseStatus, reason?: string) {
    const current = currentLongitudinalCase.value
    if (!current) throw new Error('请先选择病例')
    const revision = caseSessionRevision.value
    const saved = await updateLongitudinalCaseStatus(current.id, {
      expected_status: current.status,
      status,
      reason: reason || null,
    })
    if (!isCurrentCaseSession(revision, current.id)) return saved
    currentLongitudinalCase.value = saved
    longitudinalCases.value = longitudinalCases.value.map((item) => item.id === saved.id ? saved : item)
    await refreshLongitudinalCaseReadiness(saved.id, revision)
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
    const revision = caseSessionRevision.value
    if (!isCurrentCaseSession(revision, caseId)) return
    generating.value = true
    longitudinalPrediction.value = null
    longitudinalEvidence.value = null
    longitudinalReportContent.value = ''
    cancelFn = generateLongitudinalReportStream(caseId, {
      onStage: (stage, message) => { if (isCurrentCaseSession(revision, caseId)) { currentStage.value = stage; stageMessage.value = message } },
      onPrediction: (prediction) => { if (isCurrentCaseSession(revision, caseId)) longitudinalPrediction.value = prediction },
      onEvidence: (evidence) => { if (isCurrentCaseSession(revision, caseId)) longitudinalEvidence.value = evidence },
      onDelta: (content) => { if (isCurrentCaseSession(revision, caseId)) longitudinalReportContent.value += content },
      onSources: (sources) => { if (isCurrentCaseSession(revision, caseId)) currentSources.value = sources },
      onDone: (id) => { if (isCurrentCaseSession(revision, caseId)) { generating.value = false; fetchReports(); fetchReport(id, revision) } },
      onError: () => { if (isCurrentCaseSession(revision, caseId)) { generating.value = false; currentStage.value = 'error'; fetchReports() } },
    })
    return cancelFn
  }

  function clearCurrent() {
    beginCaseSession()
    currentReport.value = null
    loading.value = false
    longitudinalReportContent.value = ''
    longitudinalEvidence.value = null
    currentStage.value = ''
    stageMessage.value = ''
    currentSources.value = []
  }

  function startNewLongitudinalCase() {
    stopGeneration()
    clearCurrent()
    currentLongitudinalCase.value = null
    draft.value = null
    readiness.value = null
    readinessLoading.value = false
    saving.value = false
    longitudinalPrediction.value = null
    createIdempotencyKey = null
  }

  function selectLongitudinalCase(item: LongitudinalCase) {
    stopGeneration()
    clearCurrent()
    currentLongitudinalCase.value = item
    draft.value = null
    readiness.value = null
    readinessLoading.value = false
    saving.value = false
    longitudinalPrediction.value = null
    return caseSessionRevision.value
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
    caseSessionRevision: readonly(caseSessionRevision),
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
    longitudinalEvidence,
    longitudinalReportContent,

    fetchReports,
    fetchReport,
    loadSavedReport,
    removeReport,
    fetchDiseases,
    fetchOperatorIndicatorCatalog,
    cancelGeneration,
    clearCurrent,
    startNewLongitudinalCase,
    selectLongitudinalCase,
    fetchLongitudinalCases,
    saveLongitudinalCase,
    refreshLongitudinalCaseReadiness,
    changeLongitudinalCaseStatus,
    removeLongitudinalCase,
    generateLongitudinalReport,
  }
})
