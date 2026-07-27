import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

function formatErrorDetail(detail: any): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: any) => {
        if (typeof item === 'string') return item
        if (item.msg) return item.msg
        return JSON.stringify(item)
      })
      .filter(Boolean)
      .join('；')
  }
  if (detail?.msg) return detail.msg
  return '请求失败'
}

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const detail = formatErrorDetail(error.response?.data?.detail)
    const url = error.config?.url || ''

    // 登录/注册相关错误由页面自行提示，避免重复弹窗
    const isAuthEndpoint = url.includes('/auth/')

    // 请求超时（如向量化大文档）给出更友好的提示
    const isTimeout =
      error.code === 'ECONNABORTED' ||
      error.message?.toLowerCase().includes('timeout') ||
      error.message?.toLowerCase().includes('timeout of')

    // 401 由路由守卫统一处理，登录页本身不需要弹错误
    if (status === 401) {
      localStorage.removeItem('token')
      if (window.location.pathname !== '/login') {
        ElMessage.error(detail)
        window.location.href = '/login'
      }
    } else if (isTimeout) {
      ElMessage.warning('请求处理时间较长，请稍后刷新页面查看结果')
    } else if (!isAuthEndpoint) {
      ElMessage.error(detail)
    }

    return Promise.reject(error)
  }
)

export default request
