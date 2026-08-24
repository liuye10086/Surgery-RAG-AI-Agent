import fs from 'node:fs'

const api = fs.readFileSync(new URL('../src/api/operator.ts', import.meta.url), 'utf8')
const store = fs.readFileSync(new URL('../src/stores/operator.ts', import.meta.url), 'utf8')

if (api.includes('function generateReportStream')) throw new Error('legacy API still present')
if (store.includes('function generateReport(')) throw new Error('legacy store action still present')
if (store.includes('generateReportStream')) throw new Error('legacy store import still present')
if (api.includes('analysis_backend')) throw new Error('legacy backend selector still present')

console.log('operator legacy cleanup contract passed')
