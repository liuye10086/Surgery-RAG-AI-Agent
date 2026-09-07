import { ApiRequestError, normalizeApiError } from './request'

export interface PdfArchiveStatus {
  report_id: number
  state:
    | 'not_requested'
    | 'queued'
    | 'rendering'
    | 'ready'
    | 'failed'
    | 'missing'
    | 'corrupt'
  attempt_id: number | null
  revision: number
  phase: string | null
  code: string | null
  message: string
  can_retry: boolean
  pdf_sha256?: string | null
  size_bytes?: number | null
  page_count?: number | null
  archived_at?: string | null
}
async function call(
  reportId: number,
  signal?: AbortSignal,
  key?: string,
  retry = false,
): Promise<PdfArchiveStatus> {
  const token = localStorage.getItem('token')
  const response = await fetch(
    `/api/v1/operator/reports/${reportId}/pdf-archive${retry ? '/retry' : ''}`,
    {
      method: key ? 'POST' : 'GET',
      signal,
      cache: 'no-store',
      headers: {
        Authorization: token ? `Bearer ${token}` : '',
        ...(key
          ? { 'Idempotency-Key': key, 'Content-Type': 'application/json' }
          : {}),
      },
      ...(key ? { body: '{}' } : {}),
    },
  )
  const data = await response.json().catch(() => ({}))
  if (!response.ok)
    throw normalizeApiError({
      response: {
        status: response.status,
        data,
        headers: { 'retry-after': response.headers.get('Retry-After') },
      },
    })
  if (
    data.report_id !== reportId ||
    !Number.isSafeInteger(data.revision) ||
    ![
      'not_requested',
      'queued',
      'rendering',
      'ready',
      'failed',
      'missing',
      'corrupt',
    ].includes(data.state)
  )
    throw new Error('PDF 状态响应无效')
  return data
}
export const readArchive = (id: number, signal?: AbortSignal) =>
  call(id, signal)
export const prepareArchive = (
  id: number,
  key: string,
  retry = false,
  signal?: AbortSignal,
) => call(id, signal, key, retry)

export function downloadFilename(header: string | null, id: number): string {
  const encoded = header?.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const plain = header?.match(/filename="([^"]+)"/i)?.[1]
  let name = ''
  try {
    name = encoded ? decodeURIComponent(encoded) : plain || ''
  } catch {
    /* safe fallback */
  }
  return name.length <= 180 &&
    name.endsWith('.pdf') &&
    !/[\\/\x00-\x1f\x7f:]/.test(name)
    ? name
    : `report-${id}.pdf`
}
export async function downloadOriginal(
  id: number,
  signal?: AbortSignal,
  isCurrent: () => boolean = () => true,
): Promise<void> {
  const token = localStorage.getItem('token')
  const current = () =>
    !signal?.aborted && token === localStorage.getItem('token') && isCurrent()
  const response = await fetch(`/api/v1/operator/reports/${id}/download`, {
    signal,
    cache: 'no-store',
    headers: { Authorization: token ? `Bearer ${token}` : '' },
  })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw normalizeApiError({
      response: {
        status: response.status,
        data,
        headers: { 'retry-after': response.headers.get('Retry-After') },
      },
    })
  }
  if (
    response.headers.get('Content-Type')?.split(';')[0]?.trim() !==
    'application/pdf'
  )
    throw new ApiRequestError({
      code: 'invalid_pdf_response',
      message: '下载响应不是 PDF 文件',
    })
  const blob = await response.blob()
  if (!current()) return
  const url = URL.createObjectURL(blob),
    anchor = document.createElement('a')
  try {
    anchor.href = url
    anchor.download = downloadFilename(
      response.headers.get('Content-Disposition'),
      id,
    )
    document.body.appendChild(anchor)
    anchor.click()
  } finally {
    anchor.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  }
}
