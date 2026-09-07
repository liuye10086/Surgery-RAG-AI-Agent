export function chartCoordinates(points: Array<{visit_date: string; value: number}>) {
  const times = points.map(p => Date.parse(`${p.visit_date}T00:00:00Z`))
  if (!points.length || points.some((p, i) => typeof p.value !== 'number' || !Number.isFinite(p.value) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(p.visit_date) || !Number.isFinite(times[i]) ||
    new Date(times[i]!).toISOString().slice(0,10) !== p.visit_date)) throw new Error('invalid_chart_points')
  const first = Math.min(...times), span = Math.max(...times)-first || 1
  const low = Math.min(...points.map(p=>p.value)), height = Math.max(...points.map(p=>p.value))-low || 1
  return points.map((p,i)=>({x:42+(times[i]!-first)/span*360,y:116-(p.value-low)/height*96,date:p.visit_date,value:p.value}))
}

export function legacyChartPoints(item: {series?: unknown;unit_state?:string}) {
  if (item.unit_state!=='consistent' || !Array.isArray(item.series)) return []
  const points=item.series.filter((p:unknown):p is {visit_date:string;value:number}=>{
    if (!p || typeof p!=='object') return false
    try {chartCoordinates([p as {visit_date:string;value:number}]);return true} catch {return false}
  })
  return points.length>=3?chartCoordinates(points):[]
}
