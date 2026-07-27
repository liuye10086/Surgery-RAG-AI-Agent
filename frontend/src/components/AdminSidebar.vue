<template>
  <div :class="['admin-sidebar', { collapsed }]">
    <div class="sidebar-inner">
      <!-- ====== 展开列 ====== -->
      <div class="expanded-col">
        <!-- 顶部：品牌 + 折叠 -->
        <div class="sidebar-top">
          <div class="top-row">
            <span class="brand-text">
              <el-icon :size="18"><Setting /></el-icon>
              管理后台
            </span>
            <el-button class="fold-btn" :icon="Fold" text @click="$emit('toggle')" title="折叠侧边栏" />
          </div>
        </div>

        <!-- 中间：导航菜单 -->
        <div class="sidebar-mid">
          <div
            v-for="item in navItems"
            :key="item.key"
            :class="['nav-item', { active: activeKey === item.key, disabled: item.disabled }]"
            @click="handleNav(item)"
          >
            <el-icon :size="16"><component :is="item.icon" /></el-icon>
            <span class="nav-label">{{ item.label }}</span>
            <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
          </div>

          <!-- 知识分类子列表（展开后可见） -->
          <div v-if="activeKey === 'categories'" class="sub-nav">
            <div class="sub-nav-empty">
              <el-icon :size="14"><FolderAdd /></el-icon>
              <span>暂无分类，敬请期待</span>
            </div>
          </div>
        </div>

        <!-- 底部：返回会话 + 用户信息 -->
        <div class="sidebar-bot">
          <div class="back-row">
            <el-button text size="small" @click="$router.push('/')">
              <el-icon :size="14"><ArrowLeft /></el-icon>
              <span>返回会话</span>
            </el-button>
          </div>
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

      <!-- ====== 折叠列 ====== -->
      <div class="collapsed-col">
        <div class="cs-top">
          <el-button class="toggle-btn" :icon="Expand" text @click="$emit('toggle')" title="展开侧边栏" />
        </div>
        <div class="cs-mid">
          <el-tooltip
            v-for="item in navItems"
            :key="item.key"
            :content="item.label"
            placement="right"
            :show-after="300"
          >
            <div
              :class="['cs-nav-item', { active: activeKey === item.key, disabled: item.disabled }]"
              @click="handleNav(item)"
            >
              <el-icon :size="18"><component :is="item.icon" /></el-icon>
            </div>
          </el-tooltip>
        </div>
        <div class="cs-bot">
          <el-tooltip content="返回会话" placement="right" :show-after="300">
            <el-button text circle :icon="ArrowLeft" @click="$router.push('/')" />
          </el-tooltip>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Setting, Fold, Expand, ArrowLeft, Document, Folder, FolderAdd, Picture, VideoCamera, MoreFilled, SwitchButton } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

defineProps<{
  activeKey: string
  collapsed: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle'): void
  (e: 'navigate', key: string): void
}>()

const authStore = useAuthStore()

interface NavItem {
  key: string
  label: string
  icon: any
  disabled?: boolean
  badge?: string
}

const navItems: NavItem[] = [
  { key: 'documents', label: '文档管理', icon: Document },
  { key: 'images', label: '图片管理', icon: Picture },
  { key: 'videos', label: '视频管理', icon: VideoCamera },
  { key: 'categories', label: '知识分类', icon: Folder, disabled: true },
]

function handleNav(item: NavItem) {
  if (item.disabled) return
  emit('navigate', item.key)
}

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

function handleLogout() {
  authStore.logout()
  window.location.href = '/login'
}
</script>

<style scoped>
/* ===== 外层 ===== */
.admin-sidebar {
  width: var(--sidebar-width);
  height: 100vh;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-default);
  flex-shrink: 0;
  transition: width var(--duration-normal) var(--ease-standard);
  overflow: hidden;
}

.admin-sidebar.collapsed {
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

.admin-sidebar.collapsed .sidebar-inner {
  transform: translateX(calc(-1 * var(--sidebar-width)));
}

/* ===== 展开列 ===== */
.expanded-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

/* 顶部 */
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

/* 中间导航 */
.sidebar-mid {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2) var(--space-3);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px var(--space-3);
  margin-bottom: var(--space-1);
  border-radius: var(--radius-item);
  cursor: pointer;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  transition: background var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out;
  user-select: none;
}

.nav-item:hover:not(.disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
  font-weight: 500;
}

.nav-item.disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.nav-label {
  flex: 1;
}

.nav-badge {
  font-size: 11px;
  padding: 0 6px;
  border-radius: var(--radius-pill);
  background: var(--color-accent-light);
  color: var(--color-accent);
  line-height: 1.8;
}

/* 子导航 */
.sub-nav {
  padding: var(--space-1) 0 var(--space-2) var(--space-8);
}

.sub-nav-empty {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--text-disabled);
  font-size: var(--text-xs);
  padding: var(--space-2) 0;
}

/* 底部 */
.sidebar-bot {
  flex-shrink: 0;
  border-top: 1px solid var(--border-default);
}

.back-row {
  padding: var(--space-2) var(--space-3);
}

.back-row .el-button {
  color: var(--text-secondary);
  font-size: var(--text-xs);
}

.user-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 var(--space-3) var(--space-3);
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
  padding: var(--space-2) 0;
}

.toggle-btn {
  color: var(--text-secondary);
}

.cs-mid {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) 0;
}

.cs-nav-item {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-item);
  color: var(--text-secondary);
  cursor: pointer;
  transition: background var(--duration-fast) ease-out,
              color var(--duration-fast) ease-out;
}

.cs-nav-item:hover:not(.disabled) {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.cs-nav-item.active {
  background: var(--color-primary-light);
  color: var(--color-primary);
}

.cs-nav-item.disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.cs-bot {
  flex-shrink: 0;
  padding: var(--space-2) 0;
}
</style>
