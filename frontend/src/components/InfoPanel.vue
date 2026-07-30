<template>
  <div :class="['info-panel', { visible }]">
    <div class="panel-inner">
      <!-- 头部 -->
      <div class="panel-top">
        <div class="panel-title">
          <el-icon :size="16"><Collection /></el-icon>
          <span>信息来源</span>
        </div>
        <el-badge v-if="flatSources.length" :value="flatSources.length" type="primary" class="source-count" />
        <el-button :icon="Close" text size="small" @click="$emit('close')" title="关闭面板 (Ctrl+B)" />
      </div>

      <!-- 来源列表（按问题分组） -->
      <div class="panel-body" v-if="flatSources.length">
        <div
          v-for="(group, gi) in groups"
          :key="group.messageId"
          class="source-group"
        >
          <div class="group-question">{{ group.question }}</div>
          <div
            v-for="(source, si) in group.sources"
            :key="`${source.chunk_id}-${si}`"
            :class="['panel-source-card', {
              active: activeGroupIndex === gi && activeSourceIndex === si,
              expanded: expandedKey === `${gi}-${si}`
            }]"
            @click="toggleExpand(source, gi, si)"
          >
            <div class="psc-header">
              <span class="psc-index">{{ source.citation_index ?? si + 1 }}</span>
              <span class="psc-title">{{ source.title || '未知来源' }}</span>
              <el-icon v-if="source.content" :class="['psc-arrow', { down: expandedKey === `${gi}-${si}` }]" :size="14">
                <ArrowDown />
              </el-icon>
            </div>
            <div class="psc-meta" v-if="source.page_number">
              <span>第 {{ source.page_number }} 页</span>
            </div>
            <!-- 展开态：完整知识块内容 -->
            <div class="psc-excerpt" v-if="source.content && expandedKey === `${gi}-${si}`">
              {{ source.content }}
            </div>
            <!-- 查看完整病例按钮 -->
            <el-button
              v-if="source.content && expandedKey === `${gi}-${si}`"
              class="view-full-case-btn"
              size="small"
              text
              type="primary"
              @click.stop="openFullCase(source)"
            >
              <el-icon :size="14"><Document /></el-icon>
              查看完整病例
            </el-button>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else class="panel-empty">
        <el-icon :size="32"><Document /></el-icon>
        <p>暂无引用来源</p>
        <span>发送问题并从 AI 获取回答后，引用来源会展示在这里。</span>
      </div>

      <!-- 底部提示 -->
      <div v-if="flatSources.length" class="panel-foot">
        <el-icon :size="13"><WarningFilled /></el-icon>
        来源内容由知识库检索生成，仅供参考。
      </div>
    </div>

    <!-- 完整病例弹窗 -->
    <el-dialog
      v-model="caseDialogVisible"
      :title="caseTitle"
      width="760px"
      top="5vh"
      destroy-on-close
      class="case-dialog"
    >
      <div class="case-body">
        <div v-if="casePageNumber" class="case-page-marker">第 {{ casePageNumber }} 页</div>
        <div v-loading="caseLoading" class="case-text">{{ caseContent }}</div>
        <!-- 关联图片 -->
        <div v-if="caseImages.length" class="case-images">
          <div class="case-images-title">
            <el-icon :size="14"><Picture /></el-icon>
            病例图片 · {{ caseImages.length }}
          </div>
          <div class="case-images-grid">
            <el-image
              v-for="(img, ii) in caseImages"
              :key="ii"
              :src="img.url"
              :preview-src-list="caseImages.map(i => i.url)"
              :initial-index="ii"
              :preview-teleported="true"
              :zoom-rate="1.35"
              :min-scale="0.2"
              :max-scale="12"
              fit="contain"
              class="case-image-thumb"
            >
              <template #error>
                <div class="case-image-error">
                  <el-icon :size="20"><Picture /></el-icon>
                </div>
              </template>
            </el-image>
          </div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, Collection, Close, Document, Picture, WarningFilled } from '@element-plus/icons-vue'
import { getDocumentContent, getProtectedImage } from '@/api/chat'

interface SourceItem {
  chunk_id: number
  document_id?: number
  title?: string
  page_number?: number | null
  content?: string
  citation_index?: number
  images?: { url: string; page?: number }[]
  messageId?: number
}

interface SourceGroup {
  question: string
  messageId: number
  sources: SourceItem[]
}

const props = defineProps<{
  visible: boolean
  groups: SourceGroup[]
  activeGroupIndex?: number | null
  activeSourceIndex?: number | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'source-click', source: SourceItem): void
}>()

// 当前展开的卡片 key（`gi-si`），null = 全部收起
const expandedKey = ref<string | null>(null)

// 所有来源的扁平列表（用于计数）
const flatSources = computed<SourceItem[]>(() => {
  return props.groups.flatMap(g => g.sources)
})

function toggleExpand(source: SourceItem, gi: number, si: number) {
  const key = `${gi}-${si}`
  // 点击已展开的卡片 → 收起；否则展开
  expandedKey.value = expandedKey.value === key ? null : key
  // 同时通知父组件（用于滚动到聊天区对应来源）
  emit('source-click', source)
}

// ===== 查看完整病例弹窗 =====
const caseDialogVisible = ref(false)
const caseTitle = ref('')
const caseContent = ref('')
const casePageNumber = ref<number | null>(null)
const caseImages = ref<{ url: string; page?: number }[]>([])
const caseLoading = ref(false)
let imageObjectUrls: string[] = []

function clearImageObjectUrls() {
  imageObjectUrls.forEach(url => URL.revokeObjectURL(url))
  imageObjectUrls = []
}

async function openFullCase(source: SourceItem) {
  caseDialogVisible.value = true
  caseTitle.value = source.title || '完整病例'
  caseContent.value = source.content || '暂无内容'
  casePageNumber.value = source.page_number ?? null
  caseImages.value = []
  caseLoading.value = true
  clearImageObjectUrls()

  try {
    if (source.document_id) {
      const document = await getDocumentContent(source.document_id)
      caseTitle.value = document.title || caseTitle.value
      caseContent.value = document.chunks.map(chunk => chunk.content).join('\n\n') || caseContent.value
    }

    const images = await Promise.all((source.images || []).map(async img => {
      const blob = await getProtectedImage(img.url)
      const objectUrl = URL.createObjectURL(blob)
      imageObjectUrls.push(objectUrl)
      return { ...img, url: objectUrl }
    }))
    caseImages.value = images
  } catch {
    ElMessage.error('完整病例或关联图片加载失败')
  } finally {
    caseLoading.value = false
  }
}

onUnmounted(clearImageObjectUrls)
</script>

<style scoped>
/* ===== 外层 ===== */
.info-panel {
  max-width: 0;
  width: 50%;
  min-width: 0;
  flex-shrink: 0;
  height: 100%;
  background: var(--bg-surface);
  border-left: 1px solid var(--border-default);
  transition: max-width var(--duration-normal) var(--ease-standard),
              border-color var(--duration-normal) var(--ease-standard);
  overflow: hidden;
}

.info-panel.visible {
  max-width: 600px;
}

/* ===== 内层（填满外层） ===== */
.panel-inner {
  width: min(600px, 50vw);
  min-width: min(600px, 50vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 0;
  transform: translateX(100%);
  transition: transform var(--duration-normal) var(--ease-standard);
}

.info-panel.visible .panel-inner {
  transform: translateX(0);
}

/* ===== 头部 ===== */
.panel-top {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-4) var(--space-5);
  border-bottom: 1px solid var(--border-default);
  height: var(--topbar-height);
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  flex: 1;
}

.source-count {
  margin-right: auto;
}

/* ===== 主体列表 ===== */
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-3) var(--space-4);
}

.source-group {
  margin-bottom: var(--space-4);
}

.group-question {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  padding: var(--space-1) 0 var(--space-2);
  border-bottom: 1px solid var(--border-light);
  margin-bottom: var(--space-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.panel-source-card {
  padding: var(--space-3);
  margin-bottom: var(--space-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  cursor: pointer;
  transition: border-color var(--duration-fast) ease-out,
              box-shadow var(--duration-fast) ease-out,
              transform var(--duration-fast) ease-out;
}

.panel-source-card:hover {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
  transform: translateY(-1px);
}

.panel-source-card.active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.panel-source-card.expanded {
  border-color: var(--border-default);
  box-shadow: var(--shadow-sm);
}

/* ===== 卡片头部 ===== */
.psc-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 4px;
}

.psc-index {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.psc-title {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.psc-arrow {
  flex-shrink: 0;
  color: var(--text-disabled);
  transition: transform var(--duration-fast) ease-out;
}

.psc-arrow.down {
  transform: rotate(180deg);
}

.psc-meta {
  font-size: 11px;
  color: var(--text-disabled);
  margin-bottom: 6px;
  padding-left: 28px;
}

/* ===== 内容区域 ===== */
.psc-excerpt {
  font-size: var(--text-xs);
  line-height: 1.6;
  color: var(--text-secondary);
  padding: var(--space-2);
  background: var(--bg-canvas);
  border-left: 2px solid var(--color-primary);
  border-radius: var(--radius-item);
  max-height: 420px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ===== 空状态 ===== */
.panel-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-10);
  text-align: center;
  color: var(--text-disabled);
}

.panel-empty p {
  margin: var(--space-3) 0 var(--space-2);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.panel-empty span {
  font-size: var(--text-xs);
  max-width: 240px;
  line-height: 1.5;
}

/* ===== 查看完整病例按钮 ===== */
.view-full-case-btn {
  margin-top: var(--space-2);
  font-size: var(--text-xs);
}

/* ===== 完整病例弹窗 ===== */
.case-body {
  max-height: 70vh;
  overflow-y: auto;
}

.case-page-marker {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--color-primary);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-1);
  border-bottom: 1px dashed var(--border-light);
}

.case-text {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.case-images {
  margin-top: var(--space-5);
  padding-top: var(--space-4);
  border-top: 1px solid var(--border-light);
}

.case-images-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: var(--space-3);
}

.case-images-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--space-3);
}

.case-image-thumb {
  aspect-ratio: 4 / 3;
  min-height: 220px;
  border-radius: var(--radius-item);
  overflow: hidden;
  cursor: pointer;
  background: var(--bg-canvas);
  border: 1px solid var(--border-light);
  transition: transform var(--duration-fast) ease-out,
              box-shadow var(--duration-fast) ease-out;
}

.case-image-thumb:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-sm);
}

.case-image-error {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-canvas);
  color: var(--text-disabled);
}

/* ===== 底部 ===== */
.panel-foot {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-5);
  border-top: 1px solid var(--border-light);
  font-size: 11px;
  color: var(--text-disabled);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
