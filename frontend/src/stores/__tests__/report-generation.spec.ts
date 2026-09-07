import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest'
import {createPinia,setActivePinia} from 'pinia'
import {useReportGenerationStore} from '@/stores/report-generation'
import {getGenerationStatus,cancelReportJob,subscribeReportJob,submitReportJob} from '@/api/report-generation'
import {getReport} from '@/api/operator'
vi.mock('@/api/report-generation',()=>({getGenerationStatus:vi.fn(),cancelReportJob:vi.fn(),submitReportJob:vi.fn(),subscribeReportJob:vi.fn(()=>vi.fn())}))
vi.mock('@/api/operator',()=>({getReport:vi.fn()}))
describe('report generation state',()=>{
  it.each(['failed','cancelled'])('reads saved detail for %s without starting another job',async(status)=>{
    vi.mocked(getGenerationStatus).mockResolvedValue({report_id:7,batch_id:'batch',revision:4,status,phase:'terminal'} as never)
    vi.mocked(getReport).mockResolvedValue({id:7,generation_batch_id:'batch',status,publication_status:'not_published'} as never)
    const store=useReportGenerationStore();await store.observe(7)
    expect(getReport).toHaveBeenCalledWith(7)
    expect(store.report?.status).toBe(status)
    expect(submitReportJob).not.toHaveBeenCalled()
  })
  it('honors Retry-After even when the window regains focus',async()=>{
    vi.useFakeTimers()
    vi.mocked(getGenerationStatus).mockRejectedValue({status:429,retryAfterSeconds:30})
    const store=useReportGenerationStore();await store.observe(7)
    store.refreshConnection()
    await vi.advanceTimersByTimeAsync(29999)
    expect(getGenerationStatus).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(getGenerationStatus).toHaveBeenCalledTimes(2)
    store.detach()
  })
  afterEach(()=>vi.useRealTimers())
  beforeEach(()=>{setActivePinia(createPinia());vi.clearAllMocks();sessionStorage.clear()})
  it('detaches without cancelling',()=>{
    const store=useReportGenerationStore();store.detach()
    expect(cancelReportJob).not.toHaveBeenCalled()
    expect(store.viewState).toBe('idle')
  })
  it('keeps loading_completed until the detail arrives',async()=>{
    vi.mocked(getGenerationStatus).mockResolvedValue({report_id:7,batch_id:'batch',revision:4,status:'completed',phase:'terminal'} as never)
    let resolve!: (value:never)=>void
    vi.mocked(getReport).mockReturnValue(new Promise(r=>{resolve=r}))
    const store=useReportGenerationStore()
    const pending=store.observe(7)
    await Promise.resolve();await Promise.resolve()
    expect(store.viewState).toBe('loading_completed')
    resolve({id:7,generation_batch_id:'batch',status:'completed'} as never)
    await pending
    expect(store.viewState).toBe('completed')
  })
  it('ignores a late completion after detaching',async()=>{
    vi.mocked(getGenerationStatus).mockResolvedValue({report_id:7,batch_id:'batch',revision:1,status:'running',phase:'prediction'} as never)
    const store=useReportGenerationStore()
    await store.observe(7)
    const deliver=vi.mocked(subscribeReportJob).mock.calls[0]![1]
    store.detach()
    deliver({report_id:7,batch_id:'batch',revision:4,status:'completed',phase:'terminal'} as never)
    expect(store.viewState).toBe('idle')
    expect(getReport).not.toHaveBeenCalled()
  })
  it('retries completed detail without creating another job',async()=>{
    vi.mocked(getGenerationStatus).mockResolvedValue({report_id:7,batch_id:'batch',revision:4,status:'completed',phase:'terminal'} as never)
    vi.mocked(getReport).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({id:7,generation_batch_id:'batch',status:'completed'} as never)
    const store=useReportGenerationStore();await store.observe(7)
    expect(store.viewState).toBe('load_failed')
    await store.retryDetail()
    expect(store.viewState).toBe('completed')
    expect(submitReportJob).not.toHaveBeenCalled()
  })
  it('uses 2, 5, 10 second backoff and rejects stale revisions',async()=>{
    vi.useFakeTimers()
    const running={report_id:7,batch_id:'batch',revision:3,status:'running',phase:'prediction'}
    vi.mocked(getGenerationStatus).mockResolvedValueOnce(running as never).mockRejectedValue(new Error('offline'))
    const store=useReportGenerationStore();await store.observe(7)
    const deliver=vi.mocked(subscribeReportJob).mock.calls[0]![1]
    deliver({...running,revision:2,status:'completed'} as never)
    deliver({...running,batch_id:'other',revision:4,status:'completed'} as never)
    expect(getReport).not.toHaveBeenCalled()
    vi.mocked(subscribeReportJob).mock.calls[0]![2]()
    for(const delay of [2000,5000,10000]) {
      const count=vi.mocked(getGenerationStatus).mock.calls.length
      await vi.advanceTimersByTimeAsync(delay-1)
      expect(getGenerationStatus).toHaveBeenCalledTimes(count)
      await vi.advanceTimersByTimeAsync(1)
      expect(getGenerationStatus).toHaveBeenCalledTimes(count+1)
    }
    store.detach()
  })
  it('reuses the original key after an uncertain admission response',async()=>{
    vi.mocked(submitReportJob).mockRejectedValue(new Error('response lost'))
    const store=useReportGenerationStore()
    await store.submit(8);await store.submit(8)
    expect(vi.mocked(submitReportJob).mock.calls[0]![1]).toBe(vi.mocked(submitReportJob).mock.calls[1]![1])
    expect(JSON.stringify(store.recoverPending())).not.toContain('notes')
  })
  it('restores an unresolved request after page reload',()=>{
    sessionStorage.setItem('operator-report-request:unknown',JSON.stringify({case_id:8,key:'same-key'}))
    const store=useReportGenerationStore();store.restorePending()
    expect(store.pendingCaseId).toBe(8)
    expect(store.viewState).toBe('load_failed')
    expect(submitReportJob).not.toHaveBeenCalled()
  })

})
