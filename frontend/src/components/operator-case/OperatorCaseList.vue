<template>
  <section class="case-list" aria-label="我的病例">
    <div class="case-list__toolbar">
      <label>
        <span>搜索匿名编号</span>
        <input :value="query" type="search" placeholder="CASE-" @input="$emit('update:query', ($event.target as HTMLInputElement).value)" />
      </label>
      <label><span>病例状态</span><select aria-label="病例状态筛选" :value="status" @change="$emit('update:status', ($event.target as HTMLSelectElement).value as 'active' | 'archived')"><option value="active">使用中</option><option value="archived">已归档</option></select></label>
      <button type="button" @click="$emit('new')">新建病例</button>
    </div>
    <div v-if="loading" class="case-list__state" role="status">加载中…</div>
    <div v-else-if="!cases.length" class="case-list__state">暂无病例</div>
    <button v-for="item in cases" v-else :key="item.id" type="button" :class="['case-list__item', { selected: item.id === selectedId }]" @click="$emit('select', item)">
      <strong>{{ item.anonymous_case_code || '待补录匿名编号' }}</strong>
      <span>{{ item.disease.name }} · {{ item.visits.length }} 次访视</span>
    </button>
    <nav class="case-list__pagination" aria-label="病例分页">
      <button type="button" aria-label="上一页病例" :disabled="loading || pagination.skip === 0" @click="$emit('page', Math.max(0, pagination.skip - pagination.limit))">上一页</button>
      <span aria-live="polite">共 {{ pagination.total }} 例 · 第 {{ Math.floor(pagination.skip / pagination.limit) + 1 }} / {{ Math.max(1, Math.ceil(pagination.total / pagination.limit)) }} 页</span>
      <button type="button" aria-label="下一页病例" :disabled="loading || pagination.skip + pagination.limit >= pagination.total" @click="$emit('page', pagination.skip + pagination.limit)">下一页</button>
    </nav>
  </section>
</template>

<script setup lang="ts">
import type { LongitudinalCase } from '@/api/operator'

withDefaults(defineProps<{
  pagination?: { total: number; skip: number; limit: number }
  cases: LongitudinalCase[]
  selectedId?: number
  query?: string
  status?: 'active' | 'archived'
  loading?: boolean
}>(), { pagination: () => ({ total: 0, skip: 0, limit: 20 }) })

defineEmits<{
  page: [skip: number]
  select: [item: LongitudinalCase]
  new: []
  'update:query': [value: string]
  'update:status': [value: 'active' | 'archived']
}>()
</script>

<style scoped>
.case-list { display: grid; gap: var(--space-3); }
.case-list__toolbar { display: flex; gap: var(--space-2); align-items: end; }
.case-list__toolbar label { flex: 1; display: grid; gap: var(--space-1); color: var(--text-secondary); font-size: var(--text-xs); }
.case-list input, .case-list select { min-height: 44px; border: 1px solid var(--border-default); border-radius: var(--radius-input); padding: 0 var(--space-3); background: var(--bg-input); color:var(--text-primary); }
.case-list button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-4); color: var(--text-primary); background: var(--bg-surface); cursor: pointer; }
.case-list__toolbar button { color: white; background: var(--color-primary); }
.case-list__item { display: grid; gap: 4px; text-align: left; border: 1px solid var(--border-light); box-shadow: var(--shadow-sm); }
.case-list__item.selected { border-color: var(--border-focus); box-shadow: 0 0 0 3px hsla(200, 65%, 40%, .16); }
.case-list__item span { color: var(--text-secondary); font-size: var(--text-sm); }
.case-list__state { padding: var(--space-6); color: var(--text-secondary); text-align: center; }
.case-list__pagination { display: flex; align-items: center; justify-content: space-between; gap: var(--space-2); color: var(--text-secondary); font-size: var(--text-xs); }
.case-list__pagination button { border: 1px solid var(--color-primary); border-radius: var(--radius-pill); color: var(--color-primary); }
.case-list button:disabled { opacity: .4; cursor: not-allowed; }
.case-list button:focus-visible { box-shadow: 0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--color-primary); }
</style>
