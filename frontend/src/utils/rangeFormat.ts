export interface RangeLike {
  lower: number | null
  upper: number | null
  lower_inclusive: boolean
  upper_inclusive: boolean
  unit?: string | null
}

export function formatRange(r: RangeLike): string {
  const u = r.unit ? ` ${r.unit}` : ''
  if (r.lower == null && r.upper != null) {
    return `${r.upper_inclusive ? '≤' : '<'}${r.upper}${u}`
  }
  if (r.upper == null && r.lower != null) {
    return `${r.lower_inclusive ? '≥' : '>'}${r.lower}${u}`
  }
  return `${r.lower}~${r.upper}${u}`
}
