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
        <!-- 病例库视图 -->
        <CaseManageView v-if="activeView === 'cases'" />

        <!-- 纵向进展预测视图 -->
        <div v-else-if="activeView === 'progression'" class="progression-view">
          <div class="progression-inner">
            <div class="longitudinal-case-actions">
              <el-button @click="startNewLongitudinalCase">新建纵向病例</el-button>
              <el-select
                v-if="operatorStore.longitudinalCases.length"
                :model-value="operatorStore.currentLongitudinalCase?.id"
                placeholder="选择已保存病例"
                @update:model-value="selectLongitudinalCase"
              >
                <el-option
                  v-for="item in operatorStore.longitudinalCases"
                  :key="item.id"
                  :label="item.patient_label"
                  :value="item.id"
                />
              </el-select>
            </div>
            <LongitudinalCaseEditor
              :diseases="progressionDiseases"
              :model-value="operatorStore.currentLongitudinalCase"
              @saved="handleLongitudinalCaseSaved"
            />
            <LongitudinalPredictionSummary :prediction="operatorStore.longitudinalPrediction" />
            <header class="progression-heading">
              <div>
                <h3>纵向进展预测</h3>
                <p>录入同一患者按时间排列的多次访视指标。</p>
              </div>
            </header>

            <div class="progression-form">
              <div class="progression-disease-row">
                <label for="progression-disease">预测疾病</label>
                <el-select
                  id="progression-disease"
                  v-model="progressionDiseaseId"
                  placeholder="选择疾病"
                  filterable
                  :disabled="operatorStore.progressionLoading"
                  style="width: 280px"
                >
                  <el-option
                    v-for="disease in progressionDiseases"
                    :key="disease.id"
                    :label="disease.name"
                    :value="disease.id"
                  />
                </el-select>
              </div>

              <div class="visit-list">
                <article v-for="(visit, visitIndex) in progressionVisits" :key="visit.id" class="visit-card">
                  <div class="visit-card-head">
                    <h4>第 {{ visitIndex + 1 }} 次访视</h4>
                    <el-button
                      :icon="Delete"
                      text
                      :disabled="operatorStore.progressionLoading"
                      aria-label="删除访视"
                      title="删除访视"
                      @click="removeVisit(visitIndex)"
                    />
                  </div>
                  <el-date-picker
                    v-model="visit.visit_date"
                    type="date"
                    value-format="YYYY-MM-DD"
                    placeholder="选择访视日期"
                    :disabled="operatorStore.progressionLoading"
                  />
                  <IndicatorRowsEditor
                    v-model="visit.indicators"
                    :disabled="operatorStore.progressionLoading"
                    class="visit-indicators"
                  />
                </article>
              </div>

              <div class="progression-actions">
                <el-button
                  :icon="Plus"
                  :disabled="progressionVisits.length >= 10 || operatorStore.progressionLoading"
                  @click="addVisit"
                >
                  添加访视（{{ progressionVisits.length }}/10）
                </el-button>
                <el-button
                  type="primary"
                  :loading="operatorStore.progressionLoading"
                  :disabled="!canPredictProgression"
                  @click="handleProgressionPredict"
                >
                  评估进展风险
                </el-button>
              </div>
            </div>

            <div v-if="progressionResult" class="progression-result">
              <section class="progression-disclosures" aria-label="模型适用范围">
                <div class="progression-disclosure">
                  <div class="disclosure-title">
                    <el-icon><WarningFilled /></el-icon>
                    <span>重要使用限制</span>
                  </div>
                  <p>{{ progressionResult.disclaimer }}</p>
                </div>
                <div class="progression-disclosure">
                  <div class="disclosure-title">模型验证说明</div>
                  <p>{{ progressionResult.model_caveat }}</p>
                </div>
              </section>

              <section class="progression-risk-card" aria-label="进展风险结果">
                <div>
                  <div class="progression-risk-label">进展风险等级</div>
                  <div class="progression-risk-band">
                    {{ progressionResult.risk_band }}风险
                  </div>
                </div>
                <div class="progression-risk-score">
                  <span>模式匹配分数</span>
                  <strong>{{ formatRiskScore(progressionResult.risk_score) }}</strong>
                </div>
              </section>

              <section class="progression-summary">
                <h4>纵向特征摘要</h4>
                <el-table :data="progressionResult.feature_summary" size="small">
                  <el-table-column prop="indicator" label="指标" min-width="120" />
                  <el-table-column prop="first" label="首次值" min-width="100" />
                  <el-table-column prop="last" label="末次值" min-width="100" />
                  <el-table-column label="斜率" min-width="120">
                    <template #default="{ row }">{{ formatSlope(row.slope) }}</template>
                  </el-table-column>
                  <el-table-column prop="rises_count" label="上升次数" min-width="100" />
                </el-table>
              </section>
            </div>
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

              <IndicatorRowsEditor
                v-model="indicatorRows"
                :disabled="operatorStore.generating"
                class="single-indicator-editor"
              />

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
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, WarningFilled, InfoFilled, DataAnalysis, Plus, Delete } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OperatorSidebar from '@/components/OperatorSidebar.vue'
import CaseManageView from '@/components/CaseManageView.vue'
import IndicatorRowsEditor from '@/components/IndicatorRowsEditor.vue'
import LongitudinalCaseEditor from '@/components/LongitudinalCaseEditor.vue'
import LongitudinalPredictionSummary from '@/components/LongitudinalPredictionSummary.vue'
import { useAuthStore } from '@/stores/auth'
import { useOperatorStore } from '@/stores/operator'
import { downloadReport, type IndicatorInput } from '@/api/operator'
import { formatRange } from '@/utils/rangeFormat'

const authStore = useAuthStore()
const operatorStore = useOperatorStore()

const sidebarCollapsed = ref(localStorage.getItem('operator_sidebar_collapsed') === 'true')
const activeView = ref<'predict' | 'progression' | 'cases'>('predict')
const selectedDiseaseId = ref<number | null>(null)
const indicatorRows = ref<IndicatorInput[]>([])
const patientSummary = ref('')
let nextVisitId = 1

interface ProgressionVisitForm {
  id: number
  visit_date: string
  indicators: IndicatorInput[]
}

function emptyVisit(): ProgressionVisitForm {
  return {
    id: nextVisitId++,
    visit_date: '',
    indicators: [{ name: '', value: null, unit: '' }],
  }
}

const progressionDiseaseId = ref<number | null>(null)
const progressionVisits = ref<ProgressionVisitForm[]>([emptyVisit()])
const reportAreaRef = ref<HTMLDivElement | null>(null)
const shouldFollowReport = ref(true)
const scrollBottomThreshold = 72

const selectedDisease = computed(() =>
  operatorStore.diseases.find((d) => d.id === selectedDiseaseId.value) || null
)

const progressionDiseases = computed(() =>
  operatorStore.diseases.filter((disease) =>
    disease.name === '脂肪肝' || disease.name === '阿尔茨海默病'
  )
)

const progressionResult = computed(() => operatorStore.progressionResult)

const canPredict = computed(() => {
  if (!selectedDiseaseId.value) return false
  return indicatorRows.value.some(
    (r) => r.name.trim() && r.value !== null && r.value !== undefined && r.unit.trim(),
  )
})

const canPredictProgression = computed(() => {
  if (!progressionDiseaseId.value || !progressionVisits.value.length) return false
  return progressionVisits.value.every((visit) =>
    Boolean(visit.visit_date) && visit.indicators.some(isValidIndicator)
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

function isValidIndicator(row: IndicatorInput) {
  return Boolean(
    row.name.trim() && row.value !== null && row.value !== undefined && row.unit.trim()
  )
}

async function handleLongitudinalCaseSaved(draft: any) {
  try {
    const invalidVisit = (draft.visits || []).find((visit: any) =>
      !visit.visit_date || !visit.indicators?.length || !visit.indicators.every(isValidIndicator),
    )
    if (invalidVisit) {
      ElMessage.error('请完整填写每次访视的日期、指标、数值和单位')
      return
    }
    const visits = (draft.visits || [])
      .map((visit: any) => ({
        visit_date: visit.visit_date,
        indicators: visit.indicators.map((indicator: IndicatorInput) => ({
          name: indicator.name.trim(),
          value: Number(indicator.value),
          unit: indicator.unit.trim(),
        })),
        notes: visit.notes || null,
      }))
    const saved = await operatorStore.saveLongitudinalCase({ disease_id: draft.disease_id, patient_label: draft.patient_label, sex: draft.sex, visits })
    operatorStore.generateLongitudinalReport(saved.id)
    ElMessage.success('已开始生成纵向预测报告')
  } catch (error: any) {
    ElMessage.error(error?.message || '病例保存失败')
  }
}

function startNewLongitudinalCase() {
  operatorStore.currentLongitudinalCase = null
  operatorStore.longitudinalPrediction = null
  operatorStore.longitudinalReportContent = ''
}

function selectLongitudinalCase(caseId: number) {
  operatorStore.currentLongitudinalCase = operatorStore.longitudinalCases.find((item) => item.id === caseId) || null
}

function handlePredict() {
  const validRows = indicatorRows.value.filter(isValidIndicator)
  if (!validRows.length || !selectedDiseaseId.value) return
  shouldFollowReport.value = true
  operatorStore.clearCurrent()
  operatorStore.generatePrediction({
    disease_id: selectedDiseaseId.value,
    indicators: validRows.map((r) => ({
      name: r.name.trim(),
      value: Number(r.value),
      unit: r.unit.trim(),
    })),
    patient_summary: patientSummary.value.trim() || undefined,
  })
}

function addVisit() {
  if (progressionVisits.value.length >= 10) return
  progressionVisits.value.push(emptyVisit())
}

function removeVisit(index: number) {
  if (progressionVisits.value.length <= 1) {
    progressionVisits.value = [emptyVisit()]
    return
  }
  progressionVisits.value.splice(index, 1)
}

async function handleProgressionPredict() {
  if (!canPredictProgression.value || !progressionDiseaseId.value) return
  try {
    await operatorStore.predictLongitudinalProgression({
      disease_id: progressionDiseaseId.value,
      visits: progressionVisits.value.map((visit) => ({
        visit_date: visit.visit_date,
        indicators: visit.indicators.filter(isValidIndicator).map((indicator) => ({
          name: indicator.name.trim(),
          value: Number(indicator.value),
          unit: indicator.unit.trim(),
        })),
      })),
    })
  } catch {
    // 全局请求拦截器负责展示 API 的明确错误信息。
  }
}

function formatRiskScore(score: number) {
  return `${(score * 100).toFixed(1)}%`
}

function formatSlope(slope: number | null) {
  return slope === null ? '无法计算' : slope.toFixed(4)
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
  // 从病例库等非预测视图选择历史报告时，先切回预测/报告视图
  activeView.value = 'predict'
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
  // 新建分析必须切回预测输入视图，避免在病例库视图下按钮无可见效果
  activeView.value = 'predict'
  operatorStore.clearCurrent()
  operatorStore.generatedContent = ''
  operatorStore.currentStage = ''
  patientSummary.value = ''
  indicatorRows.value = [{ name: '', value: null, unit: '' }]
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
  operatorStore.fetchLongitudinalCases()
  if (!indicatorRows.value.length) {
    indicatorRows.value = [{ name: '', value: null, unit: '' }]
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

.progression-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--space-6);
}

.progression-heading h3 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.progression-heading p {
  margin: var(--space-1) 0 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.progression-form {
  padding-bottom: var(--space-6);
  border-bottom: 1px solid var(--border-default);
}

.progression-disease-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-5);
}

.progression-disease-row label {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.visit-list {
  display: grid;
  gap: var(--space-4);
}

.visit-card {
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
}

.visit-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3);
}

.visit-card-head h4 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.visit-indicators {
  margin-top: var(--space-4);
}

.progression-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  margin-top: var(--space-5);
}

.progression-result {
  display: grid;
  gap: var(--space-5);
  margin-top: var(--space-6);
  padding-bottom: var(--space-8);
}

.progression-disclosures {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  background: var(--color-accent-light);
  border: 1px solid var(--color-warning);
  border-left: 4px solid var(--color-warning);
  border-radius: var(--radius-card);
}

.progression-disclosure {
  font-size: var(--text-md);
  line-height: 1.6;
  color: var(--text-primary);
}

.progression-disclosure + .progression-disclosure {
  padding-top: var(--space-4);
  border-top: 1px solid var(--color-warning);
}

.disclosure-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
}

.progression-disclosure p {
  max-width: 80ch;
  margin: 0;
}

.progression-risk-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-5) var(--space-6);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-left: 4px solid var(--color-primary);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
}

.progression-risk-label,
.progression-risk-score span {
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.progression-risk-band {
  margin-top: var(--space-1);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--color-primary);
}

.progression-risk-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.progression-risk-score strong {
  margin-top: var(--space-1);
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
}

.progression-summary {
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
}

.progression-summary h4 {
  margin: 0 0 var(--space-4);
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text-primary);
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

.single-indicator-editor {
  margin-bottom: var(--space-3);
}

@media (max-width: 760px) {
  .progression-view {
    padding: var(--space-4);
  }

  .progression-disease-row,
  .progression-actions,
  .progression-risk-card {
    align-items: stretch;
    flex-direction: column;
  }

  .progression-disease-row :deep(.el-select) {
    width: 100% !important;
  }

  .progression-risk-score {
    align-items: flex-start;
  }
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
