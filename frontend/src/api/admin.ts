import request from './request'

export interface DepartmentOut {
  id: number
  name: string
  description: string | null
  is_active: boolean
  created_at: string
}

export interface DocumentUploadResponse {
  id: number
  filename: string
  title: string | null
  status: string
  department_id: number | null
}

export interface DocumentOut {
  id: number
  title: string | null
  filename: string
  file_type: string | null
  file_size: number | null
  status: string
  error_message: string | null
  version: number
  is_current: boolean
  chunk_count: number
  department_id: number | null
  department_name: string | null
  created_at: string
  updated_at: string
}

export interface DocumentListOut {
  total: number
  items: DocumentOut[]
}

export interface ChunkOut {
  id: number
  document_id: number
  content: string
  page_number: number | null
  chunk_index: number
  chunk_metadata: Record<string, any>
  created_at: string
}

export interface DocumentWithChunksOut extends DocumentOut {
  chunks: ChunkOut[]
}

export function uploadDocument(file: File, title?: string, department_id?: number): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (title) {
    formData.append('title', title)
  }
  if (department_id !== undefined && department_id !== null) {
    formData.append('department_id', String(department_id))
  }
  return request.post('/v1/admin/documents/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
}

export function listDocuments(skip = 0, limit = 100, search?: string, department_id?: number): Promise<DocumentListOut> {
  return request.get('/v1/admin/documents', { params: { skip, limit, search, department_id } })
}

export function updateDocument(id: number, department_id: number | null): Promise<DocumentOut> {
  return request.put(`/v1/admin/documents/${id}`, { department_id })
}

// 科室 API
export function listDepartments(activeOnly?: boolean): Promise<DepartmentOut[]> {
  return request.get('/v1/admin/departments', { params: { active_only: activeOnly } })
}

// 用户侧公开科室列表（无需管理员权限）
export function listPublicDepartments(): Promise<DepartmentOut[]> {
  return request.get('/v1/departments', { params: { active_only: true } })
}

export function getDocument(id: number): Promise<DocumentWithChunksOut> {
  return request.get(`/v1/admin/documents/${id}`)
}

export function deleteDocument(id: number): Promise<void> {
  return request.delete(`/v1/admin/documents/${id}`)
}

export function chunkDocument(id: number): Promise<DocumentWithChunksOut> {
  return request.post(`/v1/admin/documents/${id}/chunk`)
}

export function indexDocument(id: number): Promise<DocumentWithChunksOut> {
  // 向量化可能涉及模型加载 + 大量 chunk 编码，给 5 分钟超时
  return request.post(`/v1/admin/documents/${id}/index`, {}, { timeout: 300000 })
}

export function deleteChunk(documentId: number, chunkId: number): Promise<void> {
  return request.delete(`/v1/admin/documents/${documentId}/chunks/${chunkId}`)
}
