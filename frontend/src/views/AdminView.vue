<template>
  <div class="admin-view">
    <AdminSidebar
      :active-key="activeSection"
      :collapsed="sidebarCollapsed"
      @toggle="toggleSidebar"
      @navigate="handleNavigate"
    />

    <div class="admin-main">
      <!-- 文档管理 -->
      <div v-if="activeSection === 'documents'" class="section-documents">
        <div class="section-header">
          <div class="section-title">
            <el-icon :size="18"><Document /></el-icon>
            <h2>文档管理</h2>
          </div>
          <p class="section-desc">上传和管理知识库文档，支持 PDF、Word、图片格式。</p>
        </div>

        <!-- 操作栏：搜索（左）+ 上传（右） -->
        <div class="toolbar-card">
          <div class="toolbar-row">
            <!-- 左侧：搜索 -->
            <div class="toolbar-left">
              <el-input
                v-model="searchKeyword"
                placeholder="搜索文档标题或文件名..."
                clearable
                @keydown.enter="handleSearch"
                @clear="handleSearch"
                class="search-input"
              >
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
              </el-input>
              <el-button type="primary" @click="handleSearch">
                <el-icon :size="16"><Search /></el-icon>
                <span>搜索</span>
              </el-button>
            </div>
            <!-- 右侧：上传 -->
            <div class="toolbar-right">
              <el-input
                v-model="uploadTitle"
                placeholder="修改当前上传文档标题（可选）"
                class="upload-title-input"
              />
              <el-upload
                ref="uploadRef"
                action="#"
                :auto-upload="false"
                :show-file-list="false"
                :on-change="handleFileChange"
                accept=".pdf,.docx,.doc,.jpg,.jpeg,.png"
              >
                <el-button type="primary">选择文件</el-button>
              </el-upload>
              <span v-if="selectedFile" class="selected-file">{{ selectedFile.name }}</span>
              <el-button
                type="success"
                :loading="uploading"
                :disabled="!selectedFile"
                @click="submitUpload"
              >
                上传
              </el-button>
            </div>
          </div>
        </div>

        <!-- 文档表格 -->
        <div class="table-card">
          <el-table :data="documents" v-loading="loading" stripe>
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column label="文件名 / 标题" min-width="200">
              <template #default="{ row }">
                <div class="doc-title">{{ row.title || row.filename }}</div>
                <div class="doc-filename">{{ row.filename }}</div>
              </template>
            </el-table-column>
            <el-table-column prop="file_type" label="类型" width="80" />
            <el-table-column label="大小" width="100">
              <template #default="{ row }">
                {{ formatSize(row.file_size) }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="110">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="chunk_count" label="分块数" width="90" />
            <el-table-column label="上传时间" width="160">
              <template #default="{ row }">
                {{ formatTime(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="300" fixed="right">
              <template #default="{ row }">
                <el-button
                  v-if="canChunk(row.status)"
                  type="primary"
                  size="small"
                  :loading="row.id === chunkingId"
                  @click="handleChunk(row)"
                >
                  分块
                </el-button>
                <el-button
                  v-if="canIndex(row.status)"
                  type="success"
                  size="small"
                  :loading="row.id === indexingId"
                  @click="handleIndex(row)"
                >
                  向量化入库
                </el-button>
                <el-button
                  v-if="canReIndex(row.status)"
                  type="success"
                  size="small"
                  :loading="row.id === indexingId"
                  @click="handleIndex(row)"
                >
                  重新向量化
                </el-button>
                <el-button
                  v-if="row.chunk_count > 0"
                  size="small"
                  @click="handlePreview(row)"
                >
                  预览
                </el-button>
                <el-button type="danger" size="small" @click="handleDelete(row)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div v-if="!documents.length && !loading" class="empty-tip">
            <el-icon :size="32"><FolderOpened /></el-icon>
            <p>暂无文档</p>
            <span>请上传 PDF / Word / 图片以构建知识库</span>
          </div>
        </div>
      </div>

      <!-- 图片管理（占位） -->
      <div v-else-if="activeSection === 'images'" class="section-placeholder">
        <div class="placeholder-content">
          <el-icon :size="48"><Picture /></el-icon>
          <h3>图片管理</h3>
          <p>当前功能正在开发中。完成后您可以上传和管理病例相关的影像图片（如超声、CT、MRI 等），并支持图片与知识库内容的关联检索。</p>
        </div>
      </div>

      <!-- 视频管理（占位） -->
      <div v-else-if="activeSection === 'videos'" class="section-placeholder">
        <div class="placeholder-content">
          <el-icon :size="48"><VideoCamera /></el-icon>
          <h3>视频管理</h3>
          <p>当前功能正在开发中。完成后您可以管理手术视频素材库，支持按手术步骤标记视频片段，并结合语音识别和字幕功能实现视频内容的智能检索。</p>
        </div>
      </div>

      <!-- 知识分类（占位） -->
      <div v-else-if="activeSection === 'categories'" class="section-placeholder">
        <div class="placeholder-content">
          <el-icon :size="48"><Folder /></el-icon>
          <h3>知识分类</h3>
          <p>知识分类功能正在开发中，完成后您可以按疾病类型（如胆囊结石、肝病等）对知识库进行分类管理。</p>
        </div>
      </div>
    </div>

    <!-- 分块预览抽屉 -->
    <el-drawer v-model="previewVisible" title="分块预览" size="60%">
      <div v-if="previewDoc" class="preview-header">
        <h3>{{ previewDoc.title || previewDoc.filename }}</h3>
        <p>共 {{ previewDoc.chunks.length }} 个分块</p>
      </div>
      <div v-if="previewLoading" class="preview-loading">加载中...</div>
      <div v-else class="chunk-list">
        <div
          v-for="chunk in previewChunks"
          :key="chunk.id"
          class="chunk-item"
        >
          <div class="chunk-meta">
            <span>分块 {{ (chunk.chunk_index ?? 0) + 1 }}</span>
            <span v-if="chunk.page_number">页码：{{ chunk.page_number }}</span>
            <span>字符数：{{ chunk.content.length }}</span>
            <el-button
              type="danger"
              size="small"
              style="margin-left: auto"
              :loading="deletingChunkId === chunk.id"
              @click="handleDeleteChunk(chunk)"
            >
              删除
            </el-button>
          </div>
          <pre class="chunk-content">{{ chunk.content }}</pre>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Document, FolderOpened, Folder, Search, Picture, VideoCamera } from '@element-plus/icons-vue'
import type { UploadInstance, UploadFile } from 'element-plus'
import AdminSidebar from '@/components/AdminSidebar.vue'
import {
  uploadDocument,
  listDocuments,
  deleteDocument,
  chunkDocument,
  indexDocument,
  deleteChunk,
  getDocument,
  type DocumentOut,
  type DocumentWithChunksOut,
  type ChunkOut,
} from '@/api/admin'

// ===== 侧边栏 =====
const sidebarCollapsed = ref(localStorage.getItem('admin_sidebar_collapsed') === 'true')

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('admin_sidebar_collapsed', String(sidebarCollapsed.value))
}

// ===== 导航 =====
const activeSection = ref('documents')

function handleNavigate(key: string) {
  activeSection.value = key
}

// ===== 文档管理 =====
const loading = ref(false)
const uploading = ref(false)
const uploadTitle = ref('')
const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File | null>(null)
const documents = ref<DocumentOut[]>([])
const chunkingId = ref<number | null>(null)
const indexingId = ref<number | null>(null)
const searchKeyword = ref('')

const previewVisible = ref(false)
const previewLoading = ref(false)
const previewDoc = ref<DocumentWithChunksOut | null>(null)
const previewChunks = ref<ChunkOut[]>([])
const deletingChunkId = ref<number | null>(null)

function statusType(status: string) {
  switch (status) {
    case 'indexed':
    case 'chunked':
      return 'success'
    case 'failed':
      return 'danger'
    case 'parsing':
    case 'indexing':
      return 'info'
    case 'pending':
    default:
      return 'warning'
  }
}

function statusLabel(status: string) {
  const map: Record<string, string> = {
    pending: '待处理',
    parsing: '解析中',
    chunked: '已分块',
    indexing: '向量化中',
    indexed: '已入库',
    failed: '失败',
  }
  return map[status] || status
}

function canChunk(status: string) {
  return status === 'pending' || status === 'chunked' || status === 'indexed' || status === 'failed'
}

function canIndex(status: string) {
  return status === 'chunked'
}

function canReIndex(status: string) {
  return status === 'indexed' || status === 'failed'
}

function formatSize(bytes: number | null) {
  if (bytes === null || bytes === undefined) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

function formatTime(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function loadDocuments(search?: string) {
  loading.value = true
  try {
    const res = await listDocuments(0, 100, search || undefined)
    documents.value = res.items
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载文档列表失败')
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  loadDocuments(searchKeyword.value.trim() || undefined)
}

function handleFileChange(uploadFile: UploadFile) {
  selectedFile.value = uploadFile.raw || null
}

async function submitUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  try {
    await uploadDocument(selectedFile.value, uploadTitle.value)
    ElMessage.success('上传成功')
    uploadTitle.value = ''
    selectedFile.value = null
    uploadRef.value?.clearFiles()
    await loadDocuments()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '上传失败'
    ElMessage.error(detail)
  } finally {
    uploading.value = false
  }
}

async function handleChunk(row: DocumentOut) {
  chunkingId.value = row.id
  try {
    const res = await chunkDocument(row.id)
    ElMessage.success(`分块完成，共 ${res.chunks.length} 个分块`)
    await loadDocuments()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '分块失败'
    ElMessage.error(detail)
    await loadDocuments()
  } finally {
    chunkingId.value = null
  }
}

async function handleIndex(row: DocumentOut) {
  indexingId.value = row.id
  try {
    const res = await indexDocument(row.id)
    ElMessage.success(`向量化完成，共 ${res.chunks.length} 个分块`)
    await loadDocuments()
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '向量化失败'
    ElMessage.error(detail)
    await loadDocuments()
  } finally {
    indexingId.value = null
  }
}

async function handlePreview(row: DocumentOut) {
  previewVisible.value = true
  previewLoading.value = true
  previewDoc.value = null
  previewChunks.value = []
  try {
    const res = await getDocument(row.id)
    previewDoc.value = res
    previewChunks.value = res.chunks
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载分块预览失败')
  } finally {
    previewLoading.value = false
  }
}

async function handleDeleteChunk(chunk: ChunkOut) {
  if (!previewDoc.value) return
  try {
    await ElMessageBox.confirm('确定删除该分块吗？', '确认删除', {
      type: 'warning',
    })
    deletingChunkId.value = chunk.id
    await deleteChunk(chunk.document_id, chunk.id)
    ElMessage.success('删除分块成功')
    const res = await getDocument(chunk.document_id)
    previewDoc.value = res
    previewChunks.value = res.chunks
    await loadDocuments()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.detail || '删除分块失败')
    }
  } finally {
    deletingChunkId.value = null
  }
}

async function handleDelete(row: DocumentOut) {
  try {
    await ElMessageBox.confirm('确定删除该文档及其分块吗？', '确认删除', {
      type: 'warning',
    })
    await deleteDocument(row.id)
    ElMessage.success('删除成功')
    await loadDocuments()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.detail || '删除失败')
    }
  }
}

onMounted(() => {
  loadDocuments()
})
</script>

<style scoped>
.admin-view {
  display: flex;
  height: 100vh;
  background: var(--bg-canvas);
}

/* ===== 主内容区 ===== */
.admin-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

/* ===== 区块头部 ===== */
.section-header {
  padding: var(--space-6) var(--space-8) 0;
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  color: var(--text-primary);
}

.section-title h2 {
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 600;
}

.section-desc {
  margin: var(--space-2) 0 0;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

/* ===== 操作栏（搜索 + 上传） ===== */
.toolbar-card {
  margin: var(--space-6) var(--space-8);
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
}

.toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex-shrink: 0;
}

.search-input {
  width: 280px;
  flex-shrink: 0;
}

.upload-title-input {
  width: 260px;
}

.selected-file {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== 表格卡片 ===== */
.table-card {
  margin: 0 var(--space-8) var(--space-8);
  padding: var(--space-5);
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
}

.empty-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) 0;
  color: var(--text-disabled);
}

.empty-tip p {
  margin: var(--space-3) 0 var(--space-1);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.empty-tip span {
  font-size: var(--text-xs);
}

.doc-title {
  font-weight: 600;
  color: var(--text-primary);
  font-size: var(--text-sm);
}

/* 覆盖 Element Plus 表格默认的 break-all，让长标题按自然边界换行 */
.table-card :deep(.el-table__body-wrapper .cell) {
  word-break: break-word;
}

.doc-filename {
  font-size: var(--text-xs);
  color: var(--text-disabled);
  margin-top: var(--space-1);
}

/* 操作列按钮更紧凑，留出 loading 动画的扩展空间 */
.table-card :deep(.el-button--small) {
  padding: 5px 10px;
}

/* ===== 占位页 ===== */
.section-placeholder {
  height: 100%;
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

/* ===== 预览抽屉 ===== */
.preview-header {
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--border-default);
}

.preview-header h3 {
  margin: 0 0 var(--space-2);
  color: var(--text-primary);
  font-weight: 600;
}

.preview-header p {
  margin: 0;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.preview-loading {
  text-align: center;
  color: var(--text-disabled);
  padding: var(--space-10) 0;
}

.chunk-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.chunk-item {
  border: 1px solid var(--border-default);
  border-radius: var(--radius-item);
  padding: var(--space-3);
  background: var(--bg-surface);
}

.chunk-meta {
  display: flex;
  gap: var(--space-4);
  margin-bottom: var(--space-2);
  font-size: var(--text-xs);
  color: var(--text-secondary);
}

.chunk-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: var(--font-sans);
  font-size: var(--text-sm);
  line-height: 1.6;
  color: var(--text-primary);
  background: var(--bg-canvas);
  padding: var(--space-3);
  border-radius: var(--radius-item);
  max-height: 240px;
  overflow-y: auto;
}
</style>
