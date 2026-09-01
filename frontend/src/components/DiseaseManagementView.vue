<template>
  <section class="disease-management" aria-labelledby="disease-management-title">
    <header class="section-header">
      <div>
        <div class="section-title">
          <el-icon :size="20"><FirstAidKit /></el-icon>
          <h2 id="disease-management-title">疾病管理</h2>
        </div>
        <p class="section-desc">维护全局疾病字典，并控制哪些疾病可供 AI 操作者使用。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreateDialog">新建疾病</el-button>
    </header>

    <div class="catalog-card">
      <el-table v-loading="loading" :data="diseases" stripe>
        <el-table-column prop="name" label="显示名称" min-width="150" />
        <el-table-column label="固定代码" min-width="150">
          <template #default="{ row }">
            <code class="disease-code">{{ row.code }}</code>
          </template>
        </el-table-column>
        <el-table-column label="操作者状态" width="120" align="center">
          <template #default="{ row }">
            <el-tag :type="row.operator_enabled ? 'success' : 'info'">
              {{ row.operator_enabled ? '已启用' : '已停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="病例引用" width="100" align="center">
          <template #default="{ row }">{{ row.usage_counts.operator_cases }}</template>
        </el-table-column>
        <el-table-column label="参考病例" width="100" align="center">
          <template #default="{ row }">{{ row.usage_counts.case_records }}</template>
        </el-table-column>
        <el-table-column label="AI 报告" width="90" align="center">
          <template #default="{ row }">{{ row.usage_counts.ai_reports }}</template>
        </el-table-column>
        <el-table-column label="参考标准" width="100" align="center">
          <template #default="{ row }">{{ row.usage_counts.reference_standards }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="300" fixed="right" align="center">
          <template #default="{ row }">
            <div class="action-row">
              <el-button @click="openEditDialog(row)">编辑</el-button>
              <el-button
                :type="row.operator_enabled ? 'warning' : 'success'"
                :loading="updatingId === row.id"
                :disabled="updatingId !== null || deletingId !== null"
                @click="toggleEnabled(row)"
              >
                {{ row.operator_enabled ? '停用' : '启用' }}
              </el-button>
              <el-tooltip
                :disabled="row.can_delete"
                content="该疾病已被业务数据引用，只能停用"
                placement="top"
              >
                <span class="delete-action-wrap">
                  <el-button
                    type="danger"
                    plain
                    :loading="deletingId === row.id"
                    :disabled="!row.can_delete || deletingId !== null || updatingId !== null"
                    @click="confirmDelete(row)"
                  >
                    删除
                  </el-button>
                </span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && diseases.length === 0" description="暂无疾病记录" />
    </div>

    <el-dialog v-model="createVisible" title="新建疾病" width="min(520px, calc(100vw - 32px))">
      <el-form label-position="top" @submit.prevent="submitCreate">
        <el-form-item label="显示名称" required>
          <el-input v-model="createForm.name" maxlength="100" placeholder="请输入疾病显示名称" />
        </el-form-item>
        <el-form-item label="固定代码" required>
          <el-input v-model="createForm.code" maxlength="64" placeholder="例如：gastric_cancer" />
          <p class="form-hint">创建后不可修改，仅允许小写英文字母、数字和下划线。</p>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="3" maxlength="1000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="creating" @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑疾病" width="min(520px, calc(100vw - 32px))">
      <el-form label-position="top" @submit.prevent="submitEdit">
        <el-form-item label="固定代码">
          <code class="readonly-code">{{ selectedDisease?.code }}</code>
        </el-form-item>
        <el-form-item label="显示名称" required>
          <el-input v-model="editForm.name" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="3" maxlength="1000" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="editing" @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="editing" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { FirstAidKit, Plus } from '@element-plus/icons-vue'
import {
  createAdminDisease,
  deleteAdminDisease,
  listAdminDiseases,
  updateAdminDisease,
  type AdminDisease,
} from '@/api/adminDiseases'

const diseases = ref<AdminDisease[]>([])
const loading = ref(false)
const creating = ref(false)
const editing = ref(false)
const updatingId = ref<number | null>(null)
const deletingId = ref<number | null>(null)
const createVisible = ref(false)
const editVisible = ref(false)
const selectedDisease = ref<AdminDisease | null>(null)

const createForm = reactive({ code: '', name: '', description: '' })
const editForm = reactive({ name: '', description: '' })

function errorDetail(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.message || fallback
}

async function loadDiseases() {
  loading.value = true
  try {
    diseases.value = await listAdminDiseases()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '疾病列表加载失败'))
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  createForm.code = ''
  createForm.name = ''
  createForm.description = ''
  createVisible.value = true
}

async function submitCreate() {
  if (creating.value) return
  const code = createForm.code.trim()
  const name = createForm.name.trim()
  if (!code || !name) {
    ElMessage.warning('请填写疾病名称和固定代码')
    return
  }
  creating.value = true
  try {
    await createAdminDisease({
      code,
      name,
      description: createForm.description.trim() || null,
    })
    ElMessage.success('疾病创建成功，新疾病默认停用')
    createVisible.value = false
    await loadDiseases()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '疾病创建失败'))
  } finally {
    creating.value = false
  }
}

function openEditDialog(disease: AdminDisease) {
  selectedDisease.value = disease
  editForm.name = disease.name
  editForm.description = disease.description || ''
  editVisible.value = true
}

async function submitEdit() {
  if (editing.value || !selectedDisease.value) return
  const name = editForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写疾病名称')
    return
  }
  editing.value = true
  try {
    await updateAdminDisease(selectedDisease.value.id, {
      name,
      description: editForm.description.trim() || null,
    })
    ElMessage.success('疾病信息已更新')
    editVisible.value = false
    await loadDiseases()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '疾病更新失败'))
  } finally {
    editing.value = false
  }
}

async function toggleEnabled(disease: AdminDisease) {
  if (updatingId.value !== null) return
  const enabling = !disease.operator_enabled
  if (!enabling) {
    try {
      await ElMessageBox.confirm(
        '停用后，该疾病的既有病例将变为只读，不能新增访视或生成新报告。',
        '确认停用疾病',
        { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' },
      )
    } catch (error) {
      if (error === 'cancel' || error === 'close') return
      throw error
    }
  }
  updatingId.value = disease.id
  try {
    await updateAdminDisease(disease.id, { operator_enabled: enabling })
    ElMessage.success(enabling ? '疾病已启用' : '疾病已停用')
    await loadDiseases()
  } catch (error: any) {
    const fallback = enabling ? '该疾病尚未配置预测能力，不能启用' : '疾病停用失败'
    ElMessage.error(errorDetail(error, fallback))
  } finally {
    updatingId.value = null
  }
}

async function confirmDelete(disease: AdminDisease) {
  if (!disease.can_delete || deletingId.value !== null) return
  try {
    await ElMessageBox.confirm(
      `确定永久删除“${disease.name}”吗？此操作无法恢复。`,
      '删除疾病',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    throw error
  }
  deletingId.value = disease.id
  try {
    await deleteAdminDisease(disease.id)
    ElMessage.success('疾病已删除')
    await loadDiseases()
  } catch (error: any) {
    ElMessage.error(errorDetail(error, '疾病删除失败'))
  } finally {
    deletingId.value = null
  }
}

onMounted(loadDiseases)
</script>

<style scoped>
.disease-management {
  min-height: 100%;
  padding: var(--space-6);
  color: var(--text-primary);
  background: var(--bg-canvas);
}

.section-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.section-title { display: flex; align-items: center; gap: var(--space-2); }
.section-title h2 { margin: 0; font-size: var(--text-lg); font-weight: 600; }
.section-desc { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--text-sm); }

.catalog-card {
  overflow: hidden;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-sm);
}

.disease-code,
.readonly-code {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: var(--text-sm);
}

.readonly-code {
  display: block;
  width: 100%;
  padding: var(--space-3);
  color: var(--text-secondary);
  background: var(--bg-input);
  border-radius: var(--radius-input);
}

.action-row { display: flex; align-items: center; justify-content: center; gap: var(--space-2); }
.delete-action-wrap { display: inline-flex; }
.form-hint { margin: var(--space-2) 0 0; color: var(--text-secondary); font-size: var(--text-xs); }

.section-header :deep(.el-button),
.action-row :deep(.el-button),
.disease-management :deep(.el-dialog__footer .el-button),
.disease-management :deep(.el-input__wrapper),
.disease-management :deep(.el-textarea__inner) {
  min-height: 44px;
}

.disease-management :deep(.el-button:focus-visible),
.disease-management :deep(.el-input__wrapper:focus-within) {
  box-shadow: 0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--color-primary);
}

@media (max-width: 900px) {
  .disease-management { padding: var(--space-4); }
  .section-header { flex-direction: column; }
  .catalog-card { overflow-x: auto; }
  .catalog-card :deep(.el-table) { min-width: 1080px; }
}

@media (prefers-reduced-motion: reduce) {
  .disease-management *,
  .disease-management *::before,
  .disease-management *::after { transition: none !important; animation: none !important; }
}
</style>
