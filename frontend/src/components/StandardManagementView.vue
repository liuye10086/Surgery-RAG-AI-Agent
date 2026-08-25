<template>
  <div class="standard-management">
    <div class="section-header">
      <div class="section-title"><el-icon :size="18"><Collection /></el-icon><h2>标准管理</h2></div>
      <p class="section-desc">管理员维护 DOCX 标准、审核规则并发布当前版本；evidence-only 内容只作为证据展示。</p>
    </div>

    <section class="panel-card upload-card">
      <div class="panel-heading"><div><h3>上传标准 DOCX</h3><p class="upload-hint">上传文件默认仅操作者可见，刷新页面后仍会保留在下方列表。</p></div><el-tag type="info" effect="plain">{{ standardDocuments.length }} 个文档</el-tag></div>
      <div class="upload-row">
        <el-input v-model="uploadTitle" placeholder="文档标题（可选）" class="upload-title" />
        <el-upload ref="uploadRef" :auto-upload="false" :show-file-list="false" accept=".docx" :on-change="handleFileChange"><el-button>选择 DOCX</el-button></el-upload>
        <span v-if="selectedFile" class="selected-file" :title="selectedFile.name">{{ selectedFile.name }}</span>
        <el-button type="primary" :loading="uploading" :disabled="!selectedFile" @click="submitUpload">上传标准</el-button>
      </div>
      <el-table v-if="standardDocuments.length" :data="standardDocuments" class="document-table" size="small">
        <el-table-column label="ID" prop="id" width="70" />
        <el-table-column label="文档"><template #default="{ row: document }"><span class="document-name" :title="document.title || document.filename">{{ document.title || document.filename }}</span></template></el-table-column>
        <el-table-column label="文件名" prop="filename" min-width="220" />
        <el-table-column label="状态" width="110"><template #default="{ row: document }"><el-tag size="small" effect="plain">{{ document.status }}</el-tag></template></el-table-column>
        <el-table-column label="访问范围" width="120"><template #default="{ row: document }">{{ document.access_scope === 'operator' ? '仅操作者' : document.access_scope }}</template></el-table-column>
      </el-table>
      <div v-else class="document-list-empty">暂无已上传的 DOCX 标准文档</div>
    </section>

    <div class="workbench">
      <section class="panel-card">
        <h3>标准集合</h3>
        <el-button v-for="item in standards" :key="item.id" class="list-button" :class="{ active: selectedStandard?.id === item.id }" text @click="selectStandard(item)">{{ item.name }}</el-button>
        <el-empty v-if="!standards.length" description="暂无标准集合" />
      </section>
      <section class="panel-card">
        <h3>版本审核</h3>
        <el-select v-model="selectedVersionId" placeholder="选择版本" clearable @change="loadVersionData"><el-option v-for="version in versions" :key="version.id" :label="`${version.version_label} · ${version.status}`" :value="version.id" /></el-select>
        <div class="action-row">
          <el-button size="small" :disabled="!selectedVersion || selectedVersion.status !== 'draft'" @click="runAction(parseVersion, '解析完成')">解析</el-button>
          <el-button size="small" :disabled="!selectedVersion || selectedVersion.status !== 'draft'" @click="runAction(submitReview, '已提交审核')">提交审核</el-button>
          <el-button size="small" type="primary" :disabled="!selectedVersion || selectedVersion.status !== 'review'" @click="runAction(approveVersion, '已批准发布')">批准发布</el-button>
          <el-button size="small" type="warning" :disabled="!selectedVersion || selectedVersion.status !== 'approved'" @click="runAction(retireVersion, '已退役')">退役</el-button>
        </div>
        <el-alert v-if="validation.errors.length" type="error" :title="`存在 ${validation.errors.length} 个阻止发布的问题`" show-icon />
        <el-alert v-else-if="selectedVersion" type="success" :title="`可投影规则 ${validation.projection_count} 条`" show-icon />
      </section>
    </div>

    <div class="content-grid">
      <section class="panel-card"><h3>源片段</h3><el-scrollbar height="360px"><div v-for="segment in segments" :key="segment.id" class="segment-item">{{ segment.raw_text }}</div></el-scrollbar></section>
      <section class="panel-card">
        <h3>规则审核</h3>
        <el-table :data="rules" size="small"><el-table-column prop="id" label="ID" width="60" /><el-table-column prop="rule_type" label="类型" /><el-table-column prop="machine_actionability" label="状态" /><el-table-column prop="interpretation" label="解释" /><el-table-column label="操作" width="90"><template #default="{ row }"><el-button text size="small" :disabled="selectedVersion?.status === 'approved' || selectedVersion?.status === 'retired'" @click="openRuleEditor(row)">编辑</el-button></template></el-table-column></el-table>
        <el-empty v-if="!rules.length" description="暂无规则" />
      </section>
    </div>

    <el-dialog v-model="editorVisible" title="编辑规则" width="440px"><el-form label-width="90px"><el-form-item label="上限"><el-input-number v-model="editorUpper" :controls="false" /></el-form-item><el-form-item label="修改原因"><el-input v-model="editorReason" type="textarea" placeholder="请输入修改原因" /></el-form-item></el-form><template #footer><el-button @click="editorVisible = false">取消</el-button><el-button type="primary" :disabled="!editorReason.trim()" @click="saveRule">保存</el-button></template></el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, type UploadFile, type UploadInstance } from 'element-plus'
import { Collection } from '@element-plus/icons-vue'
import { listDocuments, uploadDocument, type DocumentOut } from '@/api/admin'
import { approveVersion, listRules, listSegments, listStandards, listVersions, parseVersion, patchRule, retireVersion, submitReview, validateVersion, type Standard, type StandardRule, type StandardSegment, type StandardVersion, type ValidationReport } from '@/api/adminStandards'

const standards = ref<Standard[]>([])
const selectedStandard = ref<Standard | null>(null)
const versions = ref<StandardVersion[]>([])
const selectedVersionId = ref<number | null>(null)
const segments = ref<StandardSegment[]>([])
const rules = ref<StandardRule[]>([])
const validation = ref<ValidationReport>({ errors: [], warnings: [], infos: [], projection_count: 0 })
const selectedVersion = computed(() => versions.value.find(item => item.id === selectedVersionId.value) || null)
const uploadRef = ref<UploadInstance>()
const selectedFile = ref<File | null>(null)
const uploadTitle = ref('')
const uploading = ref(false)
const standardDocuments = ref<DocumentOut[]>([])
const editorVisible = ref(false)
const editorRule = ref<StandardRule | null>(null)
const editorUpper = ref<number | null>(null)
const editorReason = ref('')

function handleFileChange(file: UploadFile) { selectedFile.value = file.raw || null }

async function loadStandardDocuments() {
  try {
    const result = await listDocuments(0, 100)
    standardDocuments.value = result.items.filter(document => document.filename.toLowerCase().endsWith('.docx'))
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '标准文档列表加载失败')
  }
}

async function submitUpload() {
  if (!selectedFile.value) return
  uploading.value = true
  const accessScope = 'operator'
  try {
    await uploadDocument(selectedFile.value, uploadTitle.value.trim() || undefined, undefined, accessScope)
    ElMessage.success('标准文档上传成功')
    selectedFile.value = null
    uploadTitle.value = ''
    uploadRef.value?.clearFiles()
    await loadStandardDocuments()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '标准文档上传失败')
  } finally {
    uploading.value = false
  }
}

async function selectStandard(item: Standard) {
  selectedStandard.value = item
  versions.value = await listVersions(item.id).catch(() => [])
  selectedVersionId.value = null
  segments.value = []
  rules.value = []
}

async function loadVersionData() {
  if (!selectedVersionId.value) return
  const id = selectedVersionId.value
  ;[segments.value, rules.value, validation.value] = await Promise.all([listSegments(id), listRules(id), validateVersion(id)])
}

async function runAction(action: (id: number) => Promise<unknown>, message: string) {
  if (!selectedVersionId.value) return
  try {
    await action(selectedVersionId.value)
    ElMessage.success(message)
    if (selectedStandard.value) await selectStandard(selectedStandard.value)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '操作失败')
  }
}

function openRuleEditor(rule: StandardRule) { editorRule.value = rule; editorUpper.value = rule.upper ?? null; editorReason.value = ''; editorVisible.value = true }

async function saveRule() {
  if (!editorRule.value) return
  try {
    await patchRule(editorRule.value.id, { upper: editorUpper.value }, editorReason.value.trim())
    editorVisible.value = false
    ElMessage.success('规则已保存')
    await loadVersionData()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '规则保存失败')
  }
}

onMounted(async () => {
  await Promise.all([listStandards().then(items => { standards.value = items }).catch(() => []), loadStandardDocuments()])
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
.upload-hint { margin: calc(var(--space-1) * -1) 0 var(--space-3); color: var(--text-secondary); font-size: var(--text-sm); }
.upload-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.upload-title { width: 280px; }
.selected-file { max-width: 300px; overflow: hidden; color: var(--text-secondary); font-size: var(--text-sm); text-overflow: ellipsis; white-space: nowrap; }
.document-table { margin-top: var(--space-4); }
.document-name { display: block; overflow: hidden; color: var(--text-primary); text-overflow: ellipsis; white-space: nowrap; }
.document-list-empty { margin-top: var(--space-4); padding: var(--space-5); color: var(--text-secondary); text-align: center; border-top: 1px solid var(--border-light); }
.workbench, .content-grid { display: grid; grid-template-columns: minmax(220px, .8fr) minmax(0, 2fr); gap: var(--space-4); margin-bottom: var(--space-4); }
.content-grid { grid-template-columns: minmax(260px, 1fr) minmax(0, 2fr); }
.panel-card { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); padding: var(--space-4); box-shadow: var(--shadow-sm); }
.panel-card h3 { margin: 0 0 var(--space-3); color: var(--text-primary); font-size: var(--text-md); }
.list-button { display: block; width: 100%; min-height: 44px; text-align: left; }
.list-button.active { color: var(--color-primary); background: var(--color-primary-light); }
.action-row { display: flex; flex-wrap: wrap; gap: var(--space-2); margin: var(--space-3) 0; }
.segment-item { padding: var(--space-3); color: var(--text-secondary); font-size: var(--text-sm); line-height: 1.5; border-bottom: 1px solid var(--border-light); }
@media (max-width: 900px) { .workbench, .content-grid { grid-template-columns: 1fr; } }
</style>
