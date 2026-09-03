<template>
  <section class="case-list" aria-label="我的病例">
    <div class="case-list__toolbar">
      <label>
        <span>搜索匿名编号</span>
        <input :value="query" type="search" placeholder="CASE-" @input="$emit('update:query', ($event.target as HTMLInputElement).value)" />
      </label>
      <button type="button" @click="$emit('new')">新建病例</button>
    </div>
    <div v-if="loading" class="case-list__state" role="status">加载中…</div>
    <div v-else-if="!cases.length" class="case-list__state">暂无病例</div>
    <button v-for="item in cases" v-else :key="item.id" type="button" :class="['case-list__item', { selected: item.id === selectedId }]" @click="$emit('select', item)">
      <strong>{{ item.anonymous_case_code || '待补录匿名编号' }}</strong>
      <span>{{ item.disease.name }} · {{ item.visits.length }} 次访视</span>
    </button>
  </section>
</template>

<script setup lang="ts">
import type { LongitudinalCase } from '@/api/operator'

defineProps<{
  cases: LongitudinalCase[]
  selectedId?: number
  query?: string
  loading?: boolean
}>()

defineEmits<{
  select: [item: LongitudinalCase]
  new: []
  'update:query': [value: string]
}>()
</script>

<style scoped>
.case-list { display: grid; gap: var(--space-3); }
.case-list__toolbar { display: flex; gap: var(--space-2); align-items: end; }
.case-list__toolbar label { flex: 1; display: grid; gap: var(--space-1); color: var(--text-secondary); font-size: var(--text-xs); }
.case-list input { min-height: 44px; border: 1px solid var(--border-default); border-radius: var(--radius-control); padding: 0 var(--space-3); background: var(--bg-input); }
.case-list button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-4); color: var(--text-primary); background: var(--bg-surface); cursor: pointer; }
.case-list__toolbar button { color: white; background: var(--color-primary); }
.case-list__item { display: grid; gap: 4px; text-align: left; border: 1px solid var(--border-light); box-shadow: var(--shadow-sm); }
.case-list__item.selected { border-color: var(--border-focus); box-shadow: 0 0 0 3px hsla(200, 65%, 40%, .16); }
.case-list__item span { color: var(--text-secondary); font-size: var(--text-sm); }
.case-list__state { padding: var(--space-6); color: var(--text-secondary); text-align: center; }
</style>
