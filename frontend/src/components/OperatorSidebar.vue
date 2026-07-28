<template>
  <div :class="['operator-sidebar', { collapsed }]">
    <div class="sidebar-inner">
      <!-- 展开列 -->
      <div class="expanded-col">
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
        </div>

        <!-- 报告列表 -->
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
                <div
                  class="popover-item danger"
                  @click.stop="$emit('delete', report.id)"
                >
                  <el-icon :size="14"><Delete /></el-icon>
                  <span>删除报告</span>
                </div>
              </div>
            </el-popover>
          </div>
          <div v-if="!reports.length && !loading" class="empty-tip">暂无分析报告</div>
          <div v-if="loading" class="empty-tip">加载中...</div>
        </div>
      </div>

      <!-- 折叠列 -->
      <div class="collapsed-col">
        <el-button :icon="Expand" text @click="$emit('toggle')" title="展开侧边栏" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Fold, Expand, Plus, MoreFilled, Delete, DataAnalysis } from '@element-plus/icons-vue'
import type { ReportListItem } from '@/api/operator'

defineProps<{
  reports: ReportListItem[]
  currentId?: number
  collapsed: boolean
  loading: boolean
  generating: boolean
}>()

defineEmits<{
  toggle: []
  select: [id: number]
  'new-analysis': []
  delete: [id: number]
}>()

function formatTime(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
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
</script>

<style scoped>
.operator-sidebar {
  width: var(--sidebar-width, 260px);
  height: 100vh;
  background: var(--bg-sidebar, hsl(200, 10%, 95%));
  border-right: 1px solid var(--border-default, hsl(210, 8%, 88%));
  display: flex;
  flex-shrink: 0;
  transition: width var(--duration-normal, 250ms) var(--ease-standard, cubic-bezier(0.2, 0, 0.8, 1));
  overflow: hidden;
}

.operator-sidebar.collapsed {
  width: var(--sidebar-collapsed, 64px);
}

.sidebar-inner {
  width: var(--sidebar-width, 260px);
  height: 100%;
  display: flex;
  flex-shrink: 0;
}

.expanded-col {
  width: calc(var(--sidebar-width, 260px) - var(--sidebar-collapsed, 64px));
  display: flex;
  flex-direction: column;
}

.collapsed-col {
  width: var(--sidebar-collapsed, 64px);
  display: flex;
  justify-content: center;
  padding-top: var(--space-3, 12px);
  border-left: 1px solid var(--border-light, hsl(210, 10%, 93%));
}

/* Top */
.sidebar-top {
  padding: var(--space-4, 16px) var(--space-3, 12px);
  border-bottom: 1px solid var(--border-light, hsl(210, 10%, 93%));
}

.top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-3, 12px);
}

.brand-text {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  font-size: var(--text-sm, 14px);
  font-weight: 600;
  color: var(--text-primary, hsl(210, 18%, 18%));
}

.fold-btn {
  color: var(--text-secondary, hsl(210, 6%, 45%));
}

/* Middle */
.sidebar-mid {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2, 8px);
}

.report-item {
  display: flex;
  align-items: flex-start;
  padding: var(--space-3, 12px);
  margin-bottom: var(--space-1, 4px);
  border-radius: var(--radius-item, 8px);
  cursor: pointer;
  transition: background var(--duration-fast, 150ms);
  gap: var(--space-2, 8px);
}

.report-item:hover {
  background: var(--bg-hover, hsl(200, 15%, 93%));
}

.report-item.active {
  background: var(--color-primary-light, hsl(200, 65%, 92%));
}

.report-info {
  flex: 1;
  min-width: 0;
}

.report-time {
  font-size: 11px;
  color: var(--text-disabled, hsl(210, 4%, 62%));
  margin-bottom: var(--space-1, 4px);
}

.report-title {
  font-size: var(--text-xs, 13px);
  color: var(--text-primary, hsl(210, 18%, 18%));
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-meta {
  margin-top: var(--space-1, 4px);
}

.report-more-btn {
  opacity: 0;
  flex-shrink: 0;
  margin-top: -2px;
}

.report-item:hover .report-more-btn {
  opacity: 1;
}

.empty-tip {
  text-align: center;
  padding: var(--space-8, 32px) var(--space-4, 16px);
  font-size: var(--text-xs, 13px);
  color: var(--text-disabled, hsl(210, 4%, 62%));
}

/* Popover */
.popover-menu {
  padding: var(--space-1, 4px);
}

.popover-item {
  display: flex;
  align-items: center;
  gap: var(--space-2, 8px);
  padding: var(--space-2, 8px) var(--space-3, 12px);
  border-radius: var(--radius-item, 8px);
  cursor: pointer;
  font-size: var(--text-xs, 13px);
  color: var(--text-primary, hsl(210, 18%, 18%));
  transition: background var(--duration-fast, 150ms);
}

.popover-item:hover {
  background: var(--bg-hover, hsl(200, 15%, 93%));
}

.popover-item.danger {
  color: var(--color-danger, hsl(0, 60%, 48%));
}

.popover-item.danger:hover {
  background: hsl(0, 40%, 94%);
}
</style>
