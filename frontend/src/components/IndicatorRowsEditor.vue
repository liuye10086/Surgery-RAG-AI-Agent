<template>
  <div class="indicator-rows-editor">
    <div v-for="(row, index) in modelValue" :key="index" class="indicator-row">
      <el-input
        :model-value="row.name"
        placeholder="指标名"
        :disabled="disabled"
        class="indicator-name"
        @update:model-value="updateText(index, 'name', $event)"
      />
      <el-input
        :model-value="row.value"
        type="number"
        placeholder="数值"
        :disabled="disabled"
        class="indicator-value"
        @update:model-value="updateValue(index, $event)"
      />
      <el-input
        :model-value="row.unit"
        placeholder="单位"
        :disabled="disabled"
        class="indicator-unit"
        @update:model-value="updateText(index, 'unit', $event)"
      />
      <el-button
        :icon="Delete"
        text
        :disabled="disabled"
        aria-label="删除指标"
        title="删除指标"
        @click="removeRow(index)"
      />
    </div>
    <el-button size="small" :icon="Plus" text :disabled="disabled" @click="addRow">
      添加指标
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import type { IndicatorInput } from '@/api/operator'

const props = withDefaults(defineProps<{
  modelValue: IndicatorInput[]
  disabled?: boolean
}>(), {
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [rows: IndicatorInput[]]
}>()

function emptyRow(): IndicatorInput {
  return { name: '', value: null, unit: '' }
}

function updateText(index: number, field: 'name' | 'unit', value: string) {
  emit('update:modelValue', props.modelValue.map((row, rowIndex) => (
    rowIndex === index ? { ...row, [field]: value } : row
  )))
}

function updateValue(index: number, value: string | number) {
  const parsedValue = value === '' ? null : Number(value)
  emit('update:modelValue', props.modelValue.map((row, rowIndex) => (
    rowIndex === index ? { ...row, value: parsedValue } : row
  )))
}

function addRow() {
  emit('update:modelValue', [...props.modelValue, emptyRow()])
}

function removeRow(index: number) {
  if (props.modelValue.length <= 1) {
    emit('update:modelValue', [emptyRow()])
    return
  }
  emit('update:modelValue', props.modelValue.filter((_, rowIndex) => rowIndex !== index))
}
</script>

<style scoped>
.indicator-rows-editor {
  width: 100%;
}

.indicator-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.indicator-name {
  width: 150px;
}

.indicator-value {
  width: 120px;
}

.indicator-unit {
  width: 100px;
}

@media (max-width: 760px) {
  .indicator-row {
    flex-wrap: wrap;
  }

  .indicator-name,
  .indicator-value,
  .indicator-unit {
    width: min(100%, 180px);
  }
}
</style>
