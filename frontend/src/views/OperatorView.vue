<template>
  <div class="operator-view">
    <OperatorSidebar
      :reports="history.items"
      :total="history.items.length + (history.hasMore ? 1 : 0)"
      :current-id="generation.reportId || operatorStore.currentReport?.id"
      :collapsed="sidebarCollapsed"
      :loading="history.loading || history.loadingMore"
      :generating="generation.active"
      :active-view="activeView"
      @toggle="toggleSidebar"
      @select="handleSelect"
      @new-longitudinal-case="startNewLongitudinalCase"
      @delete="handleDelete"
      @load-more="loadMoreReports"
      @navigate="handleNavigate"
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
        <section v-if="reportReadingMode && !generation.report && generation.viewState !== 'idle'" class="generation-status" aria-live="polite" :aria-busy="generation.active">
          <h3>{{ generationTitle }}</h3>
          <p>{{ generation.message }}</p>
          <p v-if="generation.canCancel">刷新页面或返回病例不会取消生成。</p>
          <div class="generation-actions">
            <el-button @click="closeReport">返回病例</el-button>
            <el-button v-if="generation.canCancel" type="danger" plain @click="generation.cancel()">取消生成</el-button>
            <el-button v-if="generation.viewState === 'load_failed'" @click="retryReport">重试读取或受理</el-button>
          </div>
        </section>
        <LongitudinalReportView
          v-else-if="reportReadingMode"
          :report="generation.report || operatorStore.currentReport"
          :prediction-result="operatorStore.longitudinalPrediction"
          :evidence-snapshot="operatorStore.longitudinalEvidence"
          :rendered-content="renderMarkdown((generation.report || operatorStore.currentReport)?.content || '')"
          :generating="generation.active"
          @back="closeReport"
          @download="handleDownload"
        />

        <ReportHistoryWorkspace v-else-if="activeView === 'history'" @select="handleSelect" @delete="handleDelete" />

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
              :report-generating="generation.active"
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
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ReportHistoryWorkspace from '@/components/report/ReportHistoryWorkspace.vue'
import { useReportHistoryStore } from '@/stores/report-history'
import { useReportGenerationStore } from '@/stores/report-generation'
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
const generation = useReportGenerationStore()
const history = useReportHistoryStore()
const router = useRouter(), route = useRoute()
const generationTitle = computed(()=>({idle:'',submitting:'正在受理',queued:'报告已排队',running:'报告生成中',reconnecting:'正在恢复连接',loading_completed:'正在读取保存的报告资料',completed:'报告已完成',load_failed:'暂未取得报告',failed:'报告生成失败',cancelled:'报告已取消'}[generation.viewState]))

const sidebarCollapsed = ref(localStorage.getItem('operator_sidebar_collapsed') === 'true')
const activeView = ref<'cases' | 'history' | 'report'>('cases')
const reportReturnView = ref<'cases' | 'history'>('cases')
const progressionDiseases = computed(() => operatorStore.diseases)
const draftDiseaseCode = ref('')
const activeDiseaseCode = computed(() => operatorStore.currentLongitudinalCase?.disease.code || draftDiseaseCode.value)
const activeIndicatorCatalog = computed(() => activeDiseaseCode.value ? operatorStore.indicatorCatalogs[activeDiseaseCode.value] || null : null)
const validationIssues = ref<Record<string, string>>({})

const reportReadingMode = computed(() =>
  activeView.value === 'report'
  && Boolean(generation.viewState !== 'idle' || operatorStore.currentReport),
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
  return history.loadMore()
}

async function handleWorkspaceSave(payload: LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload) {
  const sessionRevision = operatorStore.caseSessionRevision
  validationIssues.value = {}
  try {
    const saved = operatorStore.currentLongitudinalCase?.id
      ? await operatorStore.saveLongitudinalCase(operatorStore.currentLongitudinalCase.id, payload as LongitudinalCaseSavePayload)
      : await operatorStore.saveLongitudinalCase(payload as LongitudinalCaseCreatePayload)
    if (operatorStore.caseSessionRevision !== sessionRevision) return
    ElMessage.success(`病例已保存：${saved.anonymous_case_code || '匿名编号待生成'}`)
  } catch (error: any) {
    if (operatorStore.caseSessionRevision !== sessionRevision) return
    validationIssues.value = validationIssueMap(error)
    ElMessage.error(error?.message || '病例保存失败')
  }
}

function startNewLongitudinalCase() {
  closeReport()
  activeView.value='cases'
  operatorStore.startNewLongitudinalCase()
  draftDiseaseCode.value = ''
  validationIssues.value = {}
}

async function selectLongitudinalCase(item: any) {
  closeReport()
  const sessionRevision = operatorStore.selectLongitudinalCase(item)
  draftDiseaseCode.value = ''
  validationIssues.value = {}
  await Promise.all([
    operatorStore.refreshLongitudinalCaseReadiness(item.id, sessionRevision),
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
  if (id) { reportReturnView.value='cases'; activeView.value = 'report'; void generation.submit(id) }
}

async function handleDownload() {
  const report = generation.report || operatorStore.currentReport
  if (!report) return
  try {
    const filename = `${report.anonymous_case_code || `report-${report.id}`}.pdf`
    await downloadReport(report.id, filename)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function handleSelect(id: number) {
  // 从病例库选择历史报告时，切回纵向报告视图
  if(activeView.value !== 'report') reportReturnView.value=activeView.value
  activeView.value = 'report'
  operatorStore.clearCurrent()
  await generation.observe(id)
}

function handleNavigate(view:'cases'|'history'|'report') {
  closeReport();activeView.value=view
}
function closeReport() {
  activeView.value=reportReturnView.value
  generation.detach()
  operatorStore.clearCurrent()
  const query = {...route.query}; delete query.reportId
  void router.replace({query})
}

async function handleDelete(id: number) {
  try {
    await ElMessageBox.confirm('确定删除该报告？删除后不可恢复。', '确认删除', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    history.invalidate()
    const result = await operatorStore.removeReport(id)
    history.remove(id)
    if (generation.reportId===id) closeReport()
    if(result?.cleanup_state==='pending') ElMessage.info('报告已删除，文件清理中')
    else ElMessage.success('报告已删除')
  } catch (error) {
    if(error !== 'cancel' && error !== 'close') ElMessage.error((error as Error).message || '删除失败')
  }
}

function retryReport() {
  if (generation.reportId) void generation.retryDetail()
  else if (generation.pendingCaseId) void generation.submit(generation.pendingCaseId)
}
watch(()=>generation.reportId,id=>{
  if (id) {activeView.value='report';history.updatesAvailable=true}
  if (id && String(route.query.reportId || '') !== String(id)) void router.replace({query:{...route.query,reportId:String(id)}})
})
watch(()=>operatorStore.currentReport,report=>{if(report)activeView.value='report'},{immediate:true})
watch(()=>route.query.reportId,value=>{
  const id=Number(value)
  if (typeof value==='string' && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(id) && generation.reportId!==id) void generation.observe(id)
  else if (value===undefined && generation.reportId) generation.detach()
}, {immediate:true})
watch(()=>generation.state?.status,status=>{
  if (status && ['completed','failed','cancelled'].includes(status)) history.updatesAvailable=true
})
watch(()=>authStore.token,token=>{if (!token) void router.replace('/login')})
onBeforeUnmount(()=>{
  window.removeEventListener('online',generation.refreshConnection)
  window.removeEventListener('focus',generation.refreshConnection)
  generation.detach()
})
onMounted(async () => {
  window.addEventListener('online',generation.refreshConnection)
  window.addEventListener('focus',generation.refreshConnection)
  if (!route.query.reportId) generation.restorePending()
  void history.refresh()
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
.generation-status { width:min(100%,var(--content-max-width)); margin:var(--space-6) auto; padding:var(--space-6); color:var(--text-primary); background:var(--bg-surface); border:1px solid var(--border-default); border-radius:var(--radius-card); }
.generation-actions { display:flex; flex-wrap:wrap; gap:var(--space-3); }
.generation-actions :deep(button) { min-height:44px; border-radius:var(--radius-pill); }
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
