<template>
  <div :class="['operator-sidebar', { collapsed }]">
    <div class="sidebar-inner">
      <!-- ====== 展开列 ====== -->
      <div class="expanded-col">
        <!-- 顶部固定：品牌 + 折叠 + 新建分析 -->
        <div class="sidebar-top">
          <div class="top-row">
            <span class="brand-text">
              <el-icon :size="18"><DataAnalysis /></el-icon>
              AI 操作者
            </span>
            <el-button class="fold-btn" :icon="Fold" text @click="$emit('toggle')" title="折叠侧边栏" />
          </div>
          <div class="new-report-row">
            <el-button
              type="primary"
              :icon="Plus"
              @click="$emit('new-analysis')"
              :disabled="generating"
              style="width: 100%; border-radius: 10px"
            >
              新建分析
            </el-button>
          </div>
          <div class="nav-row">
            <div :class="['nav-item', { active: activeView === 'predict' }]" @click="$emit('navigate', 'predict')">
              <el-icon :size="15"><TrendCharts /></el-icon><span>预测分析</span>
            </div>
            <div :class="['nav-item', { active: activeView === 'cases' }]" @click="$emit('navigate', 'cases')">
              <el-icon :size="15"><FolderOpened /></el-icon><span>病例库</span>
            </div>
          </div>
        </div>

        <!-- 中间滚动：报告列表 -->
        <div class="sidebar-mid">
          <div
            v-for="report in reports"
            :key="report.id"
            :class="['report-item', { active: currentId === report.id }]"
            @click="$emit('select', report.id)"
          >
            <div class="report-info">
              <div class="report-time">{{ formatTime(report.created_at) }}</div>
              <div class="report-title">{{ report.title || report.query }}</div>
              <div class="report-meta">
                <el-tag
                  :type="statusTagType(report.status)"
                  size="small"
                  :effect="report.status === 'generating' ? 'dark' : 'plain'"
                >
                  {{ statusLabel(report.status) }}
                </el-tag>
              </div>
            </div>
            <el-popover
              placement="bottom"
              trigger="click"
              :width="100"
              :offset="4"
              :show-arrow="false"
              @click.stop
            >
              <template #reference>
                <el-button
                  class="report-more-btn"
                  :icon="MoreFilled"
                  text
                  size="small"
                  @click.stop
                />
              </template>
              <div class="popover-menu">
                <div class="popover-item danger" @click.stop="$emit('delete', report.id)">
                  <el-icon :size="14"><Delete /></el-icon>
                  <span>删除报告</span>
                </div>
              </div>
            </el-popover>
          </div>
          <div v-if="!reports.length && !loading" class="empty-tip">暂无分析报告</div>
          <div v-if="loading" class="empty-tip">加载中...</div>
        </div>

        <!-- 底部固定：用户信息 -->
        <div class="sidebar-bot">
          <div class="user-info">
            <el-avatar :size="32" :style="{ background: 'var(--color-primary)' }">
              {{ (authStore.user?.username || '?')[0] }}
            </el-avatar>
            <div class="user-name">
              <div class="user-display">{{ authStore.user?.username }}</div>
              <span class="role-tag" :style="{ background: roleTagColor }">{{ roleLabel }}</span>
            </div>
            <el-popover
              placement="top"
              trigger="click"
              :width="140"
              :offset="8"
              :show-arrow="false"
            >
              <template #reference>
                <el-button class="more-btn" :icon="MoreFilled" text size="small" />
              </template>
              <div class="popover-menu">
                <div class="popover-item" @click="handleLogout">
                  <el-icon :size="15"><SwitchButton /></el-icon>
                  <span>退出登录</span>
                </div>
              </div>
            </el-popover>
          </div>
        </div>
      </div>

      <!-- ====== 折叠列 ====== -->
      <div class="collapsed-col">
        <div class="cs-top">
          <el-button class="toggle-btn" :icon="collapsed ? Expand : Fold" text @click="$emit('toggle')" :title="collapsed ? '展开' : '折叠'" />
          <el-button type="primary" :icon="Plus" circle @click="$emit('new-analysis')" :disabled="generating" title="新建分析" />
        </div>
        <div class="cs-mid" />
        <div class="cs-bot">
          <el-popover
            placement="right-end"
            trigger="click"
            :width="140"
            :offset="8"
            :show-arrow="false"
          >
            <template #reference>
              <el-avatar :size="32" :style="{ background: 'var(--color-primary)', cursor: 'pointer' }">
                {{ (authStore.user?.username || '?')[0] }}
              </el-avatar>
            </template>
            <div class="popover-menu">
              <div class="popover-item" @click="handleLogout">
                <el-icon :size="15"><SwitchButton /></el-icon>
                <span>退出登录</span>
              </div>
            </div>
          </el-popover>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Plus, SwitchButton, Fold, Expand, MoreFilled, Delete, DataAnalysis, TrendCharts, FolderOpened } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import type { ReportListItem } from '@/api/operator'

defineProps<{
  reports: ReportListItem[]
  currentId?: number
  collapsed: boolean
  loading: boolean
  generating: boolean
  activeView: 'predict' | 'cases'
}>()

defineEmits<{
  toggle: []
  select: [id: number]
  'new-analysis': []
  delete: [id: number]
  navigate: [view: 'predict' | 'cases']
}>()

const authStore = useAuthStore()

const roleLabel = computed(() => {
  const role = authStore.user?.role
  const map: Record<string, string> = {
    admin: '管理员',
    user: '用户',
    doctor: '医生',
    patient: '患者',
    ai_operator: 'AI 操作者',
  }
  return map[role || ''] || role || '未知'
})

const roleTagColor = computed(() => {
  const role = authStore.user?.role
  const map: Record<string, string> = {
    admin: 'hsl(0, 55%, 55%)',
    doctor: 'hsl(25, 55%, 52%)',
    patient: 'hsl(155, 50%, 40%)',
    ai_operator: 'hsl(200, 65%, 40%)',
  }
  return map[role || ''] || 'hsl(200, 65%, 40%)'
})

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
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

function handleLogout() {
  authStore.logout()
  window.location.href = '/login'
}
</script>

<style scoped>
/* ===== 外层 ===== */
.operator-sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-default);
  flex-shrink: 0;
  transition: width var(--duration-normal) var(--ease-standard);
  overflow: hidden;
}

.operator-sidebar.collapsed {
  width: var(--sidebar-collapsed);
}

/* ===== 内层 ===== */
.sidebar-inner {
  position: relative;
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  height: 100%;
  display: flex;
  transition: transform var(--duration-normal) var(--ease-standard);
}

.operator-sidebar.collapsed .sidebar-inner {
  transform: translateX(calc(-1 * var(--sidebar-width)));
}

/* ===== 展开列 ===== */
.expanded-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 顶部固定 */
.sidebar-top {
  flex-shrink: 0;
}

.top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-2) var(--space-3);
}

.fold-btn {
  flex-shrink: 0;
  color: var(--text-secondary);
}

.brand-text {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.new-report-row {
  padding: 0 var(--space-3) var(--space-3);
}

/* ===== 顶部导航（预测分析 / 病例库） ===== */
.nav-row {
  display: flex;
  gap: var(--space-2);
  padding: 0 var(--space-3) var(--space-3);
}

.nav-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 0;
  font-size: var(--text-sm);
  color: var(--text-secondary);
  border-radius: var(--radius-item);
  cursor: pointer;
  transition: background var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out;
  user-select: none;
}

.nav-item:hover {
  background: var(--bg-hover);
}

.nav-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 500;
}

/* 中间滚动 */
.sidebar-mid {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 var(--space-3);
}

.report-item {
  display: flex;
  align-items: center;
  padding: 8px var(--space-2) 8px var(--space-3);
  margin-bottom: var(--space-1);
  border-radius: var(--radius-item);
  cursor: pointer;
  transition: background var(--duration-fast) ease-out;
}

.report-item:hover {
  background: var(--bg-hover);
}

.report-item:hover .report-more-btn {
  opacity: 1;
}

.report-item.active {
  background: var(--color-primary-light);
}

.report-info {
  flex: 1;
  min-width: 0;
}

.report-time {
  font-size: var(--text-xs);
  color: var(--text-disabled);
  margin-bottom: 2px;
}

.report-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-meta {
  margin-top: 2px;
}

.report-more-btn {
  flex-shrink: 0;
  color: var(--text-disabled);
  opacity: 0;
  transition: opacity var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out;
  padding: 2px;
}

.report-more-btn:hover {
  color: var(--text-secondary);
}

.empty-tip {
  padding: var(--space-10) var(--space-4);
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--text-xs);
}

/* 底部固定 */
.sidebar-bot {
  flex-shrink: 0;
  padding: var(--space-3);
  border-top: 1px solid var(--border-default);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.user-name {
  flex: 1;
  min-width: 0;
}

.user-display {
  font-size: var(--text-sm);
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-tag {
  display: inline-block;
  padding: 1px 8px;
  font-size: 11px;
  line-height: 1.8;
  color: #fff;
  border-radius: var(--radius-item);
  white-space: nowrap;
}

.more-btn {
  flex-shrink: 0;
  color: var(--text-disabled);
  padding: 4px;
}

.more-btn:hover {
  color: var(--text-secondary);
}

.popover-menu {
  padding: 4px 0;
}

.popover-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px 14px;
  font-size: var(--text-sm);
  color: var(--text-primary);
  cursor: pointer;
  border-radius: var(--radius-item);
  transition: background var(--duration-fast) ease-out;
}

.popover-item:hover {
  background: var(--bg-hover);
}

.popover-item.danger {
  color: var(--color-danger);
}

.popover-item.danger:hover {
  background: hsl(0, 55%, 95%);
}

/* ===== 折叠列 ===== */
.collapsed-col {
  position: absolute;
  left: var(--sidebar-width);
  top: 0;
  width: var(--sidebar-collapsed);
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.cs-top {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
}

.cs-top .el-button + .el-button {
  margin-left: 0;
}

.cs-mid {
  flex: 1;
}

.cs-bot {
  flex-shrink: 0;
  padding: var(--space-2) 0;
}

.toggle-btn {
  color: var(--text-secondary);
}
</style>
