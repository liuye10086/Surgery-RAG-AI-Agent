<template>
  <section v-if="prediction" class="prediction-summary" aria-labelledby="prediction-summary-title">
    <h3 id="prediction-summary-title">纵向预测摘要</h3>
    <div class="summary-grid">
      <div><span>模型风险等级</span><strong>{{ prediction.outcome_prediction?.risk_band || '未估计' }}</strong></div>
      <div><span>阶段模型</span><strong>{{ prediction.outcome_prediction?.stage_projection?.status || '未估计' }}</strong></div>
      <div><span>访视次数</span><strong>{{ prediction.observation?.visit_count || 0 }}</strong></div>
    </div>
    <p class="caveat">模型分数未校准，不代表临床概率；方向预测不包含未来精确数值。</p>
    <el-table :data="prediction.trend_predictions || []" size="small">
      <el-table-column prop="indicator" label="指标" />
      <el-table-column label="观察趋势"><template #default="{ row }">{{ row.forecast?.direction || '不可估计' }}</template></el-table-column>
      <el-table-column label="状态"><template #default="{ row }">{{ row.forecast?.status }}</template></el-table-column>
    </el-table>
    <ul v-if="prediction.warnings?.length" class="warnings"><li v-for="warning in prediction.warnings" :key="warning">{{ warning }}</li></ul>
  </section>
</template>

<script setup lang="ts">
import type { LongitudinalPrediction } from '@/api/operator'
defineProps<{ prediction: LongitudinalPrediction | null }>()
</script>

<style scoped>
.prediction-summary { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: var(--radius-card); padding: var(--space-5); box-shadow: var(--shadow-sm); }
.summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-4); }
.summary-grid div { display: grid; gap: var(--space-1); } .summary-grid span { color: var(--text-secondary); font-size: var(--text-xs); } .summary-grid strong { color: var(--text-primary); font-size: var(--text-md); }
.caveat { color: var(--text-secondary); background: var(--color-accent-light); border-left: 3px solid var(--color-accent); padding: var(--space-3); border-radius: var(--radius-item); }
.warnings { color: var(--text-secondary); font-size: var(--text-sm); } @media (max-width: 720px) { .summary-grid { grid-template-columns: 1fr; } }
</style>
