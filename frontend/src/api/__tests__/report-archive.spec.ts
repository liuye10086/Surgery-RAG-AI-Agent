import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  downloadFilename,
  downloadOriginal,
  prepareArchive,
} from '../report-archive'
describe('archive HTTP contract', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('rejects unsafe filenames and decodes the server filename', () => {
    expect(
      downloadFilename(
        "attachment; filename*=UTF-8''%E6%8A%A5%E5%91%8A.pdf",
        1,
      ),
    ).toBe('报告.pdf')
    expect(downloadFilename('attachment; filename="../private.pdf"', 1)).toBe(
      'report-1.pdf',
    )
  })
  it('normalizes structured errors and Retry-After', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({
              detail: { code: 'pdf_capacity_exceeded', message: '请稍后重试' },
            }),
            { status: 429, headers: { 'Retry-After': '10' } },
          ),
        ),
    )
    await expect(prepareArchive(1, 'key')).rejects.toMatchObject({
      code: 'pdf_capacity_exceeded',
      message: '请稍后重试',
      retryAfterSeconds: 10,
    })
  })
  it('never creates a download after account or page identity changed', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('%PDF', {
            headers: { 'Content-Type': 'application/pdf' },
          }),
        ),
    )
    const create = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create }))
    await downloadOriginal(1, undefined, () => false)
    expect(create).not.toHaveBeenCalled()
  })
  it('rejects an HTML success response before creating a blob download', async () => {
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('login', { headers: { 'Content-Type': 'text/html' } }),
        ),
    )
    await expect(downloadOriginal(1)).rejects.toMatchObject({
      code: 'invalid_pdf_response',
    })
  })
})
