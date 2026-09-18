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
          <thead><tr><th scope="col">指标</th><th scope="col">时距</th><th scope="col">目标日期</th><th scope="col">{{ trainedDocument ? '模型预测值' : '数值' }}</th><th v-if="trainedDocument" scope="col">末次值保持基线</th><th scope="col">单位</th><th scope="col">{{ historyDocument ? '模型状态' : '可用状态' }}</th><th scope="col">{{ historyDocument ? '模型原因' : '缺失原因' }}</th><th v-if="historyDocument" scope="col">基线状态与原因</th><th v-if="historyDocument" scope="col">任务算法</th></tr></thead>
          <tbody><tr v-for="row in predictions" :key="row.task_id"><td>{{ row.indicator.toUpperCase() }}</td><td>{{ row.horizon_months }} 个月</td><td>{{ row.target_date }}</td><td>{{ row.status === 'available' ? displayValue(row.value) : '—' }}</td><td v-if="trainedDocument">{{ baselineValue(row.task_id) }}</td><td>{{ row.unit }}</td><td>{{ statusLabel(row.status, row.reason) }}</td><td>{{ reasonLabel(row.reason) }}</td><td v-if="historyDocument">{{ baselineStatus(row.task_id) }}</td><td v-if="historyDocument">{{ 'algorithm' in row ? algorithmLabel(row.algorithm) : '—' }}</td></tr></tbody>
        </table></div>
        <p v-if="trainedDocument" class="numeric-report__precision">预测结果与比较基线的展示值已四舍五入至两位小数，保存值保持原始精度。</p>
      </section>
      <section class="numeric-report__section" aria-label="输入完整性与历史覆盖">
        <h4>输入完整性与历史覆盖</h4>
        <p v-for="packet in numericInput.packets" :key="packet.task_id">{{ packet.horizon_months }} 个月：{{ historyLabels[packet.history_state] }}；{{ packet.input_status === 'available' ? '输入可用' : reasonLabel(packet.input_reason) }}</p>
      </section>
      <template v-if="trainedDocument">
        <section class="numeric-report__section" aria-label="已保存的结果说明">
          <h4>结果说明</h4>
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
      <section class="numeric-report__section" aria-label="算法说明">
        <h4>模型与生成版本</h4>
        <template v-if="historyContext">
          <p v-for="task in contextTasks" :key="task.task_id" class="numeric-report__task-algorithm">{{ task.horizon_months }} 个月任务：{{ algorithmLabel(task.algorithm) }}；输入特征：{{ task.algorithm.feature_names.map(name => featureLabels[name]).join('、') }}。算法版本：{{ task.algorithm.algorithm_version }}</p>
          <p>末次值保持（last_value）作为比较基线；报告保存完成不表示全部任务预测可用。</p>
        </template>
        <template v-else-if="trainedContext">
          <p>模型：Ridge（{{ trainedContext.algorithm.model_id }}），使用固定模型参数和锚点值计算。</p>
          <p>末次值保持（last_value）作为比较基线；当前展示不表示模型优于基线。</p>
        </template>
        <p v-else-if="generationContext">算法：末次值保持（last_value），无拟合基线，仅使用锚点值。</p>
        <p v-else>未保存可验证的算法身份。</p>
        <p>只展示生成时保存的输入和结果；未作临床有效性或正式应用结论。</p>
        <p v-if="generationContext">算法版本：{{ generationContext.algorithm.algorithm_version.startsWith('synthetic_numeric.') ? '末次值保持（历史版本）' : generationContext.algorithm.algorithm_version }}</p>
        <p v-if="trainedDocument">说明模型：{{ trainedDocument.narrative.response_model || trainedDocument.narrative.model }}</p>
      </section>
    </template>
    <p v-else role="alert">数值输入快照无法验证或版本不受支持，已停止展示输入。</p>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { NumericObservation, NumericTaskAlgorithm, NumericTaskPrediction, NumericTaskPredictionV3, ObservedChart, SyntheticGenerationContext, SyntheticNumericInput, SyntheticNumericReportDocumentV1, NumericReportDocumentV1, NumericReportDocumentV2, NumericReportDocumentV3 } from '@/types/report-document'
import ReportDocumentCharts from './ReportDocumentCharts.vue'
const props = defineProps<{ document?: SyntheticNumericReportDocumentV1 | NumericReportDocumentV1 | NumericReportDocumentV2 | NumericReportDocumentV3; input?: SyntheticNumericInput | NumericReportDocumentV1['numeric_input'] | null; context?: SyntheticGenerationContext | NumericReportDocumentV1['generation_context'] | NumericReportDocumentV2['generation_context'] | NumericReportDocumentV3['generation_context'] | null; anonymousCaseCode?: string | null }>()
const numericInput = computed(() => props.document?.numeric_input || props.input)
const generationContext = computed(() => props.document?.generation_context || props.context)
const trainedDocument = computed(() => props.document?.schema_version === 'numeric_report_document.v2' || props.document?.schema_version === 'numeric_report_document.v3' ? props.document : null)
const historyDocument = computed(() => props.document?.schema_version === 'numeric_report_document.v3' ? props.document : null)
const historyContext = computed(() => generationContext.value?.schema_version === 'numeric_generation_context.v3' ? generationContext.value : null)
const contextTasks = computed(() => [...(numericInput.value?.packets || [])].sort((a, b) => a.horizon_months - b.horizon_months).flatMap(packet => {
  const algorithm = historyContext.value?.task_algorithms[packet.task_id]
  return algorithm ? [{ task_id: packet.task_id, horizon_months: packet.horizon_months, algorithm }] : []
}))
const featureLabels = { anchor_value: '锚点实测值', prior_value: '最近历史实测值', slope_per_day: '历史斜率' }
function algorithmLabel(algorithm: NumericTaskAlgorithm) {
  return { 'ridge:main_anchor': 'Ridge（锚点实测值）', 'random_forest:history_v1:value_history': '随机森林（历史数值）', last_value: '末次值保持' }[algorithm.model_id]
}
const trainedContext = computed(() => generationContext.value?.schema_version === 'numeric_generation_context.v2' ? generationContext.value : null)
const predictions = computed(() => [...(props.document?.prediction.predictions || [])].sort((a, b) => a.horizon_months - b.horizon_months))
const resultFormatter = new Intl.NumberFormat('en-US', { useGrouping: false, minimumFractionDigits: 2, maximumFractionDigits: 2 })
function displayValue(value: number | null) {
  if (value === null) return '—'
  if (!trainedDocument.value) return Number(value.toPrecision(6))
  const formatted = resultFormatter.format(value)
  return formatted === '-0.00' ? '0.00' : formatted
}
function baselineValue(taskId: string) {
  const row = trainedDocument.value?.prediction.baseline_predictions.find(item => item.task_id === taskId)
  return row?.status === 'available' ? displayValue(row.value) : '—'
}
const historyLabels = { confirmed_none: '已确认无锚点前历史', observed: '已保存锚点前实测历史', unknown: '历史覆盖未知' }
function reasonLabel(reason: NumericTaskPrediction['reason'] | NumericTaskPredictionV3['reason']) {
  return reason ? { anchor_unavailable: '锚点观测不可用', population_not_confirmed: '适用人群未确认', population_not_known_at_anchor: '锚点时尚未知适用人群', conflicting_history: '历史记录存在冲突', history_coverage_incomplete: '历史覆盖不完整', history_not_observed: '缺少已观察历史', comparable_history_required: '缺少可比历史记录', history_calculation_error: '历史特征计算失败', standardization_error: '特征标准化失败', prediction_calculation_error: '预测计算失败', nonfinite_prediction: '结果非有限值', prediction_out_of_bounds: '结果超出允许范围' }[reason] : '—'
}
function statusLabel(status: NumericTaskPrediction['status'] | NumericTaskPredictionV3['status'], reason: NumericTaskPredictionV3['reason']) {
  if (status === 'available') return '可用'
  if (status === 'error') return '计算失败'
  if (status === 'abstain') return ['history_coverage_incomplete', 'history_not_observed', 'comparable_history_required'].includes(reason || '') ? '历史不足，未预测' : '未预测'
  return '不可用'
}
function baselineStatus(taskId: string) {
  const row = historyDocument.value?.prediction.baseline_predictions.find(item => item.task_id === taskId)
  return row ? `${statusLabel(row.status, row.reason)}${row.reason ? `：${reasonLabel(row.reason)}` : ''}` : '—'
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
.numeric-report__task-algorithm { overflow-wrap: anywhere; }
.numeric-report__citations { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.numeric-report__citations a { display: inline-flex; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; color: var(--text-link); border-radius: var(--radius-item); }
.numeric-report__citations a:focus-visible, .numeric-report__reference:focus-visible { outline: none; box-shadow: 0 0 0 2px var(--bg-canvas), 0 0 0 4px var(--color-primary); }
.numeric-report__reference { padding: var(--space-3); margin-top: var(--space-3); background: var(--bg-canvas); border: 1px solid var(--border-light); border-radius: var(--radius-item); scroll-margin-top: var(--space-6); overflow-wrap: anywhere; }
.numeric-report__reference:target { background: var(--color-accent-light); }
.numeric-report__precision { color: var(--text-secondary); font-size: var(--text-sm); }
.numeric-report__table { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: var(--text-sm); }
th, td { padding: var(--space-3); text-align: left; border-bottom: 1px solid var(--border-light); white-space: nowrap; }
</style>
