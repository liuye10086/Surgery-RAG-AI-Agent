import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')
const workspace = fs.readFileSync(new URL('../src/components/operator-case/OperatorCaseWorkspace.vue', import.meta.url), 'utf8')

if (!api.includes('saveLongitudinalCase')) throw new Error('missing aggregate case save API')
if (!store.includes('saveLongitudinalCaseRequest')) throw new Error('store does not persist the aggregate timeline')
if (!workspace.includes('watch(() => props.model')) throw new Error('workspace does not react to selected case changes')
if (!workspace.includes('const { disease_id: _diseaseId')) throw new Error('immutable disease ID leaks into case updates')
if (!workspace.includes(':disease-locked="Boolean(model?.id)"')) throw new Error('existing case disease can be edited')
if (!api.includes('payload.error || payload.message')) throw new Error('SSE errors drop the backend message')
if (!view.includes('fetchLongitudinalCases')) throw new Error('longitudinal cases are not loaded')
if (!view.includes('startNewLongitudinalCase')) throw new Error('new longitudinal case lifecycle is missing')
if (!api.includes('disease: LongitudinalCaseDisease')) throw new Error('case disease identity is missing')
if (!store.includes('fetchOperatorIndicatorCatalog')) throw new Error('disease catalog is not synchronized')

console.log('longitudinal case sync contract passed')
