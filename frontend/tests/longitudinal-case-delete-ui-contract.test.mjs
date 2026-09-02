import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const apiPath = new URL('../src/api/operator.ts', import.meta.url)
const storePath = new URL('../src/stores/operator.ts', import.meta.url)
const viewPath = new URL('../src/views/OperatorView.vue', import.meta.url)

test('longitudinal case deletion is exposed as a guarded danger action', async () => {
  const view = await readFile(viewPath, 'utf8')

  assert.match(view, /type="danger"/)
  assert.match(view, />\s*删除病例\s*</)
  assert.match(view, /病例及全部访视将永久删除/)
  assert.match(view, /历史报告仍会保留/)
  assert.match(view, /只能通过生成时输入快照追溯/)
  assert.match(view, /handleDeleteLongitudinalCase/)
  assert.match(view, /:disabled="!canDeleteCurrentCase"/)
  assert.match(view, /请先恢复病例后再删除/)
  assert.match(view, /疾病已停用，当前不能删除病例/)
})

test('deleting a longitudinal case calls the API and converges local state', async () => {
  const [api, store] = await Promise.all([
    readFile(apiPath, 'utf8'),
    readFile(storePath, 'utf8'),
  ])

  assert.match(api, /export function deleteLongitudinalCase/)
  assert.match(store, /deleteLongitudinalCase/)
  assert.match(store, /async function removeLongitudinalCase/)
  assert.match(store, /await fetchLongitudinalCases\(undefined, longitudinalCaseStatusFilter\.value\)/)
  assert.match(store, /currentLongitudinalCase\.value = null/)
  assert.match(store, /longitudinalPrediction\.value = null/)
  assert.match(store, /longitudinalReportContent\.value = ''/)
})

test('local case state is cleared even when the post-delete refresh fails', async () => {
  const store = await readFile(storePath, 'utf8')
  const removeCase = store.slice(
    store.indexOf('async function removeLongitudinalCase'),
    store.indexOf('async function saveLongitudinalVisit'),
  )

  assert.match(removeCase, /try\s*{[\s\S]*await fetchLongitudinalCases/)
  assert.match(removeCase, /finally\s*{[\s\S]*currentLongitudinalCase\.value = null/)
  assert.match(removeCase, /病例已删除，但病例列表刷新失败，请重新加载页面/)
})
