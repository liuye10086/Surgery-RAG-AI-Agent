import { defineStore } from 'pinia'
import { readonly, ref, watch } from 'vue'
import { useAuthStore } from './auth'
import {
  deleteReport,
  listLongitudinalCases,
  createLongitudinalCase,
  saveLongitudinalCase as saveLongitudinalCaseRequest,
  deleteLongitudinalCase,
  updateLongitudinalCaseStatus,
  getLongitudinalCaseReportReadiness,
  listDiseases,
  listOperatorIndicatorCatalog,
  type Disease,
  type LongitudinalCase,
  type LongitudinalCaseCreatePayload,
  type LongitudinalCaseSavePayload,
  type LongitudinalCaseStatus,
  type OperatorCaseListParams,
  type OperatorCaseReportReadiness,
  type OperatorIndicatorCatalog,
} from '@/api/operator'

export const useOperatorStore = defineStore('operator', () => {
  const auth = useAuthStore()
  let caseListEpoch = 0
  let caseListParams: OperatorCaseListParams = {}
  const caseListLoading = ref(false)
  const saving = ref(false)
  const readinessLoading = ref(false)
  const diseases = ref<Disease[]>([])
  const indicatorCatalogs = ref<Record<string, OperatorIndicatorCatalog>>({})
  const indicatorCatalogLoading = ref<Record<string, boolean>>({})
  const longitudinalCases = ref<LongitudinalCase[]>([])
  const currentLongitudinalCase = ref<LongitudinalCase | null>(null)
  const draft = ref<LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload | null>(null)
  const readiness = ref<OperatorCaseReportReadiness | null>(null)
  const longitudinalCaseStatusFilter = ref<LongitudinalCaseStatus | undefined>(undefined)
  const caseSessionRevision = ref(0)

  let createIdempotencyKey: string | null = null

  function beginCaseSession() {
    caseSessionRevision.value += 1
    return caseSessionRevision.value
  }

  function isCurrentCaseSession(revision: number, caseId?: number) {
    return caseSessionRevision.value === revision
      && (caseId === undefined || currentLongitudinalCase.value?.id === caseId)
  }

  async function removeReport(reportId: number) {
    return deleteReport(reportId)
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

  async function fetchLongitudinalCases(params: OperatorCaseListParams = {}) {
    const epoch = ++caseListEpoch
    caseListParams = { ...params }
    longitudinalCaseStatusFilter.value = params.status
    caseListLoading.value = true
    try {
      const result = await listLongitudinalCases(params)
      if (epoch !== caseListEpoch) return result
      longitudinalCases.value = result.cases
      return result
    } finally {
      if (epoch === caseListEpoch) caseListLoading.value = false
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
      await Promise.all([
        fetchLongitudinalCases(caseListParams),
        refreshLongitudinalCaseReadiness(saved.id, revision),
      ])
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
    await Promise.all([
      fetchLongitudinalCases(caseListParams),
      refreshLongitudinalCaseReadiness(saved.id, revision),
    ])
    return saved
  }

  async function removeLongitudinalCase() {
    if (currentLongitudinalCase.value && currentLongitudinalCase.value.status !== 'active') throw new Error(currentLongitudinalCase.value.status === 'archived' ? '病例已归档，请先恢复病例' : '病例状态未知，已停止写入操作')
    const current = currentLongitudinalCase.value
    if (!current) throw new Error('请先选择病例')
    const revision = caseSessionRevision.value
    await deleteLongitudinalCase(current.id)
    if (!isCurrentCaseSession(revision, current.id)) return
    try {
      await fetchLongitudinalCases(caseListParams)
    } catch {
      throw new Error('病例已删除，但病例列表刷新失败，请重新加载页面')
    } finally {
      if (isCurrentCaseSession(revision, current.id)) startNewLongitudinalCase()
    }
  }

  function clearCurrent() {
    beginCaseSession()
  }

  function startNewLongitudinalCase() {
    clearCurrent()
    currentLongitudinalCase.value = null
    draft.value = null
    readiness.value = null
    readinessLoading.value = false
    saving.value = false
    createIdempotencyKey = null
  }

  function selectLongitudinalCase(item: LongitudinalCase) {
    clearCurrent()
    currentLongitudinalCase.value = item
    draft.value = null
    readiness.value = null
    readinessLoading.value = false
    saving.value = false
    return caseSessionRevision.value
  }

  watch(() => auth.user?.id, (next, previous) => {
    if (next === previous) return
    caseListEpoch += 1
    longitudinalCases.value = []
    caseListLoading.value = false
    startNewLongitudinalCase()
  }, { flush: 'sync' })

  return {
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
    removeReport,
    fetchDiseases,
    fetchOperatorIndicatorCatalog,
    clearCurrent,
    startNewLongitudinalCase,
    selectLongitudinalCase,
    fetchLongitudinalCases,
    saveLongitudinalCase,
    refreshLongitudinalCaseReadiness,
    changeLongitudinalCaseStatus,
    removeLongitudinalCase,
  }
})
