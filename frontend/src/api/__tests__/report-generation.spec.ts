import {afterEach,describe,expect,it,vi} from 'vitest'
import {eventDecoder,subscribeReportJob,parseState} from '../report-generation'
import {parseRetryAfter} from '../request'

const state={report_id:7,batch_id:'batch',revision:2,status:'running',report_status:'generating',phase:'prediction',message:'模型预测中',legacy:false}
afterEach(()=>vi.unstubAllGlobals())

describe('durable report SSE transport',()=>{
  it('parses Retry-After seconds and HTTP dates',()=>{
    expect(parseRetryAfter('30')).toBe(30)
    expect(parseRetryAfter(new Date(Date.now()+60000).toUTCString())).toBeGreaterThanOrEqual(59)
    expect(parseRetryAfter('invalid')).toBeUndefined()
  })
  it('decodes CRLF across chunks and multiline final data',()=>{
    const consume=vi.fn(),decode=eventDecoder(consume)
    decode(': heartbeat\r\nevent: state\r\ndata: {"a":\r')
    decode('\ndata: 1}\r\n\r');decode('\n')
    decode('event: state\ndata: {"b":2}',true)
    expect(consume.mock.calls).toEqual([['state','{"a":\n1}'],['state','{"b":2}']])
  })
  it('preserves split UTF8 and treats nonterminal EOF as disconnect',async()=>{
    const bytes=new TextEncoder().encode(`event: state\ndata: ${JSON.stringify(state)}\n\n`)
    vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,body:new ReadableStream({start(controller){
      for(let index=0;index<bytes.length;index++)controller.enqueue(bytes.slice(index,index+1))
      controller.close()
    }})})))
    const onState=vi.fn(),disconnected=vi.fn()
    subscribeReportJob(7,onState,disconnected)
    await vi.waitFor(()=>expect(disconnected).toHaveBeenCalledOnce())
    expect(onState.mock.calls[0]?.[0].message).toBe('模型预测中')
  })
  it('abort only detaches and never posts cancel',async()=>{
    const fetcher=vi.fn((_url,options)=>new Promise((_resolve,reject)=>{
      options.signal.addEventListener('abort',()=>reject(new DOMException('Aborted','AbortError')))
    }))
    vi.stubGlobal('fetch',fetcher)
    const disconnected=vi.fn(),detach=subscribeReportJob(7,vi.fn(),disconnected)
    detach();await Promise.resolve();await Promise.resolve()
    expect(fetcher).toHaveBeenCalledOnce()
    expect(String(fetcher.mock.calls[0]?.[0])).toContain('/events')
    expect(disconnected).not.toHaveBeenCalled()
  })
  it('rejects inconsistent server state',()=>{
    expect(()=>parseState({...state,status:'completed'})).toThrow()
    expect(()=>parseState({...state,revision:0})).toThrow()
  })
})
