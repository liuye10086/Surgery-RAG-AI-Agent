<template>
  <section
    ref="scroller"
    class="history"
    aria-labelledby="history-title"
    @scroll="saveScroll"
  >
    <div class="history-inner">
      <h3 id="history-title">历史报告</h3>
      <p>查看生成时保存的报告、输入资料与审计记录。</p>
      <form class="filters" @submit.prevent="applyFilters">
        <label
          >病种<select v-model="disease" aria-label="病种">
            <option value="">全部</option>
            <option value="fatty_liver">脂肪肝</option>
            <option value="ad">阿尔茨海默病</option>
          </select></label
        >
        <label
          >病例编号<input
            v-model="code"
            aria-label="病例编号"
            placeholder="CASE-ABCD-2345"
            maxlength="14"
        /></label>
        <label
          >状态<select v-model="status" aria-label="状态">
            <option value="">全部</option>
            <option value="completed">已完成</option>
            <option value="failed">失败</option>
            <option value="cancelled">已取消</option>
            <option value="generating">生成中</option>
          </select></label
        >
        <label
          >起始日期<input
            v-model="from"
            aria-label="起始日期"
            type="date" /></label
        ><label
          >结束日期<input v-model="to" aria-label="结束日期" type="date"
        /></label>
        <el-button native-type="submit" type="primary">筛选</el-button
        ><el-button @click="resetFilters">清除筛选</el-button>
      </form>
      <p v-if="store.updatesAvailable" role="status">
        报告状态有更新。<el-button @click="store.refresh()">刷新查看</el-button>
      </p>
      <div v-if="store.error" role="alert">
        {{ store.error }}
        <el-button @click="store.refresh()">重试读取</el-button>
      </div>
      <p v-if="store.loading" role="status">正在读取历史报告…</p>
      <p v-else-if="!store.items.length">当前筛选条件下没有报告。</p>
      <article
        v-for="item in store.items"
        :key="item.id"
        :data-report-id="item.id"
        class="history-row"
      >
        <button class="open-report" @click="$emit('select', item.id)">
          <strong>{{ item.anonymous_case_code || `报告-${item.id}` }}</strong
          ><span
            >{{ item.disease_name || '病种未记录' }} ·
            {{ stageLabel(item.baseline_stage) }}</span
          >
        </button>
        <p>
          {{ item.visit_count ?? '未记录' }} 次访视 ·
          {{ statuses[item.status] || '状态未记录' }} ·
          {{
            new Date(item.created_at).toLocaleString('zh-CN', {
              timeZone: 'Asia/Shanghai',
            })
          }}
        </p>
        <p>
          模型版本：{{ item.model_version_summary || '未记录' }} · PDF：{{
            pdfLabels[item.pdf_status] || '未准备'
          }}
          · 下载 {{ item.download_count }} 次
        </p>
        <el-button
          type="danger"
          plain
          :disabled="item.status === 'generating'"
          @click="$emit('delete', item.id)"
          >删除报告</el-button
        >
      </article>
      <el-button
        v-if="store.hasMore"
        :loading="store.loadingMore"
        :disabled="store.loading"
        @click="store.loadMore()"
        >加载更多</el-button
      >
      <p v-else-if="store.items.length">已加载全部报告</p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useReportHistoryStore } from '@/stores/report-history'
import { stageLabel, shanghaiDateRange } from '@/utils/report-read-model'
import type { HistoryFilters } from '@/api/report-history'
defineEmits<{ select: [id: number]; delete: [id: number] }>()
const store = useReportHistoryStore(),
  scroller = ref<HTMLElement | null>(null)
const disease = ref(store.filters.disease_code || ''),
  code = ref(store.filters.anonymous_case_code || ''),
  status = ref(store.filters.status || ''),
  from = ref(filterDate(store.filters.created_from)),
  to = ref(filterDate(store.filters.created_before, true))
function filterDate(value?: string, end = false) {
  if (!value) return ''
  return new Date(Date.parse(value) + 8 * 3600000 - (end ? 86400000 : 0))
    .toISOString()
    .slice(0, 10)
}
const statuses: Record<string, string> = {
  generating: '生成中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}
const pdfLabels: Record<string, string> = {
  not_requested: '未准备',
  queued: '排队中',
  rendering: '准备中',
  ready: '原件已归档',
  failed: '准备失败',
  missing: '原件缺失',
  corrupt: '原件校验失败',
}
function applyFilters() {
  if (from.value && to.value && from.value > to.value) {
    store.error = '起始日期不能晚于结束日期'
    return
  }
  void store.setFilters({
    disease_code: (disease.value ||
      undefined) as HistoryFilters['disease_code'],
    anonymous_case_code: code.value.trim() || undefined,
    status: (status.value || undefined) as HistoryFilters['status'],
    ...shanghaiDateRange(from.value, to.value),
  })
}
function resetFilters() {
  disease.value = ''
  code.value = ''
  status.value = ''
  from.value = ''
  to.value = ''
  void store.setFilters({})
}
function saveScroll() {
  store.scrollTop = scroller.value?.scrollTop || 0
}
onMounted(() => {
  if (scroller.value) scroller.value.scrollTop = store.scrollTop
})
</script>
<style scoped>
.history {
  flex: 1;
  overflow: auto;
  padding: var(--space-6);
  color: var(--text-primary);
}
.history-inner {
  max-width: var(--content-max-width);
  margin: auto;
}
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  align-items: end;
}
.filters label {
  display: grid;
  gap: var(--space-2);
  font-size: var(--text-sm);
}
input,
select {
  min-height: 44px;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-input);
  padding: 0 var(--space-3);
  background: var(--bg-input);
  color: var(--text-primary);
}
.history-row {
  margin: var(--space-4) 0;
  padding: var(--space-5);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  background: var(--bg-surface);
}
.open-report {
  display: grid;
  gap: var(--space-2);
  text-align: left;
  background: none;
  border: 0;
  color: var(--text-link);
  cursor: pointer;
  min-height: 44px;
  font: inherit;
}
.history-row p {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  overflow-wrap: anywhere;
}
:deep(button) {
  min-height: 44px;
}
button:focus-visible,
input:focus-visible,
select:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}
</style>
