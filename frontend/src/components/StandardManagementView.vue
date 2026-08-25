<template>
  <div class="standard-management">
    <div class="section-header">
      <div class="section-title">
        <el-icon :size="18"><Collection /></el-icon>
        <h2>标准管理</h2>
      </div>
      <p class="section-desc">管理员维护 DOCX 标准、审核规则并发布当前版本；evidence-only 内容只作为证据展示。</p>
    </div>

    <section class="panel-card upload-card">
      <div class="panel-heading">
        <div>
          <h3>标准文档库</h3>
          <p class="upload-hint">先上传 DOCX 源文件，再将可用文档关联为标准版本。</p>
        </div>
        <el-tag type="info" effect="plain">{{ standardDocuments.length }} 个文档</el-tag>
      </div>
      <div class="upload-row">
        <el-input v-model="uploadTitle" placeholder="文档标题（可选）" class="upload-title" aria-label="文档标题" />
        <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false" accept=".docx" :on-change="handleFileChange">
          <el-button><el-icon><Upload /></el-icon>选择 DOCX</el-button>
        </el-upload>
        <span v-if="selectedFile" class="selected-file" :title="selectedFile.name">{{ selectedFile.name }}</span>
        <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="submitUpload">上传标准</el-button>
      </div>
      <div v-if="standardDocuments.length" class="document-table-wrap">
        <el-table :data="standardDocuments" class="document-table" size="small">
          <el-table-column label="文档" min-width="180">
            <template #default="{ row: document }">
              <span class="document-name" :title="document.title || document.filename">{{ document.title || document.filename }}</span>
              <span v-if="document.title" class="document-filename" :title="document.filename">{{ document.filename }}</span>
            </template>
          </el-table-column>
          <el-table-column label="哈希" min-width="116">
            <template #default="{ row: document }"><code class="document-hash">{{ document.content_hash.slice(0, 12) }}</code></template>
          </el-table-column>
          <el-table-column label="大小 / 上传时间" min-width="168">
            <template #default="{ row: document }">
              <span class="document-meta">{{ formatBytes(document.file_size) }}</span>
              <span class="document-meta">{{ formatDateTime(document.created_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" min-width="160">
            <template #default="{ row: document }">
              <el-tag :type="document.is_locked ? 'info' : 'success'" size="small" effect="plain">{{ document.is_locked ? '已关联' : '可用' }}</el-tag>
              <span v-if="document.is_locked" class="link-detail" :title="`${document.standard_name || '-'} · ${document.version_label || '-'}`">
                {{ document.standard_name || '-' }} · {{ document.version_label || '-' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="72" fixed="right">
            <template #default="{ row: document }">
              <el-tooltip v-if="!document.is_locked" content="删除源文档" placement="top">
                <el-button
                  class="icon-action"
                  text
                  type="danger"
                  aria-label="删除源文档"
                  :loading="documentDeletingId === document.id"
                  :disabled="documentDeletingId !== null"
                  @click="confirmDeleteDocument(document)"
                >
                  <el-icon><Delete /></el-icon>
                </el-button>
              </el-tooltip>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div v-else class="document-list-empty">暂无已上传的 DOCX 标准文档</div>
    </section>

    <div class="workbench">
      <section class="panel-card">
        <div class="panel-heading collection-heading">
          <h3>标准集合</h3>
          <el-tooltip :disabled="availableDiseases.length > 0" content="所有疾病均已创建标准集合" placement="top">
            <span>
              <el-button :disabled="lifecyclePending || !availableDiseases.length" @click="standardDialogVisible = true">
                <el-icon><Plus /></el-icon>新建标准集合
              </el-button>
            </span>
          </el-tooltip>
        </div>
        <el-button
          v-for="item in standards"
          :key="item.id"
          class="list-button"
          :class="{ active: selectedStandard?.id === item.id }"
          :disabled="lifecyclePending"
          text
          @click="selectStandard(item)"
        >{{ item.name }}</el-button>
        <el-empty v-if="!standards.length" description="暂无标准集合" />
      </section>

      <section class="panel-card">
        <div class="panel-heading version-heading">
          <h3>版本审核</h3>
          <el-button :disabled="lifecyclePending || !selectedStandard" @click="openVersionDialog"><el-icon><Plus /></el-icon>新建版本</el-button>
        </div>
        <el-select v-model="selectedVersionId" class="version-select" placeholder="选择版本" clearable :disabled="lifecyclePending" :loading="versionDataLoading" @change="loadVersionData">
          <el-option v-for="version in versions" :key="version.id" :label="`${version.version_label} · ${version.status}`" :value="version.id" />
        </el-select>
        <div class="action-row">
          <el-button :disabled="lifecyclePending || !selectedVersion || selectedVersion.status !== 'draft'" @click="runAction(parseVersion, '解析完成')">解析</el-button>
          <el-button :disabled="lifecyclePending || !selectedVersion || selectedVersion.status !== 'draft'" @click="runAction(submitReview, '已提交审核')">提交审核</el-button>
          <el-button type="primary" :disabled="lifecyclePending || !selectedVersion || selectedVersion.status !== 'review'" @click="runAction(approveVersion, '已批准发布')">批准发布</el-button>
          <el-button type="warning" :disabled="lifecyclePending || !selectedVersion || selectedVersion.status !== 'approved'" @click="runAction(retireVersion, '已退役')">退役</el-button>
          <el-button v-if="selectedVersion && ['draft', 'review'].includes(selectedVersion.status)" type="danger" plain :disabled="lifecyclePending" @click="confirmDeleteVersion">
            <el-icon><Delete /></el-icon>删除版本
          </el-button>
        </div>
        <el-alert v-if="workspaceIsCurrent && validation.errors.length" type="error" :title="`存在 ${validation.errors.length} 个阻止发布的问题`" show-icon />
        <el-alert v-else-if="workspaceIsCurrent && selectedVersion" type="success" :title="`可投影规则 ${validation.projection_count} 条`" show-icon />
      </section>
    </div>

    <div class="content-grid">
      <section class="panel-card">
        <h3>源片段</h3>
        <el-scrollbar height="360px"><div v-for="segment in segments" :key="segment.id" class="segment-item">{{ segment.raw_text }}</div></el-scrollbar>
      </section>
      <section class="panel-card">
        <h3>规则审核</h3>
        <div class="rule-table-wrap">
          <el-table :data="rules" size="small" :loading="versionDataLoading">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="rule_type" label="类型" min-width="100" />
            <el-table-column prop="machine_actionability" label="状态" min-width="130" />
            <el-table-column prop="interpretation" label="解释" min-width="180" />
            <el-table-column label="操作" width="90" fixed="right">
              <template #default="{ row }">
                <el-button text :disabled="!canEditRule(row)" @click="openRuleEditor(row)">编辑</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-empty v-if="!rules.length" description="暂无规则" />
      </section>
    </div>

    <el-dialog v-model="standardDialogVisible" title="新建标准集合" width="min(520px, calc(100vw - 32px))">
      <el-form label-position="top">
        <el-form-item label="选择疾病">
          <el-select v-model="newStandardDiseaseId" class="dialog-control" placeholder="请选择疾病" aria-label="选择疾病" :disabled="standardCreating">
            <el-option v-for="disease in availableDiseases" :key="disease.id" :label="disease.name" :value="disease.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="standardCreating" @click="standardDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="standardCreating" :disabled="standardCreating || !newStandardDiseaseId || !availableDiseases.length" @click="submitStandard">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="versionDialogVisible" title="新建版本" width="min(520px, calc(100vw - 32px))">
      <el-form label-position="top">
        <el-form-item label="标准文档">
          <el-select v-model="newVersionDocumentId" class="dialog-control" placeholder="选择可用文档" aria-label="选择可用标准文档" :disabled="versionCreating">
            <el-option v-for="document in availableDocuments" :key="document.id" :label="document.title || document.filename" :value="document.id" />
          </el-select>
          <p v-if="!availableDocuments.length" class="form-hint">请先上传 DOCX 标准文档</p>
        </el-form-item>
        <el-form-item label="版本标签"><el-input v-model="newVersionLabel" placeholder="例如：2026.1" aria-label="版本标签" :disabled="versionCreating" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="versionCreating" @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="versionCreating" :disabled="versionCreating || !newVersionDocumentId || !newVersionLabel.trim() || !availableDocuments.length" @click="submitVersion">创建草稿</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editorVisible" title="编辑规则" width="min(440px, calc(100vw - 32px))">
      <el-form label-width="90px">
        <el-form-item label="上限"><el-input-number v-model="editorUpper" :controls="false" :disabled="ruleSaving" /></el-form-item>
        <el-form-item label="修改原因"><el-input v-model="editorReason" type="textarea" placeholder="请输入修改原因" :disabled="ruleSaving" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="ruleSaving" @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" :disabled="ruleSaving || lifecyclePending || !editorReason.trim()" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox, type UploadFile, type UploadInstance } from 'element-plus'
import { Collection, Delete, Plus, Upload } from '@element-plus/icons-vue'
import { listDiseases, type Disease } from '@/api/operator'
import {
  approveVersion,
  createStandard,
  createVersion,
  deleteStandardDocument,
  deleteVersion,
  listRules,
  listSegments,
  listStandardDocuments,
  listStandards,
  listVersions,
  parseVersion,
  patchRule,
  retireVersion,
  submitReview,
  uploadStandardDocument,
  validateVersion,
  type Standard,
  type StandardDocument,
  type StandardRule,
  type StandardSegment,
  type StandardVersion,
  type ValidationReport,
} from '@/api/adminStandards'

const emptyValidation = (): ValidationReport => ({ errors: [], warnings: [], infos: [], projection_count: 0 })

const standards = ref<Standard[]>([])
const diseases = ref<Disease[]>([])
const selectedStandard = ref<Standard | null>(null)
const versions = ref<StandardVersion[]>([])
const selectedVersionId = ref<number | null>(null)
const segments = ref<StandardSegment[]>([])
const rules = ref<StandardRule[]>([])
const validation = ref<ValidationReport>(emptyValidation())
const standardDocuments = ref<StandardDocument[]>([])
const workspaceLoadedVersionId = ref<number | null>(null)
const versionDataLoading = ref(false)
const lifecyclePending = ref(false)
const standardCreating = ref(false)
const versionCreating = ref(false)
const documentDeletingId = ref<number | null>(null)
const ruleSaving = ref(false)
const selectedVersion = computed(() => versions.value.find(item => item.id === selectedVersionId.value) || null)
const workspaceIsCurrent = computed(() => workspaceLoadedVersionId.value === selectedVersionId.value
  && selectedVersionId.value !== null
  && !versionDataLoading.value)
const availableDocuments = computed(() => standardDocuments.value.filter(document => !document.is_locked))
const availableDiseases = computed(() => {
  const usedDiseaseIds = new Set(standards.value.map(standard => standard.disease_id))
  return diseases.value.filter(disease => !usedDiseaseIds.has(disease.id))
})

const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File | null>(null)
const uploadTitle = ref('')
const uploading = ref(false)
const standardDialogVisible = ref(false)
const newStandardDiseaseId = ref<number | null>(null)
const versionDialogVisible = ref(false)
const newVersionDocumentId = ref<number | null>(null)
const newVersionLabel = ref('')
const editorVisible = ref(false)
const editorRule = ref<StandardRule | null>(null)
const editorUpper = ref<number | null>(null)
const editorReason = ref('')
let standardsRequestSequence = 0
let standardDocumentsRequestSequence = 0
let versionsRequestSequence = 0
let versionDataRequestSequence = 0
const latestVersionsRequestByStandard = new Map<number, number>()

function getErrorMessage(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

async function refreshAfterMutation(refreshTasks: Array<() => Promise<unknown>>) {
  try {
    const results = await Promise.all(refreshTasks.map(refresh => refresh()))
    if (results.some(result => result === false)) throw new Error('refresh failed')
    return true
  } catch {
    ElMessage.warning('操作已完成，但刷新失败，请手动重试')
    return false
  }
}

function handleFileChange(file: UploadFile) {
  selectedFile.value = file.raw || null
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function clearVersionWorkspace() {
  workspaceLoadedVersionId.value = null
  segments.value = []
  rules.value = []
  validation.value = emptyValidation()
  editorVisible.value = false
  editorRule.value = null
}

async function loadStandards(notifyError = true) {
  const requestSequence = ++standardsRequestSequence
  try {
    const items = await listStandards()
    if (requestSequence !== standardsRequestSequence) return true
    standards.value = items
    return true
  } catch (error: any) {
    if (requestSequence !== standardsRequestSequence) return true
    if (notifyError) ElMessage.error(getErrorMessage(error, '标准集合加载失败'))
    return false
  }
}

async function loadStandardDocuments(notifyError = true) {
  const requestSequence = ++standardDocumentsRequestSequence
  try {
    const documents = await listStandardDocuments()
    if (requestSequence !== standardDocumentsRequestSequence) return true
    standardDocuments.value = documents
    return true
  } catch (error: any) {
    if (requestSequence !== standardDocumentsRequestSequence) return true
    if (notifyError) ElMessage.error(getErrorMessage(error, '标准文档列表加载失败'))
    return false
  }
}

async function submitUpload() {
  if (uploading.value || !selectedFile.value) return
  uploading.value = true
  try {
    try {
      await uploadStandardDocument(selectedFile.value, uploadTitle.value.trim() || undefined)
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '标准文档上传失败'))
      return
    }
    ElMessage.success('标准文档上传成功')
    selectedFile.value = null
    uploadTitle.value = ''
    uploadRef.value?.clearFiles()
    await refreshAfterMutation([() => loadStandardDocuments(false)])
  } finally {
    uploading.value = false
  }
}

async function confirmDeleteDocument(document: StandardDocument) {
  if (documentDeletingId.value !== null) return
  documentDeletingId.value = document.id
  try {
    try {
      await ElMessageBox.confirm('删除后源文件将被移除，且无法恢复。', '删除标准文档', {
        type: 'warning',
        confirmButtonText: '删除',
        cancelButtonText: '取消',
      })
    } catch (error: any) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '删除确认失败'))
      return
    }
    try {
      await deleteStandardDocument(document.id)
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '标准文档删除失败'))
      return
    }
    ElMessage.success('标准文档已删除')
    await refreshAfterMutation([() => loadStandardDocuments(false)])
  } finally {
    documentDeletingId.value = null
  }
}

async function submitStandard() {
  if (standardCreating.value || !newStandardDiseaseId.value) return
  standardCreating.value = true
  try {
    let created: Standard
    try {
      created = await createStandard({ disease_id: newStandardDiseaseId.value })
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '标准集合创建失败'))
      return
    }
    standardDialogVisible.value = false
    newStandardDiseaseId.value = null
    selectedStandard.value = created
    versions.value = []
    selectedVersionId.value = null
    clearVersionWorkspace()
    ElMessage.success('标准集合已创建')
    await refreshAfterMutation([
      () => loadStandards(false),
      () => loadVersions(created.id),
    ])
  } finally {
    standardCreating.value = false
  }
}

async function loadVersions(standardId: number) {
  const requestSequence = ++versionsRequestSequence
  latestVersionsRequestByStandard.set(standardId, requestSequence)
  try {
    const loadedVersions = await listVersions(standardId)
    if (latestVersionsRequestByStandard.get(standardId) !== requestSequence || selectedStandard.value?.id !== standardId) return
    versions.value = loadedVersions
    if (selectedVersionId.value && versions.value.some(version => version.id === selectedVersionId.value)) return
    selectedVersionId.value = null
    clearVersionWorkspace()
  } catch (error) {
    if (latestVersionsRequestByStandard.get(standardId) !== requestSequence || selectedStandard.value?.id !== standardId) return
    throw error
  }
}

async function selectStandard(item: Standard) {
  const standardChanged = selectedStandard.value?.id !== item.id
  selectedStandard.value = item
  if (standardChanged) {
    versions.value = []
    selectedVersionId.value = null
    clearVersionWorkspace()
  }
  try {
    await loadVersions(item.id)
  } catch (error: any) {
    if (selectedStandard.value?.id !== item.id) return
    versions.value = []
    ElMessage.error(getErrorMessage(error, '标准版本加载失败'))
  }
}

async function openVersionDialog() {
  if (!selectedStandard.value) return
  await loadStandardDocuments()
  versionDialogVisible.value = true
}

async function submitVersion() {
  if (versionCreating.value || !selectedStandard.value || !newVersionDocumentId.value) return
  const standardId = selectedStandard.value.id
  versionCreating.value = true
  try {
    let created: StandardVersion
    try {
      created = await createVersion(standardId, {
        standard_document_id: newVersionDocumentId.value,
        version_label: newVersionLabel.value.trim(),
      })
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '标准版本创建失败'))
      if (error?.response?.status === 409) await loadStandardDocuments(false)
      return
    }
    versionDialogVisible.value = false
    newVersionDocumentId.value = null
    newVersionLabel.value = ''
    ElMessage.success('草稿版本已创建，请手动解析')
    const refreshed = await refreshAfterMutation([
      () => loadStandardDocuments(false),
      () => loadVersions(standardId),
    ])
    if (!refreshed || selectedStandard.value?.id !== standardId) return
    selectedVersionId.value = created.id
    await refreshAfterMutation([() => loadVersionData(false)])
  } finally {
    versionCreating.value = false
  }
}

async function loadVersionData(notifyError = true) {
  const requestSequence = ++versionDataRequestSequence
  clearVersionWorkspace()
  if (!selectedVersionId.value) {
    versionDataLoading.value = false
    return true
  }
  const id = selectedVersionId.value
  versionDataLoading.value = true
  try {
    const [loadedSegments, loadedRules, loadedValidation] = await Promise.all([listSegments(id), listRules(id), validateVersion(id)])
    if (requestSequence !== versionDataRequestSequence || selectedVersionId.value !== id) return true
    segments.value = loadedSegments
    rules.value = loadedRules
    validation.value = loadedValidation
    workspaceLoadedVersionId.value = id
    return true
  } catch (error: any) {
    if (requestSequence !== versionDataRequestSequence || selectedVersionId.value !== id) return true
    clearVersionWorkspace()
    if (notifyError) ElMessage.error(getErrorMessage(error, '版本数据加载失败'))
    return false
  } finally {
    if (requestSequence === versionDataRequestSequence) versionDataLoading.value = false
  }
}

async function runAction(action: (id: number) => Promise<unknown>, message: string) {
  if (lifecyclePending.value) return
  if (!selectedVersionId.value || !selectedStandard.value) return
  const versionId = selectedVersionId.value
  const standardId = selectedStandard.value.id
  lifecyclePending.value = true
  try {
    try {
      await action(versionId)
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '操作失败'))
      return
    }
    ElMessage.success(message)
    const refreshed = await refreshAfterMutation([
      () => loadVersions(standardId),
      () => loadStandardDocuments(false),
    ])
    if (refreshed && selectedStandard.value?.id === standardId && selectedVersionId.value === versionId) {
      await refreshAfterMutation([() => loadVersionData(false)])
    }
  } finally {
    lifecyclePending.value = false
  }
}

async function confirmDeleteVersion() {
  if (lifecyclePending.value) return
  if (!selectedVersion.value || !selectedStandard.value) return
  const targetVersionId = selectedVersion.value.id
  const targetStandardId = selectedStandard.value.id
  lifecyclePending.value = true
  try {
    try {
      await ElMessageBox.confirm(
        '删除后解析片段、候选和规则将一并删除，标准文档会恢复为可用。',
        '删除标准版本',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch (error: any) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(getErrorMessage(error, '删除确认失败'))
      return
    }
    try {
      await deleteVersion(targetVersionId)
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '标准版本删除失败'))
      return
    }
    ElMessage.success('标准版本已删除')
    await refreshAfterMutation([
      () => loadStandardDocuments(false),
      () => loadVersions(targetStandardId),
    ])
    if (selectedStandard.value?.id === targetStandardId && selectedVersionId.value === targetVersionId) {
      selectedVersionId.value = null
      clearVersionWorkspace()
    }
  } finally {
    lifecyclePending.value = false
  }
}

function canEditRule(rule: StandardRule) {
  if (rule.version_id !== selectedVersionId.value) return false
  return !lifecyclePending.value
    && !versionDataLoading.value
    && workspaceLoadedVersionId.value === selectedVersionId.value
    && selectedVersion.value?.status !== 'approved'
    && selectedVersion.value?.status !== 'retired'
}

function openRuleEditor(rule: StandardRule) {
  if (rule.version_id !== selectedVersionId.value || !canEditRule(rule)) return
  editorRule.value = rule
  editorUpper.value = rule.upper ?? null
  editorReason.value = ''
  editorVisible.value = true
}

async function saveRule() {
  if (ruleSaving.value || !editorRule.value) return
  if (editorRule.value.version_id !== selectedVersionId.value) return
  if (workspaceLoadedVersionId.value !== selectedVersionId.value || lifecyclePending.value) return
  const ruleId = editorRule.value.id
  ruleSaving.value = true
  try {
    try {
      await patchRule(ruleId, { upper: editorUpper.value }, editorReason.value.trim())
    } catch (error: any) {
      ElMessage.error(getErrorMessage(error, '规则保存失败'))
      return
    }
    editorVisible.value = false
    ElMessage.success('规则已保存')
    await refreshAfterMutation([() => loadVersionData(false)])
  } finally {
    ruleSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    loadStandards(),
    listDiseases().then(items => { diseases.value = items }).catch(error => {
      ElMessage.error(getErrorMessage(error, '疾病列表加载失败'))
    }),
    loadStandardDocuments(),
  ])
})
</script>

<style scoped>
.standard-management { flex: 1; overflow-y: auto; padding: var(--space-6); background: var(--bg-canvas); }
.section-header { margin-bottom: var(--space-4); }
.section-title { display: flex; align-items: center; gap: var(--space-2); color: var(--text-primary); }
.section-title h2 { margin: 0; font-size: var(--text-lg); }
.section-desc { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--text-sm); }
.upload-card { margin-bottom: var(--space-4); }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-4); }
.panel-heading h3 { margin-bottom: 0; }
.upload-hint { margin: var(--space-1) 0 var(--space-3); color: var(--text-secondary); font-size: var(--text-sm); }
.upload-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.upload-title { width: min(280px, 100%); }
.upload-title :deep(.el-input__wrapper) { min-height: 44px; }
.selected-file { max-width: 300px; overflow: hidden; color: var(--text-secondary); font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.document-table-wrap, .rule-table-wrap { overflow-x: auto; }
.document-table { min-width: 760px; margin-top: var(--space-4); }
.document-name, .document-filename, .document-meta, .link-detail { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.document-name { color: var(--text-primary); }
.document-filename, .document-meta, .link-detail { color: var(--text-secondary); font-size: var(--text-xs); }
.document-hash { color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--text-xs); }
.link-detail { max-width: 150px; margin-top: var(--space-1); }
.icon-action { width: 44px; min-height: 44px; padding: 0; }
.document-list-empty { margin-top: var(--space-4); padding: var(--space-5); color: var(--text-secondary); text-align: center; border-top: 1px solid var(--border-light); }
.workbench, .content-grid { display: grid; grid-template-columns: minmax(240px, .8fr) minmax(0, 2fr); gap: var(--space-4); margin-bottom: var(--space-4); }
.content-grid { grid-template-columns: minmax(260px, 1fr) minmax(0, 2fr); }
.panel-card { padding: var(--space-4); background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); box-shadow: var(--shadow-sm); }
.panel-card h3 { margin: 0 0 var(--space-3); color: var(--text-primary); font-size: var(--text-md); }
.collection-heading, .version-heading { align-items: center; flex-wrap: wrap; margin-bottom: var(--space-3); }
.list-button { display: block; width: 100%; min-height: 44px; overflow: hidden; text-align: left; text-overflow: ellipsis; white-space: nowrap; }
.list-button.active { color: var(--color-primary); background: var(--color-primary-light); }
.version-select { width: min(360px, 100%); }
.version-select :deep(.el-select__wrapper) { min-height: 44px; }
.action-row { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: var(--space-3) 0; }
.upload-row :deep(.el-button), .collection-heading :deep(.el-button), .version-heading :deep(.el-button), .action-row :deep(.el-button) { min-height: 44px; }
.segment-item { padding: var(--space-3); color: var(--text-secondary); font-size: var(--text-sm); line-height: 1.5; border-bottom: 1px solid var(--border-light); overflow-wrap: anywhere; }
.rule-table-wrap :deep(.el-table) { min-width: 620px; }
.rule-table-wrap :deep(.el-button) { min-width: 44px; min-height: 44px; }
.dialog-control { width: 100%; }
.standard-management :deep(.el-dialog__footer .el-button),
.standard-management :deep(.el-dialog .el-input__wrapper),
.standard-management :deep(.el-dialog .el-select__wrapper),
.standard-management :deep(.el-dialog .el-input-number) { min-height: 44px; }
.form-hint { margin: var(--space-2) 0 0; color: var(--text-secondary); font-size: var(--text-sm); }
@media (max-width: 900px) {
  .standard-management { padding: var(--space-4); }
  .workbench, .content-grid { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .upload-row, .upload-row > *, .upload-title { width: 100%; }
  .selected-file { max-width: 100%; }
  .panel-heading { align-items: flex-start; flex-direction: column; }
  .action-row :deep(.el-button) { flex: 1 1 calc(50% - var(--space-2)); margin-left: 0; }
}
</style>
