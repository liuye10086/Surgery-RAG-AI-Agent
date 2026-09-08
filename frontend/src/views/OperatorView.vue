<template>
  <div class="operator-view">
    <OperatorSidebar
      :reports="history.items"
      :total="history.items.length + (history.hasMore ? 1 : 0)"
      :current-id="generation.reportId || undefined"
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
          :report="generation.report"
          :rendered-content="renderMarkdown(generation.report?.content || '')"
          :generating="generation.active"
          @back="closeReport"
          @download="handleDownload"
        />

        <ReportHistoryWorkspace v-else-if="activeView === 'history'" @select="handleSelect" @delete="handleDelete" />

        <!-- 统一病例工作区：病例库和进展预测共用同一份聚合草稿 -->
        <div v-show="!reportReadingMode && activeView !== 'history'" class="progression-view">
          <div class="progression-inner">
            <OperatorCaseList v-if="activeView === 'cases'" v-model:query="caseQuery" v-model:status="caseStatus" :pagination="operatorStore.caseListPagination" @page="refreshCases" :cases="operatorStore.longitudinalCases" :selected-id="operatorStore.currentLongitudinalCase?.id" :loading="operatorStore.caseListLoading" @select="selectLongitudinalCase" @new="startNewLongitudinalCase" />
            <div v-if="operatorStore.currentLongitudinalCase" class="case-management" :aria-busy="caseOperationPending">
              <button data-test="case-status" :disabled="!canChangeCurrentCaseStatus" @click="handleCaseStatus">{{ operatorStore.currentLongitudinalCase.status === 'archived' ? '恢复病例' : '归档病例' }}</button>
              <button data-test="delete-case" class="case-management__danger" :disabled="!canDeleteCurrentCase" @click="handleDeleteLongitudinalCase">删除病例</button>
              <span v-if="caseOperationPending" role="status">正在处理病例操作…</span>
            </div>
            <OperatorCaseWorkspace
              ref="caseWorkspace"
              :key="operatorStore.caseSessionRevision"
              :model="operatorStore.currentLongitudinalCase"
              :diseases="progressionDiseases"
              :indicator-catalog="activeIndicatorCatalog"
              :validation-issues="validationIssues"
              :readiness="operatorStore.readiness"
              :saving="operatorStore.saving || caseOperationPending || caseSwitchPending"
              :report-generating="generation.active"
              @save="handleWorkspaceSave"
              @disease-change="handleDiseaseChange"
              @edit="handleWorkspaceEdit"
              @generate-report="generateCurrentReport"
            />
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
const caseQuery = ref('')
const caseStatus = ref<'active' | 'archived'>('active')
const caseOperationPending = ref(false)
const caseSwitchPending = ref(false)
const caseWorkspace = ref<InstanceType<typeof OperatorCaseWorkspace> | null>(null)
let initialCaseSelectionAllowed = true
const canDeleteCurrentCase = computed(() => Boolean(operatorStore.currentLongitudinalCase?.status === 'active' && operatorStore.currentLongitudinalCase.disease.operator_enabled !== false && !caseOperationPending.value && !caseSwitchPending.value && !operatorStore.saving && !generation.active))
const canChangeCurrentCaseStatus = computed(() => {
  const current = operatorStore.currentLongitudinalCase
  if (!current || !['active', 'archived'].includes(current.status) || caseOperationPending.value || caseSwitchPending.value || operatorStore.saving || generation.active) return false
  return current.status === 'active' || current.disease.operator_enabled !== false
})
async function refreshCases(skip = operatorStore.caseListPagination.skip) {
  const q = caseQuery.value.trim() || undefined
  try { await operatorStore.fetchLongitudinalCases({ ...(q ? { q } : {}), status: caseStatus.value, skip, limit: operatorStore.caseListPagination.limit }) }
  catch (error: any) { ElMessage.error(error?.message || '病例列表加载失败') }
}
watch([caseQuery, caseStatus], () => {
  initialCaseSelectionAllowed = false
  void refreshCases(0)
})

function handleWorkspaceEdit() {
  initialCaseSelectionAllowed = false
  validationIssues.value = {}
}

async function manageCurrentCase(action: 'delete' | 'status') {
  const current = operatorStore.currentLongitudinalCase
  if (!current || caseOperationPending.value || caseSwitchPending.value || operatorStore.saving || generation.active) return
  if (action === 'delete' && !canDeleteCurrentCase.value) return
  if (action === 'status' && !canChangeCurrentCaseStatus.value) return
  const revision = operatorStore.caseSessionRevision
  const restoring = current.status === 'archived'
  caseOperationPending.value = true
  try {
    let reason: string | undefined
    if (action === 'delete') {
      await ElMessageBox.confirm(`确定删除 ${current.anonymous_case_code}？病例及全部访视将永久删除。历史报告仍会保留，只能通过生成时输入快照追溯。`, '确认病例操作', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
    } else {
      const result = await ElMessageBox.prompt(`请输入${restoring ? '恢复' : '归档'} ${current.anonymous_case_code} 的原因。`, '确认病例操作', {
        confirmButtonText: '确认', cancelButtonText: '取消', inputPlaceholder: '请输入原因（最多 500 字）',
        inputValidator: value => value.trim().length > 0 && value.trim().length <= 500 || '原因须为 1–500 个字符',
      })
      reason = result.value.trim()
    }
    if (revision !== operatorStore.caseSessionRevision || current.id !== operatorStore.currentLongitudinalCase?.id) return
    if (action === 'delete') await operatorStore.removeLongitudinalCase()
    else await operatorStore.changeLongitudinalCaseStatus(restoring ? 'active' : 'archived', reason)
    ElMessage.success(action === 'delete' ? '病例已删除，历史报告仍会保留' : restoring ? '病例已恢复' : '病例已归档')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error?.message || '病例操作失败')
  } finally { caseOperationPending.value = false }
}
function handleDeleteLongitudinalCase() { return manageCurrentCase('delete') }
function handleCaseStatus() { return manageCurrentCase('status') }

const reportReadingMode = computed(() =>
  activeView.value === 'report'
  && generation.viewState !== 'idle',
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

async function confirmDraftDiscard() {
  if (operatorStore.saving || caseOperationPending.value || caseSwitchPending.value || generation.active) return false
  if (!caseWorkspace.value?.dirty) return true
  const revision = operatorStore.caseSessionRevision
  caseSwitchPending.value = true
  try {
    await ElMessageBox.confirm('当前病例有未保存的修改，是否丢弃这些修改？', '确认切换病例', { confirmButtonText: '丢弃修改', cancelButtonText: '继续编辑', type: 'warning' })
    return revision === operatorStore.caseSessionRevision && !operatorStore.saving && !generation.active
  } catch { return false }
  finally { caseSwitchPending.value = false }
}

async function startNewLongitudinalCase() {
  if (!await confirmDraftDiscard()) return
  initialCaseSelectionAllowed = false
  closeReport()
  activeView.value='cases'
  operatorStore.startNewLongitudinalCase()
  draftDiseaseCode.value = ''
  validationIssues.value = {}
}

async function selectLongitudinalCase(item: any, openWorkspace = true) {
  initialCaseSelectionAllowed = false
  if (openWorkspace && item.id === operatorStore.currentLongitudinalCase?.id) return
  if (!await confirmDraftDiscard()) return
  if (openWorkspace) { closeReport(); activeView.value = 'cases' }
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
  const report = generation.report
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
  await generation.observe(id)
}

function handleNavigate(view:'cases'|'history'|'report') {
  closeReport();activeView.value=view
}
function closeReport() {
  activeView.value=reportReturnView.value
  generation.detach()
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
  initialCaseSelectionAllowed = false
  window.removeEventListener('online',generation.refreshConnection)
  window.removeEventListener('focus',generation.refreshConnection)
  generation.detach()
})
onMounted(async () => {
  const sessionRevision = operatorStore.caseSessionRevision
  window.addEventListener('online',generation.refreshConnection)
  window.addEventListener('focus',generation.refreshConnection)
  if (!route.query.reportId) generation.restorePending()
  void history.refresh()
  await Promise.all([
    operatorStore.fetchDiseases(),
    refreshCases(),
  ])
  if (!initialCaseSelectionAllowed || sessionRevision !== operatorStore.caseSessionRevision) return
  const selected = operatorStore.currentLongitudinalCase || operatorStore.longitudinalCases[0]
  if (selected) await selectLongitudinalCase(selected, false)
})
</script>

<style scoped>
.case-management { display:flex; flex-wrap:wrap; align-items:center; gap:var(--space-3); margin-top:var(--space-4); color:var(--text-secondary); }
.case-management button { min-height:44px; padding:var(--space-2) var(--space-5); border:1px solid var(--color-primary); border-radius:var(--radius-pill); background:var(--bg-surface); color:var(--color-primary); cursor:pointer; }
.case-management button.case-management__danger { color:var(--color-danger); border-color:var(--color-danger-soft); }
.case-management button:disabled { opacity:.4; cursor:not-allowed; }
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

@media (max-width: 760px) {
  .progression-view {
    padding: var(--space-4);
  }

}

</style>
