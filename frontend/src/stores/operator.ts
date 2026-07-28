import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listReports,
  getReport,
  deleteReport,
  generateReportStream,
  type ReportListItem,
  type ReportDetail,
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
        onDone(_reportId) {
          generating.value = false
          currentStage.value = 'done'
          // 刷新报告列表
          fetchReports()
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
    fetchReports,
    fetchReport,
    removeReport,
    generateReport,
    cancelGeneration,
    clearCurrent,
  }
})
