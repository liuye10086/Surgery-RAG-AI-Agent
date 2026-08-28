import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')

if (api.includes('function generateReportStream')) throw new Error('legacy API still present')
if (store.includes('function generateReport(')) throw new Error('legacy store action still present')
if (store.includes('generateReportStream')) throw new Error('legacy store import still present')
if (api.includes('analysis_backend')) throw new Error('legacy backend selector still present')

for (const legacy of [
  '/v1/operator/progression-predictions',
  'function predictProgression(',
  'interface ProgressionPredictionOut',
  'ProgressionPredictionRequest',
]) {
  if (api.includes(legacy)) throw new Error(`legacy progression API still present: ${legacy}`)
}

for (const legacy of [
  'progressionResult',
  'progressionLoading',
  'predictLongitudinalProgression',
  'clearProgression',
]) {
  if (store.includes(legacy)) throw new Error(`legacy progression store state still present: ${legacy}`)
}

for (const legacy of [
  'progressionVisits',
  'handleProgressionPredict',
  '评估进展风险',
  'progression-risk-card',
]) {
  if (view.includes(legacy)) throw new Error(`duplicate progression UI still present: ${legacy}`)
}

console.log('operator legacy cleanup contract passed')
