import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import AdminView from '../AdminView.vue'

const api = vi.hoisted(() => ({ listDocuments: vi.fn(), listDepartments: vi.fn(), chunkDocument: vi.fn(), updateDocument: vi.fn() }))
vi.mock('@/api/admin', async () => ({ ...await vi.importActual('@/api/admin'), ...api }))
vi.mock('element-plus', async () => ({ ...await vi.importActual('element-plus'), ElMessage: { success: vi.fn(), error: vi.fn() } }))

const original = { id: 9, title: '旧标题', filename: 'fixture.pdf', file_type: '.pdf', file_size: 20, status: 'pending', error_message: null, version: 1, is_current: true, access_scope: 'both', department_id: null, department_name: null, chunk_count: 0, created_at: '2026-09-08T00:00:00Z', updated_at: '2026-09-08T00:00:00Z' }
let wrapper: VueWrapper

async function click(label: string) {
  const button = wrapper.findAll('button').find(item => item.text() === label)
  expect(button, `button ${label}`).toBeDefined()
  await button!.trigger('click')
  await flushPromises()
}

beforeEach(async () => {
  vi.clearAllMocks()
  api.listDocuments.mockResolvedValue({ total: 1, items: [{ ...original }] })
  api.listDepartments.mockResolvedValue([])
  wrapper = mount(AdminView, { attachTo: document.body, global: { plugins: [ElementPlus], stubs: { AdminSidebar: true, DiseaseManagementView: true, StandardManagementView: true, ElSelect: true, ElOption: true, teleport: true } } })
  await flushPromises()
})
afterEach(() => { wrapper.unmount(); document.body.innerHTML = '' })

describe('document administration', () => {
  it('shows one chunk failure and refreshes failed state with loading cleared', async () => {
    const detail = '分块失败，请检查文件是否损坏或格式是否受支持'
    api.chunkDocument.mockImplementationOnce(async () => {
      ElMessage.error(detail) // The shared request interceptor already reports the failure.
      api.listDocuments.mockResolvedValue({ total: 1, items: [{ ...original, status: 'failed', error_message: detail }] })
      throw new Error(detail)
    })
    await click('分块')
    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('失败')
    expect(api.listDocuments).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('button').find(item => item.text() === '分块')!.classes()).not.toContain('is-loading')
  })

  it('saves only title and refreshes displayed value', async () => {
    await click('编辑标题')
    await wrapper.get('input[aria-label="文档标题"]').setValue(' 新标题 ')
    api.updateDocument.mockImplementationOnce(async () => {
      api.listDocuments.mockResolvedValue({ total: 1, items: [{ ...original, title: '新标题' }] })
      return { ...original, title: '新标题' }
    })
    await click('保存')
    expect(api.updateDocument).toHaveBeenCalledWith(9, { title: '新标题' })
    expect(wrapper.get('.doc-title').text()).toBe('新标题')
  })

  it('cancels without sending an update', async () => {
    await click('编辑标题')
    await wrapper.get('input[aria-label="文档标题"]').setValue('取消内容')
    await click('取消')
    expect(api.updateDocument).not.toHaveBeenCalled()
    expect(wrapper.get('.doc-title').text()).toBe('旧标题')
  })

  it('retains failed edits for retry and blocks duplicate saves while pending', async () => {
    await click('编辑标题')
    await wrapper.get('input[aria-label="文档标题"]').setValue('重试标题')
    let reject!: (reason: Error) => void
    api.updateDocument.mockImplementationOnce(() => new Promise((_resolve, rejectPromise) => { reject = rejectPromise }))
    await click('保存')
    expect(wrapper.findAll('button').find(item => item.text() === '保存')!.attributes('disabled')).toBeDefined()
    reject(new Error('Request failed'))
    await flushPromises()
    expect((wrapper.get('input[aria-label="文档标题"]').element as HTMLInputElement).value).toBe('重试标题')
    expect(wrapper.findAll('button').find(item => item.text() === '保存')!.attributes('disabled')).toBeUndefined()
  })

  it('clears an optional title to use the filename', async () => {
    await click('编辑标题')
    await wrapper.get('input[aria-label="文档标题"]').setValue(' ')
    api.updateDocument.mockImplementationOnce(async () => {
      api.listDocuments.mockResolvedValue({ total: 1, items: [{ ...original, title: null }] })
      return { ...original, title: null }
    })
    await click('保存')
    expect(api.updateDocument).toHaveBeenCalledWith(9, { title: null })
    expect(wrapper.get('.doc-title').text()).toBe('fixture.pdf')
  })
})
