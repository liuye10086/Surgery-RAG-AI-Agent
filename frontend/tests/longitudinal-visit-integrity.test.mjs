import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/LongitudinalCaseEditor.vue', import.meta.url), 'utf8')

if (!editor.includes('visit.visit_index')) throw new Error('editor does not render the server visit index')
if (editor.includes('index + 1')) throw new Error('editor derives a business index from the array position')
if (!view.includes('至少保留 1 次访视')) throw new Error('view does not block an empty timeline')
if (!api.includes('visits: Array<{ visit_date: string')) throw new Error('create payload does not carry initial visits')
if (!store.includes('visits: visits || []')) throw new Error('store does not submit initial visits during case creation')

console.log('longitudinal visit integrity UI contract passed')
