import {defineStore} from 'pinia'
import {computed,ref,watch} from 'vue'
import {useAuthStore} from '@/stores/auth'
import {getReport,type ReportDetail} from '@/api/operator'
import {submitReportJob,getGenerationStatus,subscribeReportJob,cancelReportJob,type GenerationStatus} from '@/api/report-generation'

export type GenerationViewState='idle'|'submitting'|'queued'|'running'|'reconnecting'|'loading_completed'|'completed'|'load_failed'|'failed'|'cancelled'
interface PendingRequest {case_id:number;key:string;report_id?:number}
const PREFIX='operator-report-request:'
export function clearReportRequestStorage() {
  for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key)
}
export function acceptsRevision(current:GenerationStatus|null,next:GenerationStatus) {
  return !current || (current.report_id===next.report_id && current.batch_id===next.batch_id && next.revision>current.revision)
}

export const useReportGenerationStore=defineStore('report-generation',()=>{
  const auth=useAuthStore()
  const reportId=ref<number|null>(null),state=ref<GenerationStatus|null>(null),report=ref<ReportDetail|null>(null)
  const viewState=ref<GenerationViewState>('idle'),message=ref(''),pendingCaseId=ref<number|null>(null)
  const active=computed(()=>['submitting','queued','running','reconnecting','loading_completed'].includes(viewState.value))
  const canCancel=computed(()=>state.value?.status==='queued' || state.value?.status==='running')
  let retryNotBefore=0
  let detailAttempt=0
  let epoch=0,disconnect:(()=>void)|null=null,timer:ReturnType<typeof setTimeout>|null=null,attempt=0
  const storageKey=()=>PREFIX+String(auth.user?.id || 'unknown')
  function saved():PendingRequest|null {
    try {
      const value=JSON.parse(sessionStorage.getItem(storageKey()) || 'null') as PendingRequest|null
      return value && Number.isSafeInteger(value.case_id) && typeof value.key==='string'?value:null
    } catch {return null}
  }
  function persist(value:PendingRequest) {sessionStorage.setItem(storageKey(),JSON.stringify(value))}
  function stop() {
    disconnect?.();disconnect=null
    if (timer) clearTimeout(timer)
    timer=null
  }
  function detach() {
    retryNotBefore=0;epoch++;detailAttempt++;stop();reportId.value=null;state.value=null;report.value=null;viewState.value='idle';message.value=''
  }
  function terminalError(error:unknown) {
    const e=error as {status?:number;code?:string;message?:string}
    if ([401,403,404].includes(e?.status || 0)) {
      stop();viewState.value='load_failed';message.value=e.message || '无法读取该报告'
      if (e.status===401) {auth.clearAuth();clearReportRequestStorage()}
      return true
    }
    return false
  }
  async function loadDetail(currentEpoch=epoch) {
    const id=reportId.value
    const detailRevision=++detailAttempt
    if (!id) return
    viewState.value='loading_completed'
    try {
      const detail=await getReport(id)
      if (currentEpoch!==epoch || detailRevision!==detailAttempt || reportId.value!==id) return
      if (detail.id!==id || detail.status!=='completed' || (state.value?.batch_id && detail.generation_batch_id!==state.value.batch_id)) throw new Error('报告详情与生成状态不一致')
      report.value=detail;viewState.value='completed';message.value='报告已完成'
    } catch(error) {
      if (currentEpoch!==epoch || detailRevision!==detailAttempt) return
      terminalError(error);viewState.value='load_failed';message.value=(error as Error).message || '报告已生成，详情加载失败，请重试读取'
    }
  }
  async function receive(next:GenerationStatus,currentEpoch:number) {
    if (currentEpoch!==epoch || next.report_id!==reportId.value || !acceptsRevision(state.value,next)) return
    state.value=next;message.value=next.message
    if (next.status==='completed') {stop();await loadDetail(currentEpoch)}
    else if (next.status==='failed' || next.status==='cancelled') {stop();viewState.value=next.status}
    else viewState.value=next.status
  }
  function reconnect(currentEpoch:number,error?:unknown) {
    if (currentEpoch!==epoch || !reportId.value || ['completed','failed','cancelled','loading_completed'].includes(viewState.value)) return
    disconnect?.();disconnect=null
    if (error && terminalError(error)) return
    viewState.value='reconnecting';message.value='连接已中断，正在查询报告状态；任务仍在后台执行'
    if (timer) clearTimeout(timer)
    const retryAfter=(error as {retryAfterSeconds?:number}|undefined)?.retryAfterSeconds
    if (retryAfter !== undefined && Number.isFinite(retryAfter) && retryAfter >= 0) retryNotBefore=Date.now()+retryAfter*1000
    const delay=Math.min(2147483647,Math.max([2000,5000,10000][Math.min(attempt++,2)]!,retryNotBefore-Date.now()))
    timer=setTimeout(()=>void poll(currentEpoch),delay)
  }
  async function poll(currentEpoch:number) {
    if (Date.now()<retryNotBefore) {reconnect(currentEpoch);return}
    const id=reportId.value;if (!id || currentEpoch!==epoch) return
    try {
      const next=await getGenerationStatus(id)
      await receive(next,currentEpoch)
      if (currentEpoch===epoch && ['queued','running','reconnecting'].includes(viewState.value)) {
        // Even an unchanged revision confirms the server's actual state.
        viewState.value=next.status==='queued'?'queued':'running'
        disconnect=subscribeReportJob(id,s=>void receive(s,currentEpoch),e=>reconnect(currentEpoch,e))
      }
    } catch(error) {
      if (currentEpoch!==epoch) return
      if ((error as {code?:string}).code==='legacy_generation_unmanaged') {viewState.value='load_failed';message.value='旧版生成任务待维护人员处理';return}
      reconnect(currentEpoch,error)
    }
  }
  async function observe(id:number) {
    detach();reportId.value=id;viewState.value='reconnecting';attempt=0
    await poll(epoch)
  }
  async function submit(caseId:number) {
    if (active.value) return
    const userId=auth.user?.id
    const prior=saved()
    const pending=prior?.case_id===caseId && !prior.report_id?prior:{case_id:caseId,key:crypto.randomUUID()}
    persist(pending);pendingCaseId.value=caseId
    detach();const currentEpoch=epoch;viewState.value='submitting';message.value='正在受理报告'
    try {
      const accepted=await submitReportJob(caseId,pending.key)
      if (auth.user?.id!==userId) return
      persist({...pending,report_id:accepted.report_id})
      if (currentEpoch!==epoch) return
      await observe(accepted.report_id)
    } catch(error) {
      if (currentEpoch!==epoch) return
      const e=error as {status?:number;reportId?:number;code?:string;message?:string}
      if (e.code==='active_report_exists' && e.reportId) {await observe(e.reportId);return}
      // Keep the same request key when the admission response is uncertain.
      if (e.status && e.status<500) sessionStorage.removeItem(storageKey())
      viewState.value='load_failed';message.value=e.message || '受理结果暂未确认，重试会复用本次请求标识'
      terminalError(error)
    }
  }
  async function cancel() {
    if (!reportId.value || !canCancel.value) return
    const currentEpoch=epoch
    try {await receive(await cancelReportJob(reportId.value),currentEpoch)}
    catch(error) {if (currentEpoch===epoch) message.value=(error as Error).message || '取消结果暂未确认，请查询状态'}
  }
  async function retryDetail() {if (state.value?.status==='completed') await loadDetail();else if (reportId.value) await poll(epoch)}
  function recoverPending() {return saved()}
  watch(()=>auth.user?.id,(next,previous)=>{
    if (previous!==undefined && next!==previous) {detach();clearReportRequestStorage()}
  })
  function refreshConnection() {
    if (reportId.value && ['queued','running','reconnecting'].includes(viewState.value)) {stop();void poll(epoch)}
  }
  function restorePending() {
    const pending=saved()
    if (!pending) return
    pendingCaseId.value=pending.case_id
    if (pending.report_id) void observe(pending.report_id)
    else {viewState.value='load_failed';message.value='上次受理结果未确认，请重试查询受理结果'}
  }
  return {reportId,state,report,viewState,message,active,canCancel,pendingCaseId,submit,observe,detach,cancel,retryDetail,recoverPending,restorePending,refreshConnection}
})
