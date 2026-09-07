<template>
  <div class="archive-actions" aria-label="PDF 归档">
    <p v-if="store.error" role="alert">
      {{ store.error }}
      <el-button @click="store.refreshConnection()">重新连接</el-button>
    </p>
    <p
      v-if="
        store.status?.state === 'missing' || store.status?.state === 'corrupt'
      "
      role="status"
    >
      {{ store.status.message }}
    </p>
    <el-button
      v-else-if="store.status?.state === 'ready'"
      type="primary"
      :loading="store.downloading"
      @click="store.download()"
      >下载 PDF</el-button
    >
    <el-button
      v-else-if="store.status?.state === 'not_requested'"
      type="primary"
      :loading="store.acting"
      :disabled="cooling"
      @click="store.prepare()"
      >准备 PDF</el-button
    >
    <el-button
      v-else-if="store.status?.state === 'failed' && store.status.can_retry"
      type="primary"
      :loading="store.acting"
      :disabled="cooling"
      @click="store.retry()"
      >重新准备 PDF</el-button
    >
    <p
      v-else-if="
        store.status?.state === 'queued' || store.status?.state === 'rendering'
      "
      role="status"
    >
      正在准备 PDF，可离开页面
    </p>
    <p v-else-if="store.loading" role="status">正在读取 PDF 状态…</p>
    <p v-if="cooling" role="status">请等待 {{ remaining }} 秒后重试</p>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { useReportArchiveStore } from '@/stores/report-archive'
const props = defineProps<{ reportId: number }>(),
  store = useReportArchiveStore(),
  now = ref(Date.now())
const clock = setInterval(() => {
  now.value = Date.now()
}, 1000)
const remaining = computed(() =>
    Math.max(0, Math.ceil((store.retryAt - now.value) / 1000)),
  ),
  cooling = computed(() => remaining.value > 0)
watch(
  () => props.reportId,
  (id) => void store.observe(id),
  { immediate: true },
)
onUnmounted(() => {
  clearInterval(clock)
  store.detach()
})
</script>
<style scoped>
.archive-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
  max-width: 100%;
  color: var(--text-secondary);
  font-size: var(--text-sm);
}
.archive-actions p {
  margin: 0;
  overflow-wrap: anywhere;
}
.archive-actions :deep(button) {
  min-height: 44px;
}
</style>
