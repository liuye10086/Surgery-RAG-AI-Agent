<template>
  <div class="login-page">
    <div class="login-box">
      <h1>Surgery RAG Agent</h1>
      <p class="subtitle">外科/手术领域垂直知识库问答系统</p>

      <el-tabs v-model="activeTab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form :model="form" label-position="top" @submit.prevent="handleLogin">
            <el-form-item label="用户名">
              <el-input v-model="form.username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="handleLogin" style="width: 100%">
                登录
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form :model="form" label-position="top" @submit.prevent="handleRegister">
            <el-form-item label="用户名">
              <el-input v-model="form.username" placeholder="请输入用户名" />
            </el-form-item>
            <el-form-item label="邮箱">
              <el-input v-model="form.email" type="email" placeholder="请输入邮箱" />
            </el-form-item>
            <el-form-item label="真实姓名">
              <el-input v-model="form.realName" placeholder="请输入真实姓名" />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="form.password" type="password" placeholder="请输入密码" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="loading" @click="handleRegister" style="width: 100%">
                注册
              </el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>

      <p class="disclaimer">
        ⚠️ 本系统仅供医学研究与参考，不构成医疗建议或诊断依据。
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const activeTab = ref('login')
const loading = ref(false)
const form = reactive({
  username: '',
  email: '',
  realName: '',
  password: '',
})

async function handleLogin() {
  const username = form.username.trim()
  const password = form.password
  if (!username || !password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.doLogin(username, password)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '登录失败，请检查用户名和密码'
    ElMessage.error(detail)
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  const username = form.username.trim()
  const email = form.email.trim()
  const realName = form.realName.trim()
  const password = form.password

  if (!username || !email || !password) {
    ElMessage.warning('请填写用户名、邮箱和密码')
    return
  }
  if (!isValidEmail(email)) {
    ElMessage.warning('请输入有效的邮箱地址')
    return
  }
  if (password.length < 6) {
    ElMessage.warning('密码长度不能少于 6 位')
    return
  }

  loading.value = true
  try {
    await authStore.doRegister({
      username,
      email,
      real_name: realName || undefined,
      password,
    })
    ElMessage.success('注册成功，请登录')
    form.password = ''
    form.email = ''
    form.realName = ''
    activeTab.value = 'login'
  } catch (e: any) {
    const detail = e?.response?.data?.detail || '注册失败，请重试'
    ElMessage.error(detail)
  } finally {
    loading.value = false
  }
}

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-canvas);
}

.login-box {
  width: 420px;
  padding: var(--space-10);
  background: var(--bg-surface);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-lg);
}

h1 {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xl);
  text-align: center;
  color: var(--text-primary);
  font-weight: 600;
}

.subtitle {
  margin: 0 0 var(--space-8);
  text-align: center;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.disclaimer {
  margin-top: var(--space-6);
  text-align: center;
  color: var(--text-disabled);
  font-size: var(--text-xs);
  line-height: 1.5;
}
</style>
