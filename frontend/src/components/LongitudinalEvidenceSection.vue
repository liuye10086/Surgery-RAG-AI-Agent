<template>
  <section id="section-8" class="evidence-section" aria-labelledby="evidence-title">
    <div class="evidence-card">
      <h4 id="evidence-title">正式标准证据</h4>
      <p class="evidence-meta">{{ standardInfo.document?.title || '已批准标准' }} · {{ standardInfo.version?.version_label || '版本未记录' }}</p>
      <details v-for="rule in standardRules" :key="String(rule.rule_id)" class="evidence-rule">
        <summary>{{ rule.display_name || rule.indicator }} · {{ rule.status }}</summary>
        <p>最新观察：{{ rule.latest_value ?? '未记录' }} {{ rule.unit || '' }}</p>
        <p>条件：{{ rule.conditions?.status || '未记录' }}</p>
        <p>来源：{{ rule.source?.section_title || '章节未记录' }}<span v-if="rule.source?.page_number">，第 {{ rule.source.page_number }} 页</span></p>
      </details>
    </div>
    <div class="evidence-card" aria-labelledby="reference-title">
      <h4 id="reference-title">参考病例</h4>
      <p v-if="referenceCopy">{{ referenceCopy }}</p>
      <template v-else>
        <p v-for="item in referenceCases.cases || []" :key="String(item.anonymous_case_code)">
          {{ item.anonymous_case_code }} · 覆盖率 {{ item.score?.coverage ?? '—' }} · 排名分 {{ item.score?.ranking_score ?? '—' }}
        </p>
      </template>
      <p class="non-causal-notice">参考病例结果不代表当前病例将发生相同结局。</p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { EvidenceBundleV1, ReferenceCaseStatus } from '@/api/operator'

const props = defineProps<{ evidence: EvidenceBundleV1 }>()
const evidence = computed(() => props.evidence)
const standardInfo = computed(() => evidence.value.standard as Record<string, any>)
const standardRules = computed(() => (standardInfo.value.rules || []) as Record<string, any>[])
const referenceCases = computed(() => evidence.value.reference_cases as Record<string, any>)
const referenceStateCopy: Record<ReferenceCaseStatus, string> = {
  available: '',
  no_eligible_cases: '当前没有通过生产准入的参考病例。',
  insufficient_comparability: '存在合格病例，但与当前病例可比信息不足。',
  reference_query_failed: '参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。',
  reference_index_stale: '参考病例索引版本已过期，本报告未使用旧版本病例。',
}
const referenceCopy = computed(() => referenceStateCopy[evidence.value.reference_cases.status])
</script>

<style scoped>
.evidence-section { display: grid; gap: var(--space-4); margin: var(--space-6) 0; }
.evidence-card { padding: var(--space-5); border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-surface); box-shadow: var(--shadow-sm); }
.evidence-card h4 { margin: 0 0 var(--space-2); color: var(--text-primary); font-size: var(--text-md); }
.evidence-meta, .evidence-card p { color: var(--text-secondary); font-size: var(--text-sm); }
.evidence-rule { margin-top: var(--space-2); padding: var(--space-2) var(--space-3); border: 1px solid var(--border-light); border-radius: var(--radius-item); }
.evidence-rule summary { min-height: 44px; display: flex; align-items: center; cursor: pointer; color: var(--text-primary); }
.non-causal-notice { padding: var(--space-3); border-radius: var(--radius-item); background: var(--color-accent-light); }
@media (prefers-reduced-motion: reduce) { .evidence-section *, .evidence-section *::before, .evidence-section *::after { transition: none !important; animation: none !important; } }
</style>
