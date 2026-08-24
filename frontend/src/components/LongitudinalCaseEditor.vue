<template>
  <section class="longitudinal-editor" aria-labelledby="longitudinal-editor-title">
    <div class="editor-heading">
      <div>
        <h3 id="longitudinal-editor-title">纵向病例</h3>
        <p>保存同一病例的多次访视结果，再生成进展预测报告。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="saveCase">保存病例</el-button>
    </div>
    <div class="editor-grid">
      <el-input v-model="draft.patient_label" placeholder="病例内部标签" aria-label="病例内部标签" />
      <el-select v-model="draft.disease_id" placeholder="选择疾病" aria-label="选择疾病">
        <el-option v-for="disease in diseases" :key="disease.id" :label="disease.name" :value="disease.id" />
      </el-select>
      <el-select v-model="draft.sex" clearable placeholder="性别" aria-label="性别">
        <el-option label="男" value="male" /><el-option label="女" value="female" />
      </el-select>
    </div>
    <div class="visit-timeline">
      <article v-for="(visit, index) in draft.visits" :key="visit.id || index" class="visit-item">
        <div class="visit-title"><strong>访视 {{ index + 1 }}</strong><el-button text type="danger" @click="removeVisit(index)">删除</el-button></div>
        <el-date-picker v-model="visit.visit_date" type="date" value-format="YYYY-MM-DD" aria-label="访视日期" />
        <div v-for="(indicator, indicatorIndex) in visit.indicators" :key="indicatorIndex" class="indicator-row">
          <el-input v-model="indicator.name" placeholder="指标" /><el-input-number v-model="indicator.value" placeholder="数值" /><el-input v-model="indicator.unit" placeholder="单位" />
        </div>
        <el-button text @click="visit.indicators.push({ name: '', value: null, unit: '' })">添加指标</el-button>
      </article>
    </div>
    <el-button :disabled="draft.visits.length >= 10" @click="addVisit">添加访视</el-button>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import type { Disease, LongitudinalCase } from '@/api/operator'

const props = defineProps<{ diseases: Disease[]; modelValue?: LongitudinalCase | null }>()
const emit = defineEmits<{ saved: [LongitudinalCase]; 'update:modelValue': [LongitudinalCase] }>()
const saving = ref(false)
const draft = reactive<any>({ patient_label: props.modelValue?.patient_label || '', disease_id: props.modelValue?.disease_id || null, sex: props.modelValue?.sex || null, visits: props.modelValue?.visits ? props.modelValue.visits.map((visit) => ({ ...visit, indicators: [...visit.indicators] })) : [] })
function addVisit() { draft.visits.push({ visit_date: '', indicators: [{ name: '', value: null, unit: '' }] }) }
function removeVisit(index: number) { draft.visits.splice(index, 1) }
async function saveCase() { saving.value = true; try { emit('saved', draft as LongitudinalCase); emit('update:modelValue', draft as LongitudinalCase) } finally { saving.value = false } }
</script>

<style scoped>
.longitudinal-editor { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); padding: var(--space-5); box-shadow: var(--shadow-sm); }
.editor-heading, .visit-title { display: flex; justify-content: space-between; align-items: center; gap: var(--space-4); }
.editor-heading h3 { margin: 0; color: var(--text-primary); font-size: var(--text-lg); }
.editor-heading p { color: var(--text-secondary); font-size: var(--text-sm); }
.editor-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-3); margin: var(--space-4) 0; }
.visit-timeline { display: grid; gap: var(--space-4); margin-bottom: var(--space-4); }
.visit-item { border: 1px solid var(--border-light); border-radius: var(--radius-item); padding: var(--space-4); background: var(--bg-canvas); }
.indicator-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: var(--space-2); margin-top: var(--space-2); }
@media (max-width: 720px) { .editor-grid, .indicator-row { grid-template-columns: 1fr; } }
</style>
