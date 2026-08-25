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

test('standard management uses the dedicated two-stage document workflow', async () => {
  const source = await readFile(new URL('../src/components/StandardManagementView.vue', import.meta.url), 'utf8')

  assert.match(source, /uploadStandardDocument/)
  assert.match(source, /listStandardDocuments/)
  assert.doesNotMatch(source, /from '@\/api\/admin'/)
  assert.doesNotMatch(source, /uploadDocument/)
  assert.match(source, /新建标准集合/)
  assert.match(source, /选择疾病/)
  assert.doesNotMatch(source, /标准名称.*el-input/)
  assert.match(source, /新建版本/)
  assert.match(source, /standard_document_id/)
  assert.match(source, /可用|已关联/)
  assert.match(source, /deleteStandardDocument/)
  assert.match(source, /deleteVersion/)
  assert.match(source, /ElMessageBox/)
  assert.match(source, /parseVersion/)
  assert.match(source, /v-if="!document\.is_locked"/)
  assert.match(source, /\['draft', 'review'\]\.includes\(selectedVersion\.status\)/)
  assert.match(source, /width="min\(520px, calc\(100vw - 32px\)\)"/)

  const submitVersion = source.match(/async function submitVersion\(\)[\s\S]*?\n}\n\nasync function loadVersionData/)?.[0] || ''
  assert.match(submitVersion, /createVersion/)
  assert.doesNotMatch(submitVersion, /parseVersion/)
})

test('standard management rejects stale async workspace responses and preserves accessible targets', async () => {
  const source = await readFile(new URL('../src/components/StandardManagementView.vue', import.meta.url), 'utf8')

  assert.match(source, /selectedStandard\.value\?\.id !== standardId/)
  assert.match(source, /selectedVersionId\.value !== id/)
  assert.match(source, /\.standard-management :deep\(\.el-dialog__footer \.el-button\)/)
  assert.match(source, /min-height: 44px/)
})

test('standard management hardens workspace mutations and repeated request ordering', async () => {
  const source = await readFile(new URL('../src/components/StandardManagementView.vue', import.meta.url), 'utf8')

  assert.match(source, /workspaceLoadedVersionId/)
  assert.match(source, /async function loadVersionData\(\)[\s\S]*?clearVersionWorkspace\(\)[\s\S]*?Promise\.all/)
  assert.match(source, /rule\.version_id !== selectedVersionId\.value/)
  assert.match(source, /editorRule\.value\.version_id !== selectedVersionId\.value/)

  assert.match(source, /const lifecyclePending = ref\(false\)/)
  assert.match(source, /if \(lifecyclePending\.value\) return/)
  assert.match(source, /lifecyclePending\.value = true/)
  assert.match(source, /lifecyclePending\.value = false/)
  assert.match(source, /:disabled="lifecyclePending \|\|/)

  assert.match(source, /let standardDocumentsRequestSequence = 0/)
  assert.match(source, /const requestSequence = \+\+standardDocumentsRequestSequence/)
  assert.match(source, /requestSequence !== standardDocumentsRequestSequence/)
  assert.match(source, /let versionsRequestSequence = 0/)
  assert.match(source, /const requestSequence = \+\+versionsRequestSequence/)
  assert.match(source, /latestVersionsRequestByStandard\.get\(standardId\) !== requestSequence/)

  assert.match(source, /const targetVersionId = selectedVersion\.value\.id/)
  assert.match(source, /const targetStandardId = selectedStandard\.value\.id/)
  assert.match(source, /selectedVersionId\.value === targetVersionId/)

  assert.match(source, /\.upload-title :deep\(\.el-input__wrapper\)/)
  assert.match(source, /\.version-select :deep\(\.el-select__wrapper\)/)
})

test('admin standards API exposes dedicated standard document contracts', async () => {
  const api = await readFile(
    new URL('../src/api/adminStandards.ts', import.meta.url),
    'utf8',
  )

  assert.match(api, /uploadStandardDocument/)
  assert.match(api, /listStandardDocuments/)
  assert.match(api, /deleteStandardDocument/)
  assert.match(api, /deleteVersion/)
  assert.match(api, /disease_id: number/)
  assert.match(api, /standard_document_id/)
  assert.doesNotMatch(api, /(^|[^A-Za-z0-9_])document_id: number/)
  assert.match(api, /available_only/)
  assert.match(
    api,
    /createStandard\s*=\s*\(payload:\s*\{\s*disease_id:\s*number\s*\}\)/,
  )
  assert.match(
    api,
    /createVersion[\s\S]*?standard_document_id:\s*number/,
  )
})

test('operator cannot mutate standards', async () => {
  const api = await readFile(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
  const caseManage = await readFile(new URL('../src/components/CaseManageView.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(api, /syncReferenceRanges/)
  assert.doesNotMatch(caseManage, /解析为参考范围/)
})
