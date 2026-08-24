import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const operatorViewPath = new URL('../src/views/OperatorView.vue', import.meta.url)
const caseManagePath = new URL('../src/components/CaseManageView.vue', import.meta.url)
const apiPath = new URL('../src/api/operator.ts', import.meta.url)
const storePath = new URL('../src/stores/operator.ts', import.meta.url)

test('single-timepoint prediction UI and endpoint are removed', async () => {
  const [operatorView, api] = await Promise.all([
    readFile(operatorViewPath, 'utf8'),
    readFile(apiPath, 'utf8'),
  ])

  assert.doesNotMatch(operatorView, /AI 操作者预测分析/)
  assert.doesNotMatch(operatorView, /开始分析/)
  assert.doesNotMatch(operatorView, /v-model="indicatorRows"/)
  assert.doesNotMatch(api, /function generatePredictionStream\(/)
  assert.doesNotMatch(api, /request\.post\(['"`]\/v1\/operator\/reports['"`]/)
})

test('progression API and store expose the model caveat', async () => {
  const [api, store] = await Promise.all([
    readFile(apiPath, 'utf8'),
    readFile(storePath, 'utf8'),
  ])

  assert.match(api, /interface ProgressionPredictionOut[\s\S]*model_caveat:\s*string/)
  assert.match(api, /function predictProgression\([\s\S]*\/v1\/operator\/progression-predictions/)
  assert.match(store, /progressionResult\s*=\s*ref<ProgressionPredictionOut \| null>/)
  assert.match(store, /async function predictLongitudinalProgression\(/)
})

test('both disclosures render before the progression risk score', async () => {
  const operatorView = await readFile(operatorViewPath, 'utf8')
  const disclaimerIndex = operatorView.indexOf('progressionResult.disclaimer')
  const caveatIndex = operatorView.indexOf('progressionResult.model_caveat')
  const scoreIndex = operatorView.indexOf('progressionResult.risk_score')

  assert.ok(disclaimerIndex >= 0, 'disclaimer must be rendered')
  assert.ok(caveatIndex >= 0, 'model_caveat must be rendered')
  assert.ok(scoreIndex >= 0, 'risk score must be rendered')
  assert.ok(disclaimerIndex < scoreIndex, 'disclaimer must precede risk score')
  assert.ok(caveatIndex < scoreIndex, 'model_caveat must precede risk score')
  assert.match(operatorView, /class="progression-disclosures"/)
  assert.match(operatorView, /\.progression-disclosure\s*\{[^}]*font-size:\s*var\(--text-md\)/)
})
