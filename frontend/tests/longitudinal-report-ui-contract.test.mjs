import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const viewPath = new URL('../src/components/LongitudinalReportView.vue', import.meta.url)
const storePath = new URL('../src/stores/operator.ts', import.meta.url)
const operatorViewPath = new URL('../src/views/OperatorView.vue', import.meta.url)

test('longitudinal report has three summary answers and eleven sections', async () => {
  const view = await readFile(viewPath, 'utf8')
  assert.match(view, /数据够不够/)
  assert.match(view, /模型是否可用/)
  assert.match(view, /实际看到了哪些信号/)
  for (const title of ['报告摘要', '病例与预测范围', '数据质量与适用性', '已观察到的纵向变化', '未来 365 天进展风险', '阶段模型和下一次随访趋势的可用状态', '关键进展信号', '参考标准和相似病例', '不确定性与局限性', '人工复核重点', '模型和数据技术附录']) {
    assert.match(view, new RegExp(title))
  }
  assert.doesNotMatch(view, /likely_rising|direction_only/)
})

test('history loading clears live prediction state before reading saved report', async () => {
  const [store, operatorView] = await Promise.all([
    readFile(storePath, 'utf8'),
    readFile(operatorViewPath, 'utf8'),
  ])
  assert.match(store, /longitudinalPrediction\.value\s*=\s*null/)
  assert.match(store, /async function loadSavedReport\(/)
  assert.match(operatorView, /LongitudinalReportView/)
})

test('report opens as a dedicated reading view with a return action', async () => {
  const [view, operatorView] = await Promise.all([
    readFile(viewPath, 'utf8'),
    readFile(operatorViewPath, 'utf8'),
  ])
  assert.match(operatorView, /v-else-if="reportReadingMode"/)
  assert.match(operatorView, /const reportReadingMode = computed/)
  assert.match(operatorView, /@back="closeReport"/)
  assert.match(view, /返回病例/)
  assert.match(view, /ArrowLeft/)
})

test('report directory targets ids assigned to persisted markdown headings', async () => {
  const operatorView = await readFile(operatorViewPath, 'utf8')
  assert.match(operatorView, /new DOMParser\(\)/)
  assert.match(operatorView, /heading\.id = section\.id/)
})
