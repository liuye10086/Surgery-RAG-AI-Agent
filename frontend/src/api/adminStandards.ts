import request from './request'

export interface Standard { id: number; disease_id: number; name: string; description?: string | null; status: string; current_version_id?: number | null }
export interface StandardVersion { id: number; standard_id: number; document_id: number; version_label: string; status: 'draft' | 'review' | 'approved' | 'retired'; content_hash: string; parser_version: string; effective_from?: string | null }
export interface StandardRule { id: number; version_id: number; rule_type?: string; indicator_id?: number | null; unit?: string | null; lower?: number | null; upper?: number | null; machine_actionability: 'calculable' | 'evidence-only' | 'blocked'; applicability?: Record<string, unknown>; interpretation?: string | null }
export interface StandardSegment { id: number; raw_text: string; segment_type: string; table_index?: number | null; row_index?: number | null; column_index?: number | null; parse_status: string }
export interface ValidationReport { errors: Array<Record<string, unknown>>; warnings: Array<Record<string, unknown>>; infos: Array<Record<string, unknown>>; projection_count: number }
export interface StandardCandidate { id: number; version_id: number; segment_id: number; source_type: 'deterministic' | 'llm'; raw_output?: string | null; candidate_json: Record<string, unknown>; status: string }
export interface StandardChangeLog { id: number; version_id: number; entity_type: string; entity_id: number; action: string; before_json: Record<string, unknown>; after_json: Record<string, unknown>; reason: string; created_at?: string }
export interface PublishResult { version: StandardVersion; projections: Array<Record<string, unknown>> }
export const createStandard = (payload: { disease_id: number; name: string; description?: string }): Promise<Standard> => request.post('/v1/admin/reference-standards', payload)
export const getStandard = (standardId: number): Promise<Standard> => request.get(`/v1/admin/reference-standards/${standardId}`)
export const createVersion = (standardId: number, payload: { document_id: number; version_label: string; parser_version?: string }): Promise<StandardVersion> => request.post(`/v1/admin/reference-standards/${standardId}/versions`, payload)
export const getVersion = (versionId: number): Promise<StandardVersion> => request.get(`/v1/admin/reference-standard-versions/${versionId}`)
export const listStandards = (): Promise<Standard[]> => request.get('/v1/admin/reference-standards')
export const listVersions = (standardId: number): Promise<StandardVersion[]> => request.get(`/v1/admin/reference-standards/${standardId}/versions`)
export const parseVersion = (versionId: number) => request.post(`/v1/admin/reference-standard-versions/${versionId}/parse`)
export const submitReview = (versionId: number): Promise<StandardVersion> => request.post(`/v1/admin/reference-standard-versions/${versionId}/submit-review`)
export const approveVersion = (versionId: number): Promise<StandardVersion> => request.post(`/v1/admin/reference-standard-versions/${versionId}/approve`)
export const retireVersion = (versionId: number): Promise<StandardVersion> => request.post(`/v1/admin/reference-standard-versions/${versionId}/retire`)
export const listSegments = (versionId: number): Promise<StandardSegment[]> => request.get(`/v1/admin/reference-standard-versions/${versionId}/segments`)
export const listRules = (versionId: number): Promise<StandardRule[]> => request.get(`/v1/admin/reference-standard-versions/${versionId}/rules`)
export const validateVersion = (versionId: number): Promise<ValidationReport> => request.get(`/v1/admin/reference-standard-versions/${versionId}/validation`)
export const patchRule = (ruleId: number, payload: Partial<StandardRule>, reason: string): Promise<StandardRule> => request.patch(`/v1/admin/reference-standard-rules/${ruleId}`, payload, { params: { reason } })
export const listCandidates = (versionId: number): Promise<StandardCandidate[]> => request.get(`/v1/admin/reference-standard-versions/${versionId}/candidates`)
export const reviewCandidate = (candidateId: number, status: StandardCandidate['status']): Promise<StandardCandidate> => request.patch(`/v1/admin/reference-standard-candidates/${candidateId}`, { status })
export const materializeCandidate = (candidateId: number, reason: string): Promise<StandardRule> => request.post(`/v1/admin/reference-standard-candidates/${candidateId}/materialize`, {}, { params: { reason } })
export const listHistory = (versionId: number): Promise<StandardChangeLog[]> => request.get(`/v1/admin/reference-standard-versions/${versionId}/history`)
