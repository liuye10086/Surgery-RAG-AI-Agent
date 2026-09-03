<template>
  <section class="timeline" aria-labelledby="timeline-title">
    <div class="timeline__heading"><h3 id="timeline-title">访视时间线</h3><button type="button" :disabled="readonly || visits.length >= 10" @click="addVisit">添加访视</button></div>
    <p v-if="visits.length === 0" class="timeline__error" role="alert">至少需要 1 次访视才能保存病例。</p>
    <article v-for="(visit, index) in visits" :key="`${visit.visit_date}-${index}`" class="timeline__card">
      <header><strong>第 {{ index + 1 }} 次访视</strong><button type="button" :disabled="readonly || visits.length <= 1" @click="removeVisit(index)">删除</button></header>
      <label>日期<input :value="visit.visit_date" type="date" :disabled="readonly" @input="updateDate(index, ($event.target as HTMLInputElement).value)" /></label>
      <label>备注<textarea :value="visit.notes ?? ''" :disabled="readonly" @input="updateNotes(index, ($event.target as HTMLTextAreaElement).value || null)" /></label>
      <div v-for="(indicator, indicatorIndex) in visit.indicators" :key="indicatorIndex" class="timeline__indicator">
        <input :value="indicator.name" aria-label="指标名称" :disabled="readonly" @input="updateIndicator(index, indicatorIndex, 'name', ($event.target as HTMLInputElement).value)" />
        <input :value="indicator.value ?? ''" aria-label="指标值" type="number" :disabled="readonly" @input="updateIndicator(index, indicatorIndex, 'value', Number(($event.target as HTMLInputElement).value))" />
        <input :value="indicator.unit" aria-label="指标单位" :disabled="readonly" @input="updateIndicator(index, indicatorIndex, 'unit', ($event.target as HTMLInputElement).value)" />
      </div>
    </article>
  </section>
</template>

<script setup lang="ts">
import type { LongitudinalVisitInput } from '@/api/operator'

const props = defineProps<{ visits: LongitudinalVisitInput[]; readonly?: boolean }>()
const emit = defineEmits<{ update: [visits: LongitudinalVisitInput[]] }>()
function clone() { return props.visits.map((visit) => ({ ...visit, indicators: visit.indicators.map((indicator) => ({ ...indicator })) })) }
function addVisit() { emit('update', [...clone(), { visit_date: '', indicators: [{ name: '', value: null, unit: '' }], notes: null }]) }
function removeVisit(index: number) { if (props.visits.length <= 1) return; const next = clone(); next.splice(index, 1); emit('update', next) }
function updateDate(index: number, value: string) { const next = clone(); next[index].visit_date = value; emit('update', next) }
function updateNotes(index: number, value: string | null) { const next = clone(); next[index].notes = value; emit('update', next) }
function updateIndicator(index: number, indicatorIndex: number, field: 'name' | 'value' | 'unit', value: string | number | null) { const next = clone(); next[index].indicators[indicatorIndex] = { ...next[index].indicators[indicatorIndex], [field]: value }; emit('update', next) }
</script>

<style scoped>
.timeline { margin-top: var(--space-6); }
.timeline__heading { display: flex; justify-content: space-between; align-items: center; }
.timeline__heading h3 { margin: 0; }
.timeline button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-4); color: white; background: var(--color-primary); cursor: pointer; }
.timeline button:disabled { color: var(--text-disabled); background: var(--bg-hover); cursor: not-allowed; }
.timeline__card { display: grid; gap: var(--space-3); margin-top: var(--space-4); padding: var(--space-5); border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.timeline__card header { display: flex; justify-content: space-between; align-items: center; }
.timeline__card header button { color: var(--color-danger); background: transparent; padding: 0 var(--space-2); }
.timeline label { display: grid; gap: var(--space-1); color: var(--text-secondary); font-size: var(--text-sm); }
.timeline input, .timeline textarea { min-height: 44px; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-control); padding: var(--space-2) var(--space-3); background: var(--bg-input); }
.timeline textarea { min-height: 64px; }
.timeline__indicator { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--space-2); }
.timeline__error { color: var(--color-danger); }
</style>
