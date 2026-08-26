import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listReports,
  getReport,
  deleteReport,
  listLongitudinalCases,
  createLongitudinalCase,
  updateLongitudinalCase,
  addLongitudinalVisit,
  replaceLongitudinalVisits,
  generateLongitudinalReportStream,
  predictProgression,
  listDiseases,
  listCases,
  type ReportListItem,
  type ReportDetail,
  type Disease,
  type CaseRecord,
  type IndicatorInput,
  type ProgressionPredictionRequest,
  type ProgressionPredictionOut,
  type LongitudinalCase,
  type LongitudinalPrediction,
} from '@/api/operator'

export const useOperatorStore = defineStore('operator', () => {
  const reports = ref<ReportListItem[]>([])
  const total = ref(0)
  const currentReport = ref<ReportDetail | null>(null)
  const loading = ref(false)
  const generating = ref(false)
  const currentStage = ref('')
  const stageMessage = ref('')
  const currentSources = ref<any[]>([])
  const diseases = ref<Disease[]>([])
  const cases = ref<CaseRecord[]>([])
  const progressionResult = ref<ProgressionPredictionOut | null>(null)
  const progressionLoading = ref(false)
  const longitudinalCases = ref<LongitudinalCase[]>([])
  const currentLongitudinalCase = ref<LongitudinalCase | null>(null)
  const longitudinalPrediction = ref<LongitudinalPrediction | null>(null)
  const longitudinalReportContent = ref('')

  let cancelFn: (() => void) | null = null

  async function fetchReports(skip = 0, limit = 20) {
    loading.value = true
    try {
      const res = await listReports(skip, limit, 'longitudinal_predictive')
      reports.value = res.reports
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

  async function fetchCases(diseaseId?: number) {
    const res = await listCases(diseaseId)
    cases.value = res.items
  }

  function cancelGeneration() {
    if (cancelFn) {
      cancelFn()
      cancelFn = null
    }
    generating.value = false
    currentStage.value = 'cancelled'
  }

  async function predictLongitudinalProgression(request: ProgressionPredictionRequest) {
    progressionLoading.value = true
    progressionResult.value = null
    try {
      progressionResult.value = await predictProgression(request)
      return progressionResult.value
    } finally {
      progressionLoading.value = false
    }
  }

  function clearProgression() {
    progressionResult.value = null
  }

  async function fetchLongitudinalCases(diseaseId?: number) {
    const result = await listLongitudinalCases(diseaseId)
    longitudinalCases.value = result.cases
    if (!currentLongitudinalCase.value && result.cases.length) currentLongitudinalCase.value = result.cases[0]
  }

  async function saveLongitudinalCase(data: { disease_id: number; patient_label: string; sex?: string | null; baseline_stage?: import('@/api/operator').BaselineStage | null; notes?: string | null; visits?: Array<{ visit_date: string; indicators: IndicatorInput[]; notes?: string | null }> }) {
    const { visits, ...caseData } = data
    const saved = currentLongitudinalCase.value?.id
      ? await updateLongitudinalCase(currentLongitudinalCase.value.id, caseData)
      : await createLongitudinalCase(caseData)
    if (visits) saved.visits = await replaceLongitudinalVisits(saved.id, visits)
    currentLongitudinalCase.value = saved
    longitudinalCases.value = [currentLongitudinalCase.value, ...longitudinalCases.value.filter((item) => item.id !== currentLongitudinalCase.value?.id)]
    return currentLongitudinalCase.value
  }

  async function saveLongitudinalVisit(data: { visit_date: string; indicators: IndicatorInput[]; notes?: string }) {
    if (!currentLongitudinalCase.value) throw new Error('请先选择病例')
    const visit = await addLongitudinalVisit(currentLongitudinalCase.value.id, data)
    currentLongitudinalCase.value.visits = [...currentLongitudinalCase.value.visits, visit].sort((a, b) => a.visit_date.localeCompare(b.visit_date))
    return visit
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
    cases,
    progressionResult,
    progressionLoading,
    longitudinalCases,
    currentLongitudinalCase,
    longitudinalPrediction,
    longitudinalReportContent,

    fetchReports,
    fetchReport,
    removeReport,
    fetchDiseases,
    fetchCases,
    cancelGeneration,
    clearCurrent,
    predictLongitudinalProgression,
    clearProgression,
    fetchLongitudinalCases,
    saveLongitudinalCase,
    saveLongitudinalVisit,
    generateLongitudinalReport,
  }
})
