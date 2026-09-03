<template>
  <main class="workspace" aria-labelledby="workspace-title">
    <header class="workspace__header"><div><h1 id="workspace-title">{{ model?.id ? '病例详情' : '建立病例' }}</h1><p v-if="model?.anonymous_case_code">匿名编号：{{ model.anonymous_case_code }}</p></div><span v-if="legacyIncomplete" class="workspace__warning" role="alert">历史病例资料不完整，请补全后再保存或生成报告。</span></header>
    <OperatorCaseProfileForm :model="draftProfile" :diseases="props.diseases" :disease-code="diseaseCode" :disease-locked="Boolean(model?.id)" :validation-issues="validationIssues" :readonly="readonly" @update="updateProfile" />
    <OperatorVisitTimelineEditor :visits="draft.visits" :indicator-catalog="indicatorCatalog" :validation-issues="validationIssues" :readonly="readonly" @update="updateVisits" />
    <OperatorCaseActionBar :dirty="dirty" :saving="saving" :report-generating="reportGenerating" :readiness="readiness" @save="requestSave" @generate-report="$emit('generate-report')" />
    <CaseChangeReasonDialog :open="reasonOpen" @cancel="reasonOpen = false" @confirm="saveWithReason" />
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { LongitudinalCase, LongitudinalCaseCreatePayload, LongitudinalCaseSavePayload, OperatorCaseReportReadiness, OperatorIndicatorCatalog } from '@/api/operator'
import OperatorCaseProfileForm from './OperatorCaseProfileForm.vue'
import OperatorVisitTimelineEditor from './OperatorVisitTimelineEditor.vue'
import OperatorCaseActionBar from './OperatorCaseActionBar.vue'
import CaseChangeReasonDialog from './CaseChangeReasonDialog.vue'

const props = withDefaults(defineProps<{ model?: LongitudinalCase | null; diseases?: Array<{ id: number; code: string; name: string }>; indicatorCatalog?: OperatorIndicatorCatalog | null; validationIssues?: Record<string, string>; readiness?: OperatorCaseReportReadiness | null; saving?: boolean; legacyIncomplete?: boolean; reportGenerating?: boolean }>(), {
  model: null,
  diseases: () => [],
  indicatorCatalog: null,
  validationIssues: () => ({}),
  readiness: null,
  saving: false,
  legacyIncomplete: false,
  reportGenerating: false,
})
const emit = defineEmits<{ save: [payload: LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload]; 'generate-report': []; 'disease-change': [code: string]; edit: [] }>()
const reasonOpen = ref(false)
const draft = ref<LongitudinalCaseCreatePayload | LongitudinalCaseSavePayload>(makeDraft(props.model))
const baseline = ref(JSON.stringify(draft.value))
watch(() => props.model, (model) => { if (model) { draft.value = makeDraft(model); baseline.value = JSON.stringify(draft.value) } }, { deep: true })
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
const readonly = computed(() => props.model?.status !== undefined && props.model.status !== 'active')
const diseaseCode = computed(() => props.model?.disease.code || props.diseases?.find((d) => d.id === (draft.value as LongitudinalCaseCreatePayload).disease_id)?.code)
const draftProfile = computed(() => draft.value)
function makeDraft(model?: LongitudinalCase | null): LongitudinalCaseCreatePayload {
  return model ? { disease_id: model.disease_id, age: model.age ?? 0, sex: model.sex || 'male', baseline_stage: (model.baseline_stage || '') as any, notes: model.notes || null, visits: model.visits.map((visit) => ({ visit_date: visit.visit_date, indicators: visit.indicators.map((item) => ({ ...item })), notes: visit.notes || null, visit_context: { ...(visit.visit_context || {}) } })) } : { disease_id: 0, age: 0, sex: 'male', baseline_stage: '' as any, notes: null, visits: [{ visit_date: '', indicators: [{ name: '', value: null, unit: '' }], notes: null, visit_context: {} }] }
}
function updateProfile(field: 'age' | 'sex' | 'baseline_stage' | 'notes' | 'disease_id', value: unknown) {
  emit('edit')
  if (field === 'disease_id' && !props.model?.id) {
    const diseaseId = Number(value)
    const code = props.diseases.find((disease) => disease.id === diseaseId)?.code || ''
    draft.value = { ...draft.value, disease_id: diseaseId, baseline_stage: '' as any, visits: draft.value.visits.map((visit) => ({ ...visit, indicators: [{ name: '', value: null, unit: '' }] })) } as any
    emit('disease-change', code)
    return
  }
  draft.value = { ...draft.value, [field]: value } as any
}
function updateVisits(visits: LongitudinalCaseCreatePayload['visits']) { emit('edit'); draft.value = { ...draft.value, visits } as any }
function requestSave() { if (props.model?.id) reasonOpen.value = true; else emit('save', draft.value) }
function saveWithReason(reason: string) { const { disease_id: _diseaseId, ...editable } = draft.value as LongitudinalCaseCreatePayload; reasonOpen.value = false; emit('save', { ...editable, change_reason: reason } as LongitudinalCaseSavePayload) }
</script>

<style scoped>
.workspace { width: min(100%, 880px); margin: 0 auto; padding: var(--space-6) var(--space-4); box-sizing: border-box; }
.workspace__header { display: flex; justify-content: space-between; gap: var(--space-4); align-items: start; margin-bottom: var(--space-5); }
.workspace__header h1 { margin: 0; color: var(--text-primary); font-size: var(--text-xl); }
.workspace__header p { margin: var(--space-1) 0 0; color: var(--text-secondary); }
.workspace__warning { max-width: 360px; padding: var(--space-3); border-radius: var(--radius-control); color: var(--text-primary); background: var(--color-accent-light); }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; } }
</style>
