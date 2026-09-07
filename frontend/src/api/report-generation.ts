import request, {ApiRequestError,parseRetryAfter} from './request'

export type JobStatus='queued'|'running'|'completed'|'failed'|'cancelled'
export type JobPhase='queued'|'model_loading'|'prediction'|'standard_evidence'|'rendering'|'persistence'|'terminal'
export interface GenerationStatus {
  report_id:number; batch_id:string|null; status:JobStatus; report_status:'generating'|'completed'|'failed'|'cancelled'
  phase:JobPhase; revision:number; updated_at:string; error_code:string|null; message:string;cancel_requested:boolean;legacy:boolean
}
export interface JobAccepted {report_id:number;batch_id:string;status:JobStatus;status_url:string;events_url:string}
export const submitReportJob=(caseId:number,key:string):Promise<JobAccepted>=>request.post(`/v1/operator/longitudinal-cases/${caseId}/report-jobs`,{model_options:{}},{headers:{'Idempotency-Key':key}})
export const getGenerationStatus=(reportId:number):Promise<GenerationStatus>=>request.get(`/v1/operator/reports/${reportId}/generation-status`)
export const cancelReportJob=(reportId:number):Promise<GenerationStatus>=>request.post(`/v1/operator/reports/${reportId}/cancel`)

export function parseState(value:unknown):GenerationStatus {
  if (!value || typeof value!=='object') throw new Error('invalid_generation_state')
  const state=value as GenerationStatus
  if (!Number.isSafeInteger(state.report_id) || state.report_id<=0 || !Number.isSafeInteger(state.revision) || state.revision<1 ||
    !['queued','running','completed','failed','cancelled'].includes(state.status) ||
    !['queued','model_loading','prediction','standard_evidence','rendering','persistence','terminal'].includes(state.phase) ||
    (typeof state.batch_id!=='string' && !(state.legacy && state.batch_id===null)) ||
    state.report_status!==(['queued','running'].includes(state.status)?'generating':state.status)) throw new Error('invalid_generation_state')
  return state
}

export function eventDecoder(consume:(event:string,data:string)=>void) {
  let buffer=''
  return (chunk:string,finished=false)=>{
    buffer+=chunk
    let match:RegExpExecArray|null
    while ((match=/\r?\n\r?\n/.exec(buffer))) {
      const block=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length)
      consumeBlock(block)
    }
    if (finished && buffer.trim()) {consumeBlock(buffer);buffer=''}
  }
  function consumeBlock(block:string) {
    let event='message';const data:string[]=[]
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith('event:')) event=line.slice(6).trim()
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /,''))
    }
    if (data.length) consume(event,data.join('\n'))
  }
}

export function subscribeReportJob(reportId:number,onState:(state:GenerationStatus)=>void,onDisconnect:(error?:unknown)=>void):()=>void {
  const controller=new AbortController()
  let terminal=false
  const decode=eventDecoder((event,data)=>{
    if (event==='state') {
      const state=parseState(JSON.parse(data));onState(state)
      terminal=['completed','failed','cancelled'].includes(state.status)
    } else if (event==='error') {
      const error=JSON.parse(data) as {code?:string;message?:string}
      throw new ApiRequestError({code:error.code || 'stream_error',message:error.message || '状态连接已中断',status:error.code==='auth_expired'?401:undefined})
    }
  })
  void (async()=>{
    try {
      const response=await fetch(`/api/v1/operator/reports/${reportId}/events`,{
        headers:{Authorization:`Bearer ${localStorage.getItem('token') || ''}`},signal:controller.signal})
      if (!response.ok || !response.body) throw new ApiRequestError({code:`http_${response.status}`,message:'生成状态连接失败',status:response.status,retryAfterSeconds:parseRetryAfter(response.headers.get('Retry-After'))})
      const reader=response.body.getReader();const decoder=new TextDecoder()
      try {
        while (true) {
          const {value,done}=await reader.read()
          decode(decoder.decode(value,{stream:!done}),done)
          if (done) break
        }
      } finally {reader.releaseLock()}
      if (!terminal && !controller.signal.aborted) onDisconnect()
    } catch(error) {
      if (!controller.signal.aborted) onDisconnect(error)
    }
  })()
  return ()=>controller.abort()
}
