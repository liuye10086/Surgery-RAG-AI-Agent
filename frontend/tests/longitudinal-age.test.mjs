import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const apiPath = new URL('../src/api/operator.ts', import.meta.url)
const storePath = new URL('../src/stores/operator.ts', import.meta.url)
const editorPath = new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url)
const viewPath = new URL('../src/views/OperatorView.vue', import.meta.url)

test('longitudinal case contracts carry a required integer age when saving', async () => {
  const [api, store, view] = await Promise.all([
    readFile(apiPath, 'utf8'),
    readFile(storePath, 'utf8'),
    readFile(viewPath, 'utf8'),
  ])

  assert.match(api, /interface LongitudinalCase[\s\S]*?age:\s*number\s*\|\s*null/)
  assert.match(api, /interface LongitudinalCaseCreatePayload[\s\S]*?age:\s*number/)
  assert.match(api, /createLongitudinalCase\(data:\s*LongitudinalCaseCreatePayload/)
  assert.match(store, /saveLongitudinalCase\(data:\s*LongitudinalCaseCreatePayload/)
  assert.match(view, /age:\s*draft\.age/)
  assert.match(view, /Number\.isInteger\(draft\.age\)/)
  assert.match(view, /请填写0–120岁的整数年龄/)
})

test('longitudinal editor accepts only ages from zero through 120', async () => {
  const editor = await readFile(editorPath, 'utf8')

  assert.match(editor, /v-model="draft\.age"/)
  assert.match(editor, /:min="0"/)
  assert.match(editor, /:max="120"/)
  assert.match(editor, /:precision="0"/)
  assert.match(editor, /age:\s*value\?\.age\s*\?\?\s*null/)
})
