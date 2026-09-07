export function savedValue(value: unknown): string {
  if (value === null || value === undefined) return '未记录'
  if (typeof value === 'number')
    return Number.isFinite(value) ? String(value) : '记录无效'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}
export function phaseLabel(value: string | null | undefined): string {
  return (
    (
      {
        queued: '排队',
        model_loading: '加载模型',
        prediction: '模型计算',
        standard_evidence: '查询标准与参考证据',
        rendering: '编排报告',
        persistence: '保存报告',
        terminal: '结束',
        unknown: '未记录',
      } as Record<string, string>
    )[value || 'unknown'] || '未记录'
  )
}
export function stageLabel(value: unknown): string {
  const code = typeof value === 'string' ? value : ''
  const label = (
    {
      pre_cirrhosis: '肝硬化前期',
      cirrhosis: '肝硬化',
      hcc: '肝癌',
      cn: '认知正常',
      mci: '轻度认知障碍',
      dementia: '痴呆',
    } as Record<string, string>
  )[code]
  return label ? `${label}（${code}）` : savedValue(value)
}
export function shanghaiDateRange(from: string, to: string) {
  const start = from ? new Date(`${from}T00:00:00+08:00`) : null
  const end = to
    ? new Date(new Date(`${to}T00:00:00+08:00`).getTime() + 86400000)
    : null
  return {
    created_from: start?.toISOString(),
    created_before: end?.toISOString(),
  }
}
