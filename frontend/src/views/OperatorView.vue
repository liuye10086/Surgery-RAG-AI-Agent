<template>
  <div class="operator-view">
    <OperatorSidebar
      :reports="operatorStore.reports"
      :current-id="operatorStore.currentReport?.id"
      :collapsed="sidebarCollapsed"
      :loading="operatorStore.loading"
      :generating="operatorStore.generating"
      @toggle="toggleSidebar"
      @select="handleSelect"
      @new-analysis="handleNewAnalysis"
      @delete="handleDelete"
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
        <!-- 报告内容区（可滚动） -->
        <div class="report-area" ref="reportAreaRef">
          <div class="report-area-inner">
            <!-- 状态栏 -->
            <div v-if="operatorStore.currentStage" class="status-bar">
              <template v-if="operatorStore.currentStage === 'retrieving'">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>{{ operatorStore.stageMessage }}</span>
              </template>
              <template v-else-if="operatorStore.currentStage === 'retrieved'">
                <el-icon><CircleCheck /></el-icon>
                <span>{{ operatorStore.stageMessage }}</span>
              </template>
              <template v-else-if="operatorStore.currentStage === 'generating'">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>{{ operatorStore.stageMessage }}</span>
              </template>
              <template v-else-if="operatorStore.currentStage === 'done'">
                <el-icon><CircleCheck /></el-icon>
                <span>报告生成完成</span>
                <el-button
                  v-if="operatorStore.currentReport"
                  size="small"
                  type="primary"
                  style="margin-left: auto"
                  @click="handleDownload"
                >
                  下载 PDF
                </el-button>
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
              <h1 class="welcome-title">AI 操作者工作台</h1>
              <p class="welcome-desc">
                输入分析问题，AI 将检索全库病例数据并生成结构化研究报告。
              </p>
              <div class="welcome-prompts">
                <span
                  v-for="prompt in suggestedPrompts"
                  :key="prompt"
                  class="prompt-tag"
                  @click="handlePromptClick(prompt)"
                >{{ prompt }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 输入区（固定底部） -->
        <div class="input-section">
          <div class="input-gradient"></div>
          <div class="input-card">
            <div class="input-row">
              <el-input
                v-model="query"
                type="textarea"
                :rows="1"
                :autosize="{ minRows: 1, maxRows: 4 }"
                placeholder="输入分析问题，如：所有胆囊结石患者的共同特点有哪些？"
                resize="none"
                :maxlength="2000"
                show-word-limit
                :disabled="operatorStore.generating"
                @keydown.enter.exact.prevent="handleGenerate"
              />
            </div>
            <div class="input-actions">
              <div class="actions-left">
                <el-select
                  v-model="selectedDepartmentIds"
                  multiple
                  filterable
                  placeholder="选择科室范围（默认全库）"
                  :disabled="operatorStore.generating"
                  size="small"
                  style="width: 260px"
                  collapse-tags
                  collapse-tags-tooltip
                >
                  <el-option
                    v-for="dept in departments"
                    :key="dept.id"
                    :label="dept.name"
                    :value="dept.id"
                  />
                </el-select>
              </div>
              <div class="actions-right">
                <el-button
                  v-if="operatorStore.generating"
                  type="danger"
                  size="small"
                  @click="handleCancel"
                >
                  取消生成
                </el-button>
                <el-button
                  v-else
                  type="primary"
                  :disabled="!query.trim()"
                  @click="handleGenerate"
                >
                  开始分析
                </el-button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, CircleCheck, WarningFilled, InfoFilled, DataAnalysis } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OperatorSidebar from '@/components/OperatorSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { useOperatorStore } from '@/stores/operator'
import { downloadReport } from '@/api/operator'
import { listPublicDepartments, type DepartmentOut } from '@/api/admin'

const authStore = useAuthStore()
const operatorStore = useOperatorStore()

const sidebarCollapsed = ref(localStorage.getItem('operator_sidebar_collapsed') === 'true')
const query = ref('')
const selectedDepartmentIds = ref<number[]>([])
const departments = ref<DepartmentOut[]>([])
const reportAreaRef = ref<HTMLDivElement | null>(null)

const renderedContent = computed(() =>
  renderMarkdown(operatorStore.generatedContent || operatorStore.currentReport?.content || '')
)

const suggestedPrompts = [
  '所有胆囊结石患者的共同特点有哪些？',
  '近一年内手术并发症的发生率统计',
  '不同科室患者的年龄分布对比',
]

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

function handleGenerate() {
  if (!query.value.trim()) return
  operatorStore.clearCurrent()
  operatorStore.generateReport(
    query.value.trim(),
    selectedDepartmentIds.value.length > 0 ? selectedDepartmentIds.value : null,
  )
}

function handleCancel() {
  operatorStore.cancelGeneration()
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
  query.value = ''
}

function handlePromptClick(prompt: string) {
  if (operatorStore.generating) return
  query.value = prompt
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
    if (operatorStore.generating) {
      nextTick(() => {
        if (reportAreaRef.value) {
          reportAreaRef.value.scrollTo({ top: reportAreaRef.value.scrollHeight, behavior: 'smooth' })
        }
      })
    }
  },
)

onMounted(async () => {
  operatorStore.fetchReports()
  try {
    departments.value = await listPublicDepartments()
  } catch {
    // 科室加载非关键
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
  margin: 0 0 var(--space-8);
  font-size: 15px;
  color: var(--text-secondary);
  text-align: center;
  max-width: 480px;
  line-height: 1.6;
}

.welcome-prompts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  justify-content: center;
  max-width: 560px;
}

.prompt-tag {
  display: inline-block;
  padding: 8px 18px;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-pill);
  cursor: pointer;
  transition: border-color var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out,
              background var(--duration-fast) ease-out;
  user-select: none;
}

.prompt-tag:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-light);
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

/* ===== 输入区（固定底部） ===== */
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

.input-row {
  margin-bottom: var(--space-3);
}

.input-row :deep(.el-textarea__inner) {
  border-radius: var(--radius-input);
  border: 1px solid var(--border-default);
  background: var(--bg-surface);
  padding: 12px 16px;
  font-size: 15px;
  line-height: 1.5;
  resize: none;
  transition: border-color var(--duration-fast) ease-out,
              box-shadow var(--duration-fast) ease-out;
}

.input-row :deep(.el-textarea__inner):hover {
  border-color: var(--text-disabled);
}

.input-row :deep(.el-textarea__inner):focus {
  border-color: var(--border-focus);
  box-shadow: var(--focus-ring);
}

.input-row :deep(.el-textarea__inner)::placeholder {
  color: var(--text-disabled);
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
}

.actions-left {
  flex-shrink: 0;
}

.actions-right {
  flex-shrink: 0;
  display: flex;
  gap: var(--space-2);
}
</style>
