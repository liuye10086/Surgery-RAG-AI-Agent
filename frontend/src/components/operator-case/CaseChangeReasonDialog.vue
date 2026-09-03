<template>
  <dialog v-if="open" open class="reason-dialog" aria-labelledby="reason-title">
    <h3 id="reason-title">填写变更原因</h3>
    <label>原因<textarea v-model="reason" maxlength="500" autofocus /></label>
    <p v-if="error" class="reason-dialog__error" role="alert">{{ error }}</p>
    <div class="reason-dialog__actions"><button type="button" @click="$emit('cancel')">取消</button><button type="button" @click="confirm">确认保存</button></div>
  </dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ confirm: [reason: string]; cancel: [] }>()
const reason = ref('')
const error = ref('')
watch(() => props.open, (open) => { if (open) { reason.value = ''; error.value = '' } })
function confirm() { const value = reason.value.trim(); if (value.length < 1 || value.length > 500) { error.value = '变更原因需为 1–500 个字符'; return } emit('confirm', value) }
</script>

<style scoped>
.reason-dialog { width: min(420px, calc(100vw - 32px)); border: 0; border-radius: var(--radius-card); padding: var(--space-6); box-shadow: var(--shadow-lg); }
.reason-dialog::backdrop { background: rgba(20, 30, 40, .35); }
.reason-dialog label { display: grid; gap: var(--space-2); color: var(--text-secondary); }
.reason-dialog textarea { min-height: 120px; border: 1px solid var(--border-default); border-radius: var(--radius-control); padding: var(--space-3); }
.reason-dialog__error { color: var(--color-danger); }
.reason-dialog__actions { display: flex; justify-content: end; gap: var(--space-2); margin-top: var(--space-4); }
.reason-dialog button { min-height: 44px; border: 0; border-radius: var(--radius-control); padding: 0 var(--space-4); cursor: pointer; }
.reason-dialog button:last-child { color: white; background: var(--color-primary); }
</style>
