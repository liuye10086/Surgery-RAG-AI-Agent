<template>
  <section v-if="series.length" class="document-charts" aria-label="已观察到的变化图表">
    <h4>已观察到的变化（不是模型预测）</h4>
    <figure v-for="chart in series" :key="chart.indicator">
      <figcaption>{{ chart.label }} · {{ chart.unit }} · {{ chart.points.length }} 次有效观察</figcaption>
      <svg viewBox="0 0 440 160" role="img" :aria-label="`${chart.label} 按实际日期绘制的观察值`">
        <line x1="42" y1="12" x2="42" y2="124" /><line x1="42" y1="124" x2="402" y2="124" />
        <polyline :points="chart.coordinates.map(p=>`${p.x},${p.y}`).join(' ')" />
        <circle v-for="point in chart.coordinates" :key="point.date" :cx="point.x" :cy="point.y" r="4">
          <title>{{ point.date }}：{{ point.value }} {{ chart.unit }}</title>
        </circle>
        <text x="42" y="148">{{ chart.coordinates[0]?.date }}</text>
        <text x="402" y="148" text-anchor="end">{{ chart.coordinates[chart.coordinates.length - 1]?.date }}</text>
      </svg>
      <details><summary>查看日期与原值</summary><ul><li v-for="point in chart.points" :key="point.visit_date">{{ point.visit_date }}：{{ point.value }} {{ chart.unit }}</li></ul></details>
    </figure>
  </section>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import type { ObservedChart } from '@/types/report-document'
import { chartCoordinates } from '@/utils/report-chart'
const props = defineProps<{charts: ObservedChart[]}>()
const series = computed(()=>props.charts.map(chart=>({...chart,coordinates:chartCoordinates(chart.points)})))
</script>
<style scoped>
.document-charts { margin:var(--space-4) 0; padding:var(--space-4); background:var(--bg-surface); border:1px solid var(--border-light); border-radius:var(--radius-card); }
figure { margin:var(--space-4) 0; color:var(--text-primary); }
svg { width:100%; max-width:600px; height:auto; }
line { stroke:var(--text-secondary); opacity:.5; }
polyline { fill:none; stroke:var(--color-accent); stroke-width:2; }
circle { fill:var(--color-accent); }
text { fill:var(--text-primary); font-size:12px; }
summary { min-height:44px; display:flex; align-items:center; cursor:pointer; color:var(--text-link); }
</style>
