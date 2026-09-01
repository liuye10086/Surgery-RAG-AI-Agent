import request from './request'

export interface DiseaseUsageCounts {
  operator_cases: number
  case_records: number
  ai_reports: number
  reference_standards: number
}

export interface AdminDisease {
  id: number
  code: string
  name: string
  description: string | null
  operator_enabled: boolean
  usage_counts: DiseaseUsageCounts
  can_delete: boolean
  created_at: string
}

export interface AdminDiseaseCreate {
  code: string
  name: string
  description?: string | null
}

export interface AdminDiseaseUpdate {
  name?: string
  description?: string | null
  operator_enabled?: boolean
}

export const listAdminDiseases = (): Promise<AdminDisease[]> =>
  request.get('/v1/admin/diseases')

export const createAdminDisease = (payload: AdminDiseaseCreate): Promise<AdminDisease> =>
  request.post('/v1/admin/diseases', payload)

export const updateAdminDisease = (id: number, payload: AdminDiseaseUpdate): Promise<AdminDisease> =>
  request.put(`/v1/admin/diseases/${id}`, payload)

export const deleteAdminDisease = (id: number): Promise<void> =>
  request.delete(`/v1/admin/diseases/${id}`)
