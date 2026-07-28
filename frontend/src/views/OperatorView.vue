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
        <!-- 输入区 -->
        <div class="input-section">
          <div class="input-row">
            <el-input
              v-model="query"
              type="textarea"
              :rows="2"
              placeholder="输入分析问题，如：所有胆囊结石患者的共同特点有哪些？"
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
                style="width: 320px"
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

        <!-- 报告正文区域 -->
        <div class="report-area">
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
            <el-icon :size="48"><DataAnalysis /></el-icon>
            <p>输入分析问题开始生成研究报告</p>
            <p class="hint">支持 7 章结构化报告：摘要 → 研究问题 → 数据来源 → 数据分析 → 观察性特征 → 讨论 → 结论</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Loading, CircleCheck, WarningFilled, InfoFilled, DataAnalysis } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import OperatorSidebar from '@/components/OperatorSidebar.vue'
import { useAuthStore } from '@/stores/auth'
import { useOperatorStore } from '@/stores/operator'
import { downloadReport } from '@/api/operator'
import { listDepartments, type DepartmentOut } from '@/api/admin'

const authStore = useAuthStore()
const operatorStore = useOperatorStore()

const sidebarCollapsed = ref(false)
const query = ref('')
const selectedDepartmentIds = ref<number[]>([])
const departments = ref<DepartmentOut[]>([])

const renderedContent = computed(() =>
  renderMarkdown(operatorStore.generatedContent || operatorStore.currentReport?.content || '')
)

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
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

onMounted(async () => {
  operatorStore.fetchReports()
  try {
    departments.value = await listDepartments(true)
  } catch {
    // 科室加载非关键
  }
})
</script>

<style scoped>
.operator-view {
  display: flex;
  height: 100vh;
  background: var(--bg-canvas, hsl(40, 15%, 98%));
  font-family: var(--font-sans);
}

.operator-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.operator-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--topbar-height, 56px);
  padding: 0 var(--space-6, 24px);
  border-bottom: 1px solid var(--border-light, hsl(210, 10%, 93%));
  background: var(--bg-surface, #fff);
  flex-shrink: 0;
}

.operator-header h2 {
  font-size: var(--text-md, 18px);
  font-weight: 600;
  color: var(--text-primary, hsl(210, 18%, 18%));
  margin: 0;
}

.operator-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6, 24px);
  max-width: var(--content-max-width, 880px);
  width: 100%;
  margin: 0 auto;
}

/* Input */
.input-section {
  background: var(--bg-surface, #fff);
  border-radius: var(--radius-card, 12px);
  padding: var(--space-5, 20px);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.04));
  margin-bottom: var(--space-4, 16px);
}

.input-row {
  margin-bottom: var(--space-3, 12px);
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3, 12px);
}

/* Status bar */
.status-bar {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-3, 12px) var(--space-4, 16px);
  background: var(--bg-surface, #fff);
  border-radius: var(--radius-item, 8px);
  margin-bottom: var(--space-4, 16px);
  font-size: var(--text-sm, 14px);
  color: var(--text-secondary, hsl(210, 6%, 45%));
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.04));
}

/* Report area */
.report-area {
  flex: 1;
}

.report-content {
  background: var(--bg-surface, #fff);
  border-radius: var(--radius-card, 12px);
  padding: var(--space-6, 24px) var(--space-8, 32px);
  box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.04));
}

.report-head {
  margin-bottom: var(--space-6, 24px);
  padding-bottom: var(--space-4, 16px);
  border-bottom: 1px solid var(--border-light, hsl(210, 10%, 93%));
}

.report-head h3 {
  font-size: var(--text-lg, 22px);
  font-weight: 600;
  color: var(--text-primary, hsl(210, 18%, 18%));
  margin: 0 0 var(--space-3, 12px) 0;
}

.report-head-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3, 12px);
}

.meta-time {
  font-size: var(--text-xs, 13px);
  color: var(--text-disabled, hsl(210, 4%, 62%));
}

/* Markdown body */
.markdown-body {
  font-size: var(--text-base, 16px);
  line-height: 1.8;
  color: var(--text-primary, hsl(210, 18%, 18%));
}

.markdown-body :deep(h2) {
  font-size: var(--text-md, 18px);
  font-weight: 600;
  margin: 1.5em 0 0.8em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid var(--border-light, hsl(210, 10%, 93%));
}

.markdown-body :deep(h3) {
  font-size: var(--text-base, 16px);
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
  font-size: var(--text-sm, 14px);
}

.markdown-body :deep(th), .markdown-body :deep(td) {
  border: 1px solid var(--border-default, hsl(210, 8%, 88%));
  padding: 6px 10px;
  text-align: left;
}

.markdown-body :deep(th) {
  background: var(--bg-sidebar, hsl(200, 10%, 95%));
  font-weight: 600;
}

.markdown-body :deep(blockquote) {
  margin: 0.8em 0;
  padding: 0.6em 1em;
  border-left: 3px solid var(--color-accent, hsl(25, 55%, 52%));
  background: var(--color-accent-light, hsl(25, 55%, 93%));
  color: var(--text-secondary, hsl(210, 6%, 45%));
}

.markdown-body :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.9em;
  background: var(--bg-input, hsl(200, 10%, 97%));
  padding: 1px 5px;
  border-radius: 4px;
}

.markdown-body :deep(pre) {
  background: var(--bg-sidebar, hsl(200, 10%, 95%));
  padding: var(--space-4, 16px);
  border-radius: var(--radius-item, 8px);
  overflow-x: auto;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

/* Sources */
.sources-section {
  margin-top: var(--space-8, 32px);
  padding-top: var(--space-6, 24px);
  border-top: 1px solid var(--border-light, hsl(210, 10%, 93%));
}

.sources-section h4 {
  font-size: var(--text-sm, 14px);
  font-weight: 600;
  color: var(--text-secondary, hsl(210, 6%, 45%));
  margin: 0 0 var(--space-3, 12px) 0;
}

.source-card {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  font-size: var(--text-xs, 13px);
  color: var(--text-secondary, hsl(210, 6%, 45%));
  background: var(--bg-canvas, hsl(40, 15%, 98%));
  border-radius: var(--radius-item, 8px);
  margin-bottom: var(--space-1, 4px);
}

.source-index {
  font-weight: 600;
  color: var(--color-primary, hsl(200, 65%, 40%));
  min-width: 24px;
}

.source-title {
  flex: 1;
}

.source-page {
  color: var(--text-disabled, hsl(210, 4%, 62%));
}

/* Empty state */
.empty-state {
  text-align: center;
  padding: var(--space-16, 64px) var(--space-6, 24px);
  color: var(--text-disabled, hsl(210, 4%, 62%));
}

.empty-state .el-icon {
  color: var(--border-default, hsl(210, 8%, 88%));
  margin-bottom: var(--space-4, 16px);
}

.empty-state p {
  margin: var(--space-2, 8px) 0;
  font-size: var(--text-sm, 14px);
}

.empty-state .hint {
  font-size: var(--text-xs, 13px);
  color: var(--text-disabled, hsl(210, 4%, 62%));
}
</style>
