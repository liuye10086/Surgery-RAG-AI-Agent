<template>
  <section id="section-8" class="evidence-section" aria-labelledby="evidence-title">
    <div class="evidence-card">
      <h4 id="evidence-title">正式标准证据</h4>
      <p class="evidence-meta">{{ standardInfo.document?.title || '已批准标准' }} · {{ standardInfo.version?.version_label || '版本未记录' }}</p>
      <details v-for="rule in standardRules" :key="String(rule.rule_id)" class="evidence-rule">
        <summary>{{ rule.display_name || rule.indicator }} · {{ rule.status }}</summary>
        <p>最新观察：{{ rule.latest_value ?? '未记录' }} {{ rule.unit || '' }}</p>
        <p>条件：{{ rule.conditions.status }}<span v-if="rule.conditions.missing.length">；缺少 {{ rule.conditions.missing.join('、') }}</span><span v-if="rule.conditions.mismatched.length">；不匹配 {{ rule.conditions.mismatched.join('、') }}</span></p>
        <p>来源：{{ rule.source?.section_title || '章节未记录' }}<span v-if="rule.source?.page_number">，第 {{ rule.source.page_number }} 页</span></p>
      </details>
    </div>
    <div class="evidence-card" aria-labelledby="reference-title">
      <h4 id="reference-title">参考病例</h4>
      <p v-if="referenceCopy">{{ referenceCopy }}</p>
      <template v-else>
        <details v-for="item in referenceCases.cases" :key="item.anonymous_case_code" class="evidence-rule">
          <summary>{{ item.anonymous_case_code }} · 覆盖率 {{ formatPercent(item.score.coverage) }} · 排名分 {{ item.score.ranking_score }}</summary>
          <p>{{ ageBand(item.features.age) }} · {{ sexText(item.features.sex) }} · 基线阶段 {{ item.features.baseline_stage }}</p>
          <p>{{ item.features.visit_count }} 次访视 · 观察跨度 {{ item.features.observation_span_days }} 天 · 截止 {{ item.features.as_of }}</p>
          <p>结局来源：{{ item.outcome_source }} · 可靠性：{{ reliabilityText(item.outcome_reliability) }}</p>
          <p v-if="item.comparisons.length">比较项：{{ item.comparisons.map(entry => `${entry.indicator}（${entry.status}）`).join('、') }}</p>
        </details>
      </template>
      <p class="non-causal-notice">参考病例结果不代表当前病例将发生相同结局。</p>
      <p class="technical-meta">数据版本：{{ referenceCases.data_release.dataset_release_id || '未记录' }} · 算法：{{ referenceCases.algorithm_version }}</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceBundleV1, ReferenceCaseStatus } from '@/api/operator'

const props = defineProps<{ evidence: EvidenceBundleV1 }>()
const evidence = computed(() => props.evidence)
const standardInfo = computed(() => evidence.value.standard)
const standardRules = computed(() => standardInfo.value.rules)
const referenceCases = computed(() => evidence.value.reference_cases)
const referenceStateCopy: Record<ReferenceCaseStatus, string> = {
  available: '',
  no_eligible_cases: '当前没有通过生产准入的参考病例。',
  insufficient_comparability: '存在合格病例，但与当前病例可比信息不足。',
  reference_query_failed: '参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。',
  reference_index_stale: '参考病例索引版本已过期，本报告未使用旧版本病例。',
}
const referenceCopy = computed(() => referenceStateCopy[evidence.value.reference_cases.status])
function formatPercent(value: number) { return `${Math.round(value * 100)}%` }
function ageBand(value: number | null) {
  if (value === null) return '年龄未记录'
  const floor = Math.floor(value / 10) * 10
  return `${floor}–${floor + 9} 岁`
}
function sexText(value: 'male' | 'female' | null) {
  return value === 'male' ? '男性' : value === 'female' ? '女性' : '性别未记录'
}
function reliabilityText(value: 'low' | 'medium' | 'high') {
  return ({ low: '低', medium: '中', high: '高' } as const)[value]
}
</script>

<style scoped>
.evidence-section { display: grid; gap: var(--space-4); margin: var(--space-6) 0; }
.evidence-card { padding: var(--space-5); border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.evidence-card h4 { margin: 0 0 var(--space-2); color: var(--text-primary); font-size: var(--text-md); }
.evidence-meta, .evidence-card p { color: var(--text-secondary); font-size: var(--text-sm); }
.evidence-rule { margin-top: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--border-light); border-radius: var(--radius-item); }
.evidence-rule summary { min-height: 44px; display: flex; align-items: center; cursor: pointer; color: var(--text-primary); }
.non-causal-notice { padding: var(--space-3); border-radius: var(--radius-item); background: var(--color-accent-light); }
.technical-meta { font-family: var(--font-mono); font-size: var(--text-xs) !important; }
@media (prefers-reduced-motion: reduce) { .evidence-section *, .evidence-section *::before, .evidence-section *::after { transition: none !important; animation: none !important; } }
</style>
