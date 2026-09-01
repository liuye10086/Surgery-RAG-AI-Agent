import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = path => readFile(new URL(path, import.meta.url), 'utf8')

test('operator UI has no disease catalog write controls', async () => {
  const [caseView, api] = await Promise.all([
    readSource('../src/components/CaseManageView.vue'),
    readSource('../src/api/operator.ts'),
  ])

  assert.doesNotMatch(caseView, /疾病字典/)
  assert.doesNotMatch(caseView, /createDisease|updateDisease|deleteDisease/)
  assert.doesNotMatch(api, /export function createDisease/)
  assert.doesNotMatch(api, /export function updateDisease/)
  assert.doesNotMatch(api, /export function deleteDisease/)
})

test('operator contracts expose stable disease identity and immutable update payload', async () => {
  const api = await readSource('../src/api/operator.ts')

  assert.match(api, /export interface Disease[\s\S]*?code: string[\s\S]*?operator_enabled: boolean/)
  assert.match(api, /export interface LongitudinalCaseDisease[\s\S]*?code: string[\s\S]*?operator_enabled: boolean/)
  assert.match(api, /export interface LongitudinalCase[\s\S]*?disease: LongitudinalCaseDisease/)
  const updatePayload = api.match(/export interface LongitudinalCaseUpdatePayload \{[\s\S]*?\n\}/)?.[0] || ''
  assert.ok(updatePayload, 'explicit longitudinal update payload must exist')
  assert.doesNotMatch(updatePayload, /disease_id/)
  assert.match(api, /updateLongitudinalCase\(id: number, data: LongitudinalCaseUpdatePayload\)/)
})

test('stage routing uses stable code and preserves disabled case disease identity', async () => {
  const editor = await readSource('../src/components/LongitudinalCaseEditor.vue')

  assert.match(editor, /stageOptionsByCode/)
  assert.match(editor, /selectedDisease\.value\?\.code/)
  assert.match(editor, /props\.modelValue\?\.disease/)
  assert.doesNotMatch(editor, /selectedDisease\.value\?\.name === '脂肪肝'/)
  assert.doesNotMatch(editor, /selectedDisease\.value\?\.name === '阿尔茨海默病'/)
})

test('disabled existing disease renders every case mutation read only', async () => {
  const [editor, view] = await Promise.all([
    readSource('../src/components/LongitudinalCaseEditor.vue'),
    readSource('../src/views/OperatorView.vue'),
  ])

  assert.match(editor, /该疾病当前已停用，病例暂时只读/)
  assert.match(editor, /const readOnly = computed/)
  assert.match(editor, /:disabled="readOnly"/)
  assert.match(editor, /if \(readOnly\.value\) return/)
  assert.match(view, /该疾病已停用，病例当前只读/)
  assert.match(view, /operatorStore\.currentLongitudinalCase\?\.disease\.operator_enabled === false/)
})

test('existing case updates omit disease id while creation retains it', async () => {
  const [store, view] = await Promise.all([
    readSource('../src/stores/operator.ts'),
    readSource('../src/views/OperatorView.vue'),
  ])

  assert.match(store, /LongitudinalCaseUpdatePayload/)
  assert.match(store, /updateLongitudinalCase\([^,]+, updatePayload\)/)
  assert.match(store, /createLongitudinalCase\(createPayload\)/)
  assert.match(view, /disease_id: draft\.disease_id/)
  assert.match(view, /progressionDiseases = computed\(\(\) => operatorStore\.diseases\)/)
  assert.doesNotMatch(view, /disease\.name === '脂肪肝'/)
  assert.doesNotMatch(view, /disease\.name === '阿尔茨海默病'/)
})
