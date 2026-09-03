<template>
  <div class="action-bar">
    <span v-if="readiness && !readiness.ready" class="action-bar__hint">{{ readiness.blockers[0]?.message || `还需 ${readiness.minimum_visits ?? '更多'} 次访视` }}</span>
    <span v-else-if="readiness?.ready" class="action-bar__ready">病例已满足报告条件</span>
    <span v-else class="action-bar__hint">请完整填写病例资料</span>
    <button type="button" :disabled="saving || !dirty" @click="$emit('save')">{{ saving ? '保存中…' : '保存病例' }}</button>
    <button type="button" class="action-bar__report" :disabled="saving || !readiness?.ready" @click="$emit('generate-report')">生成报告</button>
  </div>
</template>

<script setup lang="ts">
import type { OperatorCaseReportReadiness } from '@/api/operator'
defineProps<{ dirty: boolean; saving: boolean; readiness: OperatorCaseReportReadiness | null }>()
defineEmits<{ save: []; 'generate-report': [] }>()
</script>

<style scoped>
.action-bar { position: sticky; bottom: 0; z-index: 2; display: flex; gap: var(--space-3); align-items: center; padding: var(--space-4) 0; background: color-mix(in srgb, var(--bg-canvas) 92%, transparent); }
.action-bar__hint { flex: 1; color: var(--text-secondary); font-size: var(--text-sm); }
.action-bar__ready { flex: 1; color: var(--color-success); font-size: var(--text-sm); }
.action-bar button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-5); color: white; background: var(--color-primary); cursor: pointer; }
.action-bar button:disabled { color: var(--text-disabled); background: var(--bg-hover); cursor: not-allowed; }
.action-bar__report { color: var(--text-primary) !important; background: var(--color-accent-light) !important; }
</style>
