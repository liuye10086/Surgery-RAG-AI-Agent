<template>
  <section class="longitudinal-report-view" aria-labelledby="longitudinal-report-title">
    <div class="report-inner">
      <div class="report-head">
        <div>
          <h3 id="longitudinal-report-title">{{ report?.title || '纵向进展报告' }}</h3>
          <span class="report-meta">{{ report ? formatTime(report.created_at) : '正在生成' }}</span>
        </div>
        <div class="report-head-actions">
          <el-button :icon="ArrowLeft" @click="$emit('back')">返回病例</el-button>
          <el-button v-if="report?.status === 'completed'" :icon="Download" type="primary" @click="$emit('download')">下载 PDF</el-button>
        </div>
      </div>

      <section class="summary-block" aria-label="报告摘要">
        <h4>报告摘要</h4>
        <div class="summary-grid">
          <div><span>数据够不够</span><strong class="ok">{{ visitCount >= 3 ? '够用' : '有限' }}</strong><small>{{ visitCount }} 次有效访视</small></div>
          <div><span>模型是否可用</span><strong :class="outcomeAvailable ? 'ok' : 'warn'">{{ outcomeAvailable ? '可用' : '暂不可用' }}</strong><small>{{ outcomeAvailable ? '可提供 365 天风险结果' : '未计算未来风险分数' }}</small></div>
          <div><span>实际看到了哪些信号</span><strong>{{ signalCount }} 个</strong><small>{{ signalCount ? '来自结构化关键进展信号' : '当前没有足够的关键信号' }}</small></div>
        </div>
        <p v-if="releaseSetId" class="technical-release">模型组版本：{{ releaseSetId }} · 数据版本：{{ dataReleaseId }}</p>
      </section>

      <nav class="report-toc" aria-label="报告目录">
        <strong>报告目录</strong>
        <a v-for="item in sections" :key="item.id" :href="`#${item.id}`">{{ item.label }}</a>
      </nav>

      <section v-if="chartSeries.length" class="observed-charts" aria-label="已观察到的变化图表">
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

      <section class="snapshot-block" aria-label="生成时输入快照">
        <h4>生成时输入快照</h4>
        <p class="snapshot-note">历史报告只展示生成时保存的资料，不会自动按当前模型重新计算。</p>
        <div v-if="snapshotAvailable" class="summary-grid">
          <div><span>病例编号</span><strong>{{ snapshot.anonymous_case_code || '旧病例未设置匿名编号' }}</strong></div>
          <div><span>疾病</span><strong>{{ snapshot.disease || '未记录' }}</strong></div>
          <div><span>基线阶段</span><strong>{{ snapshot.baseline_stage || '未记录' }}</strong></div>
          <div><span>访视次数</span><strong>{{ Array.isArray(snapshot.visits) ? snapshot.visits.length : '未记录' }}</strong></div>
        </div>
        <p v-else class="snapshot-missing">历史资料未完整保存。</p>
      </section>

      <div class="markdown-body" v-html="renderedContent" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowLeft, Download } from '@element-plus/icons-vue'
import type { LongitudinalPrediction, ReportDetail } from '@/api/operator'

const props = defineProps<{ report?: ReportDetail | null; predictionResult?: LongitudinalPrediction | null; renderedContent: string; generating?: boolean }>()
defineEmits<{ back: []; download: [] }>()

const prediction = computed<LongitudinalPrediction | null>(() => props.report?.prediction_result || props.predictionResult || null)
const observation = computed(() => prediction.value?.observation || {})
const visitCount = computed(() => Number(observation.value.visit_count || 0))
const signalCount = computed(() => {
  const signals = prediction.value && 'progression_signals' in prediction.value ? prediction.value.progression_signals : undefined
  return Number(signals?.summary?.signal_count || signals?.signals?.length || 0)
})
const outcomeAvailable = computed(() => prediction.value && 'model_status' in prediction.value && prediction.value.model_status.outcome.status === 'available')
const snapshot = computed(() => props.report?.input_snapshot || {})
const snapshotAvailable = computed(() => Object.keys(snapshot.value).length > 0)
const releaseSetId = computed(() => prediction.value?.schema_version === 'longitudinal_prediction.v3' ? prediction.value.release_set.release_set_id : '')
const dataReleaseId = computed(() => prediction.value?.schema_version === 'longitudinal_prediction.v3' ? prediction.value.release_set.data_release_id : '')
const chartSeries = computed(() => Object.entries(observation.value.indicators || {}).flatMap(([name, item]: [string, any]) => {
  const series = Array.isArray(item?.series) ? item.series : []
  if (series.length < 3 || item?.unit_state && item.unit_state !== 'consistent') return []
  const values = series.map((entry: any) => Number(entry.value)).filter(Number.isFinite)
  if (values.length < 3) return []
  const min = Math.min(...values); const max = Math.max(...values); const span = max - min || 1
  const dots = values.map((value: number, index: number) => ({ key: `${name}-${index}`, x: 42 + (index * 360) / Math.max(values.length - 1, 1), y: 116 - ((value - min) / span) * 96 }))
  return [{ name, unit: item?.unit, values, dots, points: dots.map((point: any) => `${point.x},${point.y}`).join(' ') }]
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
