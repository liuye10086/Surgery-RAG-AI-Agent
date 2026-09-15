<template>
  <section class="audit" aria-label="生成审计记录">
    <h4>生成审计记录</h4>
    <p>
      最后确认阶段：{{ auditPhaseLabel(audit?.last_execution_phase)
      }}<span v-if="audit?.failure_phase">
        · 结束前阶段：{{ auditPhaseLabel(audit.failure_phase) }}</span
      >
    </p>
    <p>{{ audit?.note || '此报告未保存生成审计记录。' }}</p>
    <details v-for="(event, index) in audit?.events || []" :key="index">
      <summary>
        {{ index + 1 }}. {{ auditPhaseLabel(event.phase) }} ·
        {{ numeric && event.result_state === 'not_requested' ? '未执行临床标准或参考病例评价' : kinds[event.kind] || '已确认记录' }} {{ event.task || '' }}
      </summary>
      <p v-if="event.input_audit">
        模型调用：{{
          event.input_audit.model_invoked
            ? '已进入调用边界'
            : '此记录未确认调用'
        }}
        · 结果：{{
          event.result_state === 'available'
            ? '可用'
            : event.result_state === 'unavailable'
              ? '不可用'
              : '未确认'
        }}
      </p>
      <p v-if="numeric && !event.input_audit && ['available', 'unavailable'].includes(event.result_state || '')">结果：{{ event.result_state === 'available' ? '可用' : '不可用' }}</p>
      <ul>
        <li v-for="field in event.input_audit?.fields || []" :key="field.name">
          {{ field.name }}：{{ fieldStates[field.state] || '未记录' }}
        </li>
      </ul>
    </details>
  </section>
</template>
<script setup lang="ts">
import { phaseLabel } from '@/utils/report-read-model'
import type { GenerationAuditSummary } from '@/api/operator'
const props = defineProps<{ audit?: GenerationAuditSummary | null; numeric?: boolean }>()
function auditPhaseLabel(value: string | null | undefined) {
  if (props.numeric) {
    if (value === 'model_loading') return '校验固定算法'
    if (value === 'prediction') return '数值预测计算'
    if (value === 'standard_evidence') return '记录证据状态'
  }
  return phaseLabel(value)
}
const kinds: Record<string, string> = {
  phase_entered: '进入阶段',
  input_prepared: '输入准备',
  invocation_started: '开始调用',
  task_finished: '任务结束',
  evidence_resolved: '证据查询完成',
  terminal: '报告生成结束',
}
const fieldStates: Record<string, string> = {
  present: '已提供',
  allowed_missing: '允许缺失',
  required_missing: '缺少必填输入',
  invalid: '输入无效',
}
</script>
<style scoped>
.audit {
  padding: var(--space-5);
  margin: var(--space-4) 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  overflow-wrap: anywhere;
}
summary {
  min-height: 44px;
  cursor: pointer;
  line-height: 1.6;
}
summary:focus-visible {
  outline: 2px solid var(--color-primary);
}
</style>
