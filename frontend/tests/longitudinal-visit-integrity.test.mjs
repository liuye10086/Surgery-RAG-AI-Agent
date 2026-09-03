import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const workspace = fs.readFileSync(new URL('../src/components/operator-case/OperatorCaseWorkspace.vue', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/operator-case/OperatorVisitTimelineEditor.vue', import.meta.url), 'utf8')

if (!editor.includes('visits.length <= 1')) throw new Error('editor does not protect the final visit')
if (!editor.includes('visits.length >= 10')) throw new Error('editor does not enforce the ten-visit UI guard')
if (!editor.includes('visit.indicators.length <= 1')) throw new Error('editor does not protect the final indicator')
if (!editor.includes("trimmed === '' ? null")) throw new Error('empty numeric input is converted to zero')
if (!editor.includes('visit_context')) throw new Error('structured visit context is missing')
if (!api.includes('visits: LongitudinalVisitInput[]')) throw new Error('aggregate payload does not carry visits')
if (!api.includes('visit_context?: VisitContext')) throw new Error('visit context is absent from the API contract')
if (!workspace.includes("visit_date: ''")) throw new Error('new case does not start with one editable visit')

console.log('longitudinal visit integrity UI contract passed')
