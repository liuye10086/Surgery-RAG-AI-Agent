import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Chat',
    component: () => import('@/views/ChatView.vue'),
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/AdminView.vue'),
    meta: { admin: true },
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/SettingsView.vue'),
    // 所有登录用户可访问，不加 meta.admin
  },
  {
    path: '/operator',
    name: 'Operator',
    component: () => import('@/views/OperatorView.vue'),
    meta: { aiOperator: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, _from, next) => {
  const authStore = useAuthStore()

  if (!authStore.isAuthenticated && authStore.token) {
    await authStore.fetchUser()
  }

  if (!to.meta.public && !authStore.isAuthenticated) {
    return next('/login')
  }

  // ai_operator 不可访问聊天和管理页面
  if (authStore.isAiOperator && (to.path === '/' || to.path.startsWith('/admin'))) {
    return next('/operator')
  }

  // 非 ai_operator/admin 不可访问 operator 页面
  if (to.meta.aiOperator && !authStore.canAccessOperator) {
    return next('/')
  }

  if (to.meta.admin && !authStore.isAdmin) {
    return next('/')
  }

  if (to.path === '/login' && authStore.isAuthenticated) {
    if (authStore.isAiOperator) {
      return next('/operator')
    }
    return next('/')
  }

  next()
})

export default router
