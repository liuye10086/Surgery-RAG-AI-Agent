<template>
  <div class="case-manage-view">
    <!-- 疾病管理区 -->
    <div class="manage-section">
      <h4>疾病字典</h4>
      <div class="disease-add">
        <el-input v-model="newDiseaseName" placeholder="新疾病名称" style="width: 220px" />
        <el-button type="primary" size="small" :disabled="!newDiseaseName.trim()" @click="handleAddDisease">新增</el-button>
      </div>
      <el-table :data="operatorStore.diseases" size="small">
        <el-table-column prop="name" label="疾病" />
        <el-table-column prop="case_count" label="病例数" width="90" />
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button :icon="Edit" text size="small" @click="openDiseaseEdit(row)" />
            <el-button :icon="Delete" text size="small" @click="handleDeleteDisease(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 病例管理区 -->
    <div class="manage-section">
      <h4>病例库（{{ operatorStore.cases.length }}）</h4>
      <div class="case-toolbar">
        <el-select
          v-model="caseFilterDiseaseId"
          placeholder="按疾病筛选"
          clearable
          filterable
          style="width: 240px"
          @change="loadCases"
        >
          <el-option v-for="d in operatorStore.diseases" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-button type="primary" size="small" @click="openCaseForm()">新增病例</el-button>
      </div>
      <el-table :data="operatorStore.cases" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="patient_label" label="患者标签" width="120" />
        <el-table-column label="指标">
          <template #default="{ row }">
            {{ (row.indicators || []).map((i: any) => `${i.name}=${i.value}${i.unit}`).join('; ').slice(0, 60) }}
          </template>
        </el-table-column>
        <el-table-column label="确诊" width="80">
          <template #default="{ row }">{{ row.confirmed ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140">
          <template #default="{ row }">
            <el-button :icon="Edit" text size="small" @click="openCaseForm(row)" />
            <el-button :icon="Delete" text size="small" @click="handleDeleteCase(row)" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 参考范围同步区 -->
    <div class="manage-section">
      <h4>正常体征参考标准</h4>
      <div class="sync-toolbar">
        <el-select v-model="syncDocumentId" placeholder="选择参考标准文档" filterable style="width: 280px">
          <el-option
            v-for="doc in operatorDocuments"
            :key="doc.id"
            :label="doc.title || doc.filename"
            :value="doc.id"
            :disabled="!doc.sync_ready"
          >
            <span>{{ doc.title || doc.filename }}</span>
            <span v-if="!doc.sync_ready" class="sync-hint">（需先分块/向量化）</span>
          </el-option>
        </el-select>
        <el-button
          type="primary"
          size="small"
          :disabled="!syncDocumentId"
          :loading="syncLoading"
          @click="handleSyncReference"
        >
          解析为参考范围
        </el-button>
        <el-button size="small" :loading="rangesLoading" @click="loadReferenceRanges">查看已解析条目</el-button>
      </div>
      <div v-if="referenceRanges.length" class="range-list">
        <div v-for="r in referenceRanges" :key="r.id" class="range-item">
          <span>{{ r.indicator_name }}（{{ r.name_cn || '' }}）：{{ formatRange(r) }}</span>
        </div>
      </div>
      <div v-else-if="rangesLoaded && !rangesLoading" class="range-empty">暂无已解析的参考范围</div>
    </div>

    <!-- 疾病编辑弹窗 -->
    <el-dialog v-model="diseaseEditVisible" title="编辑疾病" width="420px">
      <el-form label-width="70px">
        <el-form-item label="名称">
          <el-input v-model="diseaseForm.name" maxlength="200" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="diseaseForm.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="diseaseEditVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!diseaseForm.name.trim()" @click="saveDisease">保存</el-button>
      </template>
    </el-dialog>

    <!-- 病例新增/编辑弹窗 -->
    <el-dialog v-model="caseFormVisible" :title="editingCaseId ? '编辑病例' : '新增病例'" width="560px">
      <el-form label-width="80px">
        <el-form-item label="疾病">
          <el-select v-model="caseForm.disease_id" placeholder="选择疾病" filterable style="width: 100%">
            <el-option v-for="d in operatorStore.diseases" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="患者标签">
          <el-input v-model="caseForm.patient_label" placeholder="如：病例 A / 门诊样本 7" maxlength="100" />
        </el-form-item>
        <el-form-item label="指标">
          <div class="case-indicator-form">
            <div v-for="(row, idx) in caseIndicatorRows" :key="idx" class="case-indicator-row">
              <el-input v-model="row.name" placeholder="指标名" style="width: 130px" />
              <el-input v-model.number="row.value" type="number" placeholder="数值" style="width: 110px" />
              <el-input v-model="row.unit" placeholder="单位" style="width: 90px" />
              <el-button :icon="Delete" text @click="removeCaseIndicator(idx)" />
            </div>
            <el-button size="small" :icon="Plus" text @click="addCaseIndicator">添加指标</el-button>
          </div>
        </el-form-item>
        <el-form-item label="确诊">
          <el-switch v-model="caseForm.confirmed" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="caseFormVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!canSaveCase" @click="saveCase">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Delete, Plus } from '@element-plus/icons-vue'
import { useOperatorStore } from '@/stores/operator'
import {
  createDisease,
  updateDisease,
  deleteDisease,
  createCase,
  updateCase,
  deleteCase,
  syncReferenceRanges,
  listReferenceRanges,
  listOperatorDocuments,
  type CaseRecord,
  type Disease,
  type IndicatorInput,
  type OperatorDocument,
  type ReferenceRange,
} from '@/api/operator'
import { formatRange } from '@/utils/rangeFormat'

const operatorStore = useOperatorStore()

// ===== 疾病 =====
const newDiseaseName = ref('')
const diseaseEditVisible = ref(false)
const editingDiseaseId = ref<number | null>(null)
const diseaseForm = reactive<{ name: string; description: string }>({ name: '', description: '' })

// ===== 病例 =====
const caseFilterDiseaseId = ref<number | null>(null)
const caseFormVisible = ref(false)
const editingCaseId = ref<number | null>(null)
const caseForm = reactive<{
  disease_id: number | null
  patient_label: string
  confirmed: boolean
}>({ disease_id: null, patient_label: '', confirmed: true })
const caseIndicatorRows = reactive<IndicatorInput[]>([])

const canSaveCase = computed(() => {
  if (!caseForm.disease_id) return false
  return caseIndicatorRows.some(
    (r) => r.name.trim() && r.value !== null && r.value !== undefined && r.unit.trim(),
  )
})

// ===== 参考范围 =====
const syncDocumentId = ref<number | null>(null)
const syncLoading = ref(false)
const rangesLoading = ref(false)
const rangesLoaded = ref(false)
const operatorDocuments = ref<OperatorDocument[]>([])
const referenceRanges = ref<ReferenceRange[]>([])

async function handleAddDisease() {
  const name = newDiseaseName.value.trim()
  if (!name) return
  try {
    await createDisease({ name })
    ElMessage.success('疾病已新增')
    newDiseaseName.value = ''
    await operatorStore.fetchDiseases()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '新增疾病失败')
  }
}

function openDiseaseEdit(row: Disease) {
  editingDiseaseId.value = row.id
  diseaseForm.name = row.name
  diseaseForm.description = row.description || ''
  diseaseEditVisible.value = true
}

async function saveDisease() {
  if (editingDiseaseId.value === null) return
  try {
    await updateDisease(editingDiseaseId.value, {
      name: diseaseForm.name.trim(),
      description: diseaseForm.description || undefined,
    })
    ElMessage.success('疾病已更新')
    diseaseEditVisible.value = false
    await operatorStore.fetchDiseases()
    await loadCases()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '更新疾病失败')
  }
}

async function handleDeleteDisease(row: Disease) {
  try {
    await ElMessageBox.confirm(`确定删除疾病「${row.name}」？`, '确认删除', {
      type: 'warning',
    })
    await deleteDisease(row.id)
    ElMessage.success('疾病已删除')
    if (caseFilterDiseaseId.value === row.id) {
      caseFilterDiseaseId.value = null
    }
    await operatorStore.fetchDiseases()
    await loadCases()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.detail || '删除疾病失败')
    }
  }
}

async function loadCases() {
  await operatorStore.fetchCases(caseFilterDiseaseId.value || undefined)
}

function openCaseForm(row?: CaseRecord) {
  if (row) {
    editingCaseId.value = row.id
    caseForm.disease_id = row.disease_id
    caseForm.patient_label = row.patient_label || ''
    caseForm.confirmed = row.confirmed
    caseIndicatorRows.splice(0, caseIndicatorRows.length, ...(row.indicators || []).map((i: any) => ({
      name: i.name || '',
      value: i.value ?? (null as unknown as number),
      unit: i.unit || '',
    })))
    if (!caseIndicatorRows.length) {
      caseIndicatorRows.push({ name: '', value: null as unknown as number, unit: '' })
    }
  } else {
    editingCaseId.value = null
    caseForm.disease_id = null
    caseForm.patient_label = ''
    caseForm.confirmed = true
    caseIndicatorRows.splice(0, caseIndicatorRows.length, { name: '', value: null as unknown as number, unit: '' })
  }
  caseFormVisible.value = true
}

function addCaseIndicator() {
  caseIndicatorRows.push({ name: '', value: null as unknown as number, unit: '' })
}

function removeCaseIndicator(idx: number) {
  if (caseIndicatorRows.length <= 1) {
    caseIndicatorRows.splice(0, 1, { name: '', value: null as unknown as number, unit: '' })
    return
  }
  caseIndicatorRows.splice(idx, 1)
}

async function saveCase() {
  const validRows = caseIndicatorRows.filter(
    (r) => r.name.trim() && r.value !== null && r.value !== undefined && r.unit.trim(),
  )
  if (!caseForm.disease_id || !validRows.length) return
  const payload = {
    disease_id: caseForm.disease_id,
    patient_label: caseForm.patient_label.trim() || null,
    indicators: validRows.map((r) => ({ name: r.name.trim(), value: r.value, unit: r.unit.trim() })),
    confirmed: caseForm.confirmed,
    metadata: {},
  }
  try {
    if (editingCaseId.value === null) {
      await createCase(payload)
      ElMessage.success('病例已新增')
    } else {
      await updateCase(editingCaseId.value, payload)
      ElMessage.success('病例已更新')
    }
    caseFormVisible.value = false
    await loadCases()
    // case_count 是实时聚合字段，新增/编辑（含迁移疾病、确诊状态变化）后刷新疾病字典
    await operatorStore.fetchDiseases()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存病例失败')
  }
}

async function handleDeleteCase(row: CaseRecord) {
  try {
    await ElMessageBox.confirm(`确定删除病例 #${row.id}？`, '确认删除', {
      type: 'warning',
    })
    await deleteCase(row.id)
    ElMessage.success('病例已删除')
    await loadCases()
    await operatorStore.fetchDiseases()
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error(e?.response?.data?.detail || '删除病例失败')
    }
  }
}

async function handleSyncReference() {
  if (!syncDocumentId.value) return
  syncLoading.value = true
  try {
    const result = await syncReferenceRanges(syncDocumentId.value)
    ElMessage.success(`解析完成：新增 ${result.inserted} 条，替换 ${result.dropped} 条`)
    await loadReferenceRanges()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '解析参考范围失败')
  } finally {
    syncLoading.value = false
  }
}

async function loadReferenceRanges() {
  rangesLoading.value = true
  try {
    referenceRanges.value = await listReferenceRanges()
    rangesLoaded.value = true
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '加载参考范围失败')
  } finally {
    rangesLoading.value = false
  }
}

onMounted(async () => {
  await operatorStore.fetchDiseases()
  await loadCases()
  try {
    operatorDocuments.value = await listOperatorDocuments()
  } catch {
    // 文档列表加载非关键
  }
})
</script>

<style scoped>
.case-manage-view {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-6);
}

.manage-section {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: var(--space-5);
  margin-bottom: var(--space-6);
}

.manage-section h4 {
  margin: 0 0 var(--space-4);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-secondary);
}

.disease-add,
.case-toolbar,
.sync-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
}

.case-indicator-form {
  width: 100%;
}

.case-indicator-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.sync-hint {
  font-size: var(--text-xs);
  color: var(--text-disabled);
  margin-left: var(--space-1);
}

.range-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  max-height: 320px;
  overflow-y: auto;
}

.range-item {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-primary);
  background: var(--bg-canvas);
  border-radius: var(--radius-item);
}

.range-empty {
  padding: var(--space-4) 0;
  font-size: var(--text-xs);
  color: var(--text-disabled);
  text-align: center;
}
</style>
