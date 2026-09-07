import { describe, expect, it } from 'vitest'
import { chartCoordinates } from '@/utils/report-chart'
describe('saved report chart', () => {
  it('uses calendar spacing', () => {
    const points = chartCoordinates([{visit_date:'2025-01-01',value:1},{visit_date:'2025-01-02',value:2},{visit_date:'2025-04-11',value:3}])
    expect(points[1]!.x-points[0]!.x).toBeCloseTo(3.6)
  })
  it('rejects missing, coerced and invalid dates', () => {
    for (const value of [null, true, '3', Infinity]) expect(() => chartCoordinates([{visit_date:'2025-01-01',value} as never])).toThrow()
    expect(() => chartCoordinates([{visit_date:'2025-02-30',value:1}])).toThrow()
  })
})

import {legacyChartPoints} from '../report-chart'
it('never coerces null, boolean or numeric strings in legacy charts',()=>{
  const item={unit_state:'consistent',series:[
    {visit_date:'2025-01-01',value:null},{visit_date:'2025-01-02',value:'2'},
    {visit_date:'2025-01-03',value:false},{visit_date:'2025-01-04',value:0},
  ]}
  expect(legacyChartPoints(item)).toEqual([])
})
