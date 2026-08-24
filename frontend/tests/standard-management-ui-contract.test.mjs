import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

test('admin navigation exposes standard management', async () => {
  const sidebar = await readFile(new URL('../src/components/AdminSidebar.vue', import.meta.url), 'utf8')
  const view = await readFile(new URL('../src/views/AdminView.vue', import.meta.url), 'utf8')
  assert.match(sidebar, /key: 'standards'/)
  assert.match(sidebar, /标准管理/)
  assert.match(view, /activeSection === 'standards'/)
})

test('review UI exposes lifecycle actions and evidence-only state', async () => {
  const source = await readFile(new URL('../src/components/StandardManagementView.vue', import.meta.url), 'utf8')
  assert.match(source, /提交审核/)
  assert.match(source, /批准发布/)
  assert.match(source, /修改原因/)
  assert.match(source, /evidence-only/)
})

test('operator cannot mutate standards', async () => {
  const api = await readFile(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
  const caseManage = await readFile(new URL('../src/components/CaseManageView.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(api, /syncReferenceRanges/)
  assert.doesNotMatch(caseManage, /解析为参考范围/)
})
