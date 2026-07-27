<template>
  <div class="settings-view">
    <div class="settings-container">
      <!-- 顶部导航 -->
      <div class="settings-top">
        <el-button text @click="$router.back()">
          <el-icon :size="16"><ArrowLeft /></el-icon>
          <span>返回</span>
        </el-button>
        <h1>账户设置</h1>
      </div>

      <!-- 数据导出卡片 -->
      <div class="settings-card">
        <div class="card-header">
          <el-icon :size="20"><Download /></el-icon>
          <div>
            <h3>导出个人数据</h3>
            <p>下载您的账户信息、会话记录、聊天消息和审计日志的完整副本（个保法第 45 条）。</p>
          </div>
        </div>
        <el-button type="primary" :loading="exporting" @click="handleExport">
          导出我的数据
        </el-button>
      </div>

      <!-- 账户删除卡片 -->
      <div class="settings-card danger-card">
        <div class="card-header">
          <el-icon :size="20"><WarningFilled /></el-icon>
          <div>
            <h3>删除账户</h3>
            <p>删除后您的账户、会话和消息将被永久清除。审计日志将匿名保留。知识库文档不受影响。此操作不可撤销。</p>
          </div>
        </div>
        <el-button type="danger" @click="showDeleteDialog = true">
          删除账户
        </el-button>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <el-dialog v-model="showDeleteDialog" title="确认删除账户" width="440px" :close-on-click-modal="false">
      <div class="delete-confirm">
        <el-icon :size="40" color="var(--color-danger)"><WarningFilled /></el-icon>
        <p>此操作将永久删除您的账户及所有关联数据，不可恢复。</p>
        <el-input
          v-model="deletePassword"
          type="password"
          placeholder="请输入当前密码以确认"
          show-password
          @keydown.enter="handleDelete"
        />
      </div>
      <template #footer>
        <el-button @click="showDeleteDialog = false">取消</el-button>
        <el-button type="danger" :loading="deleting" :disabled="!deletePassword" @click="handleDelete">
          确认删除
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download, WarningFilled } from '@element-plus/icons-vue'
import { exportData, deleteAccount } from '@/api/auth'

const exporting = ref(false)
const deleting = ref(false)
const showDeleteDialog = ref(false)
const deletePassword = ref('')

async function handleExport() {
  exporting.value = true
  try {
    const data = await exportData()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `data_export_${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('数据导出成功')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '导出失败')
  } finally {
    exporting.value = false
  }
}

async function handleDelete() {
  if (!deletePassword.value) return
  deleting.value = true
  try {
    await deleteAccount(deletePassword.value)
    ElMessage.success('账户已删除')
    localStorage.removeItem('token')
    localStorage.removeItem('surgery_rag_danger_state')
    window.location.href = '/login'
  } catch (e: any) {
    if (e?.response?.status === 401) {
      ElMessage.error('密码错误')
    } else {
      ElMessage.error(e?.response?.data?.detail || '删除失败')
    }
  } finally {
    deleting.value = false
    showDeleteDialog.value = false
  }
}
</script>

<style scoped>
.settings-view {
  height: 100vh;
  background: var(--bg-canvas);
  overflow-y: auto;
}

.settings-container {
  max-width: 640px;
  margin: 0 auto;
  padding: var(--space-8) var(--space-6);
}

.settings-top {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-8);
}

.settings-top h1 {
  margin: 0;
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--text-primary);
}

.settings-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: var(--space-6);
  margin-bottom: var(--space-4);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-6);
}

.card-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  flex: 1;
  min-width: 0;
}

.card-header h3 {
  margin: 0 0 var(--space-1);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.card-header p {
  margin: 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  line-height: 1.5;
}

.card-header > .el-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
  margin-top: 2px;
}

.danger-card {
  border-color: hsl(0, 40%, 88%);
}

.delete-confirm {
  text-align: center;
  padding: var(--space-4) 0;
}

.delete-confirm p {
  margin: var(--space-4) 0;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
</style>
