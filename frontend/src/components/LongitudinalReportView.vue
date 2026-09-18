<template>
  <section class="longitudinal-report-view" aria-labelledby="longitudinal-report-title">
    <div class="report-inner">
      <div class="report-head">
        <div>
          <h3 id="longitudinal-report-title">{{ numericReport ? `${report?.anonymous_case_code || '匿名病例'} · 数值预测报告` : report?.title || '纵向进展报告' }}</h3>
          <span class="report-meta">{{ report ? formatTime(report.created_at) : '正在生成' }}</span>
        </div>
        <div class="report-head-actions">
          <el-button :icon="ArrowLeft" @click="$emit('back')">返回</el-button>
          <ReportArchiveActions v-if="report?.status === 'completed' && !invalid && !unsupportedDocument" :report-id="report.id" />
        </div>
      </div>

      <p v-if="invalid" role="alert">报告完整性校验失败，已停止展示内容与导出。</p>
      <template v-else-if="report && report.status !== 'completed'">
        <p role="status">{{ report.status === 'generating' ? '报告正在生成' : report.status === 'cancelled' ? '报告生成已取消' : '报告生成失败' }}；以下为已保存的资料和已确认审计记录。</p>
        <NumericReportView v-if="numericReport" :input="numericInput" :context="numericContext" :anonymous-case-code="report.anonymous_case_code" />
        <LegacyReportSnapshot v-else :snapshot="report.input_snapshot" />
        <ReportGenerationAudit :audit="report.generation_audit" :numeric="numericReport" />
      </template>
      <p v-else-if="unsupportedDocument" role="alert">报告文档版本无法识别或缺失，已停止展示内容与导出。</p>
      <template v-else-if="numericDocument">
        <NumericReportView :document="numericDocument" />
        <ReportGenerationAudit v-if="report?.generation_audit" :audit="report.generation_audit" numeric />
      </template>
      <template v-else>
      <p v-if="report?.integrity_status === 'unverifiable'" role="status">历史资料未完整保存，无法验证完整性。</p>
      <section v-if="document" class="summary-block" aria-label="报告摘要">
        <h4>报告 #{{ document.identity.report_id }} · {{ document.identity.anonymous_case_code || '历史匿名编号未记录' }}</h4>
        <div class="summary-grid">
          <div><span>模型输入</span><strong>{{ inputStatus }}</strong><small>共 {{ document.summary.selected_model_count }} 个任务</small></div>
          <div><span>模型参与情况</span><strong>{{ document.summary.invoked_model_count }} 个已调用</strong><small>{{ document.summary.available_model_count }} 个结果可用</small></div>
          <div><span>观察与证据</span><strong>{{ document.summary.signal_count }} 条信号</strong><small>{{ document.summary.evidence_status === 'complete' ? '完整证据' : '部分证据' }}</small></div>
        </div>
        <p v-for="limitation in document.summary.limitations" :key="limitation">{{ limitation }}</p>
      </section>
      <section v-else class="summary-block" aria-label="报告摘要">
        <h4>报告摘要</h4>
        <div class="summary-grid">
          <div><span>保存的访视记录</span><strong>{{ visitCount }} 次</strong><small>历史报告未记录完整输入审计</small></div>
          <div><span>模型是否可用</span><strong :class="outcomeAvailable ? 'ok' : 'warn'">{{ outcomeAvailable ? '可用' : '暂不可用' }}</strong><small>{{ outcomeAvailable ? '可提供 365 天风险结果' : '未计算未来风险分数' }}</small></div>
          <div><span>实际看到了哪些信号</span><strong>{{ signalCount }} 个</strong><small>{{ signalCount ? '来自结构化关键进展信号' : '当前没有足够的关键信号' }}</small></div>
        </div>
        <p v-if="releaseSetId" class="technical-release">模型组版本：{{ releaseSetId }} · 数据版本：{{ dataReleaseId }}</p>
      </section>

      <nav class="report-toc" aria-label="报告目录">
        <strong>报告目录</strong>
        <a v-for="item in sections" :key="item.id" :href="`#${item.id}`">{{ item.label }}</a>
      </nav>

      <ReportDocumentCharts v-if="document" :charts="document.charts" />
      <section v-else-if="chartSeries.length" class="observed-charts" aria-label="已观察到的变化图表">
        <h4>已观察到的变化（不是模型预测）</h4>
        <div v-for="series in chartSeries" :key="series.name" class="observed-chart">
          <div class="chart-title"><strong>{{ series.name }}</strong><span>{{ series.unit || '单位未提供' }} · {{ series.values.length }} 次有效观察</span></div>
          <svg viewBox="0 0 420 150" role="img" :aria-label="`${series.name} 已观察值趋势图`">
            <line x1="36" y1="12" x2="36" y2="124" stroke="currentColor" stroke-opacity=".35" />
            <line x1="36" y1="124" x2="410" y2="124" stroke="currentColor" stroke-opacity=".35" />
            <polyline :points="series.points" fill="none" stroke="var(--color-primary)" stroke-width="3" />
            <circle v-for="point in series.dots" :key="point.key" :cx="point.x" :cy="point.y" r="5" fill="var(--color-primary)" />
            <text x="38" y="143" fill="currentColor" font-size="11">首次观察</text>
            <text x="350" y="143" fill="currentColor" font-size="11">最近观察</text>
          </svg>
        </div>
      </section>

      <LegacyReportSnapshot v-if="!document" :snapshot="report?.input_snapshot || null" />
      <ReportGenerationAudit v-if="report?.generation_audit" :audit="report.generation_audit" />

      <div class="markdown-body" v-html="renderedContentParts.before" />
      <LongitudinalEvidenceSection v-if="evidence && !document" :evidence="evidence" />
      <div v-if="renderedContentParts.after" class="markdown-body" v-html="renderedContentParts.after" />
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import {legacyChartPoints} from '@/utils/report-chart'
import { computed } from 'vue'
import ReportDocumentCharts from '@/components/report/ReportDocumentCharts.vue'
import NumericReportView from '@/components/report/NumericReportView.vue'
import type { SyntheticNumericInput, SyntheticGenerationContext, NumericReportDocumentV1, NumericReportDocumentV2, NumericReportDocumentV3 } from '@/types/report-document'
import ReportGenerationAudit from '@/components/report/ReportGenerationAudit.vue'
import LegacyReportSnapshot from '@/components/report/LegacyReportSnapshot.vue'
import ReportArchiveActions from '@/components/report/ReportArchiveActions.vue'
import { ArrowLeft } from '@element-plus/icons-vue'
import type { EvidenceBundleV1, LongitudinalPrediction, ReportDetail } from '@/api/operator'
import LongitudinalEvidenceSection from '@/components/LongitudinalEvidenceSection.vue'

const props = defineProps<{
  report?: ReportDetail | null
  predictionResult?: LongitudinalPrediction | null
  evidenceSnapshot?: EvidenceBundleV1 | null
  renderedContent: string
  generating?: boolean
}>()
defineEmits<{ back: []; download: [] }>()

const invalid = computed(()=>props.report?.integrity_status === 'invalid')
const document = computed(()=>props.report?.report_document?.schema_version === 'report_document.v1' ? props.report.report_document : null)
const numericDocument = computed(()=>['synthetic_numeric_report_document.v1','numeric_report_document.v1','numeric_report_document.v2','numeric_report_document.v3'].includes(props.report?.report_document?.schema_version || '') ? props.report?.report_document as NumericReportDocumentV1 | NumericReportDocumentV2 | NumericReportDocumentV3 | import('@/types/report-document').SyntheticNumericReportDocumentV1 : null)
const numericReport = computed(()=>['synthetic_numeric','numeric_prediction'].includes(props.report?.analysis_type || '') || Boolean(numericDocument.value) || ['synthetic_numeric','numeric_prediction'].includes(String(props.report?.input_snapshot?.report_kind || '')) || ['synthetic_numeric_generation_context.v1','numeric_generation_context.v1','numeric_generation_context.v2','numeric_generation_context.v3'].includes(String(props.report?.generation_context?.schema_version || '')))
const unsupportedDocument = computed(()=> Boolean(props.report?.report_document && !document.value && !numericDocument.value) || Boolean(numericReport.value && !numericDocument.value))
const numericInput = computed(()=> {
  const input = props.report?.input_snapshot?.numeric_input as SyntheticNumericInput | NumericReportDocumentV1['numeric_input'] | undefined
  return props.report?.snapshot_integrity === 'valid' && ['synthetic_numeric_input.v1','numeric_input.v1'].includes(input?.schema_version || '') ? input : null
})
const numericContext = computed(()=> props.report?.context_integrity === 'valid' && ['synthetic_numeric_generation_context.v1','numeric_generation_context.v1','numeric_generation_context.v2','numeric_generation_context.v3'].includes(String(props.report.generation_context?.schema_version || '')) ? props.report.generation_context as unknown as SyntheticGenerationContext | NumericReportDocumentV1['generation_context'] | NumericReportDocumentV2['generation_context'] | NumericReportDocumentV3['generation_context'] : null)
const inputStatus = computed(()=>({satisfied:'输入满足',partial:'部分满足',unavailable:'未满足'}[document.value?.summary.model_input_status || 'unavailable']))
const prediction = computed<LongitudinalPrediction | null>(() => {
  const saved = props.report?.prediction_result
  return saved && ['longitudinal_prediction.v1','longitudinal_prediction.v2','longitudinal_prediction.v3'].includes(saved.schema_version) ? saved as LongitudinalPrediction : props.predictionResult || null
})
const observation = computed(() => prediction.value?.observation || {})
const visitCount = computed(() => Number(observation.value.visit_count || 0))
const signalCount = computed(() => {
  const signals = prediction.value && 'progression_signals' in prediction.value ? prediction.value.progression_signals : undefined
  return Number(signals?.summary?.signal_count || signals?.signals?.length || 0)
})
const outcomeAvailable = computed(() => prediction.value && 'model_status' in prediction.value && prediction.value.model_status.outcome.status === 'available')
const evidence = computed<EvidenceBundleV1 | null>(() => props.report?.evidence_snapshot?.schema_version === 'longitudinal_evidence_bundle.v1' ? props.report.evidence_snapshot : props.evidenceSnapshot || null)
const renderedContentParts = computed(() => {
  if (document.value || !evidence.value || typeof DOMParser === 'undefined') return { before: props.renderedContent, after: '' }
  const parsedDocument = new DOMParser().parseFromString(props.renderedContent, 'text/html')
  const section = parsedDocument.body.querySelector('#section-8')
  if (!section) return { before: props.renderedContent, after: '' }
  const before: string[] = []
  const after: string[] = []
  let position: 'before' | 'skip' | 'after' = 'before'
  for (const node of Array.from(parsedDocument.body.childNodes)) {
    if (node === section) {
      position = 'skip'
      continue
    }
    if (position === 'skip' && node instanceof Element && node.matches('h2')) {
      position = 'after'
    }
    if (position === 'skip') continue
    const html = node instanceof Element ? node.outerHTML : node.textContent || ''
    if (position === 'before') before.push(html)
    else after.push(html)
  }
  return { before: before.join(''), after: after.join('') }
})
const releaseSetId = computed(() => prediction.value?.schema_version === 'longitudinal_prediction.v3' ? prediction.value.release_set.release_set_id : '')
const dataReleaseId = computed(() => prediction.value?.schema_version === 'longitudinal_prediction.v3' ? prediction.value.release_set.data_release_id : '')
const chartSeries = computed(() => Object.entries(observation.value.indicators || {}).flatMap(([name, item]: [string, any]) => {
  const points = legacyChartPoints(item)
  if (!points.length) return []
  const dots = points.map((p,index)=>({...p,key:`${name}-${index}`}))
  return [{name,unit:item.unit,values:points.map(p=>p.value),dots,points:dots.map(p=>`${p.x},${p.y}`).join(' ')}]
}))
const sections = [
  { id: 'section-1', label: '1 报告摘要' }, { id: 'section-2', label: '2 病例与预测范围' },
  { id: 'section-3', label: '3 数据质量与适用性' }, { id: 'section-4', label: '4 已观察到的纵向变化' },
  { id: 'section-5', label: '5 未来 365 天进展风险' }, { id: 'section-6', label: '6 阶段模型和下一次随访趋势的可用状态' },
  { id: 'section-7', label: '7 关键进展信号' }, { id: 'section-8', label: '8 参考标准和相似病例' },
  { id: 'section-9', label: '9 不确定性与局限性' }, { id: 'section-10', label: '10 人工复核重点' },
      { id: 'section-11', label: '11 模型和数据技术附录' },
]
function formatTime(value?: string) { return value ? new Date(value).toLocaleString('zh-CN') : '' }
</script>

<style scoped>
.longitudinal-report-view { flex:1; min-height:0; overflow-y:auto; background:var(--bg-canvas); padding:var(--space-6); }
.report-inner { width:min(100%, var(--content-max-width)); margin:0 auto; }
.report-head { display:flex; justify-content:space-between; align-items:flex-start; gap:var(--space-4); margin-bottom:var(--space-4); }
.report-head h3 { margin:0; color:var(--text-primary); font-size:var(--text-lg); }
.report-meta { color:var(--text-secondary); font-size:var(--text-xs); }
.report-head-actions { display:flex; align-items:center; gap:var(--space-2); flex-shrink:0; }
.summary-block { padding:var(--space-4); border:1px solid var(--border-light); border-radius:var(--radius-item); background:var(--bg-canvas); }
.summary-block h4 { margin:0 0 var(--space-3); color:var(--text-primary); font-size:var(--text-md); }
.summary-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-3); }
.summary-grid div { display:grid; gap:var(--space-1); padding:var(--space-3); background:var(--bg-surface); border-radius:var(--radius-item); }
.summary-grid span { color:var(--text-secondary); font-size:var(--text-xs); }
.summary-grid strong { color:var(--text-primary); font-size:var(--text-md); }
.summary-grid small { color:var(--text-secondary); font-size:var(--text-xs); }
.snapshot-block { margin:var(--space-4) 0; padding:var(--space-4); border:1px solid var(--border-light); border-radius:var(--radius-item); background:var(--bg-surface); }
.snapshot-block h4 { margin:0 0 var(--space-2); color:var(--text-primary); font-size:var(--text-md); }
.snapshot-note, .snapshot-missing { margin:0 0 var(--space-3); color:var(--text-secondary); font-size:var(--text-xs); }
.snapshot-missing { color:var(--color-warning); }
.technical-release { margin:var(--space-3) 0 0; color:var(--text-secondary); font-family:var(--font-mono); font-size:var(--text-xs); }
.ok { color:var(--color-success) !important; } .warn { color:var(--color-warning) !important; }
.report-toc { display:flex; flex-wrap:wrap; gap:var(--space-2) var(--space-4); margin:var(--space-4) 0; padding-bottom:var(--space-3); border-bottom:1px solid var(--border-light); }
.report-toc strong { width:100%; color:var(--text-primary); font-size:var(--text-sm); }
.report-toc a { color:var(--text-link); font-size:var(--text-xs); text-decoration:none; }
.report-toc a:hover { text-decoration:underline; }
.observed-charts { margin:var(--space-4) 0; padding:var(--space-4); border:1px solid var(--border-light); border-radius:var(--radius-item); background:var(--bg-canvas); }
.observed-charts h4 { margin:0 0 var(--space-3); color:var(--text-primary); font-size:var(--text-md); }
.observed-chart { padding:var(--space-3) 0; border-top:1px solid var(--border-light); }
.chart-title { display:flex; justify-content:space-between; gap:var(--space-3); color:var(--text-primary); font-size:var(--text-sm); }
.chart-title span { color:var(--text-secondary); font-size:var(--text-xs); }
.observed-chart svg { display:block; width:100%; max-width:560px; height:auto; margin-top:var(--space-2); color:var(--text-secondary); }
@media (max-width:720px) { .summary-grid { grid-template-columns:1fr; } .longitudinal-report-view { padding:var(--space-4); } .report-head { flex-direction:column; } .report-head-actions { width:100%; justify-content:space-between; } .chart-title { flex-direction:column; gap:var(--space-1); } }
</style>
