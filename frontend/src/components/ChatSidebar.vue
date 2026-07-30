<template>
  <div :class="['chat-sidebar', { collapsed }]">
    <div class="sidebar-inner">
      <!-- ====== 展开列 ====== -->
      <div class="expanded-col">
        <!-- 顶部固定：品牌 + 折叠 + 新建会话 -->
        <div class="sidebar-top">
          <div class="top-row">
            <span class="brand-text">
              <el-icon :size="18"><ChatDotSquare /></el-icon>
              Surgery RAG Agent
            </span>
            <el-button class="fold-btn" :icon="Fold" text @click="$emit('toggle')" title="折叠侧边栏" />
          </div>
          <div class="new-session-row">
            <el-button type="primary" :icon="Plus" @click="$emit('new-session')" style="width: 100%; border-radius: 10px">
              新建会话
            </el-button>
          </div>
        </div>

        <!-- 中间滚动：会话列表 -->
        <div class="sidebar-mid">
          <div
            v-for="session in sessions"
            :key="session.id"
            :class="['session-item', { active: currentId === session.id }]"
            @click="$emit('select', session.id)"
          >
            <div class="session-info">
              <div class="session-time">{{ formatTime(session.updated_at) }}</div>
              <div class="session-title">{{ session.title || '新会话' }}</div>
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
                  class="session-more-btn"
                  :icon="MoreFilled"
                  text
                  size="small"
                  @click.stop
                />
              </template>
              <div class="popover-menu">
                <div class="popover-item danger" @click.stop="$emit('delete-session', session.id)">
                  <el-icon :size="14"><Delete /></el-icon>
                  <span>删除会话</span>
                </div>
              </div>
            </el-popover>
          </div>
          <div v-if="!sessions.length" class="empty-tip">暂无会话</div>
        </div>

        <!-- 底部固定：用户信息 + 更多菜单 -->
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
                <div class="popover-item" @click="$router.push('/settings')">
                  <el-icon :size="15"><Setting /></el-icon>
                  <span>设置</span>
                </div>
                <div class="popover-item" @click="handleLogout">
                  <el-icon :size="15"><SwitchButton /></el-icon>
                  <span>退出登录</span>
                </div>
              </div>
            </el-popover>
          </div>
        </div>
      </div>

      <!-- ====== 折叠列（inner 右侧外部） ====== -->
      <div class="collapsed-col">
        <div class="cs-top">
          <el-button class="toggle-btn" :icon="collapsed ? Expand : Fold" text @click="$emit('toggle')" :title="collapsed ? '展开' : '折叠'" />
          <el-button type="primary" :icon="Plus" circle @click="$emit('new-session')" title="新建会话" />
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
              <div class="popover-item" @click="$router.push('/settings')">
                <el-icon :size="15"><Setting /></el-icon>
                <span>设置</span>
              </div>
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
import { Plus, SwitchButton, Fold, Expand, ChatDotSquare, MoreFilled, Delete, Setting } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import type { Session } from '@/api/chat'

defineProps<{
  sessions: Session[]
  currentId?: number
  collapsed: boolean
}>()

defineEmits<{
  (e: 'select', id: number): void
  (e: 'new-session'): void
  (e: 'toggle'): void
  (e: 'delete-session', id: number): void
}>()

const authStore = useAuthStore()

const roleLabel = computed(() => {
  const role = authStore.user?.role
  const map: Record<string, string> = {
    admin: '管理员',
    user: '用户',
    doctor: '医生',
    patient: '患者',
  }
  return map[role || ''] || role || '未知'
})

const roleTagColor = computed(() => {
  const role = authStore.user?.role
  const map: Record<string, string> = {
    admin: 'hsl(0, 55%, 55%)',
    doctor: 'hsl(25, 55%, 52%)',
    patient: 'hsl(155, 50%, 40%)',
  }
  return map[role || ''] || 'hsl(200, 65%, 40%)'
})

function formatTime(iso: string) {
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function handleLogout() {
  authStore.logout()
  window.location.href = '/login'
}
</script>

<style scoped>
/* ===== 外层 ===== */
.chat-sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-default);
  flex-shrink: 0;
  transition: width var(--duration-normal) var(--ease-standard);
  overflow: hidden;
}

.chat-sidebar.collapsed {
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

.chat-sidebar.collapsed .sidebar-inner {
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

.new-session-row {
  padding: 0 var(--space-3) var(--space-3);
}

/* 中间滚动 */
.sidebar-mid {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 var(--space-3);
}

.session-item {
  display: flex;
  align-items: center;
  padding: 8px var(--space-2) 8px var(--space-3);
  margin-bottom: var(--space-1);
  border-radius: var(--radius-item);
  cursor: pointer;
  transition: background var(--duration-fast) ease-out;
}

.session-item:hover {
  background: var(--bg-hover);
}

.session-item:hover .session-more-btn {
  opacity: 1;
}

.session-item.active {
  background: var(--color-primary-light);
}

.session-info {
  flex: 1;
  min-width: 0;
}

.session-time {
  font-size: var(--text-xs);
  color: var(--text-disabled);
  margin-bottom: 2px;
}

.session-title {
  font-size: var(--text-sm);
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-more-btn {
  flex-shrink: 0;
  color: var(--text-disabled);
  opacity: 0;
  transition: opacity var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out;
  padding: 2px;
}

.session-more-btn:hover {
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

/* ===== 折叠列（inner 右侧外部，absolute） ===== */
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
