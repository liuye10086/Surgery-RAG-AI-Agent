<template>
  <main class="workspace" aria-labelledby="workspace-title">
    <section v-if="boundInput" class="workspace__engineering" aria-label="固定版本输入">
      <strong>已绑定版本的输入只读</strong>
      <p>报告使用已保存的固定输入，不能在此编辑或保存。{{ predictionBlockedReason }}</p>
    </section>
    <header class="workspace__header"><div><h1 id="workspace-title">{{ model?.id ? '病例详情' : '建立病例' }}</h1><p v-if="model?.anonymous_case_code">匿名编号：{{ model.anonymous_case_code }}</p></div><span v-if="legacyIncomplete" class="workspace__warning" role="alert">历史病例资料不完整，请补全后再保存或生成报告。</span></header>
    <section v-if="boundInput && model" class="workspace__summary" aria-label="病例只读摘要">
      <h3>病例资料</h3>
      <p>{{ model.disease.name }} · 年龄 {{ model.age ?? '未记录' }} · 性别 {{ model.sex === 'male' ? '男' : model.sex === 'female' ? '女' : '未记录' }} · 基线阶段 {{ stageLabel(model.baseline_stage) }}</p>
      <p v-if="model.notes">备注：{{ model.notes }}</p>
      <h3>已保存访视</h3>
      <p v-if="!model.visits.length">没有已保存访视。</p>
      <article v-for="visit in model.visits" :key="visit.id">
        <h4>{{ visit.visit_date }}</h4>
        <ul><li v-for="(item, index) in visit.indicators" :key="index">{{ item.name }}：{{ item.value ?? '未记录' }} {{ item.unit }}</li></ul>
        <p v-if="visit.notes">备注：{{ visit.notes }}</p>
      </article>
    </section>
    <template v-else>
      <OperatorCaseProfileForm :model="draftProfile" :diseases="props.diseases" :disease-code="diseaseCode" :disease-locked="Boolean(model?.id)" :validation-issues="validationIssues" :readonly="readonly" @update="updateProfile" />
      <OperatorVisitTimelineEditor :visits="draft.visits" :indicator-catalog="indicatorCatalog" :validation-issues="validationIssues" :readonly="readonly" @update="updateVisits" />
    </template>
    <OperatorCaseActionBar :readonly-reason="readonlyReason || predictionBlockedReason" :input-readonly="boundInput" :show-report="!boundInput || predictionEnabled" :dirty="dirty" :saving="saving" :report-generating="reportGenerating" :readiness="readiness" @save="requestSave" @generate-report="requestReport" />
    <CaseChangeReasonDialog :open="reasonOpen" @cancel="reasonOpen = false" @confirm="saveWithReason" />
  </main>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { stageLabel } from '@/utils/report-read-model'
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
watch(() => props.model, (model) => { draft.value = makeDraft(model); baseline.value = JSON.stringify(draft.value); reasonOpen.value = false }, { deep: true })
const dirty = computed(() => JSON.stringify(draft.value) !== baseline.value)
defineExpose({ dirty })
const readonlyReason = computed(() => props.model?.disease.operator_enabled === false ? '疾病已停用，当前病例只读，不能保存、生成报告或删除病例。' : props.model?.status === 'archived' ? '病例已归档，请先恢复病例后再编辑、生成报告或删除。' : props.model?.status !== undefined && props.model.status !== 'active' ? '病例状态未知，已停止写入操作。' : '')
const boundInput = computed(() => Boolean(props.model?.prediction || props.model?.engineering))
const predictionEnabled = computed(() => props.model?.prediction?.verified === true && props.model.prediction.enabled === true && props.model.prediction.report_kind === 'numeric_prediction')
const predictionBlockedReason = computed(() => !boundInput.value ? '' : !props.model?.prediction?.verified ? '绑定输入未通过验证，不能生成报告。' : !predictionEnabled.value ? '数值预测报告功能未启用，不能生成报告。' : '')
const readonly = computed(() => boundInput.value || Boolean(readonlyReason.value) || props.saving || props.reportGenerating)
const diseaseCode = computed(() => props.model?.disease.code || props.diseases?.find((d) => d.id === (draft.value as LongitudinalCaseCreatePayload).disease_id)?.code)
const draftProfile = computed(() => draft.value)
function makeDraft(model?: LongitudinalCase | null): LongitudinalCaseCreatePayload {
  return model ? { disease_id: model.disease_id, age: model.age ?? 0, sex: model.sex || 'male', baseline_stage: (model.baseline_stage || '') as any, notes: model.notes || null, visits: model.visits.map((visit) => ({ visit_date: visit.visit_date, indicators: visit.indicators.map((item) => ({ ...item })), notes: visit.notes || null, visit_context: { ...(visit.visit_context || {}) } })) } : { disease_id: 0, age: 0, sex: 'male', baseline_stage: '' as any, notes: null, visits: [{ visit_date: '', indicators: [{ name: '', value: null, unit: '' }], notes: null, visit_context: {} }] }
}
function updateProfile(field: 'age' | 'sex' | 'baseline_stage' | 'notes' | 'disease_id', value: unknown) {
  if (readonly.value) return
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
function updateVisits(visits: LongitudinalCaseCreatePayload['visits']) { if (readonly.value) return; emit('edit'); draft.value = { ...draft.value, visits } as any }
function requestReport() { if (!readonlyReason.value && !predictionBlockedReason.value && !props.saving && !props.reportGenerating && !dirty.value && props.readiness?.ready) emit('generate-report') }
function requestSave() { if (readonly.value) return; if (props.model?.id) reasonOpen.value = true; else emit('save', draft.value) }
function saveWithReason(reason: string) { if (readonly.value || !reasonOpen.value) return; const { disease_id: _diseaseId, ...editable } = draft.value as LongitudinalCaseCreatePayload; reasonOpen.value = false; emit('save', { ...editable, change_reason: reason } as LongitudinalCaseSavePayload) }
</script>

<style scoped>
.workspace { width: min(100%, 880px); margin: 0 auto; padding: var(--space-6) var(--space-4); box-sizing: border-box; }
.workspace__header { display: flex; justify-content: space-between; gap: var(--space-4); align-items: start; margin-bottom: var(--space-5); }
.workspace__header h1 { margin: 0; color: var(--text-primary); font-size: var(--text-xl); }
.workspace__header p { margin: var(--space-1) 0 0; color: var(--text-secondary); }
.workspace__warning { max-width: 360px; padding: var(--space-3); border-radius: var(--radius-control); color: var(--text-primary); background: var(--color-accent-light); }
.workspace__engineering { margin-bottom: var(--space-4); padding: var(--space-4); border-radius: var(--radius-card); background: var(--color-accent-light); color: var(--text-primary); line-height: 1.6; }
.workspace__engineering p { margin: var(--space-2) 0 0; font-size: var(--text-sm); }
.workspace__summary { padding: var(--space-5); color: var(--text-primary); background: var(--bg-surface); border: 1px solid var(--border-light); border-radius: var(--radius-card); box-shadow: var(--shadow-sm); line-height: 1.6; }
.workspace__summary h3 { font-size: var(--text-md); margin: 0 0 var(--space-3); }
.workspace__summary h4 { margin: var(--space-4) 0 var(--space-2); }
.workspace__summary p { max-width: 72ch; overflow-wrap: anywhere; }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; } }
</style>
