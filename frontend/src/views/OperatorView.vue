<template>
  <div class="operator-view">
    <OperatorSidebar
      :reports="operatorStore.reports"
      :current-id="operatorStore.currentReport?.id"
      :collapsed="sidebarCollapsed"
      :loading="operatorStore.loading"
      :generating="operatorStore.generating"
      :active-view="activeView"
      @toggle="toggleSidebar"
      @select="handleSelect"
      @new-analysis="handleNewAnalysis"
      @delete="handleDelete"
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
        <!-- 病例库视图（Task 13 挂载 CaseManageView） -->
        <div v-if="activeView === 'cases'" class="cases-placeholder">
          <div class="placeholder-content">
            <el-icon :size="48"><FolderOpened /></el-icon>
            <h3>病例库</h3>
            <p>病例库管理功能正在开发中，完成后可在此管理疾病字典、确诊病例与参考标准。</p>
          </div>
        </div>

        <!-- 预测分析视图 -->
        <template v-else>
          <!-- 报告内容区（可滚动） -->
          <div class="report-area" ref="reportAreaRef">
            <div class="report-area-inner">
              <!-- 综合匹配度卡片（措辞遵循「概率措辞约定」：主视觉用风险等级 + 匹配度区间） -->
              <div v-if="operatorStore.predictionResult" class="probability-card">
                <div class="prob-band">{{ operatorStore.predictionResult.band }}风险</div>
                <div class="prob-range">
                  匹配度区间 {{ operatorStore.predictionResult.probability_range[0] }}%-{{ operatorStore.predictionResult.probability_range[1] }}%
                </div>
                <div v-if="operatorStore.predictionResult.insufficient_sample" class="prob-warning">样本量不足，匹配度仅供参考</div>
                <div class="prob-disclaimer">该结果为基于已录入病例的模式匹配参考，非临床确诊概率。</div>
              </div>

              <!-- 指标分析表（参考范围用共享 formatRange 渲染边界符号，区分 <21 与 ≤21） -->
              <div v-if="operatorStore.indicatorAnalyses.length" class="analysis-table">
                <h4>指标偏离分析</h4>
                <el-table :data="operatorStore.indicatorAnalyses" size="small">
                  <el-table-column prop="name" label="指标" width="100" />
                  <el-table-column label="实测值">
                    <template #default="{ row }">{{ row.value }} {{ row.unit }}</template>
                  </el-table-column>
                  <el-table-column label="参考范围">
                    <template #default="{ row }">{{ formatRange(row) }}</template>
                  </el-table-column>
                  <el-table-column label="偏离度">
                    <template #default="{ row }">{{ row.is_abnormal ? '+' : '' }}{{ row.deviation_pct }}%</template>
                  </el-table-column>
                  <el-table-column label="确诊异常率">
                    <template #default="{ row }">{{ (row.abnormal_rate_in_cases * 100).toFixed(1) }}%</template>
                  </el-table-column>
                </el-table>
              </div>

              <!-- 状态栏 -->
              <div v-if="showStatusBar" class="status-bar">
                <template v-if="operatorStore.currentStage === 'analyzing' || operatorStore.currentStage === 'generating'">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>{{ operatorStore.stageMessage }}</span>
                </template>
                <template v-else-if="operatorStore.currentStage === 'error'">
                  <el-icon><WarningFilled /></el-icon>
                  <span style="color: var(--color-danger)">生成失败，请重试</span>
                </template>
                <template v-else-if="operatorStore.currentStage === 'cancelled'">
                  <el-icon><InfoFilled /></el-icon>
                  <span>生成已取消</span>
                </template>
              </div>

              <!-- 流式生成中的实时预览 -->
              <div v-if="operatorStore.generating || operatorStore.generatedContent" class="report-content">
                <div
                  class="markdown-body"
                  v-html="renderedContent"
                />
              </div>

              <!-- 查看历史报告 -->
              <div v-else-if="operatorStore.currentReport" class="report-content">
                <div class="report-head">
                  <h3>{{ operatorStore.currentReport.title || '分析报告' }}</h3>
                  <div class="report-head-meta">
                    <el-tag
                      :type="statusTagType(operatorStore.currentReport.status)"
                      size="small"
                    >
                      {{ statusLabel(operatorStore.currentReport.status) }}
                    </el-tag>
                    <span class="meta-time">{{ formatTime(operatorStore.currentReport.created_at) }}</span>
                    <el-button
                      v-if="operatorStore.currentReport.status === 'completed'"
                      size="small"
                      type="primary"
                      @click="handleDownload"
                    >
                      下载 PDF
                    </el-button>
                  </div>
                </div>
                <div
                  class="markdown-body"
                  v-html="renderMarkdown(operatorStore.currentReport.content)"
                />
                <!-- 来源 -->
                <div v-if="operatorStore.currentReport.sources?.length" class="sources-section">
                  <h4>参考来源</h4>
                  <div
                    v-for="(src, idx) in operatorStore.currentReport.sources"
                    :key="idx"
                    class="source-card"
                  >
                    <span class="source-index">[{{ src.citation_index }}]</span>
                    <span class="source-title">{{ src.title || '未知文档' }}</span>
                    <span v-if="src.page_number" class="source-page">第 {{ src.page_number }} 页</span>
                  </div>
                </div>
              </div>

              <!-- 空状态 -->
              <div v-else class="empty-state">
                <div class="welcome-icon">
                  <el-icon :size="28"><DataAnalysis /></el-icon>
                </div>
                <h1 class="welcome-title">AI 操作者预测分析</h1>
                <p class="welcome-desc">
                  选择疾病并输入患者检验指标，AI 将对照参考标准与已录入病例库，生成指标级异常分析与综合匹配度报告。
                </p>
              </div>
            </div>
          </div>

          <!-- 预测输入区（固定底部） -->
          <div class="input-section">
            <div class="input-gradient"></div>
            <div class="input-card">
              <div class="predict-row">
                <el-select
                  v-model="selectedDiseaseId"
                  placeholder="选择疾病"
                  filterable
                  style="width: 240px"
                  :disabled="operatorStore.generating"
                >
                  <el-option
                    v-for="d in operatorStore.diseases"
                    :key="d.id"
                    :label="d.name"
                    :value="d.id"
                  />
                </el-select>
                <span class="case-hint" v-if="selectedDisease">{{ selectedDisease.case_count }} 例确诊病例</span>
              </div>

              <div class="indicator-form">
                <div v-for="(row, idx) in indicatorRows" :key="idx" class="indicator-row">
                  <el-input v-model="row.name" placeholder="指标名" style="width: 150px" :disabled="operatorStore.generating" />
                  <el-input v-model.number="row.value" type="number" placeholder="数值" style="width: 120px" :disabled="operatorStore.generating" />
                  <el-input v-model="row.unit" placeholder="单位" style="width: 100px" :disabled="operatorStore.generating" />
                  <el-button :icon="Delete" text :disabled="operatorStore.generating" @click="removeIndicator(idx)" />
                </div>
                <el-button size="small" :icon="Plus" text :disabled="operatorStore.generating" @click="addIndicator">添加指标</el-button>
              </div>

              <el-input
                v-model="patientSummary"
                type="textarea"
                :rows="2"
                placeholder="患者主诉（可选）"
                maxlength="2000"
                show-word-limit
                :disabled="operatorStore.generating"
              />
              <div class="predict-actions">
                <el-button v-if="operatorStore.generating" type="danger" @click="operatorStore.cancelGeneration()">取消</el-button>
                <el-button v-else type="primary" :disabled="!canPredict" @click="handlePredict">开始分析</el-button>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, WarningFilled, InfoFilled, DataAnalysis, Plus, Delete, FolderOpened } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OperatorSidebar from '@/components/OperatorSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { useOperatorStore } from '@/stores/operator'
import { downloadReport, type IndicatorInput } from '@/api/operator'
import { formatRange } from '@/utils/rangeFormat'

const authStore = useAuthStore()
const operatorStore = useOperatorStore()

const sidebarCollapsed = ref(localStorage.getItem('operator_sidebar_collapsed') === 'true')
const activeView = ref<'predict' | 'cases'>('predict')
const selectedDiseaseId = ref<number | null>(null)
const indicatorRows = reactive<IndicatorInput[]>([])
const patientSummary = ref('')
const reportAreaRef = ref<HTMLDivElement | null>(null)
const shouldFollowReport = ref(true)
const scrollBottomThreshold = 72

const selectedDisease = computed(() =>
  operatorStore.diseases.find((d) => d.id === selectedDiseaseId.value) || null
)

const canPredict = computed(() => {
  if (!selectedDiseaseId.value) return false
  return indicatorRows.some(
    (r) => r.name.trim() && r.value !== null && r.value !== undefined && r.unit.trim(),
  )
})

const renderedContent = computed(() =>
  renderMarkdown(operatorStore.generatedContent || operatorStore.currentReport?.content || '')
)

const showStatusBar = computed(() =>
  Boolean(operatorStore.currentStage && operatorStore.currentStage !== 'done')
)

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('operator_sidebar_collapsed', String(sidebarCollapsed.value))
}

function renderMarkdown(md: string): string {
  const raw = marked.parse(md || '', { breaks: true }) as string
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'p', 'ul', 'ol', 'li',
      'table', 'thead', 'tbody', 'tr', 'th', 'td',
      'strong', 'em', 'code', 'pre',
      'blockquote', 'hr', 'br',
      'sup', 'sub', 'a', 'span', 'div',
    ],
  })
}

function addIndicator() {
  indicatorRows.push({ name: '', value: null as unknown as number, unit: '' })
}

function removeIndicator(idx: number) {
  if (indicatorRows.length <= 1) {
    indicatorRows.splice(0, 1, { name: '', value: null as unknown as number, unit: '' })
    return
  }
  indicatorRows.splice(idx, 1)
}

function handlePredict() {
  const validRows = indicatorRows.filter(
    (r) => r.name.trim() && r.value !== null && r.value !== undefined && r.unit.trim(),
  )
  if (!validRows.length || !selectedDiseaseId.value) return
  shouldFollowReport.value = true
  operatorStore.clearCurrent()
  operatorStore.generatePrediction({
    disease_id: selectedDiseaseId.value,
    indicators: validRows.map((r) => ({
      name: r.name.trim(),
      value: r.value,
      unit: r.unit.trim(),
    })),
    patient_summary: patientSummary.value.trim() || undefined,
  })
}

async function handleDownload() {
  if (!operatorStore.currentReport) return
  try {
    const filename = `${operatorStore.currentReport.title || '分析报告'}.pdf`
    await downloadReport(operatorStore.currentReport.id, filename)
  } catch (e: any) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function handleSelect(id: number) {
  operatorStore.clearCurrent()
  operatorStore.generatedContent = ''
  operatorStore.currentStage = ''
  await operatorStore.fetchReport(id)
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

function handleNewAnalysis() {
  operatorStore.clearCurrent()
  operatorStore.generatedContent = ''
  operatorStore.currentStage = ''
  patientSummary.value = ''
  indicatorRows.splice(0, indicatorRows.length, { name: '', value: null as unknown as number, unit: '' })
}

function isNearReportBottom() {
  const el = reportAreaRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight <= scrollBottomThreshold
}

function handleReportScroll() {
  shouldFollowReport.value = isNearReportBottom()
}

function scrollReportToBottom(behavior: ScrollBehavior = 'smooth') {
  const el = reportAreaRef.value
  if (!el) return
  el.scrollTo({ top: el.scrollHeight, behavior })
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '等待中',
    generating: '生成中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || status
}

function statusTagType(status: string): 'info' | 'success' | 'danger' | 'warning' | '' {
  const map: Record<string, 'info' | 'success' | 'danger' | 'warning' | ''> = {
    pending: 'info',
    generating: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
  }
  return map[status] || 'info'
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

// 流式生成时自动滚动到底部
watch(
  () => operatorStore.generatedContent?.length ?? 0,
  () => {
    if (operatorStore.generating && shouldFollowReport.value) {
      nextTick(() => {
        scrollReportToBottom('auto')
      })
    }
  },
)

onMounted(async () => {
  operatorStore.fetchReports()
  operatorStore.fetchDiseases()
  if (!indicatorRows.length) {
    indicatorRows.push({ name: '', value: null as unknown as number, unit: '' })
  }
  reportAreaRef.value?.addEventListener('scroll', handleReportScroll, { passive: true })
})

onUnmounted(() => {
  reportAreaRef.value?.removeEventListener('scroll', handleReportScroll)
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

/* ===== 病例库占位（Task 13 替换为 CaseManageView） ===== */
.cases-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-content {
  text-align: center;
  color: var(--text-disabled);
  max-width: 420px;
}

.placeholder-content h3 {
  margin: var(--space-4) 0 var(--space-3);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-secondary);
}

.placeholder-content p {
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-disabled);
}

/* ===== 报告内容区（可滚动） ===== */
.report-area {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6) var(--space-6) 0;
}

.report-area-inner {
  max-width: 800px;
  margin: 0 auto;
}

/* ===== 综合匹配度卡片 ===== */
.probability-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-card);
  padding: var(--space-5) var(--space-6);
  margin-bottom: var(--space-4);
  box-shadow: var(--shadow-sm);
}

.prob-band {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--color-primary);
}

.prob-range {
  margin-top: var(--space-1);
  font-size: var(--text-md);
  color: var(--text-primary);
}

.prob-warning {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-warning);
}

.prob-disclaimer {
  margin-top: var(--space-3);
  padding-top: var(--space-3);
  border-top: 1px solid var(--border-light);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

/* ===== 指标偏离分析表 ===== */
.analysis-table {
  background: var(--bg-surface);
  border-radius: var(--radius-card);
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-4);
  box-shadow: var(--shadow-sm);
}

.analysis-table h4 {
  margin: 0 0 var(--space-3);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}

/* ===== 状态栏 ===== */
.status-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  background: var(--bg-surface);
  border-radius: var(--radius-item);
  margin-bottom: var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-secondary);
  box-shadow: var(--shadow-sm);
}

/* ===== 空状态欢迎页 ===== */
.empty-state {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10);
  min-height: 360px;
}

.welcome-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-primary-light);
  border-radius: 50%;
  color: var(--color-primary);
  margin-bottom: var(--space-6);
}

.welcome-title {
  margin: 0 0 var(--space-3);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.welcome-desc {
  margin: 0;
  font-size: 15px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
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

/* ===== 预测输入区（固定底部） ===== */
.input-section {
  flex-shrink: 0;
  position: relative;
  padding: 0 var(--space-6) var(--space-6);
}

.input-gradient {
  position: absolute;
  top: -40px;
  left: 0;
  right: 0;
  height: 40px;
  background: linear-gradient(transparent, var(--bg-canvas));
  pointer-events: none;
}

.input-card {
  max-width: 800px;
  margin: 0 auto;
  background: var(--bg-surface);
  border-radius: var(--radius-card);
  padding: var(--space-5);
  box-shadow: var(--shadow-sm);
}

.predict-row {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.case-hint {
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.indicator-form {
  margin-bottom: var(--space-3);
}

.indicator-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.indicator-row :deep(.el-input__wrapper) {
  border-radius: var(--radius-input);
}

.predict-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.predict-actions .el-button {
  min-width: 120px;
}
</style>
