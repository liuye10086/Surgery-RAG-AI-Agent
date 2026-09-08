import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const viewPath = new URL('../src/components/LongitudinalReportView.vue', import.meta.url)
const generationStorePath = new URL('../src/stores/report-generation.ts', import.meta.url)
const historyStorePath = new URL('../src/stores/report-history.ts', import.meta.url)
const operatorViewPath = new URL('../src/views/OperatorView.vue', import.meta.url)
const apiPath = new URL('../src/api/operator.ts', import.meta.url)

test('longitudinal report has three summary answers and eleven sections', async () => {
  const view = await readFile(viewPath, 'utf8')
  assert.match(view, /保存的访视记录/)
  assert.doesNotMatch(view, /visitCount\s*>=\s*3|['"]够用['"]/)
  assert.match(view, /模型是否可用/)
  assert.match(view, /实际看到了哪些信号/)
  for (const title of ['报告摘要', '病例与预测范围', '数据质量与适用性', '已观察到的纵向变化', '未来 365 天进展风险', '阶段模型和下一次随访趋势的可用状态', '关键进展信号', '参考标准和相似病例', '不确定性与局限性', '人工复核重点', '模型和数据技术附录']) {
    assert.match(view, new RegExp(title))
  }
  assert.doesNotMatch(view, /likely_rising|direction_only/)
})

test('saved and newly generated reports share the durable generation store', async () => {
  const [generationStore, operatorView] = await Promise.all([
    readFile(generationStorePath, 'utf8'),
    readFile(operatorViewPath, 'utf8'),
  ])
  assert.match(generationStore, /async function observe\(id:number\)/)
  assert.match(operatorView, /:report="generation\.report"/)
  assert.doesNotMatch(operatorView, /operatorStore\.currentReport|operatorStore\.longitudinalPrediction/)
})

test('report opens as a dedicated reading view with a return action', async () => {
  const [view, operatorView] = await Promise.all([
    readFile(viewPath, 'utf8'),
    readFile(operatorViewPath, 'utf8'),
  ])
  assert.match(operatorView, /v-else-if="reportReadingMode"/)
  assert.match(operatorView, /const reportReadingMode = computed/)
  assert.match(operatorView, /@back="closeReport"/)
  assert.match(view, /返回<\/el-button>/)
  assert.match(view, /ArrowLeft/)
})

test('report directory targets ids assigned to persisted markdown headings', async () => {
  const operatorView = await readFile(operatorViewPath, 'utf8')
  assert.match(operatorView, /new DOMParser\(\)/)
  assert.match(operatorView, /heading\.id = section\.id/)
})

test('historical prediction types remain compatible while v3 is strict', async () => {
  const api = await readFile(apiPath, 'utf8')
  assert.match(api, /LongitudinalPredictionV1\s*\|\s*LongitudinalPredictionV2\s*\|\s*LongitudinalPredictionV3/)
  assert.match(api, /schema_version:\s*'longitudinal_prediction\.v3'/)
  assert.match(api, /release_set:\s*LongitudinalReleaseSetIdentity/)
  assert.match(api, /model_status:\s*LongitudinalModelStatuses/)
})

test('report reading view shows saved release identity only as technical detail', async () => {
  const view = await readFile(viewPath, 'utf8')
  assert.match(view, /模型组版本/)
  assert.match(view, /release_set_id/)
  assert.match(view, /technical-release/)
})

test('history list supports saved snapshot summaries and load more', async () => {
  const [api, historyStore, sidebar, view] = await Promise.all([
    readFile(apiPath, 'utf8'), readFile(historyStorePath, 'utf8'),
    readFile(new URL('../src/components/OperatorSidebar.vue', import.meta.url), 'utf8'),
    readFile(viewPath, 'utf8'),
  ])
  assert.match(api, /input_snapshot/)
  assert.match(historyStore, /async function fetchPage\(append: boolean\)/)
  assert.match(sidebar, /加载更多/)
  assert.match(view, /LegacyReportSnapshot/)
  const snapshot = await readFile(new URL('../src/components/report/LegacyReportSnapshot.vue', import.meta.url), 'utf8')
  assert.match(snapshot, /生成时输入快照/)
  assert.match(snapshot, /报告生成时的保存记录/)
})

test('report API carries integrity and generation state fields', async () => {
  const api = await readFile(apiPath, 'utf8')
  for (const field of ['input_snapshot_sha256', 'generation_batch_id', 'generation_fingerprint', 'error_stage']) {
    assert.match(api, new RegExp(field))
  }
})
