import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const editorPath = new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url)
const viewPath = new URL('../src/views/OperatorView.vue', import.meta.url)
const storePath = new URL('../src/stores/operator.ts', import.meta.url)
const apiPath = new URL('../src/api/operator.ts', import.meta.url)

test('editor exposes disease-aware canonical baseline stages', async () => {
  const editor = await readFile(editorPath, 'utf8')
  for (const value of [
    'pre_cirrhosis',
    'suspected_cirrhosis',
    'cirrhosis',
    'hcc',
    'normal',
    'mci',
    'pre_dementia',
    'dementia',
  ]) assert.match(editor, new RegExp(value))
  assert.match(editor, /stageOptionsByCode/)
  assert.match(editor, /selectedDisease\.value\?\.code/)
  assert.match(editor, /aria-label="基线阶段"/)
})

test('case save persists baseline_stage', async () => {
  const [view, store, api] = await Promise.all([
    readFile(viewPath, 'utf8'),
    readFile(storePath, 'utf8'),
    readFile(apiPath, 'utf8'),
  ])
  assert.match(view, /baseline_stage:\s*draft\.baseline_stage/)
  assert.match(store, /LongitudinalCaseCreatePayload/)
  assert.match(store, /LongitudinalCaseUpdatePayload/)
  assert.match(api, /export interface LongitudinalCaseCreatePayload[\s\S]*?baseline_stage\?:/)
  assert.match(api, /export interface LongitudinalCaseUpdatePayload[\s\S]*?baseline_stage\?:/)
  assert.match(api, /export type BaselineStage/)
})

test('changing disease clears an incompatible selected stage', async () => {
  const editor = await readFile(editorPath, 'utf8')
  assert.match(editor, /watch\(\(\) => draft\.disease_id/)
  assert.match(editor, /draft\.baseline_stage = null/)
})
