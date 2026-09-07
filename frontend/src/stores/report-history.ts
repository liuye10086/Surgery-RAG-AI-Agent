import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { useAuthStore } from './auth'
import {
  listHistory,
  type HistoryItem,
  type HistoryFilters,
} from '@/api/report-history'

export const useReportHistoryStore = defineStore('report-history', () => {
  const auth = useAuthStore()
  const items = ref<HistoryItem[]>([]),
    filters = ref<HistoryFilters>({}),
    nextCursor = ref<string | null>(null)
  const hasMore = ref(false),
    loading = ref(false),
    loadingMore = ref(false),
    error = ref(''),
    scrollTop = ref(0),
    updatesAvailable = ref(false)
  let epoch = 0,
    pageRequest = 0,
    controller: AbortController | null = null
  function invalidate() {
    epoch++
    controller?.abort()
    controller = null
    loading.value = false
    loadingMore.value = false
  }
  async function fetchPage(append: boolean) {
    if (append && (loading.value || loadingMore.value || !hasMore.value)) return
    if (!append) invalidate()
    const captured = epoch,
      requestId = ++pageRequest,
      userId = auth.user?.id
    controller = new AbortController()
    if (append) loadingMore.value = true
    else loading.value = true
    error.value = ''
    try {
      const result = await listHistory(
        {
          ...filters.value,
          cursor: append ? nextCursor.value : null,
          limit: 20,
        },
        controller.signal,
      )
      if (
        captured !== epoch ||
        requestId !== pageRequest ||
        userId !== auth.user?.id
      )
        return
      items.value = append
        ? [
            ...items.value,
            ...result.items.filter(
              (x) => !items.value.some((y) => y.id === x.id),
            ),
          ]
        : result.items
      nextCursor.value = result.next_cursor
      hasMore.value = result.has_more
      if (!append) {
        updatesAvailable.value = false
        scrollTop.value = 0
      }
    } catch (cause) {
      if (
        captured === epoch &&
        requestId === pageRequest &&
        userId === auth.user?.id
      )
        error.value = (cause as Error).message || '历史报告读取失败'
    } finally {
      if (captured === epoch && requestId === pageRequest) {
        loading.value = false
        loadingMore.value = false
      }
    }
  }
  const refresh = () => fetchPage(false),
    loadMore = () => fetchPage(true)
  function setFilters(value: HistoryFilters) {
    invalidate()
    filters.value = { ...value }
    items.value = []
    nextCursor.value = null
    hasMore.value = false
    scrollTop.value = 0
    return refresh()
  }
  function remove(id: number) {
    invalidate()
    items.value = items.value.filter((x) => x.id !== id)
  }
  function resetForAccount() {
    invalidate()
    items.value = []
    filters.value = {}
    nextCursor.value = null
    hasMore.value = false
    error.value = ''
    scrollTop.value = 0
    updatesAvailable.value = false
  }
  watch(
    () => auth.user?.id,
    (next, previous) => {
      if (next !== previous) resetForAccount()
    },
    { flush: 'sync' },
  )
  return {
    items,
    filters,
    nextCursor,
    hasMore,
    loading,
    loadingMore,
    error,
    scrollTop,
    updatesAvailable,
    refresh,
    loadMore,
    setFilters,
    remove,
    resetForAccount,
    invalidate,
  }
})
