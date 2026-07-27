import request from './request'

export interface DocumentUploadResponse {
  id: number
  filename: string
  title: string | null
  status: string
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

export function uploadDocument(file: File, title?: string): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (title) {
    formData.append('title', title)
  }
  return request.post('/v1/admin/documents/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
}

export function listDocuments(skip = 0, limit = 100, search?: string): Promise<DocumentListOut> {
  return request.get('/v1/admin/documents', { params: { skip, limit, search } })
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
