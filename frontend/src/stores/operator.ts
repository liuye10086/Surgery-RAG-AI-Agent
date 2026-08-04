import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listReports,
  getReport,
  deleteReport,
  generateReportStream,
  generatePredictionStream,
  listDiseases,
  listCases,
  type ReportListItem,
  type ReportDetail,
  type Disease,
  type CaseRecord,
  type IndicatorInput,
  type PredictionResult,
  type IndicatorAnalysis,
} from '@/api/operator'

export const useOperatorStore = defineStore('operator', () => {
  const reports = ref<ReportListItem[]>([])
  const total = ref(0)
  const currentReport = ref<ReportDetail | null>(null)
  const loading = ref(false)
  const generating = ref(false)
  const generatedContent = ref('')
  const currentStage = ref('')
  const stageMessage = ref('')
  const currentSources = ref<any[]>([])
  const diseases = ref<Disease[]>([])
  const cases = ref<CaseRecord[]>([])
  const predictionResult = ref<PredictionResult | null>(null)
  const indicatorAnalyses = ref<IndicatorAnalysis[]>([])

  let cancelFn: (() => void) | null = null

  async function fetchReports(skip = 0, limit = 20) {
    loading.value = true
    try {
      const res = await listReports(skip, limit)
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
      generatedContent.value = ''
    }
  }

  function generateReport(
    query: string,
    departmentIds: number[] | null,
    analysisBackend: string = 'llm',
  ) {
    // 重置状态
    generating.value = true
    generatedContent.value = ''
    currentStage.value = ''
    stageMessage.value = ''
    currentSources.value = []

    cancelFn = generateReportStream(
      query,
      departmentIds,
      analysisBackend,
      {
        onStage(stage, message) {
          currentStage.value = stage
          stageMessage.value = message
        },
        onDelta(content) {
          generatedContent.value += content
        },
        onSources(sources) {
          currentSources.value = sources
        },
        onDone(reportId) {
          generating.value = false
          currentStage.value = 'done'
          // 清空流式缓存，切换到完整报告视图
          generatedContent.value = ''
          // 拉取完整报告（含 sources），刷新列表
          fetchReports()
          fetchReport(reportId)
        },
        onError(_error) {
          generating.value = false
          currentStage.value = 'error'
          // 刷新列表以获取 failed 状态的报告
          fetchReports()
        },
      },
    )
  }

  async function fetchDiseases() {
    diseases.value = await listDiseases()
  }

  async function fetchCases(diseaseId?: number) {
    const res = await listCases(diseaseId)
    cases.value = res.items
  }

  function generatePrediction(request: { disease_id: number; indicators: IndicatorInput[]; patient_summary?: string }) {
    // 重置状态
    generating.value = true
    generatedContent.value = ''
    currentStage.value = ''
    stageMessage.value = ''
    currentSources.value = []
    predictionResult.value = null
    indicatorAnalyses.value = []

    cancelFn = generatePredictionStream(request, {
      onStage: (s, m) => { currentStage.value = s; stageMessage.value = m },
      onIndicators: (analyses, prediction) => { indicatorAnalyses.value = analyses; predictionResult.value = prediction },
      onDelta: (c) => { generatedContent.value += c },
      onSources: (s) => { currentSources.value = s },
      onDone: (id) => {
        generating.value = false
        currentStage.value = 'done'
        generatedContent.value = ''
        fetchReports()
        fetchReport(id)
      },
      onError: () => {
        generating.value = false
        currentStage.value = 'error'
        fetchReports()
      },
    })
  }

  function cancelGeneration() {
    if (cancelFn) {
      cancelFn()
      cancelFn = null
    }
    generating.value = false
    currentStage.value = 'cancelled'
  }

  function clearCurrent() {
    currentReport.value = null
    generatedContent.value = ''
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
    generatedContent,
    currentStage,
    stageMessage,
    currentSources,
    diseases,
    cases,
    predictionResult,
    indicatorAnalyses,

    fetchReports,
    fetchReport,
    removeReport,
    generateReport,
    fetchDiseases,
    fetchCases,
    generatePrediction,
    cancelGeneration,
    clearCurrent,
  }
})
