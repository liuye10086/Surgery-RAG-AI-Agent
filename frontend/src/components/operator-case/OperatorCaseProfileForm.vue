<template>
  <section class="profile-form" aria-labelledby="profile-title">
    <h3 id="profile-title">病例资料</h3>
    <div class="profile-grid">
      <label>疾病<select :value="(model as any).disease_id ?? ''" :disabled="readonly || diseaseLocked" :aria-invalid="Boolean(errorFor('disease_id')) || undefined" :aria-describedby="errorFor('disease_id') ? 'disease-id-error' : undefined" @change="update('disease_id' as any, Number(($event.target as HTMLSelectElement).value))"><option value="">请选择疾病</option><option v-for="disease in diseases" :key="disease.id" :value="disease.id">{{ disease.name }}</option></select><span v-if="errorFor('disease_id')" id="disease-id-error" class="profile-form__error" role="alert">{{ errorFor('disease_id') }}</span></label>
      <label>年龄<input :value="model.age ?? ''" type="number" min="0" max="120" :disabled="readonly" :aria-invalid="Boolean(errorFor('age')) || undefined" :aria-describedby="errorFor('age') ? 'age-error' : undefined" @input="update('age', parseNumber(($event.target as HTMLInputElement).value))" /><span v-if="errorFor('age')" id="age-error" class="profile-form__error" role="alert">{{ errorFor('age') }}</span></label>
      <label>性别<select :value="model.sex ?? ''" :disabled="readonly" :aria-invalid="Boolean(errorFor('sex')) || undefined" :aria-describedby="errorFor('sex') ? 'sex-error' : undefined" @change="update('sex', ($event.target as HTMLSelectElement).value)"><option value="">请选择</option><option value="male">男</option><option value="female">女</option></select><span v-if="errorFor('sex')" id="sex-error" class="profile-form__error" role="alert">{{ errorFor('sex') }}</span></label>
      <label>基线阶段<select :value="model.baseline_stage ?? ''" :disabled="readonly" :aria-invalid="Boolean(errorFor('baseline_stage')) || undefined" :aria-describedby="errorFor('baseline_stage') ? 'baseline-stage-error' : undefined" @change="update('baseline_stage', ($event.target as HTMLSelectElement).value)"><option value="">请选择确定阶段</option><option v-for="option in stageOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select><span v-if="errorFor('baseline_stage')" id="baseline-stage-error" class="profile-form__error" role="alert">{{ errorFor('baseline_stage') }}</span></label>
      <label class="profile-form__notes">备注<textarea :value="model.notes ?? ''" maxlength="5000" :disabled="readonly" @input="update('notes', ($event.target as HTMLTextAreaElement).value || null)" /></label>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { BaselineStage, LongitudinalCaseCreatePayload } from '@/api/operator'

const props = defineProps<{
  model: Pick<LongitudinalCaseCreatePayload, 'age' | 'sex' | 'baseline_stage' | 'notes'>
  diseases?: Array<{ id: number; code: string; name: string }>
  diseaseCode?: string
  diseaseLocked?: boolean
  validationIssues?: Record<string, string>
  readonly?: boolean
}>()
const emit = defineEmits<{ update: [field: 'age' | 'sex' | 'baseline_stage' | 'notes' | 'disease_id', value: unknown] }>()

const labels: Record<BaselineStage, string> = {
  pre_cirrhosis: '肝硬化前期', suspected_cirrhosis: '疑似肝硬化', cirrhosis: '肝硬化', hcc: '肝细胞癌',
  normal: '认知正常', mci: '轻度认知障碍', pre_dementia: '痴呆前期', dementia: '痴呆',
}
const stagesByDisease: Record<string, BaselineStage[]> = {
  fatty_liver: ['pre_cirrhosis', 'suspected_cirrhosis', 'cirrhosis', 'hcc'],
  ad: ['normal', 'mci', 'pre_dementia', 'dementia'],
}
const stageOptions = computed(() => (stagesByDisease[props.diseaseCode || ''] || []).map((value) => ({ value, label: labels[value] })))
function errorFor(field: string) { return props.validationIssues?.[field] }
function parseNumber(value: string): number | null { return value.trim() === '' ? null : Number(value) }
function update(field: 'age' | 'sex' | 'baseline_stage' | 'notes' | 'disease_id', value: unknown) { emit('update', field, value) }
</script>

<style scoped>
.profile-form { background: var(--bg-surface); border: 1px solid var(--border-light); border-radius: var(--radius-card); padding: var(--space-5); box-shadow: var(--shadow-sm); }
.profile-form h3 { margin: 0 0 var(--space-4); color: var(--text-primary); }
.profile-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-4); }
.profile-grid label { display: grid; gap: var(--space-1); color: var(--text-secondary); font-size: var(--text-sm); }
.profile-grid input, .profile-grid select, .profile-grid textarea { min-height: 44px; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-control); padding: var(--space-2) var(--space-3); color: var(--text-primary); background: var(--bg-input); }
.profile-form__notes { grid-column: 1 / -1; }
.profile-grid textarea { min-height: 80px; resize: vertical; }
.profile-form__error { color: var(--color-danger); font-size: var(--text-xs); }
@media (max-width: 760px) { .profile-grid { grid-template-columns: 1fr; } .profile-form__notes { grid-column: auto; } }
</style>
