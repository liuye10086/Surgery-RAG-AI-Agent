# 报告历史读取与失败审计 Implementation Plan

## 执行状态（2026-09-07）

用户已选择直接在 main、本会话逐项执行。实际交付、命令和证据见 [实施记录](../notes/2026-09-07-operator-history-pdf-execution-log.md)。下文保留批准时的步骤和代码示意，原过程复选框不作为执行证据；未留存的逐条红灯过程不追补声称。

- [x] A1：仓库交付与本机隔离验收完成。
- [x] A2：仓库交付与本机隔离验收完成。
- [x] A3：仓库交付与本机隔离验收完成。
- [x] A4：仓库交付与本机隔离验收完成。
- [x] A5：仓库交付与本机隔离验收完成。

Git 检查点仅保留为建议；本次未提交、推送或部署。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让历史报告身份只来自保存快照，稳定查全历史，保留并展示失败阶段与已确认输入审计。

**Architecture:** 统一服务读取保存字段并投影 DTO；轻量 SQL 与签名游标服务历史列表；生成 worker 在实际边界发送受限审计事件并由父进程持久化。前端分离病例、历史、报告阅读状态。

**Tech Stack:** 现有 FastAPI/Pydantic/SQLAlchemy/PostgreSQL/Alembic、Vue/Pinia/TypeScript、pytest/Vitest。

## Global Constraints

- 完整遵循[总计划](2026-09-07-operator-report-history-pdf-implementation.md) Global Constraints、锁顺序和接口索引。
- 任何历史接口均不访问 `operator_case` 补编号/人口学，不使用旧自由 `title/query/patient_label` 作展示身份。
- 失败报告不凭当下模型补跑输入审计。
- 新报告 source identity 包含报告 ID、batch、指纹版本/值及文档 SHA。
- 所有新 UI 遵循 `docs/DESIGN_SPEC.md` 全部规范。
- 旧行 last/failure phase 保持 NULL，事件不补造；旧正文/快照/指纹保持原值。

## Task A1：统一保存身份、详情隔离与导出源

**Files**

- Create: `backend/app/services/report_saved_identity.py`
- Create: `backend/app/schemas/report_read_models.py`
- Create: `backend/app/services/report_read_service.py`
- Modify: `backend/app/db/models.py`（AIReport.anonymous_case_code）、`backend/app/api/operator.py`（get_report、安全标题）
- Modify: `backend/app/main.py`（操作者报告响应 no-store 中间件）
- Test: `backend/tests/test_report_read_service.py`

**Interfaces**

- Consumes: `verify_report_integrity`、`compute_input_snapshot_sha256`、`context_hash`、`ReportOut`、`ReportGenerationContext`、`validate_anonymous_case_code`。
- Produces: `saved_report_identity(report_id, snapshot)`、`project_report(row, job=None)`、`read_owned_report(db,user_id,report_id)`、`build_pdf_source(detail)`。

- [ ] **Step 1：先写身份脱离当前病例及畸形/失败报告测试。**

```python
from app.services.report_saved_identity import saved_report_identity

def test_identity_uses_only_saved_snapshot():
    identity = saved_report_identity(9, {"anonymous_case_code": "CASE-ABCD-2345"})
    assert identity.anonymous_case_code == "CASE-ABCD-2345"
    assert saved_report_identity(9, {"patient_label": "private"}).title == "报告-9"
    assert saved_report_identity(9, []).anonymous_case_code is None
```

另外使用既有 `backend.tests.test_report_document_integrity.published()` 构造完整 v2，分别改 report 顶层 batch、document、sources、content、prediction_result；每个案例断言 DTO invalid 且 content 空、prediction/sources/document 不可读。失败报告保存合法 snapshot hash 时 publication_status=not_published、snapshot_integrity=valid。

- [ ] **Step 2：运行红灯。** 根目录：`python -m pytest backend/tests/test_report_read_service.py -q --tb=short`；预期新服务未定义或旧读取行为断言失败。
- [ ] **Step 3：实现纯保存身份与读模型。**

```python
# report_saved_identity.py
from dataclasses import dataclass
from app.services.anonymous_case_code import validate_anonymous_case_code

@dataclass(frozen=True)
class SavedReportIdentity:
    report_id: int
    anonymous_case_code: str | None
    title: str

def saved_report_identity(report_id: int, snapshot: object) -> SavedReportIdentity:
    raw = snapshot.get("anonymous_case_code") if isinstance(snapshot, dict) else None
    try:
        code = validate_anonymous_case_code(raw)
    except (ValueError, TypeError):
        code = None
    title = f"{code}纵向进展预测报告" if code else f"报告-{report_id}"
    return SavedReportIdentity(report_id, code, title)
```

AIReport property 使用局部导入调用上述函数的 `.anonymous_case_code`，不访问 relationship。`_safe_report_title` 同样只使用 report.id/input_snapshot。

```python
# report_read_models.py
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.operator import ReportOut

Integrity = Literal["valid", "invalid", "unverifiable"]

class ReportReadDetail(ReportOut):
    publication_status: Literal["published", "not_published", "invalid"]
    snapshot_integrity: Integrity
    context_integrity: Integrity
    generation_context: dict | None = None
    generation_audit: dict | None = None

class PdfSource(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal["pdf_source.v1"] = "pdf_source.v1"
    report_id: int = Field(gt=0)
    batch_id: str | None
    title: str
    anonymous_case_code: str | None
    integrity_status: Integrity
    generation_fingerprint_version: str | None
    generation_fingerprint: str | None
    report_document_sha256: str | None
    content: str
    prediction_result: dict
    input_snapshot: dict | None
    evidence_snapshot: dict | None
    report_document: dict | None
```

generation_audit 在 A2 写入前为 None，A2 用 `GenerationAuditSummary.model_dump(mode="json")` 生成，不能向 dict 填任意 DB 异常。generation_context 用已存在严格模型验证后 dump，不能裸返回非可信 JSON。

- [ ] **Step 4：实现先验证后投影并接路由。** `project_report` 只接受 SQL mapping，按下列顺序执行；每条对应独立参数化测试：

```python
# report_read_service.py 中使用的受限字段投影
def restricted_payload(data: dict) -> dict:
    return {
        **data,
        "content": "",
        "prediction_result": {},
        "sources": [],
        "retrieval_meta": {},
        "input_snapshot": None,
        "evidence_snapshot": None,
        "report_document": None,
        "generation_context": None,
        "generation_audit": None,
        "indicators": [],
    }
```

`project_report` 构造基底只复制 `ReportOut.model_fields` 中存在的 SQL 标量/保存字段，title/query 改为保存身份；nullable旧字段按原 schema 缺省。先验证容器类型和 finite JSON，再调用现有 verify；v2 另检查 document.identity.report_id/batch_id/disease_code/anonymous_case_code 对 row/snapshot 的一致性。完成数据缺字段/未知版本走 restricted_payload，不尝试 Pydantic 序列化原畸形对象。未完成报告不调用完成指纹路径，分别校验快照和 context 的 SHA，禁止输出部分预测作为完成结果。

```python
# 读取必须是 owned mapping，禁止返回 ORM relationship 供后续隐式加载
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import AIReport, ReportGenerationJob
from app.schemas.report_read_models import PdfSource

def read_owned_report(db, user_id: int, report_id: int):
    row = db.execute(select(AIReport.__table__).where(
        AIReport.id == report_id, AIReport.user_id == user_id,
    )).mappings().first()
    if row is None:
        raise HTTPException(404, detail="报告不存在")
    job = db.execute(select(ReportGenerationJob.__table__).where(
        ReportGenerationJob.report_id == report_id,
        ReportGenerationJob.user_id == user_id,
    )).mappings().first()
    return project_report(dict(row), dict(job) if job else None)

def build_pdf_source(detail):
    if detail.status != "completed" or detail.publication_status != "published":
        raise ValueError("report_not_exportable")
    if detail.integrity_status == "invalid" or not detail.content:
        raise ValueError("report_not_exportable")
    return PdfSource(
        report_id=detail.id, batch_id=detail.generation_batch_id,
        title=detail.title, anonymous_case_code=detail.anonymous_case_code,
        integrity_status=detail.integrity_status,
        generation_fingerprint_version=detail.generation_fingerprint_version,
        generation_fingerprint=detail.generation_fingerprint,
        report_document_sha256=detail.report_document_sha256,
        content=detail.content, prediction_result=detail.prediction_result,
        input_snapshot=detail.input_snapshot, evidence_snapshot=detail.evidence_snapshot,
        report_document=detail.report_document,
    )
```

为 `get_report` 改 response_model=ReportReadDetail，直接调用 read_owned_report。只针对 `/api/v1/operator/reports`、`/api/v1/operator/report-history` 路径设置私有 no-store 中间件（包括404/422），不改变其他接口缓存策略。

- [ ] **Step 5：绿灯及保留旧契约。** 根目录运行 `python -m pytest backend/tests/test_report_read_service.py backend/tests/test_report_integrity.py backend/tests/test_report_document_integrity.py backend/tests/test_anonymous_case_privacy.py backend/tests/test_operator_catalog_and_reports_api.py -q`。检查序列化无正文泄漏、没有读取病例表的查询；旧API测试按新response契约更新，不能删测试绕过。
- [ ] **Step 6：检查点。** 建议 `fix: read report identities and integrity from saved data`。

## Task A2：失败阶段与受限审计 schema

**Files**

- Create: `backend/alembic/versions/0025_report_history_audit.py`
- Create: `backend/app/schemas/report_generation_audit.py`
- Create: `backend/app/services/report_generation_audit.py`
- Modify: `backend/app/db/models.py`、`backend/app/services/report_job_repository.py`、`backend/app/services/report_read_service.py`
- Modify: `database/schema.sql`、`backend/tests/integration/conftest.py`
- Test: `backend/tests/test_report_generation_audit.py`、`backend/tests/integration/test_report_generation_audit.py`

**Interfaces:** `GenerationAuditEvent`、`GenerationAuditSummary`、`append_generation_audit(db,claim,event)->bool`。父进程分配连续 seq；event 不接受客户端/子进程伪造 timestamp/user_id。

- [ ] **Step 1：写终态仍保留真实阶段的测试。**

```python
from datetime import datetime, timezone
from types import SimpleNamespace
from app.services.report_job_repository import _terminal

def test_failure_preserves_last_confirmed_phase():
    job = SimpleNamespace(phase="standard_evidence", revision=2,
                          last_execution_phase="standard_evidence")
    report = SimpleNamespace()
    _terminal(job, report, "failed", "worker_interrupted", datetime.now(timezone.utc))
    assert job.phase == "terminal"
    assert job.failure_phase == "standard_evidence"
    assert report.error_stage == "standard_evidence"
```

- [ ] **Step 2：运行 `python -m pytest backend/tests/test_report_generation_audit.py -q`，确认当前代码红灯。**
- [ ] **Step 3：迁移和 ORM 加对应字段/约束。** 0025 upgrade 的 SQL 为：

```sql
ALTER TABLE report_generation_jobs ADD COLUMN last_execution_phase VARCHAR(24);
ALTER TABLE report_generation_jobs ADD COLUMN failure_phase VARCHAR(24);
ALTER TABLE report_generation_jobs ADD COLUMN audit_event_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE report_generation_jobs ADD COLUMN audit_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_audit_limits
 CHECK (audit_event_count BETWEEN 0 AND 256 AND audit_bytes BETWEEN 0 AND 8388608);
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_last_phase
 CHECK (last_execution_phase IS NULL OR last_execution_phase IN
 ('queued','model_loading','prediction','standard_evidence','rendering','persistence'));
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_failure_phase
 CHECK (failure_phase IS NULL OR failure_phase IN
 ('queued','model_loading','prediction','standard_evidence','rendering','persistence','unknown'));
CREATE TABLE report_generation_audit_events (
 report_id INTEGER NOT NULL REFERENCES report_generation_jobs(report_id) ON DELETE CASCADE,
 event_seq INTEGER NOT NULL CHECK (event_seq BETWEEN 1 AND 256),
 generation_batch_id UUID NOT NULL,
 event_kind VARCHAR(24) NOT NULL CHECK (event_kind IN
 ('phase_entered','input_prepared','invocation_started','task_finished','evidence_resolved','terminal')),
 phase VARCHAR(24) NOT NULL,
 task VARCHAR(160),
 payload JSONB NOT NULL CHECK (jsonb_typeof(payload)='object'),
 payload_bytes INTEGER NOT NULL CHECK (payload_bytes BETWEEN 1 AND 262144),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (report_id,event_seq)
);
CREATE INDEX ix_report_history_owner_order
 ON ai_reports(user_id,analysis_type,created_at DESC,id DESC);
CREATE INDEX ix_report_history_owner_code
 ON ai_reports(user_id,(input_snapshot->>'anonymous_case_code'),created_at DESC,id DESC);
```

旧 job 不回填 phase。新增审计表 phase CHECK 使用同一六阶段+unknown/terminal映射，payload SQL只检查结构/大小；Pydantic 严格拒绝未知内容。禁止 UPDATE 审计事件的 trigger，DELETE 仅用于报告/账号删除级联；普通 API 无写入口。downgrade 若有事件或有非空新审计事实拒绝降级。

- [ ] **Step 4：定义事件、保存限制和摘要。**

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from app.schemas.report_document import InputAudit

class GenerationAuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["phase_entered","input_prepared","invocation_started",
                  "task_finished","evidence_resolved","terminal"]
    phase: Literal["queued","model_loading","prediction","standard_evidence",
                   "rendering","persistence","terminal","unknown"]
    task: str | None = Field(default=None, max_length=160)
    input_audit: InputAudit | None = None
    reason_code: str | None = Field(default=None, max_length=120)
    result_state: Literal["available","unavailable","unconfirmed"] | None = None

class GenerationAuditSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["generation_audit.v1"] = "generation_audit.v1"
    last_execution_phase: str | None
    failure_phase: str | None
    error_code: str | None
    event_count: int
    events: list[GenerationAuditEvent]
    note: str = "仅展示已确认记录；缺少结束事件不代表模型未调用。"
```

持久函数调用 `_job_lock`，验证 claim/批次/时钟及允许阶段；canonical JSON 计算 UTF-8 长度。父进程连续 seq 用 `job.audit_event_count+1`，限制单字段数和总字节；插入事件、增加 counters、更新 last phase、commit 同事务。每条 IPC 增加 child_sequence 由父监督去重；相同序号不同内容协议错误，同内容不增加事件。terminal 预留最后一个事件槽与字节空间，超限必须仍能收敛失败。

`_terminal` 在清空原 phase 前保存 failure_phase；完成保留 last_execution_phase=persistence、failure_phase=None；旧 terminal 无证据为 unknown。更新 report.error_stage 只影响新终态，不批量修改历史。read_owned_report 在校验 job context 后读有界事件映射 generation_audit；旧报告无事件返回空摘要和未记录提示。

- [ ] **Step 5：测试与 schema 对齐。** 根目录：

```powershell
python -m pytest backend/tests/test_report_generation_audit.py backend/tests/test_alembic_contracts.py backend/tests/test_database_baseline.py -q
python -m pytest backend/tests/integration/test_report_generation_audit.py -q --tb=short
```

第二条仅设置显式本机 `_test` 库后执行；覆盖 oversize/伪造字段/失租/重复IPC/强制终态预算、同事务rollback、cascade。integration fixture 清理列表加入新表，避免跨测试保留新事件；关键用例无skip。
- [ ] **Step 6：检查点。** 建议 `feat: persist bounded report generation audit checkpoints`。

## Task A3：贯通实际模型边界、父监督与失败详情

**Files**

- Modify: `backend/app/services/report_input_audit.py`、`backend/app/services/longitudinal_prediction.py`
- Modify: `backend/app/workers/report_execution.py`、`backend/app/workers/report_process_control.py`、`backend/app/workers/report_worker.py`
- Modify: `backend/app/services/report_generation_service.py`、`backend/app/schemas/report_generation.py`
- Test: `backend/tests/test_report_worker_process.py`、`backend/tests/test_report_input_audit.py`、`backend/tests/test_report_generation_service.py`

**Interfaces:** `InputAuditCollector(on_event=None)`；`run_audited_prediction(snapshot, adapter, suite, *, visits=None, minimum_visits=3, on_event=None)`；`ExecutionOutcome(publication, code, child_alive, phase: str | None = None)`；`supervise_execution(target, payload, *, maximum_seconds, lease_check, on_phase, phase_limits, on_audit=None)`，原调用者缺省保持兼容。

- [ ] **Step 1：模拟 child 在标准阶段报错，断言父监督 outcome.phase 和持久 failure_phase 一致；进程强杀只显示最后确认阶段。** 单元测试使用现有 `execute_report` fake target/真实 spawn harness，事件 callback 的 payload 禁止指标值。
- [ ] **Step 2：运行 `python -m pytest backend/tests/test_report_worker_process.py backend/tests/test_report_input_audit.py -q`，新增断言须先失败。**
- [ ] **Step 3：给 collector 加受限事件发送并贯通 IPC。**

```python
def emit_audit(callback, kind, task, audit, result_state=None):
    if callback is None:
        return
    from app.schemas.report_generation_audit import GenerationAuditEvent
    event = GenerationAuditEvent(kind=kind, phase="prediction", task=task,
                                 input_audit=audit, result_state=result_state)
    callback(event.model_dump(mode="json"))
```

prepared 写 input_prepared；invoking 在实际调用前写 invocation_started；`longitudinal_prediction.py` 每任务捕获结果/异常处调用新 collector.finished，写 task_finished；不能只在全部模型结束 finalize 时补造“逐任务实时结束”。输入审计中的 model_invoked 是调用边界事实，不等于成功结果；强杀后以已确认事件为限。

child 发送 `{kind:'audit', phase, child_sequence, audit}`；父 `_message` 对新kind独立 schema验证，最大256KiB，不放宽原publication8MiB限制。on_audit 在短 session 调用 append_generation_audit；回调卡住时独立watchdog仍终止进程。审计不延长 phase_started/总deadline。error.phase经白名单与阶段顺序检查后赋给 ExecutionOutcome，不能只保留 code。

- [ ] **Step 4：终态错误与旧版状态适配。** get_generation_status 的无job分支使用以下安全映射，补 failure_phase 字段为可空，以保持老客户端兼容：

```python
from app.services.report_generation_errors import MESSAGES

def legacy_error_message(status, raw_code):
    if status == "completed":
        return None, "历史报告"
    if status == "cancelled":
        return "cancelled_by_user", MESSAGES["cancelled_by_user"]
    code = raw_code if isinstance(raw_code, str) and raw_code in MESSAGES else "generation_failed"
    return code, MESSAGES[code]
```

只用已保存白名单 code；旧 error_message 是自由异常时不照抄。新 failed/cancelled 查询展示 failure_phase，不重置report为生成中。
- [ ] **Step 5：绿灯。** 根目录 `python -m pytest backend/tests/test_report_worker_process.py backend/tests/test_report_input_audit.py backend/tests/test_report_generation_service.py backend/tests/test_report_generation_sse.py -q`；同时运行A2真库事件/终态测试。
- [ ] **Step 6：检查点。** 建议 `fix: preserve report failure phases through worker supervision`。

## Task A4：轻量历史 SQL 与签名游标

**Files**

- Create: `backend/app/schemas/report_history.py`、`backend/app/services/report_history_cursor.py`、`backend/app/services/report_history_query.py`
- Create: `backend/app/api/operator_report_history.py`
- Modify: `backend/app/main.py`、`backend/app/api/operator.py`（旧offset适配）、`backend/app/core/config.py`、`backend/.env.example`
- Test: `backend/tests/test_report_history_cursor.py`、`backend/tests/integration/test_report_history_query.py`

**Interfaces:** HistoryFilters(disease_code,anonymous_case_code,created_from,created_before,status)；HistoryItem（id/anonymous_case_code/title/disease_name/baseline_stage/visit_count/model_version_summary/status/created_at/pdf_status/download_count）；ReportHistoryPage(items,next_cursor,has_more)。DateTime均带时区，limit单独1～100。

- [ ] **Step 1：签名/作用域与真实分页失败测试。**

```python
import pytest
from app.services.report_history_cursor import encode_cursor, decode_cursor

def test_cursor_is_bound_to_owner_and_filters():
    key = b"x" * 32
    token = encode_cursor({"v":1,"user_id":1,"filters_sha256":"a"*64,
                           "created_at":"2026-09-07T00:00:00+00:00","id":30}, key)
    assert decode_cursor(token,key,user_id=1,filters_sha256="a"*64)["id"] == 30
    with pytest.raises(ValueError):
        decode_cursor(token,key,user_id=2,filters_sha256="a"*64)
```

真库插入60条（同created_at），首批20，另一session删除已读项后下一页包含紧接上一页末尾的剩余ID；新插入不打乱后续向旧方向读取。额外记录cursor无敏感payload、畸形/超长/签名错误400。
- [ ] **Step 2：运行新测试红灯。** `python -m pytest backend/tests/test_report_history_cursor.py -q`。
- [ ] **Step 3：实现严格签名游标。**

```python
import base64
import hashlib
import hmac
import json
from datetime import datetime

def encode_cursor(payload, key):
    raw = json.dumps(payload, sort_keys=True, separators=(",",":"), allow_nan=False).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return body + "." + hmac.new(key, body.encode(), hashlib.sha256).hexdigest()

def decode_cursor(token, key, *, user_id, filters_sha256):
    if not isinstance(token,str) or len(token)>2048 or len(key)<32:
        raise ValueError("history_cursor_invalid")
    try:
        body, signature = token.split(".")
        expected = hmac.new(key,body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):
            raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body+"="*(-len(body)%4)))
        if set(payload)!={"v","user_id","filters_sha256","created_at","id"}:
            raise ValueError()
        if payload["v"]!=1 or payload["user_id"]!=user_id or payload["filters_sha256"]!=filters_sha256:
            raise ValueError()
        if type(payload["id"]) is not int or payload["id"]<1:
            raise ValueError()
        if datetime.fromisoformat(payload["created_at"]).tzinfo is None:
            raise ValueError()
        return payload
    except (ValueError,TypeError,KeyError,UnicodeError) as exc:
        raise ValueError("history_cursor_invalid") from exc
```

加入 Base64 解码异常的显式覆盖；生产key用配置字节，不由用户请求决定。filters_sha256对normalize后的白名单筛选计算；多余filter字段422、倒置日期422，匿名编号使用已有validator。

- [ ] **Step 4：列表只查所需标量。** 核心SQL结构固定如下，参数来自已校验filters；每个可选条件通过SQLAlchemy表达式添加，不拼接用户SQL。

```sql
SELECT r.id,r.created_at,r.status,r.analysis_type,
 r.input_snapshot->>'anonymous_case_code' AS anonymous_case_code,
 r.input_snapshot->>'disease' AS disease_name,
 r.input_snapshot->>'baseline_stage' AS baseline_stage,
 CASE WHEN jsonb_typeof(r.input_snapshot->'visits')='array'
      THEN jsonb_array_length(r.input_snapshot->'visits') END AS visit_count,
 COALESCE(r.prediction_result->'release_set'->>'release_set_id',
          j.generation_context->>'release_set_id') AS model_version_summary,
 r.download_count
FROM ai_reports r
LEFT JOIN report_generation_jobs j ON j.report_id=r.id AND j.user_id=r.user_id
WHERE r.user_id=:user_id AND r.analysis_type='longitudinal_predictive'
 AND (r.created_at,r.id)<(:cursor_time,:cursor_id)
ORDER BY r.created_at DESC,r.id DESC
LIMIT :limit_plus_one;
```

第一页省略cursor条件。取limit+1确定has_more，next_cursor由实际返回最后一项生成。病种来自snapshot.disease_code（旧值没有则按保存疾病名称固定映射，不查当前字典）；拒绝未知筛选。B1完成后LEFT JOIN archive读取pdf_status/新增delivery_count。旧offset接口同用列投影，保留旧response键reports/total，仅该兼容入口count。

- [ ] **Step 5：验证SQL和规模。** 测试监听实际SQL，断言不选择完整content/report_document/evidence_snapshot/prediction_result/input_snapshot、不查operator_cases；检查10000条下EXPLAIN，并测试全部分页ID与静态集合一致、删除/排序边界。运行 `python -m pytest backend/tests/test_report_history_cursor.py backend/tests/integration/test_report_history_query.py -q --tb=short`，不允许新真库关键测试skip。
- [ ] **Step 6：检查点。** 建议 `feat: add scoped cursor pagination for report history`。

## Task A5：独立历史工作区与全状态报告阅读

**Files**

- Create: `frontend/src/api/report-history.ts`、`frontend/src/stores/report-history.ts`
- Create: `frontend/src/components/report/ReportHistoryWorkspace.vue`、`frontend/src/components/report/ReportGenerationAudit.vue`、`frontend/src/components/report/LegacyReportSnapshot.vue`
- Create: `frontend/src/utils/report-read-model.ts`
- Modify: `frontend/src/api/operator.ts`、`frontend/src/stores/operator.ts`、`frontend/src/stores/report-generation.ts`
- Modify: `frontend/src/views/OperatorView.vue`、`frontend/src/components/OperatorSidebar.vue`、`frontend/src/components/LongitudinalReportView.vue`
- Test: `frontend/src/stores/__tests__/report-history.spec.ts`、`frontend/src/components/__tests__/ReportHistoryWorkspace.spec.ts`、`frontend/src/views/__tests__/OperatorView.spec.ts`

**Interfaces:** history store `refresh/loadMore/setFilters/remove/resetForAccount`；navigation `cases/history/report`；generation store 的 `loadDetail`允许completed/failed/cancelled，分别校验对应 publication_status，不把failed当作完成错误重试。

- [ ] **Step 1：写请求竞争/账号切换/导航/失败详情测试。**

```typescript
it('keeps newer history after an older response arrives', async () => {
  const pending: Array<(value: any) => void> = []
  vi.mocked(listHistory).mockImplementation(() => new Promise(resolve => pending.push(resolve)))
  const store = useReportHistoryStore()
  const first = store.refresh()
  const second = store.refresh()
  pending[1]!({items:[{id:2}],next_cursor:null,has_more:false})
  await second
  pending[0]!({items:[{id:1}],next_cursor:null,has_more:false})
  await first
  expect(store.items.map(item=>item.id)).toEqual([2])
})
```

测试模块导入createPinia/setActivePinia、vi.mock新API，并在beforeEach初始化；账号由useAuthStore测试夹具设定，不依赖localStorage实际登录。额外断言切到history显示报告列表而非病例表单，failed/cancelled读取保存审计、无PDF下载入口。
- [ ] **Step 2：frontend运行 `npm run test:unit -- src/stores/__tests__/report-history.spec.ts src/components/__tests__/ReportHistoryWorkspace.spec.ts src/views/__tests__/OperatorView.spec.ts`，新增行为先红灯。**
- [ ] **Step 3：实现列表状态机。** 使用以下完整请求核心，items类型为A4 HistoryItem，API使用AbortSignal和结构化错误，不用共享operatorStore.loading：

```typescript
let epoch = 0
let pageRequest = 0
let controller: AbortController | null = null
async function fetchPage(append: boolean) {
  if (append && (loading.value || loadingMore.value || !hasMore.value)) return
  if (!append) { epoch++; controller?.abort() }
  const captured = epoch
  const requestId = ++pageRequest
  const userId = auth.user?.id
  const cursor = append ? nextCursor.value : null
  controller = new AbortController()
  if (append) loadingMore.value = true
  else loading.value = true
  error.value = ''
  try {
    const result = await listHistory({...filters.value,cursor,limit:20},controller.signal)
    if (captured !== epoch || userId !== auth.user?.id || requestId !== pageRequest) return
    items.value = append ? [...items.value,...result.items.filter(x=>!items.value.some(y=>y.id===x.id))] : result.items
    nextCursor.value = result.next_cursor
    hasMore.value = result.has_more
  } catch (cause) {
    if (captured === epoch && userId === auth.user?.id && requestId === pageRequest) error.value = (cause as Error).message
  } finally {
    if (captured === epoch && requestId === pageRequest) { loading.value=false; loadingMore.value=false }
  }
}
```

store ref 明确定义items/filters/nextCursor/hasMore/loading/loadingMore/error/scrollTop。refresh调用fetchPage(false)，loadMore调用fetchPage(true)；切筛选清页和cursor；delete在请求前提升epoch/中止旧请求，成功后剔除id，失败恢复可读错误；账号变化resetForAccount清所有保存列表/筛选/位置，防晚响应复活。

- [ ] **Step 4：接入历史UI与只读详情。** 报告列表Element Plus表格/卡片含批准设计字段；筛选日期转上海日界UTC半开区间。独立错误区支持重试；“新报告已完成，刷新查看”不强制清除阅读位置。Sidebar导航emit稳定keys；OperatorView按keys渲染，路由reportId仍恢复观察/阅读。完成/失败/取消详情分别渲染，不再只在completed分支调用详情API。

旧快照组件读取input_snapshot的visits数组逐行安全展示，不调用目录或模型。使用以下值格式化，保留零值与False：

```typescript
export function savedValue(value: unknown): string {
  if (value === null || value === undefined) return '未记录'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '记录无效'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}
```

版本化解析器验证snapshot.schema_version（历史缺失走明确legacy分支）、字段容器和数值；未知版本显示保存原始安全文本和不可解释提示，不能强转成新schema。使用Vue文本插值，任何备注不v-html。移除旧`visitCount>=3 ? 够用`逻辑；显示保存访视数和未记录审计。中文阶段优先document.identity.baseline_stage_label，旧版用固定展示映射且保留代码，不访问当前标准。

- [ ] **Step 5：绿灯与构建。** frontend运行上述专项，再运行 `npm run test:unit`、`node --test tests/longitudinal-report-ui-contract.test.mjs`、`npm run build`。检查invalid不显示图/正文/下载；接口错误和空状态明确；44px点击区域与DESIGN_SPEC变量落实。
- [ ] **Step 6：检查点。** 建议 `feat: provide stable report history and saved failure details`。
