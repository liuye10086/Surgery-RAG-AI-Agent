import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe, login, register, type UserInfo, type RegisterData } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('token'))
  const user = ref<UserInfo | null>(null)
  const isAuthenticated = computed(() => !!token.value && !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const isAiOperator = computed(() => user.value?.role === 'ai_operator')
  const canAccessOperator = computed(
    () => user.value?.role === 'ai_operator' || user.value?.role === 'admin'
  )
  const displayName = computed(() => {
    if (!user.value) return ''
    return user.value.real_name || user.value.username
  })

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
  }

  function clearAuth() {
    token.value = null
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('surgery_rag_danger_state')
  }

  async function fetchUser() {
    if (!token.value) return
    try {
      user.value = await getMe()
    } catch {
      clearAuth()
    }
  }

  async function doLogin(username: string, password: string) {
    const res = await login(username, password)
    setToken(res.access_token)
    await fetchUser()
  }

  async function doRegister(data: RegisterData): Promise<void> {
    await register(data)
    // 注册成功后不自动登录，由页面引导用户去登录
  }

  function logout() {
    clearAuth()
  }

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    isAiOperator,
    canAccessOperator,
    displayName,
    setToken,
    clearAuth,
    fetchUser,
    doLogin,
    doRegister,
    logout,
  }
})
