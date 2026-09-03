<template>
  <div class="operator-view">
    <OperatorSidebar
      :reports="operatorStore.reports"
      :total="operatorStore.total"
      :current-id="operatorStore.currentReport?.id"
      :collapsed="sidebarCollapsed"
      :loading="operatorStore.loading"
      :generating="operatorStore.generating"
      :active-view="activeView"
      @toggle="toggleSidebar"
      @select="handleSelect"
      @new-longitudinal-case="startNewLongitudinalCase"
      @delete="handleDelete"
      @load-more="loadMoreReports"
      @navigate="activeView = $event"
    />

    <div class="operator-main">
      <div class="operator-header">
        <h2>AI 操作者工作台</h2>
        <div class="header-actions">
          <el-button
            v-if="authStore.canAccessOperator && authStore.isAdmin"
            size="small"
            @click="$router.push('/')"
          >
            返回聊天
          </el-button>
        </div>
      </div>

      <div class="operator-body">
        <LongitudinalReportView
          v-if="reportReadingMode"
          :report="operatorStore.currentReport"
          :prediction-result="operatorStore.longitudinalPrediction"
          :rendered-content="renderMarkdown(operatorStore.generating ? operatorStore.longitudinalReportContent : operatorStore.currentReport?.content || '')"
          :generating="operatorStore.generating"
          @back="closeReport"
          @download="handleDownload"
        />

        <!-- 统一病例工作区：病例库和进展预测共用同一份聚合草稿 -->
        <div v-else class="progression-view">
          <div class="progression-inner">
            <OperatorCaseList v-if="activeView === 'cases'" :cases="operatorStore.longitudinalCases" :selected-id="operatorStore.currentLongitudinalCase?.id" :loading="operatorStore.caseListLoading" @select="selectLongitudinalCase" @new="startNewLongitudinalCase" />
            <OperatorCaseWorkspace
              :model="operatorStore.currentLongitudinalCase"
              :diseases="progressionDiseases"
              :indicator-catalog="activeIndicatorCatalog"
              :validation-issues="validationIssues"
              :readiness="operatorStore.readiness"
              :saving="operatorStore.saving"
              :report-generating="operatorStore.generating"
              @save="handleWorkspaceSave"
              @disease-change="handleDiseaseChange"
              @edit="validationIssues = {}"
              @generate-report="generateCurrentReport"
            />
            <LongitudinalPredictionSummary :prediction="operatorStore.longitudinalPrediction" />
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OperatorSidebar from '@/components/OperatorSidebar.vue'
import OperatorCaseList from '@/components/operator-case/OperatorCaseList.vue'
import OperatorCaseWorkspace from '@/components/operator-case/OperatorCaseWorkspace.vue'
import LongitudinalPredictionSummary from '@/components/LongitudinalPredictionSummary.vue'
import LongitudinalReportView from '@/components/LongitudinalReportView.vue'
import { useAuthStore } from '@/stores/auth'
import { useOperatorStore } from '@/stores/operator'
import { downloadReport, type LongitudinalCaseCreatePayload, type LongitudinalCaseSavePayload } from '@/api/operator'
import { validationIssueMap } from '@/api/request'

const authStore = useAuthStore()
const operatorStore = useOperatorStore()

const sidebarCollapsed = ref(localStorage.getItem('operator_sidebar_collapsed') === 'true')
const activeView = ref<'progression' | 'cases'>('progression')
const progressionDiseases = computed(() => operatorStore.diseases)
const draftDiseaseCode = ref('')
const activeDiseaseCode = computed(() => operatorStore.currentLongitudinalCase?.disease.code || draftDiseaseCode.value)
const activeIndicatorCatalog = computed(() => activeDiseaseCode.value ? operatorStore.indicatorCatalogs[activeDiseaseCode.value] || null : null)
const validationIssues = ref<Record<string, string>>({})

const reportReadingMode = computed(() =>
  activeView.value === 'progression'
  && Boolean(operatorStore.generating || operatorStore.currentReport),
)

const REPORT_SECTIONS = [
  { id: 'section-1', title: '报告摘要' },
  { id: 'section-2', title: '病例与预测范围' },
  { id: 'section-3', title: '数据质量与适用性' },
  { id: 'section-4', title: '已观察到的纵向变化' },
  { id: 'section-5', title: '未来 365 天进展风险' },
  { id: 'section-6', title: '阶段模型和下一次随访趋势的可用状态' },
  { id: 'section-7', title: '关键进展信号' },
  { id: 'section-8', title: '参考标准和相似病例' },
  { id: 'section-9', title: '不确定性与局限性' },
  { id: 'section-10', title: '人工复核重点' },
  { id: 'section-11', title: '模型和数据技术附录' },
]

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('operator_sidebar_collapsed', String(sidebarCollapsed.value))
}

function renderMarkdown(md: string): string {
  const raw = marked.parse(md || '', { breaks: true }) as string
  const safe = DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'ul', 'ol', 'li',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'strong', 'em', 'code', 'pre',
      'blockquote', 'hr', 'br',
      'sup', 'sub', 'a', 'span', 'div',
    ],
  })
  const document = new DOMParser().parseFromString(safe, 'text/html')
  const headings = Array.from(document.body.querySelectorAll('h2'))
  REPORT_SECTIONS.forEach((section) => {
    const heading = headings.find((item) => item.textContent?.includes(section.title))
    if (heading) heading.id = section.id
  })
  return document.body.innerHTML
}

function loadMoreReports() {
  return operatorStore.fetchReports(operatorStore.reports.length, 20, true)
}

async function handleWorkspaceSave(payload: LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload) {
  validationIssues.value = {}
  try {
    const saved = operatorStore.currentLongitudinalCase?.id
      ? await operatorStore.saveLongitudinalCase(operatorStore.currentLongitudinalCase.id, payload as LongitudinalCaseSavePayload)
      : await operatorStore.saveLongitudinalCase(payload as LongitudinalCaseCreatePayload)
    ElMessage.success(`病例已保存：${saved.anonymous_case_code || '匿名编号待生成'}`)
  } catch (error: any) {
    validationIssues.value = validationIssueMap(error)
    ElMessage.error(error?.message || '病例保存失败')
  }
}

function startNewLongitudinalCase() {
  operatorStore.clearCurrent()
  operatorStore.currentLongitudinalCase = null
  operatorStore.longitudinalPrediction = null
  operatorStore.longitudinalReportContent = ''
  draftDiseaseCode.value = ''
  validationIssues.value = {}
}

async function selectLongitudinalCase(item: any) {
  operatorStore.currentLongitudinalCase = item
  draftDiseaseCode.value = ''
  validationIssues.value = {}
  await Promise.all([
    operatorStore.refreshLongitudinalCaseReadiness(item.id),
    handleDiseaseChange(item.disease.code),
  ])
}

async function handleDiseaseChange(code: string) {
  draftDiseaseCode.value = code
  if (!code) return
  try {
    await operatorStore.fetchOperatorIndicatorCatalog(code)
  } catch (error: any) {
    ElMessage.error(error?.message || '指标目录加载失败')
  }
}

function generateCurrentReport() {
  const id = operatorStore.currentLongitudinalCase?.id
  if (id) operatorStore.generateLongitudinalReport(id)
}

async function handleDownload() {
  if (!operatorStore.currentReport) return
  try {
    const filename = `${operatorStore.currentReport.anonymous_case_code || `report-${operatorStore.currentReport.id}`}.pdf`
    await downloadReport(operatorStore.currentReport.id, filename)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function handleSelect(id: number) {
  // 从病例库选择历史报告时，切回纵向报告视图
  activeView.value = 'progression'
  operatorStore.clearCurrent()
  await operatorStore.loadSavedReport(id)
}

function closeReport() {
  if (operatorStore.generating) operatorStore.cancelGeneration()
  operatorStore.clearCurrent()
}

async function handleDelete(id: number) {
  try {
    await ElMessageBox.confirm('确定删除该报告？删除后不可恢复。', '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await operatorStore.removeReport(id)
    ElMessage.success('报告已删除')
  } catch {
    // 用户取消
  }
}

onMounted(async () => {
  operatorStore.fetchReports()
  await Promise.all([
    operatorStore.fetchDiseases(),
    operatorStore.fetchLongitudinalCases(),
  ])
  const selected = operatorStore.currentLongitudinalCase
  if (selected) {
    await Promise.all([
      handleDiseaseChange(selected.disease.code),
      operatorStore.refreshLongitudinalCaseReadiness(selected.id),
    ])
  }
})
</script>

<style scoped>
.operator-view {
  display: flex;
  height: 100vh;
  background: var(--bg-surface);
}

.operator-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: var(--bg-canvas);
}

/* ===== 顶部 header ===== */
.operator-header {
  height: var(--topbar-height);
  padding: 0 var(--space-6);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.operator-header h2 {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  flex-shrink: 0;
  margin-left: var(--space-4);
}

/* ===== 主体 ===== */
.operator-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

/* ===== 纵向进展预测 ===== */
.progression-view {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
}

.progression-inner {
  width: min(100%, var(--content-max-width));
  margin: 0 auto;
}

/* ===== 报告内容卡片 ===== */
.report-content {
  background: var(--bg-surface);
  border-radius: var(--radius-card);
  padding: var(--space-6) var(--space-8);
  box-shadow: var(--shadow-sm);
  margin-bottom: var(--space-6);
}

.report-head {
  margin-bottom: var(--space-6);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-light);
}

.report-head h3 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 var(--space-3) 0;
}

.report-head-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.meta-time {
  font-size: var(--text-xs);
  color: var(--text-disabled);
}

/* ===== Markdown 正文 ===== */
.markdown-body {
  font-size: var(--text-base);
  line-height: 1.8;
  color: var(--text-primary);
}

.markdown-body :deep(h2) {
  font-size: var(--text-md);
  font-weight: 600;
  margin: 1.5em 0 0.8em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--border-light);
}

.markdown-body :deep(h3) {
  font-size: var(--text-base);
  font-weight: 600;
  margin: 1.2em 0 0.6em;
}

.markdown-body :deep(p) {
  margin: 0.6em 0;
}

.markdown-body :deep(ul), .markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin: 0.5em 0;
}

.markdown-body :deep(li) {
  margin: 0.3em 0;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: var(--text-sm);
}

.markdown-body :deep(th), .markdown-body :deep(td) {
  border: 1px solid var(--border-default);
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--bg-sidebar);
  font-weight: 600;
}

.markdown-body :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.6em 1em;
  border-left: 3px solid var(--color-accent);
  background: var(--color-accent-light);
  color: var(--text-secondary);
}

.markdown-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.9em;
  background: var(--bg-input);
  padding: 1px 5px;
  border-radius: 4px;
}

.markdown-body :deep(pre) {
  background: var(--bg-sidebar);
  padding: var(--space-4);
  border-radius: var(--radius-item);
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

/* ===== 来源卡片 ===== */
.sources-section {
  margin-top: var(--space-8);
  padding-top: var(--space-6);
  border-top: 1px solid var(--border-light);
}

.sources-section h4 {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
  margin: 0 0 var(--space-3) 0;
}

.source-card {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-xs);
  color: var(--text-secondary);
  background: var(--bg-canvas);
  border-radius: var(--radius-item);
  margin-bottom: var(--space-1);
}

.source-index {
  font-weight: 600;
  color: var(--color-primary);
  min-width: 24px;
}

.source-title {
  flex: 1;
}

.source-page {
  color: var(--text-disabled);
}

@media (max-width: 760px) {
  .progression-view {
    padding: var(--space-4);
  }

}

</style>
