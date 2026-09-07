import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useAuthStore } from './auth'
import { ApiRequestError } from '@/api/request'
import {
  readArchive,
  prepareArchive,
  downloadOriginal,
  type PdfArchiveStatus,
} from '@/api/report-archive'

export const useReportArchiveStore = defineStore('report-archive', () => {
  const auth = useAuthStore(),
    reportId = ref<number | null>(null),
    status = ref<PdfArchiveStatus | null>(null)
  const loading = ref(false),
    acting = ref(false),
    downloading = ref(false),
    error = ref(''),
    retryAt = ref(0)
  let epoch = 0,
    request = 0,
    controller: AbortController | null = null,
    timer: ReturnType<typeof setTimeout> | null = null,
    delay = 1500
  const active = () =>
    status.value?.state === 'queued' || status.value?.state === 'rendering'
  function detach() {
    epoch++
    request++
    controller?.abort()
    controller = null
    if (timer) clearTimeout(timer)
    timer = null
    reportId.value = null
    status.value = null
    loading.value = false
    acting.value = false
    downloading.value = false
    error.value = ''
    retryAt.value = 0
    delay = 1500
  }
  function capture() {
    const e = epoch,
      id = reportId.value,
      user = auth.user?.id
    return () => e === epoch && id === reportId.value && user === auth.user?.id
  }
  function accept(value: PdfArchiveStatus) {
    if (
      value.report_id === reportId.value &&
      value.revision >= (status.value?.revision ?? 0)
    )
      status.value = value
  }
  function schedule() {
    if (timer) clearTimeout(timer)
    if (active()) {
      timer = setTimeout(() => void refreshConnection(), delay)
      delay = Math.min(10000, Math.ceil(delay * 1.5))
    }
  }
  async function refreshConnection() {
    if (reportId.value === null || acting.value || Date.now() < retryAt.value)
      return
    const current = capture(),
      r = ++request
    loading.value = true
    error.value = ''
    try {
      const value = await readArchive(reportId.value, controller?.signal)
      if (current() && r === request) {
        accept(value)
        schedule()
      }
    } catch (cause) {
      if (current() && r === request) {
        if (cause instanceof ApiRequestError && cause.status === 401) {
          auth.clearAuth()
          return
        }
        if (
          cause instanceof ApiRequestError &&
          cause.retryAfterSeconds !== undefined
        )
          retryAt.value = Date.now() + cause.retryAfterSeconds * 1000
        error.value = (cause as Error).message || '连接中断，请重新连接'
      }
    } finally {
      if (current() && r === request) loading.value = false
    }
  }
  async function observe(id: number) {
    detach()
    reportId.value = id
    controller = new AbortController()
    await refreshConnection()
  }
  function storageKey() {
    return `operator-pdf-request:${auth.user?.id}:${reportId.value}`
  }
  function requestKey(action: 'prepare' | 'retry') {
    const key = storageKey()
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || 'null')
      if (
        saved?.action === action &&
        typeof saved.key === 'string' &&
        /^[0-9a-f-]{36}$/i.test(saved.key)
      )
        return saved.key
    } catch {
      /* replace malformed state */
    }
    const value = crypto.randomUUID()
    sessionStorage.setItem(
      key,
      JSON.stringify({
        key: value,
        action,
        attempt_id: status.value?.attempt_id ?? null,
      }),
    )
    return value
  }
  async function submit(retry: boolean) {
    if (reportId.value === null || acting.value || Date.now() < retryAt.value)
      return
    if (
      retry
        ? status.value?.state !== 'failed' || !status.value?.can_retry
        : status.value?.state !== 'not_requested'
    )
      return
    const current = capture(),
      savedKey = storageKey()
    acting.value = true
    error.value = ''
    request++
    loading.value = false
    if (timer) clearTimeout(timer)
    try {
      const key = requestKey(retry ? 'retry' : 'prepare')
      const value = await prepareArchive(
        reportId.value,
        key,
        retry,
        controller?.signal,
      )
      if (current()) {
        accept(value)
        sessionStorage.removeItem(savedKey)
        schedule()
      }
    } catch (cause) {
      if (current()) {
        if (cause instanceof ApiRequestError && cause.status === 401) {
          auth.clearAuth()
          return
        }
        error.value =
          (cause as Error).message || '请求结果暂未确认，请重新连接查看'
        if (cause instanceof ApiRequestError) {
          if (cause.retryAfterSeconds !== undefined)
            retryAt.value = Date.now() + cause.retryAfterSeconds * 1000
          if (cause.status && [400, 403, 404, 409, 422].includes(cause.status))
            sessionStorage.removeItem(savedKey)
        }
      }
    } finally {
      if (current()) acting.value = false
    }
  }
  async function download() {
    if (
      reportId.value === null ||
      status.value?.state !== 'ready' ||
      downloading.value
    )
      return
    const current = capture()
    downloading.value = true
    error.value = ''
    try {
      await downloadOriginal(reportId.value, controller?.signal, current)
    } catch (cause) {
      if (current()) {
        if (cause instanceof ApiRequestError && cause.status === 401) {
          auth.clearAuth()
          return
        }
        error.value = (cause as Error).message || '下载失败'
        if (cause instanceof ApiRequestError && cause.status === 409)
          await refreshConnection()
      }
    } finally {
      if (current()) downloading.value = false
    }
  }
  watch(
    () => auth.user?.id,
    (next, previous) => {
      if (next !== previous) detach()
    },
    { flush: 'sync' },
  )
  return {
    reportId,
    status,
    loading,
    acting,
    downloading,
    error,
    retryAt,
    observe,
    prepare: () => submit(false),
    retry: () => submit(true),
    download,
    detach,
    refreshConnection,
  }
})
