<template>
  <div :class="['message-row', message.role]">
    <div v-if="message.role === 'assistant'" class="message-avatar">
      <el-avatar :size="28" style="background: var(--color-primary); font-size: 14px">+</el-avatar>
    </div>
    <div class="message-content">
      <div
        class="message-bubble"
        :class="{ 'no-knowledge': message.is_no_knowledge, 'is-error': message.is_error }"
      >
        <div
          class="message-text"
          v-html="renderedContent"
          @click="handleCitationClick"
        ></div>
        <div v-if="message.is_error" class="retry-row">
          <el-button size="small" type="danger" plain @click="emit('retry', message)">
            重新生成
          </el-button>
        </div>
      </div>

      <!-- 危险症状警告卡片 -->
      <div v-if="message.role === 'user' && dangerWarning" :class="['danger-warning', dangerWarning.level]">
        <el-icon :size="16"><WarningFilled /></el-icon>
        <span>{{ dangerWarning.advice }}</span>
      </div>

      <!-- RAG 引用来源卡片 -->
      <div
        v-if="message.sources && message.sources.length"
        class="sources"
      >
        <div class="sources-header" @click="sourcesExpanded = !sourcesExpanded">
          <div class="sources-title">
            <el-icon :size="14"><Collection /></el-icon>
            参考来源 · {{ message.sources.length }}
          </div>
          <el-icon :class="['sources-arrow', { expanded: sourcesExpanded }]" :size="14">
            <ArrowDown />
          </el-icon>
        </div>
        <div v-show="sourcesExpanded" class="sources-list">
          <div
            v-for="(source, index) in message.sources"
            :key="index"
            :id="sourceId(index)"
            :class="['source-item', { highlight: highlightedIndex === index }]"
          >
            <div class="source-item-header">
              <span class="source-index">[{{ source.citation_index ?? index + 1 }}]</span>
              <span class="source-doc-title">{{ source.title || '未知来源' }}</span>
              <span v-if="source.page_number" class="source-page">第 {{ source.page_number }} 页</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 免责声明 -->
      <div v-if="message.role === 'assistant' && !message.is_error" class="disclaimer">
        <el-icon :size="13"><WarningFilled /></el-icon>
        以上内容仅供参考，不构成医疗建议或诊断依据。如有不适，请及时就医。
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Collection, ArrowDown, WarningFilled } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { sanitizeHtml } from '@/utils/sanitize'
import type { Message } from '@/api/chat'

const props = defineProps<{
  message: Message
  dangerWarning?: { level: string; advice: string } | null
}>()

const emit = defineEmits<{
  (e: 'retry', message: Message): void
}>()

const highlightedIndex = ref<number | null>(null)
const sourcesExpanded = ref(false)

function sourceId(index: number) {
  return `source-${props.message.id}-${index}`
}

/**
 * Apply citation replacement only to non-code sections of HTML.
 * Splits on <pre> and <code> blocks, replaces [N] only in plain-text segments.
 */
function replaceCitationsOutsideCode(html: string): string {
  const parts = html.split(/(<(?:pre|code)\b[^>]*>[\s\S]*?<\/(?:pre|code)>)/g)
  return parts
    .map((part) => {
      if (/^<(?:pre|code)\b/.test(part)) return part
      return part.replace(/\[(\d+)\]/g, (_match, num) => {
        const citationNum = parseInt(num, 10)
        const found = props.message.sources.find((s: any) => s.citation_index === citationNum)
        if (!found) {
          return `<span class="citation-missing">[${num}]</span>`
        }
        return `<a class="citation-link" data-citation="${citationNum}" href="#">[${num}]</a>`
      })
    })
    .join('')
}

const renderedContent = computed(() => {
  if (!props.message.content) return ''
  const rawHtml = marked.parse(props.message.content, { async: false }) as string
  const safeHtml = sanitizeHtml(rawHtml)
  return replaceCitationsOutsideCode(safeHtml)
})

function handleCitationClick(event: MouseEvent) {
  const node = event.target as Node
  const el = node instanceof Element ? node : node.parentElement
  const target = el?.closest('.citation-link') as HTMLElement | null
  if (!target) return
  event.preventDefault()
  const citationNum = parseInt(target.dataset.citation || '', 10)
  if (Number.isNaN(citationNum)) return

  // 按 citation_index 找到对应的 source 在数组中的位置
  const sourceIndex = props.message.sources.findIndex((s: any) => s.citation_index === citationNum)
  if (sourceIndex === -1) return

  // Expand sources section and highlight the clicked source
  sourcesExpanded.value = true

  const sourceEl = document.getElementById(sourceId(sourceIndex))
  if (!sourceEl) return

  sourceEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  highlightedIndex.value = sourceIndex
  setTimeout(() => {
    highlightedIndex.value = null
  }, 2000)
}
</script>

<style scoped>
/* ===== 消息行 ===== */
.message-row {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  animation: msg-fade-in var(--duration-slow) ease-out;
}

@keyframes msg-fade-in {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-row.user {
  flex-direction: row-reverse;
  animation-delay: 0ms;
}

.message-avatar {
  flex-shrink: 0;
  margin-top: 2px;
}

.message-content {
  max-width: 70%;
  min-width: 0;
}

/* ===== 对话气泡 ===== */
.message-bubble {
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-bubble);
  line-height: 1.6;
  font-size: 15px;
  color: var(--text-primary);
  word-break: break-word;
}

/* AI 气泡：左下小圆角（4px），形成尾巴指向头像，fit-content 避免被下方元素撑宽 */
.message-row.assistant .message-bubble {
  background: hsl(200, 65%, 94%);
  border-radius: var(--radius-bubble) var(--radius-bubble) var(--radius-bubble) 4px;
  width: fit-content;
  max-width: 100%;
}

/* 用户气泡：右下小圆角（4px），形成尾巴指向用户，fit-content 避免被警告卡片撑宽 */
.message-row.user .message-bubble {
  background: hsl(200, 10%, 94%);
  border-radius: var(--radius-bubble) var(--radius-bubble) 4px var(--radius-bubble);
  width: fit-content;
  max-width: 100%;
  margin-left: auto;
}

.message-bubble.no-knowledge {
  background: var(--color-accent-light);
}

.message-bubble.is-error {
  background: hsl(0, 55%, 95%);
  color: var(--color-danger);
}

.retry-row {
  margin-top: 10px;
}

/* ===== Markdown 内容 ===== */
.message-text :deep(p) {
  margin: 0 0 var(--space-2);
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(ul),
.message-text :deep(ol) {
  margin: 0 0 var(--space-2);
  padding-left: 20px;
}

.message-text :deep(pre) {
  margin: var(--space-2) 0;
  padding: var(--space-3);
  background: rgba(0, 0, 0, 0.04);
  border-radius: var(--radius-item);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  overflow-x: auto;
}

.message-text :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.9em;
}

.message-text :deep(.citation-link) {
  display: inline-block;
  color: var(--text-link);
  text-decoration: none;
  cursor: pointer;
  font-weight: 600;
  padding: 0 2px;
  transition: transform var(--duration-fast) ease-out;
}

.message-text :deep(.citation-link:hover) {
  text-decoration: underline;
  transform: translateY(-1px);
}

.message-text :deep(.citation-missing) {
  color: var(--text-disabled);
}

/* ===== 参考来源 ===== */
.sources {
  margin-top: var(--space-2);
  background: var(--bg-canvas);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  overflow: hidden;
}

.sources-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px var(--space-3);
  cursor: pointer;
  user-select: none;
  transition: background var(--duration-fast) ease-out;
}

.sources-header:hover {
  background: var(--bg-hover);
}

.sources-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-primary);
}

.sources-arrow {
  color: var(--text-disabled);
  transition: transform var(--duration-normal) var(--ease-standard);
}

.sources-arrow.expanded {
  transform: rotate(180deg);
}

.sources-list {
  border-top: 1px solid var(--border-light);
  padding: var(--space-1);
}

.source-item {
  padding: 8px 10px;
  border-radius: var(--radius-item);
  border-left: 3px solid transparent;
  transition: background-color var(--duration-fast) ease-out,
              border-color var(--duration-fast) ease-out;
}

.source-item:hover {
  background: var(--bg-hover);
}

.source-item.highlight {
  background: var(--color-accent-light);
  border-left-color: var(--color-accent);
  animation: highlight-pulse 2s ease-out;
}

@keyframes highlight-pulse {
  0% {
    background: hsl(25, 70%, 90%);
  }
  100% {
    background: var(--color-accent-light);
  }
}

.source-item-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.source-index {
  color: var(--text-link);
  font-weight: 600;
  flex-shrink: 0;
}

.source-doc-title {
  color: var(--text-primary);
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-page {
  color: var(--text-disabled);
  flex-shrink: 0;
  font-size: 11px;
}

/* ===== 免责声明 ===== */
.disclaimer {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-accent-light);
  border-left: 3px solid var(--color-warning);
  border-radius: var(--radius-item);
  font-size: var(--text-xs);
  color: hsl(38, 50%, 35%);
  display: inline-flex;
  align-items: flex-start;
  gap: 6px;
  line-height: 1.5;
  width: fit-content;
  max-width: 100%;
}

/* ===== 危险症状警告 ===== */
.danger-warning {
  margin-top: var(--space-2);
  padding: var(--space-3);
  border-radius: var(--radius-item);
  font-size: var(--text-sm);
  line-height: 1.5;
  display: inline-flex;
  align-items: flex-start;
  gap: var(--space-2);
  width: fit-content;
  max-width: 100%;
  word-break: break-word;
}

/* 用户消息的警告卡片右对齐，与气泡独立宽度 */
.message-row.user .danger-warning {
  margin-left: auto;
}

.danger-warning.critical {
  background: hsl(0, 55%, 95%);
  border-left: 3px solid var(--color-danger);
  color: hsl(0, 55%, 35%);
}

.danger-warning.warning {
  background: hsl(38, 60%, 95%);
  border-left: 3px solid var(--color-warning);
  color: hsl(38, 50%, 35%);
}
</style>
