import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const editor = fs.readFileSync(path.join(root, 'src/components/LongitudinalCaseEditor.vue'), 'utf8')
const operator = fs.readFileSync(path.join(root, 'src/views/OperatorView.vue'), 'utf8')
const api = fs.readFileSync(path.join(root, 'src/api/operator.ts'), 'utf8')

test('editor shows generated anonymous code instead of editable patient label', () => {
  assert.match(editor, /anonymous_case_code/)
  assert.doesNotMatch(editor, /v-model="draft\.patient_label"/)
})

test('operator report and API contracts carry anonymous code', () => {
  assert.match(operator, /anonymous_case_code/)
  assert.match(api, /anonymous_case_code/)
})
