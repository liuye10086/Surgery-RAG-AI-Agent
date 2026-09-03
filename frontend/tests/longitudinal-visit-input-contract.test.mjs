import fs from 'node:fs'

const request = fs.readFileSync(new URL('../src/api/request.ts', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/operator-case/OperatorVisitTimelineEditor.vue', import.meta.url), 'utf8')
const workspace = fs.readFileSync(new URL('../src/components/operator-case/OperatorCaseWorkspace.vue', import.meta.url), 'utf8')
const actionBar = fs.readFileSync(new URL('../src/components/operator-case/OperatorCaseActionBar.vue', import.meta.url), 'utf8')

if (!request.includes('class ApiRequestError')) throw new Error('API errors are not normalized')
if (!request.includes('validationIssueMap')) throw new Error('field issue mapping is missing')
if (!editor.includes('aria-label="添加指标"')) throw new Error('indicator add action missing')
if (!editor.includes("trimmed === '' ? null")) throw new Error('blank numeric input is not null-safe')
if (!editor.includes('validationIssues')) throw new Error('visit field errors are not accepted')
if (!editor.includes('aria-invalid')) throw new Error('field errors are not exposed accessibly')
if (!workspace.includes("'disease-change'")) throw new Error('disease catalog refresh event is missing')
if (actionBar.includes('至少需要 3') || actionBar.includes('至少 3')) throw new Error('report gate is hardcoded in UI')
if (!actionBar.includes('dirty || !readiness?.ready')) throw new Error('report generation can use an unsaved timeline')

console.log('longitudinal visit input UI contract passed')
