import request from './request'
import type { ReportListItem } from './operator'
export interface HistoryFilters {
  disease_code?: 'fatty_liver' | 'ad'
  anonymous_case_code?: string
  status?: 'generating' | 'completed' | 'failed' | 'cancelled'
  created_from?: string
  created_before?: string
}
export interface HistoryItem extends ReportListItem {
  pdf_status: string
}
export interface HistoryPage {
  items: HistoryItem[]
  next_cursor: string | null
  has_more: boolean
}
export function listHistory(
  params: HistoryFilters & { cursor?: string | null; limit?: number },
  signal?: AbortSignal,
): Promise<HistoryPage> {
  return request.get('/v1/operator/report-history', { params, signal })
}
