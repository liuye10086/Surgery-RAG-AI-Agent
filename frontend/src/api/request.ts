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
  if (detail?.message) return detail.message
  if (detail?.msg) return detail.msg
  return '请求失败'
}

export interface ApiValidationIssue {
  code: string
  message: string
  field?: string
}

export class ApiRequestError extends Error {
  readonly retryAfterSeconds?: number
  readonly code: string
  readonly reportId?: number
  readonly field?: string
  readonly issues: ApiValidationIssue[]
  readonly status?: number
  readonly response?: { status?: number; data: { detail: string } }

  constructor(options: { retryAfterSeconds?: number; reportId?: number; code: string; message: string; field?: string; issues?: ApiValidationIssue[]; status?: number }) {
    super(options.message)
    this.name = 'ApiRequestError'
    this.retryAfterSeconds = options.retryAfterSeconds
    this.reportId = options.reportId
    this.code = options.code
    this.field = options.field
    this.issues = options.issues || []
    this.status = options.status
    this.response = { status: options.status, data: { detail: options.message } }
  }
}

function pydanticField(location: unknown): string | undefined {
  if (!Array.isArray(location)) return undefined
  const parts = location.filter((part) => part !== 'body').map(String)
  return parts.length ? parts.join('.') : undefined
}

function normalizeIssue(value: any): ApiValidationIssue | null {
  if (!value || typeof value !== 'object') return null
  const message = typeof value.message === 'string' ? value.message : typeof value.msg === 'string' ? value.msg : ''
  if (!message) return null
  const field = typeof value.field === 'string' ? value.field : pydanticField(value.loc)
  return {
    code: typeof value.code === 'string' ? value.code : typeof value.type === 'string' ? value.type : 'validation_error',
    message,
    ...(field ? { field } : {}),
  }
}

export function parseRetryAfter(value: unknown): number | undefined {
  if (typeof value !== 'string' && typeof value !== 'number') return undefined
  const seconds = /^\d+$/.test(String(value)) ? Number(value) : (Date.parse(String(value)) - Date.now()) / 1000
  return Number.isFinite(seconds) && seconds >= 0 ? Math.ceil(seconds) : undefined
}

export function normalizeApiError(error: any): ApiRequestError {
  const retryAfterSeconds = parseRetryAfter(error?.response?.headers?.['retry-after'])
  const status = typeof error?.response?.status === 'number' ? error.response.status : undefined
  const detail = error?.response?.data?.detail
  if (detail && !Array.isArray(detail) && typeof detail === 'object') {
    const issues = Array.isArray(detail.issues) ? detail.issues.map(normalizeIssue).filter(Boolean) as ApiValidationIssue[] : []
    return new ApiRequestError({
      reportId: Number.isSafeInteger(detail.report_id) ? detail.report_id : undefined,
      retryAfterSeconds,
      code: typeof detail.code === 'string' ? detail.code : 'request_failed',
      message: typeof detail.message === 'string' ? detail.message : formatErrorDetail(detail),
      field: typeof detail.field === 'string' ? detail.field : undefined,
      issues,
      status,
    })
  }
  if (Array.isArray(detail)) {
    const issues = detail.map(normalizeIssue).filter(Boolean) as ApiValidationIssue[]
    return new ApiRequestError({
      code: 'validation_error',
      retryAfterSeconds,
      message: issues.map((issue) => issue.message).join('；') || '输入数据无效',
      field: issues[0]?.field,
      issues,
      status,
    })
  }
  return new ApiRequestError({
    code: status ? `http_${status}` : 'network_error',
    retryAfterSeconds,
    message: formatErrorDetail(detail) || (status ? '请求失败' : '网络连接失败'),
    status,
  })
}

export function validationIssueMap(error: unknown): Record<string, string> {
  if (!(error instanceof ApiRequestError)) return {}
  const mapped: Record<string, string> = {}
  if (error.field) mapped[error.field] = error.message
  for (const issue of error.issues) if (issue.field) mapped[issue.field] = issue.message
  return mapped
}

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const status = error.response?.status
    const normalized = normalizeApiError(error)
    const detail = normalized.message
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

    return Promise.reject(normalized)
  }
)

export default request
