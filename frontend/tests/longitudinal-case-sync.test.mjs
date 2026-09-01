import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url), 'utf8')

if (!api.includes('replaceLongitudinalVisits')) throw new Error('missing atomic visit replacement API')
if (!store.includes('replaceLongitudinalVisits')) throw new Error('store does not persist the complete visit timeline')
if (!view.includes('visits })')) throw new Error('case save does not submit edited visits')
if (!editor.includes('watch(')) throw new Error('editor does not react to selected case changes')
if (!api.includes('payload.error || payload.message')) throw new Error('SSE errors drop the backend message')
if (!view.includes('fetchLongitudinalCases')) throw new Error('longitudinal cases are not loaded')
if (!view.includes('startNewLongitudinalCase')) throw new Error('new longitudinal case lifecycle is missing')
if (!view.includes('请完整填写')) throw new Error('incomplete visits are silently discarded')
if (!api.includes('LongitudinalCaseUpdatePayload')) throw new Error('case update payload is not explicitly immutable')
if (!api.includes('disease: LongitudinalCaseDisease')) throw new Error('case disease identity is missing')
if (!editor.includes('props.modelValue?.disease')) throw new Error('existing case disease identity is not preserved')

console.log('longitudinal case sync contract passed')
