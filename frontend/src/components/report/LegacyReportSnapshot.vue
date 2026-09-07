<template>
  <section class="snapshot" aria-label="生成时输入快照">
    <h4>生成时输入快照</h4>
    <p>以下资料来自报告生成时的保存记录。</p>
    <p v-if="!snapshot">历史资料未完整保存。</p>
    <template v-else>
      <p>
        年龄：{{ savedValue(snapshot.age) }} · 性别：{{
          savedValue(snapshot.sex)
        }}
        · 阶段：{{ stageLabel(snapshot.baseline_stage) }}
      </p>
      <p v-if="unknownVersion">此快照版本无法解释，仅展示已保存的安全字段。</p>
      <p>备注：{{ savedValue(snapshot.notes) }}</p>
      <details v-for="(visit, index) in visits" :key="index">
        <summary>
          访视 {{ index + 1 }} · {{ savedValue(visit.visit_date) }}
        </summary>
        <p>备注：{{ savedValue(visit.notes) }}</p>
        <dl>
          <template v-for="(value, key) in safeObject(visit.context)" :key="key"
            ><dt>{{ key }}</dt>
            <dd>{{ savedValue(value) }}</dd></template
          >
        </dl>
        <table>
          <thead>
            <tr>
              <th>指标</th>
              <th>保存值</th>
              <th>单位</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(indicator, i) in safeRows(visit.indicators)" :key="i">
              <td>{{ savedValue(indicator.name ?? indicator.code) }}</td>
              <td>{{ savedValue(indicator.value) }}</td>
              <td>{{ savedValue(indicator.unit) }}</td>
            </tr>
          </tbody>
        </table>
      </details>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { savedValue, stageLabel } from '@/utils/report-read-model'
const props = defineProps<{ snapshot: Record<string, unknown> | null }>()
const safeObject = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {}
const safeRows = (v: unknown) =>
  Array.isArray(v)
    ? (v.filter(
        (x) => x && typeof x === 'object' && !Array.isArray(x),
      ) as Record<string, unknown>[])
    : []
const visits = computed(() => safeRows(props.snapshot?.visits))
const unknownVersion = computed(() =>
  Boolean(
    props.snapshot?.schema_version &&
      ![
        'longitudinal_input_snapshot.v1',
        'operator_input_snapshot.v1',
      ].includes(String(props.snapshot.schema_version)),
  ),
)
</script>
<style scoped>
.snapshot {
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
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  text-align: left;
  padding: var(--space-2);
  border-bottom: 1px solid var(--border-light);
}
dt {
  color: var(--text-secondary);
}
dd {
  margin: 0 0 var(--space-2);
}
</style>
