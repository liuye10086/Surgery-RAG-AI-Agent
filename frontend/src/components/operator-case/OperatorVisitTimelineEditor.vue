<template>
  <section class="timeline" aria-labelledby="timeline-title">
    <div class="timeline__heading">
      <div><h3 id="timeline-title">访视时间线</h3><p>当前 {{ visits.length }}/10 次访视</p></div>
      <button type="button" :disabled="readonly || visits.length >= 10" @click="addVisit">添加访视</button>
    </div>
    <p v-if="visits.length === 0" class="timeline__error" role="alert">至少需要 1 次访视才能保存病例。</p>
    <p v-if="!indicatorCatalog" class="timeline__hint">选择疾病后加载可用指标目录。</p>

    <article v-for="(visit, index) in visits" :key="`${visit.visit_date}-${index}`" class="timeline__card">
      <header><strong>第 {{ index + 1 }} 次访视</strong><button type="button" :disabled="readonly || visits.length <= 1" @click="removeVisit(index)">删除访视</button></header>
      <label>日期<input :value="visit.visit_date" type="date" :disabled="readonly" :aria-invalid="Boolean(fieldError(`visits.${index}.visit_date`)) || undefined" :aria-describedby="fieldError(`visits.${index}.visit_date`) ? errorId(`visits.${index}.visit_date`) : undefined" @input="updateDate(index, ($event.target as HTMLInputElement).value)" /><span v-if="fieldError(`visits.${index}.visit_date`)" :id="errorId(`visits.${index}.visit_date`)" class="timeline__error" role="alert">{{ fieldError(`visits.${index}.visit_date`) }}</span></label>

      <div class="timeline__indicators">
        <div class="timeline__subheading"><span>检测指标</span><button type="button" aria-label="添加指标" :disabled="readonly || !indicatorCatalog || visit.indicators.length >= 30" @click="addIndicator(index)">添加指标</button></div>
        <div v-for="(indicator, indicatorIndex) in visit.indicators" :key="indicatorIndex" class="timeline__indicator">
          <label>指标
            <select :value="indicator.name" aria-label="指标名称" :disabled="readonly || !indicatorCatalog" :aria-invalid="Boolean(indicatorError(index, indicatorIndex, 'name')) || undefined" :aria-describedby="indicatorError(index, indicatorIndex, 'name') ? errorId(`visits.${index}.indicators.${indicatorIndex}.name`) : undefined" @change="selectIndicator(index, indicatorIndex, ($event.target as HTMLSelectElement).value)">
              <option value="">请选择指标</option>
              <option v-if="isLegacyIndicator(indicator.name)" :value="indicator.name">历史指标：{{ indicator.name }}</option>
              <option v-for="item in availableIndicators(visit, indicatorIndex)" :key="item.code" :value="item.code">{{ item.name_cn || item.name_en }}（{{ item.name_en }}）</option>
            </select>
            <span v-if="indicatorError(index, indicatorIndex, 'name')" :id="errorId(`visits.${index}.indicators.${indicatorIndex}.name`)" class="timeline__error" role="alert">{{ indicatorError(index, indicatorIndex, 'name') }}</span>
            <span v-if="isLegacyIndicator(indicator.name)" class="timeline__warning" role="status">历史指标 {{ indicator.name }} 不在当前目录中，请重新选择后再保存。</span>
          </label>
          <label>数值<input :value="indicator.value ?? ''" aria-label="指标值" type="number" :disabled="readonly" :aria-invalid="Boolean(indicatorError(index, indicatorIndex, 'value')) || undefined" :aria-describedby="indicatorError(index, indicatorIndex, 'value') ? errorId(`visits.${index}.indicators.${indicatorIndex}.value`) : undefined" @input="updateIndicator(index, indicatorIndex, 'value', parseNumber(($event.target as HTMLInputElement).value))" /><span v-if="indicatorError(index, indicatorIndex, 'value')" :id="errorId(`visits.${index}.indicators.${indicatorIndex}.value`)" class="timeline__error" role="alert">{{ indicatorError(index, indicatorIndex, 'value') }}</span></label>
          <label>单位
            <select :value="indicator.unit" aria-label="指标单位" :disabled="readonly || !catalogItem(indicator.name)" :aria-invalid="Boolean(indicatorError(index, indicatorIndex, 'unit')) || undefined" :aria-describedby="indicatorError(index, indicatorIndex, 'unit') ? errorId(`visits.${index}.indicators.${indicatorIndex}.unit`) : undefined" @change="updateIndicator(index, indicatorIndex, 'unit', ($event.target as HTMLSelectElement).value)">
              <option value="">请选择单位</option>
              <option v-if="indicator.unit && !allowedUnits(indicator.name).includes(indicator.unit)" :value="indicator.unit">{{ indicator.unit }}（历史）</option>
              <option v-for="unit in allowedUnits(indicator.name)" :key="unit" :value="unit">{{ unit }}</option>
            </select>
            <span v-if="indicatorError(index, indicatorIndex, 'unit')" :id="errorId(`visits.${index}.indicators.${indicatorIndex}.unit`)" class="timeline__error" role="alert">{{ indicatorError(index, indicatorIndex, 'unit') }}</span>
          </label>
          <button type="button" class="timeline__remove-indicator" aria-label="删除指标" :disabled="readonly || visit.indicators.length <= 1" @click="removeIndicator(index, indicatorIndex)">删除</button>
        </div>
      </div>

      <details class="timeline__context">
        <summary>检测信息</summary><p>用于解释检测条件；未填写时不会生成推测值。</p>
        <div class="timeline__context-grid">
          <label>检测来源
            <select :value="visit.visit_context?.source_type ?? ''" aria-label="检测来源" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'source_type')) || undefined" :aria-describedby="contextError(index, 'source_type') ? errorId(`visits.${index}.visit_context.source_type`) : undefined" @change="updateContext(index, 'source_type', (($event.target as HTMLSelectElement).value as VisitSourceType) || null)">
              <option value="">未填写</option><option value="lab">实验室</option><option value="imaging">影像</option><option value="assessment">量表评估</option><option value="clinical">临床观察</option><option value="other">其他</option>
            </select>
            <span v-if="contextError(index, 'source_type')" :id="errorId(`visits.${index}.visit_context.source_type`)" class="timeline__error" role="alert">{{ contextError(index, 'source_type') }}</span>
          </label>
          <label>机构名称<input :value="visit.visit_context?.facility_name ?? ''" maxlength="200" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'facility_name')) || undefined" @input="updateContext(index, 'facility_name', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'facility_name')" class="timeline__error" role="alert">{{ contextError(index, 'facility_name') }}</span></label>
          <label>设备名称<input :value="visit.visit_context?.device_name ?? ''" maxlength="200" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'device_name')) || undefined" @input="updateContext(index, 'device_name', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'device_name')" class="timeline__error" role="alert">{{ contextError(index, 'device_name') }}</span></label>
          <label>检测方法<input :value="visit.visit_context?.method ?? ''" maxlength="200" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'method')) || undefined" @input="updateContext(index, 'method', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'method')" class="timeline__error" role="alert">{{ contextError(index, 'method') }}</span></label>
          <label>样本类型<input :value="visit.visit_context?.specimen ?? ''" maxlength="100" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'specimen')) || undefined" @input="updateContext(index, 'specimen', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'specimen')" class="timeline__error" role="alert">{{ contextError(index, 'specimen') }}</span></label>
          <label>是否基线检测<select :value="optionalBooleanValue(visit.visit_context?.is_baseline)" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'is_baseline')) || undefined" @change="updateContext(index, 'is_baseline', parseOptionalBoolean(($event.target as HTMLSelectElement).value))"><option value="">未填写</option><option value="true">是</option><option value="false">否</option></select><span v-if="contextError(index, 'is_baseline')" class="timeline__error" role="alert">{{ contextError(index, 'is_baseline') }}</span></label>
          <label v-if="indicatorCatalog?.disease_code === 'fatty_liver'">影像检查类型<input :value="visit.visit_context?.imaging_type ?? ''" maxlength="100" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'imaging_type')) || undefined" @input="updateContext(index, 'imaging_type', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'imaging_type')" class="timeline__error" role="alert">{{ contextError(index, 'imaging_type') }}</span></label>
          <template v-if="indicatorCatalog?.disease_code === 'ad'">
            <label>量表版本<input :value="visit.visit_context?.scale_version ?? ''" maxlength="100" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'scale_version')) || undefined" @input="updateContext(index, 'scale_version', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'scale_version')" class="timeline__error" role="alert">{{ contextError(index, 'scale_version') }}</span></label>
            <label>评估语言<input :value="visit.visit_context?.assessment_language ?? ''" maxlength="50" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'assessment_language')) || undefined" @input="updateContext(index, 'assessment_language', nullableText(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'assessment_language')" class="timeline__error" role="alert">{{ contextError(index, 'assessment_language') }}</span></label>
            <label>受教育年限<input :value="visit.visit_context?.education_years ?? ''" type="number" min="0" max="30" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'education_years')) || undefined" @input="updateContext(index, 'education_years', parseNumber(($event.target as HTMLInputElement).value))" /><span v-if="contextError(index, 'education_years')" class="timeline__error" role="alert">{{ contextError(index, 'education_years') }}</span></label>
            <label>是否校正教育年限<select :value="optionalBooleanValue(visit.visit_context?.education_adjusted)" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'education_adjusted')) || undefined" @change="updateContext(index, 'education_adjusted', parseOptionalBoolean(($event.target as HTMLSelectElement).value))"><option value="">未填写</option><option value="true">是</option><option value="false">否</option></select><span v-if="contextError(index, 'education_adjusted')" class="timeline__error" role="alert">{{ contextError(index, 'education_adjusted') }}</span></label>
          </template>
          <label class="timeline__context-wide">治疗变化<textarea :value="visit.visit_context?.treatment_change ?? ''" maxlength="2000" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'treatment_change')) || undefined" @input="updateContext(index, 'treatment_change', nullableText(($event.target as HTMLTextAreaElement).value))" /><span v-if="contextError(index, 'treatment_change')" class="timeline__error" role="alert">{{ contextError(index, 'treatment_change') }}</span></label>
          <label class="timeline__context-wide">诊断变化<textarea :value="visit.visit_context?.diagnosis_change ?? ''" maxlength="2000" :disabled="readonly" :aria-invalid="Boolean(contextError(index, 'diagnosis_change')) || undefined" @input="updateContext(index, 'diagnosis_change', nullableText(($event.target as HTMLTextAreaElement).value))" /><span v-if="contextError(index, 'diagnosis_change')" class="timeline__error" role="alert">{{ contextError(index, 'diagnosis_change') }}</span></label>
        </div>
      </details>
      <label>备注<textarea :value="visit.notes ?? ''" :disabled="readonly" @input="updateNotes(index, ($event.target as HTMLTextAreaElement).value || null)" /></label>
    </article>
  </section>
</template>

<script setup lang="ts">
import type { IndicatorInput, LongitudinalVisitInput, OperatorIndicatorCatalog, OperatorIndicatorCatalogItem, VisitContext, VisitSourceType } from '@/api/operator'

const props = defineProps<{ visits: LongitudinalVisitInput[]; indicatorCatalog?: OperatorIndicatorCatalog | null; validationIssues?: Record<string, string>; readonly?: boolean }>()
const emit = defineEmits<{ update: [visits: LongitudinalVisitInput[]] }>()

function clone() { return props.visits.map((visit) => ({ ...visit, indicators: visit.indicators.map((indicator) => ({ ...indicator })), visit_context: { ...(visit.visit_context || {}) } })) }
function catalogItem(code: string): OperatorIndicatorCatalogItem | undefined { return props.indicatorCatalog?.items.find((item) => item.code === code) }
function isLegacyIndicator(code: string): boolean { return Boolean(code && !catalogItem(code)) }
function availableIndicators(visit: LongitudinalVisitInput, indicatorIndex: number) { const selected = new Set(visit.indicators.filter((_, index) => index !== indicatorIndex).map((indicator) => indicator.name)); return props.indicatorCatalog?.items.filter((item) => !selected.has(item.code)) || [] }
function allowedUnits(code: string): string[] { return catalogItem(code)?.allowed_units || [] }
function fieldError(...paths: string[]): string | undefined { for (const path of paths) { const message = props.validationIssues?.[path]; if (message) return message }; return undefined }
function errorId(path: string): string { return `${path.split('.').join('-')}-error` }
function indicatorError(visitIndex: number, indicatorIndex: number, field: keyof IndicatorInput): string | undefined { return fieldError(`visits.${visitIndex}.indicators.${indicatorIndex}.${field}`, `visits.${visitIndex}.indicators`) }
function contextError(visitIndex: number, field: keyof VisitContext): string | undefined { return fieldError(`visits.${visitIndex}.visit_context.${field}`, `visits.${visitIndex}.visit_context`) }
function parseNumber(value: string): number | null { const trimmed = value.trim(); return trimmed === '' ? null : Number(trimmed) }
function nullableText(value: string): string | null { return value.trim() || null }
function optionalBooleanValue(value: boolean | null | undefined): string { return value === true ? 'true' : value === false ? 'false' : '' }
function parseOptionalBoolean(value: string): boolean | null { return value === 'true' ? true : value === 'false' ? false : null }
function addVisit() { emit('update', [...clone(), { visit_date: '', indicators: [{ name: '', value: null, unit: '' }], notes: null, visit_context: {} }]) }
function removeVisit(index: number) { if (props.visits.length <= 1) return; const next = clone(); next.splice(index, 1); emit('update', next) }
function addIndicator(visitIndex: number) { const next = clone(); next[visitIndex].indicators.push({ name: '', value: null, unit: '' }); emit('update', next) }
function removeIndicator(visitIndex: number, indicatorIndex: number) { if (props.visits[visitIndex].indicators.length <= 1) return; const next = clone(); next[visitIndex].indicators.splice(indicatorIndex, 1); emit('update', next) }
function updateDate(index: number, value: string) { const next = clone(); next[index].visit_date = value; emit('update', next) }
function updateNotes(index: number, value: string | null) { const next = clone(); next[index].notes = value; emit('update', next) }
function selectIndicator(index: number, indicatorIndex: number, code: string) { const item = catalogItem(code); const next = clone(); const current = next[index].indicators[indicatorIndex]; next[index].indicators[indicatorIndex] = { ...current, name: code, unit: item?.default_unit || item?.allowed_units[0] || '' }; emit('update', next) }
function updateIndicator(index: number, indicatorIndex: number, field: keyof IndicatorInput, value: string | number | null) { const next = clone(); next[index].indicators[indicatorIndex] = { ...next[index].indicators[indicatorIndex], [field]: value }; emit('update', next) }
function updateContext<K extends keyof VisitContext>(index: number, field: K, value: VisitContext[K]) { const next = clone(); next[index].visit_context = { ...(next[index].visit_context || {}), [field]: value }; emit('update', next) }
</script>

<style scoped>
.timeline { margin-top: var(--space-6); }
.timeline__heading, .timeline__subheading { display: flex; justify-content: space-between; align-items: center; gap: var(--space-3); }
.timeline__heading h3 { margin: 0; color: var(--text-primary); }
.timeline__heading p, .timeline__context p { margin: var(--space-1) 0 0; color: var(--text-secondary); font-size: var(--text-sm); }
.timeline button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-4); color: white; background: var(--color-primary); cursor: pointer; }
.timeline button:disabled { color: var(--text-disabled); background: var(--bg-hover); cursor: not-allowed; }
.timeline__card { display: grid; gap: var(--space-4); margin-top: var(--space-4); padding: var(--space-5); border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.timeline__card > header { display: flex; justify-content: space-between; align-items: center; }
.timeline__card > header button, .timeline__remove-indicator { color: var(--color-danger) !important; background: transparent !important; padding: 0 var(--space-2) !important; }
.timeline label { display: grid; gap: var(--space-1); color: var(--text-secondary); font-size: var(--text-sm); }
.timeline input, .timeline select, .timeline textarea { width: 100%; min-height: 44px; box-sizing: border-box; border: 1px solid var(--border-default); border-radius: var(--radius-control); padding: var(--space-2) var(--space-3); color: var(--text-primary); background: var(--bg-input); }
.timeline textarea { min-height: 72px; resize: vertical; }
.timeline__indicators { display: grid; gap: var(--space-3); }
.timeline__indicator { display: grid; grid-template-columns: minmax(180px, 2fr) minmax(120px, 1fr) minmax(120px, 1fr) auto; gap: var(--space-2); align-items: end; }
.timeline__context { padding: var(--space-3); border: 1px solid var(--border-light); border-radius: var(--radius-control); background: var(--bg-canvas); }
.timeline__context summary { min-height: 44px; display: flex; align-items: center; color: var(--text-primary); font-weight: 600; cursor: pointer; }
.timeline__context-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-3); margin-top: var(--space-3); }
.timeline__context-wide { grid-column: 1 / -1; }
.timeline__error, .timeline__warning { color: var(--color-danger); }
.timeline__warning, .timeline__hint { font-size: var(--text-xs); }
.timeline__hint { color: var(--text-secondary); }
@media (max-width: 760px) { .timeline__indicator, .timeline__context-grid { grid-template-columns: 1fr; } .timeline__context-wide { grid-column: auto; } }
</style>
