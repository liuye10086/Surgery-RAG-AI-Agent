<template>
  <article class="numeric-report" aria-label="数值预测报告">
    <section class="numeric-report__section" aria-label="匿名病例与输入锚点">
      <h4>{{ document?.identity.anonymous_case_code || anonymousCaseCode || '匿名病例编号未记录' }}</h4>
      <p v-if="document">{{ document.identity.disease_name }} · {{ document.identity.age }} 岁</p>
      <p>输入锚点：{{ numericInput?.anchor_date || '未记录' }}</p>
      <p>末次值保持是比较基线，数值相同不表示病情一定不变。<template v-if="document && !trainedDocument">此报告未执行临床标准或参考病例评价。</template></p>
    </section>
    <template v-if="numericInput">
      <ReportDocumentCharts :charts="charts" />
      <p v-if="!charts.length" role="status">没有可展示的已保存实测记录。</p>
      <section v-if="document" class="numeric-report__section" aria-label="6／12月数值结果">
        <h4>6／12月数值结果</h4>
        <div class="numeric-report__table"><table>
          <thead><tr><th scope="col">指标</th><th scope="col">时距</th><th scope="col">目标日期</th><th scope="col">{{ trainedDocument ? '模型预测值' : '数值' }}</th><th v-if="trainedDocument" scope="col">末次值保持基线</th><th scope="col">单位</th><th scope="col">可用状态</th><th scope="col">缺失原因</th></tr></thead>
          <tbody><tr v-for="row in predictions" :key="row.task_id"><td>{{ row.indicator.toUpperCase() }}</td><td>{{ row.horizon_months }} 个月</td><td>{{ row.target_date }}</td><td>{{ row.status === 'available' ? displayValue(row.value) : '—' }}</td><td v-if="trainedDocument">{{ baselineValue(row.task_id) }}</td><td>{{ row.unit }}</td><td>{{ row.status === 'available' ? '可用' : '不可用' }}</td><td>{{ reasonLabel(row.reason) }}</td></tr></tbody>
        </table></div>
      </section>
      <section class="numeric-report__section" aria-label="输入完整性与历史覆盖">
        <h4>输入完整性与历史覆盖</h4>
        <p v-for="packet in numericInput.packets" :key="packet.task_id">{{ packet.horizon_months }} 个月：{{ historyLabels[packet.history_state] }}；{{ packet.input_status === 'available' ? '输入可用' : reasonLabel(packet.input_reason) }}</p>
      </section>
      <section class="numeric-report__section" aria-label="算法说明">
        <h4>算法说明</h4>
        <template v-if="trainedContext">
          <p>模型：Ridge（{{ trainedContext.algorithm.model_id }}），使用固定模型参数和锚点值计算。</p>
          <p>末次值保持（last_value）作为比较基线；当前展示不表示模型优于基线。</p>
        </template>
        <p v-else-if="generationContext">算法：末次值保持（last_value），无拟合基线，仅使用锚点值。</p>
        <p v-else>未保存可验证的算法身份。</p>
        <p>只展示生成时保存的输入和结果；未作临床有效性或正式应用结论。</p>
        <p v-if="generationContext">算法版本：{{ generationContext.algorithm.algorithm_version.startsWith('synthetic_numeric.') ? '末次值保持（历史版本）' : generationContext.algorithm.algorithm_version }}</p>
      </section>
      <template v-if="trainedDocument">
        <section class="numeric-report__section" aria-label="已保存的结果说明">
          <h4>结果说明</h4>
          <p>说明模型：{{ trainedDocument.narrative.model }}</p>
          <div v-for="(section, index) in trainedDocument.narrative.sections" :key="index">
            <h5>{{ section.title }}</h5>
            <p class="numeric-report__saved-text">{{ section.text }}</p>
            <div v-if="section.citation_ids.length" class="numeric-report__citations" aria-label="引用片段">
              <a v-for="id in section.citation_ids" :key="id" :href="`#numeric-reference-${id}`" :aria-label="`查看参考片段 ${id}`">[{{ id }}]</a>
            </div>
          </div>
          <h5>局限性</h5>
          <ul><li v-for="(limitation, index) in trainedDocument.narrative.limitations" :key="index">{{ limitation }}</li></ul>
        </section>
        <section class="numeric-report__section" aria-label="已保存的参考片段">
          <h4>参考片段</h4>
          <p v-if="trainedDocument.evidence.status === 'partial'" role="status">部分检索结果可用，说明仅依据已保存片段。</p>
          <p v-if="!trainedDocument.evidence.items.length" role="status">没有可用的已保存参考片段。</p>
          <article v-for="item in trainedDocument.evidence.items" :id="`numeric-reference-${item.chunk_id}`" :key="item.chunk_id" class="numeric-report__reference" tabindex="-1">
            <h5>[{{ item.chunk_id }}] {{ item.title }}</h5>
            <p class="numeric-report__saved-text">{{ item.content }}</p>
          </article>
        </section>
      </template>
    </template>
    <p v-else role="alert">数值输入快照无法验证或版本不受支持，已停止展示输入。</p>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NumericObservation, NumericTaskPrediction, ObservedChart, SyntheticGenerationContext, SyntheticNumericInput, SyntheticNumericReportDocumentV1, NumericReportDocumentV1, NumericReportDocumentV2 } from '@/types/report-document'
import ReportDocumentCharts from './ReportDocumentCharts.vue'
const props = defineProps<{ document?: SyntheticNumericReportDocumentV1 | NumericReportDocumentV1 | NumericReportDocumentV2; input?: SyntheticNumericInput | NumericReportDocumentV1['numeric_input'] | null; context?: SyntheticGenerationContext | NumericReportDocumentV1['generation_context'] | NumericReportDocumentV2['generation_context'] | null; anonymousCaseCode?: string | null }>()
const numericInput = computed(() => props.document?.numeric_input || props.input)
const generationContext = computed(() => props.document?.generation_context || props.context)
const trainedDocument = computed(() => props.document?.schema_version === 'numeric_report_document.v2' ? props.document : null)
const trainedContext = computed(() => generationContext.value?.schema_version === 'numeric_generation_context.v2' ? generationContext.value : null)
const predictions = computed(() => [...(props.document?.prediction.predictions || [])].sort((a, b) => a.horizon_months - b.horizon_months))
function displayValue(value: number | null) {
  return value === null ? '—' : Number(value.toPrecision(6))
}
function baselineValue(taskId: string) {
  const row = trainedDocument.value?.prediction.baseline_predictions.find(item => item.task_id === taskId)
  return row?.status === 'available' ? displayValue(row.value) : '—'
}
const historyLabels = { confirmed_none: '已确认无锚点前历史', observed: '已保存锚点前实测历史', unknown: '历史覆盖未知' }
function reasonLabel(reason: NumericTaskPrediction['reason']) {
  return reason ? { anchor_unavailable: '锚点观测不可用', population_not_confirmed: '适用人群未确认', population_not_known_at_anchor: '锚点时尚未知适用人群', conflicting_history: '历史记录存在冲突' }[reason] : '—'
}
const charts = computed<ObservedChart[]>(() => {
  const observations = new Map<string, NumericObservation>()
  for (const packet of numericInput.value?.packets || []) {
    for (const item of packet.input_observations) observations.set(item.observation_id, item)
  }
  const groups = new Map<string, ObservedChart>()
  for (const item of observations.values()) {
    const key = `${item.indicator}:${item.unit}:${item.method}`
    const chart = groups.get(key) || { indicator: key, label: item.indicator.toUpperCase(), unit: item.unit, points: [] }
    chart.points.push({ visit_date: item.measured_on, value: item.value })
    groups.set(key, chart)
  }
  const series = [...groups.values()]
  const totals = new Map<string, number>()
  for (const chart of series) totals.set(`${chart.label}:${chart.unit}`, (totals.get(`${chart.label}:${chart.unit}`) || 0) + 1)
  const seen = new Map<string, number>()
  return series.map(chart => {
    const key = `${chart.label}:${chart.unit}`
    const number = (seen.get(key) || 0) + 1
    seen.set(key, number)
    return { ...chart, label: totals.get(key)! > 1 ? `${chart.label} · 序列 ${number}` : chart.label, points: chart.points.sort((a, b) => a.visit_date.localeCompare(b.visit_date)) }
  })
})
</script>

<style scoped>
.numeric-report { color: var(--text-primary); line-height: 1.6; }
.numeric-report__section { padding: var(--space-5); margin: var(--space-4) 0; background: var(--bg-surface); border: 1px solid var(--border-light); border-radius: var(--radius-card); box-shadow: var(--shadow-sm); }
h4 { font-size: var(--text-md); margin: 0 0 var(--space-3); }
h5 { font-size: var(--text-base); margin: var(--space-4) 0 var(--space-2); }
p { max-width: 72ch; margin: var(--space-2) 0; }
.numeric-report__saved-text { white-space: pre-wrap; overflow-wrap: anywhere; }
.numeric-report__citations { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.numeric-report__citations a { display: inline-flex; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; color: var(--text-link); border-radius: var(--radius-item); }
.numeric-report__citations a:focus-visible, .numeric-report__reference:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--color-primary); }
.numeric-report__reference { padding: var(--space-3); margin-top: var(--space-3); background: var(--bg-canvas); border: 1px solid var(--border-light); border-radius: var(--radius-item); scroll-margin-top: var(--space-6); overflow-wrap: anywhere; }
.numeric-report__reference:target { background: var(--color-accent-light); }
.numeric-report__table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: var(--text-sm); }
th, td { padding: var(--space-3); text-align: left; border-bottom: 1px solid var(--border-light); white-space: nowrap; }
</style>
