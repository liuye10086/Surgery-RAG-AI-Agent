<template>
  <section v-if="prediction" class="prediction-summary" aria-labelledby="prediction-summary-title">
    <div class="summary-heading">
      <div>
        <span class="eyebrow">完整模型组结果</span>
        <h3 id="prediction-summary-title">纵向预测摘要</h3>
      </div>
      <span v-if="releaseSetId" class="release-badge">模型组 {{ releaseSetId }}</span>
    </div>

    <div class="summary-grid">
      <article>
        <span>未来 365 天结局</span>
        <strong>{{ prediction.outcome_prediction.risk_band || '未估计' }}</strong>
        <small>模型分数：{{ formatScore(prediction.outcome_prediction.risk_score) }}</small>
      </article>
      <article>
        <span>下一疾病阶段</span>
        <strong>{{ stageLabel }}</strong>
        <small>{{ stageAvailable ? '阶段模型已参与' : '阶段模型未参与或推理失败' }}</small>
      </article>
      <article>
        <span>下一次访视趋势</span>
        <strong>{{ availableTrendCount }}/{{ prediction.trend_predictions.length }}</strong>
        <small>可用指标模型</small>
      </article>
    </div>

    <p class="caveat">模型分数不代表临床概率；趋势模型只预测方向，不提供未来精确数值。</p>

    <el-table v-if="prediction.trend_predictions.length" :data="prediction.trend_predictions" size="small">
      <el-table-column prop="indicator" label="指标" />
      <el-table-column label="已观察方向">
        <template #default="{ row }">{{ observedDirection(row.observed) }}</template>
      </el-table-column>
      <el-table-column label="模型预测方向">
        <template #default="{ row }">{{ predictedDirection(row) }}</template>
      </el-table-column>
      <el-table-column label="模型状态">
        <template #default="{ row }">{{ trendStatus(row) }}</template>
      </el-table-column>
    </el-table>
    <p v-else class="empty-trends">当前没有已保存的下一次访视趋势预测。</p>

    <ul v-if="prediction.warnings?.length" class="warnings">
      <li v-for="warning in prediction.warnings" :key="warning">{{ warning }}</li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { LongitudinalObservedIndicator, LongitudinalPrediction, LongitudinalTrendPrediction, LongitudinalTrendPredictionV3 } from '@/api/operator'

const props = defineProps<{ prediction: LongitudinalPrediction | null }>()

const stageLabels: Record<string, string> = {
  fatty_liver: '未肝硬化阶段', pre_cirrhosis: '未肝硬化阶段', stay_pre_cirrhosis: '维持未肝硬化阶段',
  cirrhosis: '肝硬化阶段', hcc: '肝细胞癌阶段', normal: '正常认知阶段', stay_normal: '维持正常认知阶段',
  mci: '轻度认知障碍阶段', stay_mci: '维持轻度认知障碍阶段', pre_dementia: '痴呆前阶段', dementia: '痴呆阶段',
}
const directionLabels: Record<string, string> = { rising: '上升', stable: '基本稳定', falling: '下降' }
const releaseSetId = computed(() => props.prediction?.schema_version === 'longitudinal_prediction.v3' ? props.prediction.release_set.release_set_id : '')
const stageAvailable = computed(() => props.prediction?.outcome_prediction.stage_projection.status === 'available')
const stageLabel = computed(() => {
  const value = props.prediction?.outcome_prediction.stage_projection.likely_next_stage
  return value ? stageLabels[value] || '未识别的阶段类别' : '未估计'
})
const availableTrendCount = computed(() => props.prediction?.trend_predictions.filter((row) => (
  hasModelStatus(row) ? row.model_status.status === 'available' : row.forecast.status === 'direction_only'
)).length || 0)

function formatScore(value?: number | null) { return typeof value === 'number' ? value.toFixed(2) : '未估计' }
function observedDirection(observed?: LongitudinalObservedIndicator) {
  const delta = observed?.delta
  if (typeof delta !== 'number') return '无法判断'
  return delta > 0 ? '上升' : delta < 0 ? '下降' : '基本稳定'
}
function predictedDirection(row: LongitudinalTrendPrediction) {
  return row.forecast.status === 'direction_only' && row.forecast.direction
    ? directionLabels[row.forecast.direction] || '无法估计'
    : '无法估计'
}
function hasModelStatus(row: LongitudinalTrendPrediction): row is LongitudinalTrendPredictionV3 {
  return 'model_status' in row
}
function trendStatus(row: LongitudinalTrendPrediction) {
  if (hasModelStatus(row)) return row.model_status.status === 'available' ? '模型已参与' : '安全降级'
  return row.forecast.status === 'direction_only' ? '历史结果可用' : '未估计'
}
</script>

<style scoped>
.prediction-summary { background:var(--bg-surface); border:1px solid var(--border-default); border-radius:var(--radius-card); padding:var(--space-5); box-shadow:var(--shadow-sm); }
.summary-heading { display:flex; justify-content:space-between; gap:var(--space-4); align-items:flex-start; margin-bottom:var(--space-4); }
.summary-heading h3 { margin:var(--space-1) 0 0; color:var(--text-primary); font-size:var(--text-md); }
.eyebrow { color:var(--color-accent); font-size:var(--text-xs); font-weight:600; }
.release-badge { color:var(--text-secondary); background:var(--bg-input); border-radius:var(--radius-pill); padding:var(--space-2) var(--space-3); font-size:var(--text-xs); }
.summary-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:var(--space-4); }
.summary-grid article { display:grid; gap:var(--space-1); padding:var(--space-4); background:var(--bg-canvas); border:1px solid var(--border-light); border-radius:var(--radius-item); }
.summary-grid span,.summary-grid small { color:var(--text-secondary); font-size:var(--text-xs); }
.summary-grid strong { color:var(--text-primary); font-size:var(--text-md); }
.caveat { color:var(--text-secondary); background:var(--color-accent-light); border-left:3px solid var(--color-accent); padding:var(--space-3); border-radius:var(--radius-item); }
.empty-trends,.warnings { color:var(--text-secondary); font-size:var(--text-sm); }
</style>
