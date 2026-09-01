import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const readSource = path => readFile(new URL(path, import.meta.url), 'utf8')

test('admin navigation exposes disease management', async () => {
  const sidebar = await readSource('../src/components/AdminSidebar.vue')
  const view = await readSource('../src/views/AdminView.vue')

  assert.match(sidebar, /key: 'diseases'/)
  assert.match(sidebar, /疾病管理/)
  assert.match(view, /activeSection === 'diseases'/)
  assert.match(view, /DiseaseManagementView/)
})

test('administrator disease API exposes full catalog mutations', async () => {
  const api = await readSource('../src/api/adminDiseases.ts')

  assert.match(api, /export interface AdminDisease/)
  assert.match(api, /code: string/)
  assert.match(api, /operator_enabled: boolean/)
  assert.match(api, /usage_counts:/)
  assert.match(api, /can_delete: boolean/)
  assert.match(api, /listAdminDiseases/)
  assert.match(api, /request\.get\('\/v1\/admin\/diseases'\)/)
  assert.match(api, /createAdminDisease/)
  assert.match(api, /request\.post\('\/v1\/admin\/diseases'/)
  assert.match(api, /updateAdminDisease/)
  assert.match(api, /request\.put\(`\/v1\/admin\/diseases\/\$\{id\}`/)
  assert.match(api, /deleteAdminDisease/)
  assert.match(api, /request\.delete\(`\/v1\/admin\/diseases\/\$\{id\}`\)/)
})

test('disease code is required on create and read only after creation', async () => {
  const source = await readSource('../src/components/DiseaseManagementView.vue')

  assert.match(source, /固定代码/)
  assert.match(source, /例如：gastric_cancer/)
  assert.match(source, /operator_enabled/)
  assert.match(source, /该疾病尚未配置预测能力/)
  assert.match(source, /该疾病已被业务数据引用，只能停用/)
  assert.match(source, /停用后，该疾病的既有病例将变为只读/)
  assert.doesNotMatch(source, /editForm\.code/)
})

test('disease management follows accessible design-system targets', async () => {
  const source = await readSource('../src/components/DiseaseManagementView.vue')
  const sidebar = await readSource('../src/components/AdminSidebar.vue')

  assert.match(source, /min-height:\s*44px/)
  assert.match(source, /var\(--bg-canvas\)/)
  assert.match(source, /var\(--bg-surface\)/)
  assert.match(source, /var\(--border-default\)/)
  assert.match(source, /var\(--color-primary\)/)
  assert.match(source, /:focus-visible/)
  assert.match(source, /prefers-reduced-motion/)
  assert.match(sidebar, /\.nav-item[\s\S]*?min-height:\s*44px/)
  assert.match(sidebar, /\.cs-nav-item[\s\S]*?width:\s*44px[\s\S]*?height:\s*44px/)
})

test('standard management uses administrator full disease catalog', async () => {
  const source = await readSource('../src/components/StandardManagementView.vue')

  assert.match(source, /listAdminDiseases/)
  assert.match(source, /type AdminDisease/)
  assert.doesNotMatch(source, /listDiseases, type Disease.*@\/api\/operator/)
})
