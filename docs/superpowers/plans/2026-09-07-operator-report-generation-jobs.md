# AI 操作者持久报告任务与恢复 Implementation Plan
> 执行状态（2026-09-07）：仓库任务已完成并通过本机隔离验收，实际任务状态、命令与证据见 [执行记录](../notes/2026-09-07-operator-report-execution-log.md)。下文保留批准时计划；建议的逐项提交被用户要求的最终一次提交取代。涉及目标 Linux 容量及生产发布的检查仍在部署窗口执行。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 报告受理可幂等、执行可监督、刷新可查询、取消有真实终态、重启遗留任务可自动收敛。

**Architecture:** 在原报告旁保存 PostgreSQL job，与幂等记录同事务创建。worker 用租约领取并监督可终止子进程，只有持有有效租约的发布事务可以保存模块 A 的完整结果。API/SSE 与前端仅订阅持久状态。

**Tech Stack:** 现有 PostgreSQL/SQLAlchemy/Alembic/FastAPI、multiprocessing spawn、Pinia、fetch SSE、pytest/Vitest/Playwright；不新增 Redis 或消息中间件。

## Global Constraints

- 继承总计划 `2026-09-07-operator-complete-report-implementation.md` 全部 Global Constraints 与批准设计。
- 保留 `ai_reports.status` 的四个值：`generating/completed/failed/cancelled`。
- 本期不自动重跑已经执行中断的预测。
- 关闭页面、返回病例、AbortController 断开订阅均不取消任务。
- queued 未超时可由重启后的 worker 正常领取。
- 任务结果仅一次发布；不宣称物理计算恰好执行一次。
- 不在浏览器 localStorage/sessionStorage 存临床输入；只保存请求 key、病例内部 ID 和 report_id 等导航标识。
- worker 不 import `app.main`、聊天/RAG/embedding 初始化；数据库 session 不跨进程复用。
- 本模块与 A 联合开放新写路径，真实 PostgreSQL 关键用例跳过不能算完成。

## B1：固定模型、目录与标准上下文

**Depends:** A1。

**Files:**
- Create: `backend/app/services/report_generation_context.py`
- Modify: `backend/app/services/longitudinal_model_registry.py`
- Modify: `backend/app/services/operator_case_readiness.py`
- Modify: `backend/app/services/standard_evidence.py`
- Modify: `backend/app/services/evidence_bundle.py`
- Modify: `backend/app/services/longitudinal_signal_interpreter.py`
- Test: `backend/tests/test_report_generation_context.py`
- Create: `backend/tests/report_generation_fixtures.py`

**Interfaces:**
- `capture_generation_context(snapshot: dict, session_factory, registry_root) -> ReportGenerationContext`
- `load_pinned_model_suite(context: ReportGenerationContext, registry_root) -> LoadedDiseaseModelSuite`
- `build_pinned_evidence(snapshot: dict, context: ReportGenerationContext, session_factory) -> EvidenceBuildResult`
- 既有 `load_disease_model_suite(dataset, registry_root)` 继续供 active 路径使用，内部提取 `load_model_suite_record(record, registry_root)` 公共实现。
- `evaluate_operator_case_readiness(case, registry_root, *, load_runtime=True)` 保持默认旧行为，新受理 metadata-only 用 False，仍验证路径、hash、任务覆盖和基础契约。

- [ ] **Step 1：先写固定版本测试。** 在新测试中复用现有 release_set 测试的临时 registry 建立模型组 A/B；受理 A 后改 active 为 B，pinned loader 必须继续 A，替换 A 文件必须失败。

```python
from app.services.report_generation_context import load_pinned_model_suite

def test_pinned_loader_never_reads_active(monkeypatch, tmp_path):
    from app.services import longitudinal_model_registry as registry
    monkeypatch.setattr(registry, 'load_disease_release_set',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('active read')))
    from backend.tests.report_generation_fixtures import pinned_suite_fixture
    context, root = pinned_suite_fixture(tmp_path)
    suite = load_pinned_model_suite(context, root)
    assert suite.release_set_id == context.release_set_id
    assert suite.release_set_sha256 == context.release_set_sha256
```

`pinned_suite_fixture(tmp_path)` 使用 pytest tmp_path 创建上述临时 registry，返回 `(context, tmp_path)`；从现有 release_set tests 的 fixture builder 提取建库逻辑，使用可 joblib 序列化的测试模型，不依赖真实 active 文件，也不返回已删除目录。

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_generation_context.py -q`。
- [ ] **Step 3：抽取显式 record 加载。** 旧 loader 中从 release_set 校验到 LoadedDiseaseModelSuite 构造的主体原样放公共函数。pinned 入口使用已有 `load_release_set_record(dataset, id, root)`，比较 record hash/data/split/manifest 与 context，再走同一完整性校验。路径必须先验证 release ID 安全字符与 resolve 在 registry root 内；不得用请求传来的绝对路径。active wrapper 的现有缓存与单飞保持。
- [ ] **Step 4：固定受理快照。** 独立只读 session 调用 preflight_evidence_versions，再复制 dataclass → A1 PinnedEvidenceToken；加载数据 manifest 与 catalog 显示名；校验 snapshot catalog hash 与当前读取 hash。读前后 active identity 必须相同，不同仅允许重新捕获一次，仍变则 `generation_context_changed`。最低信号观察数从 signal interpreter 提取同一个 `MINIMUM_SIGNAL_OBSERVATIONS=3` 常量，替换该模块原 summary 中的字面值，不改变规则值。
- [ ] **Step 5：实现固定证据读取。** 新 `build_standard_evidence_pinned` 按 token.version_id/document_id 查询并验证归属、原文和哈希；该版本已不在 current 但仍 approved 可用，retired/revoked 或哈希不符失败关闭。新 build_pinned_evidence 只用 token.data_release 查询参考窗口，不调用 read_version_token 或 with_retry 的 active 切换。证据构建独立 session 设置现有查询超时；每次只读结束自行关闭，不影响受理写事务。
- [ ] **Step 6：验证通过。** 覆盖 pinned 标准更新/撤销、参考 active 切换不换数据、目录 drift、反序列化模型没在受理发生、默认 readiness 旧调用兼容。运行 `python -m pytest tests/test_report_generation_context.py tests/test_longitudinal_model_registry.py tests/test_longitudinal_release_set.py tests/test_evidence_bundle_service.py -q`，文件存在性以总计划 P0 复核。建议提交：`feat: pin report generation model and evidence context`。

## B2：持久任务表、幂等约束扩展与租约仓储

**Depends:** A5 已建立 0023；B1。

**Files:**
- Create: `backend/alembic/versions/0024_operator_report_generation_jobs.py`
- Modify: `backend/app/db/models.py`
- Modify: `database/schema.sql`
- Create: `backend/app/schemas/report_generation.py`
- Create: `backend/app/services/report_job_repository.py`
- Test: `backend/tests/test_report_generation_schema.py`
- Test: `backend/tests/test_operator_report_jobs_migration.py`
- Create: `backend/tests/integration/test_report_generation_jobs.py`
- Modify: `backend/tests/integration/conftest.py`

**Interfaces:**

```python
from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal['queued', 'running', 'completed', 'failed', 'cancelled']
JobPhase = Literal['queued', 'model_loading', 'prediction', 'standard_evidence', 'rendering', 'persistence', 'terminal']

class GenerationStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    report_id: int
    batch_id: UUID | None
    status: JobStatus
    report_status: Literal['generating', 'completed', 'failed', 'cancelled']
    phase: JobPhase
    revision: int = Field(ge=1)
    updated_at: datetime
    error_code: str | None = None
    message: str
    cancel_requested: bool = False
    legacy: bool = False

class JobAccepted(BaseModel):
    report_id: int
    batch_id: UUID
    status: JobStatus
    status_url: str
    events_url: str

class JobClaim(BaseModel):
    report_id: int
    batch_id: UUID
    lease_token: UUID
    lease_owner: str
    run_deadline: datetime
```

`JobClaim` 不含 ORM 对象、密码、路径或模型实例。仓储接口：`claim_next(db, owner) -> JobClaim | None`、`heartbeat(db, claim) -> bool`、`update_phase(db, claim, phase) -> bool`、`publish_completed(db, claim, publication) -> bool`、`finish_job(db, claim, status, code) -> bool`、`reap_expired(db) -> int`。这些方法均由自身短事务负责 commit/rollback；不得在调用方已有修改事务中嵌套使用。

GenerationStatus 的 batch_id 只对 legacy 终态报告允许为空；新增 model_validator 拒绝 legacy=False 且 batch_id=None，新任务永远使用真实 UUID。旧生成中且无 job 时 GET status 返回 409 legacy_generation_unmanaged，不凭空宣称正在运行；页面提示旧任务待处置。旧终态报告 legacy=True/revision=1 可直接按 report_id 加载详情，无批次就不编造 UUID。

- [ ] **Step 1：写真实竞争测试。** 使用现有显式 `_test` 数据库 fixture，两份独立 Session、Barrier 同步并发领取，不共享 session。

```python
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from sqlalchemy.orm import sessionmaker
from app.services.report_job_repository import claim_next

def test_only_one_worker_claims_one_job(integration_engine, queued_report):
    factory = sessionmaker(bind=integration_engine, expire_on_commit=False)
    barrier = Barrier(2)
    def take(owner):
        with factory() as db:
            barrier.wait(timeout=5)
            return claim_next(db, owner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(take, ['worker-a', 'worker-b']))
    assert sum(value is not None for value in results) == 1
```

`queued_report` fixture 新增至 integration/conftest，使用 db fixture 已有 owner=1/disease=1，创建合法病例、generating report 与下表必需字段；commit 后返回 report_id。fixture 只对测试库生效，清理 tables 增加 report_generation_jobs，保留原 `_test` 校验。

- [ ] **Step 2：运行失败。** backend：`python -m pytest tests/test_report_generation_schema.py tests/test_operator_report_jobs_migration.py -q`。有显式 TEST_DATABASE_URL 时再运行上述 integration；没有变量必须 skip，不能改默认生产 DATABASE_URL。
- [ ] **Step 3：实现迁移与 ORM。** 0024 down_revision=0023，创建下表；各项 NOT NULL/约束同步 ORM/schema.sql。

| 列 | 数据类型/约束 |
|---|---|
| report_id | integer PK/FK ai_reports.id ON DELETE CASCADE，一报告一任务 |
| user_id | integer NOT NULL/FK users.id ON DELETE CASCADE；由受理服务取当前用户，不接受请求输入 |
| source_case_id | integer NOT NULL，无病例 FK，保存受理时内部 ID，不向跨用户输出 |
| generation_context | JSONB NOT NULL，jsonb_typeof=object，A1 校验 |
| context_sha256 | varchar(64) NOT NULL，SHA-256 regex |
| status | varchar(12)，五个 JobStatus，默认 queued |
| phase | varchar(24)，JobPhase 枚举，默认 queued |
| revision | bigint NOT NULL DEFAULT 1，>=1 |
| queued_at / updated_at | timestamptz NOT NULL DEFAULT now() |
| queue_deadline | timestamptz NOT NULL |
| started_at / finished_at / heartbeat_at / lease_expires_at / run_deadline | nullable timestamptz |
| lease_owner | nullable varchar(160) |
| lease_token | nullable UUID |
| cancel_requested_at | nullable timestamptz |
| error_code | nullable varchar(120)，仅安全白名单 |

约束与索引代码：

```sql
CREATE UNIQUE INDEX uq_report_jobs_active_case
ON report_generation_jobs(user_id, source_case_id)
WHERE status IN ('queued', 'running');
CREATE INDEX ix_report_jobs_queued ON report_generation_jobs(queued_at, report_id)
WHERE status = 'queued';
CREATE INDEX ix_report_jobs_running_lease ON report_generation_jobs(lease_expires_at)
WHERE status = 'running';
CREATE INDEX ix_report_jobs_user_status ON report_generation_jobs(user_id, status);
```

CHECK：running 要求 owner/token/start/lease/run_deadline 非空；终态要求 finished_at 非空且 phase=terminal；queued 的 started_at 为空。阶段与 status 不允许 running/queued 相互回跳。

扩展现有 OperatorIdempotencyKey：删除旧两个单值 CHECK，新增配对 CHECK：

```sql
CHECK ((scope = 'create_longitudinal_case' AND resource_type = 'operator_case') OR
       (scope = 'create_longitudinal_report' AND resource_type = 'ai_report'));
```

保留原唯一键。幂等表没有到 resource 的强 FK，报告删除后旧 key 仍保留 tombstone；重试返回 resource_missing 冲突，不能再造报告。

- [ ] **Step 4：实现领取与心跳。** 使用数据库时钟，不能用不同主机 Python now 决定租约。领取 SQL 核心如下，绑定 owner/new_token，claim 前先 reap_expired（单独事务）。

```sql
WITH candidate AS (
  SELECT report_id FROM report_generation_jobs
  WHERE status='queued' AND queue_deadline > clock_timestamp()
    AND cancel_requested_at IS NULL
  ORDER BY queued_at, report_id FOR UPDATE SKIP LOCKED LIMIT 1
)
UPDATE report_generation_jobs j SET
  status='running', phase='model_loading', started_at=clock_timestamp(),
  updated_at=clock_timestamp(), heartbeat_at=clock_timestamp(),
  run_deadline=clock_timestamp() + make_interval(secs => :run_seconds),
  lease_expires_at=clock_timestamp() + make_interval(secs => :lease_seconds),
  lease_owner=:owner, lease_token=:new_token, revision=revision+1
FROM candidate WHERE j.report_id=candidate.report_id RETURNING j.*;
```

heartbeat/update_phase 只匹配 running/token/owner、lease/run_deadline 均未过期且未取消；heartbeat 只能延 lease，不能延 run_deadline。phase 更新递增 revision、拒绝退回已完成阶段；heartbeat 更新 updated_at，不必每次改变对外 revision。

- [ ] **Step 5：实现终态发布。** 锁顺序统一 job → report；所有完成/取消/巡检/删除受此约束。publish_completed 检查有效租约、同 batch/report/user、snapshot/context hash、Publication 完整性；事务内更新完整 AIReport 字段及 status=completed，再更新 job=completed/terminal/finished_at/revision。任何条件更新 rowcount=0 都 rollback 并返回 False；严禁之后发送新内容或 completed。

```python
def valid_terminal_update(changed_jobs: int, changed_reports: int) -> bool:
    return changed_jobs == 1 and changed_reports == 1
```

此函数仅说明测试断言目标，实际正确性来自同事务锁与 SQL 条件，不可用 Python bool 代替数据库条件。提交异常结果不确定：关闭失败 session，重新读取真实状态；不立即写 failed 覆盖可能已经 committed 的 completed。

- [ ] **Step 6：实现巡检。** 锁住过期 queued/running，未取消分别 queue_timeout/worker_interrupted/run_timeout → failed；cancel_requested → cancelled；同时将 report 从 generating 条件更新到相同终态。重复巡检应影响 0 行。禁止将 expired running 改回 queued。无 worker 的服务启动/独立巡检进程都可调用同一 reap，不能只依赖用户打开页面。
- [ ] **Step 7：验证通过。** 真实 PG 验证重复领取、失 token 发布、过期不能 heartbeat、取消/完成 race、事务回滚不产生半报告、同病例唯一、报告所有权/快照不匹配、两次 reap、幂等旧病例兼容；`python -m pytest tests/integration/test_report_generation_jobs.py -q`。schema/migration 单测与原 schema 契约一并通过。建议提交：`feat: add durable report jobs and fenced publication`。

## B3：原子幂等受理与显式取消

**Files:**
- Create: `backend/app/services/report_generation_service.py`
- Create: `backend/app/services/report_generation_idempotency.py`
- Modify: `backend/app/services/operator_case_readiness.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/test_report_generation_service.py`
- Extend: `backend/tests/integration/test_report_generation_jobs.py`

**Interfaces:** `submit_report_job(user_id, case_id, key, request, session_factory, registry_root) -> JobAccepted`；`get_generation_status(db, user_id, report_id) -> GenerationStatus`；`cancel_report_job(db, user_id, report_id) -> GenerationStatus`。统一 `ReportJobError(code, message, status_code, report_id=None)`，仅可信中文白名单对外。

- [ ] **Step 1：写幂等和原子性测试。**

下面行为测试写入 `backend/tests/integration/test_report_generation_jobs.py`，因为依赖真库；`tests/test_report_generation_service.py` 单测请求规范化、错误映射和调用事务顺序，不依赖 integration fixture。

```python
from uuid import uuid4
from app.services.report_generation_service import submit_report_job

def test_response_retry_after_case_edit_replays_original_report(job_environment):
    env = job_environment
    key = str(uuid4())
    first = submit_report_job(1, env.case_id, key, {}, env.session_factory, env.registry_root)
    env.edit_case_age(70)
    replay = submit_report_job(1, env.case_id, key, {}, env.session_factory, env.registry_root)
    assert replay.report_id == first.report_id
    assert env.count_jobs() == 1
    assert env.saved_snapshot(first.report_id)['age'] == 62
```

`job_environment` 在测试 helper 定义，只包装真实 `_test` session_factory 与 B1 tmp registry；case_id 来自合法聚合病例写入。helper 方法明确为 edit_case_age/count_jobs/saved_snapshot，禁止 mock 掉提交事务来验证原子性。

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_generation_service.py -q`，并运行 opt-in integration。
- [ ] **Step 3：复用 key 格式与新增 scope。** 沿用 parse_idempotency_key UUID 校验。请求哈希只包含接口版本、case_id、规范化 request，不包含会随病例变化的当前 snapshot。空 options 之外拒绝 422；same key/different body 409；key 对应报告已删 409。

```python
import hashlib
import json

REPORT_SCOPE = 'create_longitudinal_report'

def hash_report_request(case_id: int, request: dict) -> str:
    if set(request) - {'model_options'} or request.get('model_options', {}) != {}:
        raise ValueError('unsupported_report_options')
    value = {'contract': 'report_job_request.v1', 'case_id': case_id, 'model_options': {}}
    raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()
```

- [ ] **Step 4：实现两阶段受理。** (a) 独立 session 先读幂等结果，有记录立即 replay，不调用当前病例；(b) 读病例/访视快照并关闭 session，B1 独立预检；(c) 新短事务获取专用全局 advisory xact lock `73606`，再检查 replay，按病例锁复核 owner/status/disease/profile/timeline，并重建 snapshot 比较 hash；改变则 409 case_changed；复核标准 pinned 状态不调用会 rollback 的预检；固定 context hash；检查 quotas；flush report 取得 ID，写 batch/input hash/job/key 后一次 commit。任何异常全部 rollback。

global admission lock 只串行很短的计数/写入，不包模型加载或文件读取。先捕获 context 时两次文件 identity 校验完成；事务内最后校验指针身份，无外部调用；指针不一致安全拒绝并让用户重新提交新 key。

容量：全局 queued 最多 20（不含 running）、单用户 queued+running 最多 2、单病例活动最多 1。第二个病例相同活动任务返回 409 active_report_exists 与当前用户自己的 report_id，方便页面定位；容量超限 429 + Retry-After=10。所有新旧入口复用同一服务，不能绕过配额。

- [ ] **Step 5：状态查询/取消/删除。** get_status 先按 report.user_id 限定，否则统一 404。legacy 没有 job 的终态报告映射 terminal/revision=1/legacy=True，缺 batch 时为 null；legacy generating 返回409 legacy_generation_unmanaged，不能重新运行。cancel：queued 直接 cancelled；running 在同事务立即 job/report → cancelled 并记录 cancel_requested_at，租约撤销，worker 下次心跳失效终止子进程；completed/failed/cancelled 重复取消返回真实当前状态、不覆盖。报告删除先锁 job 再 report，活动则 409，终态按旧权限删除；幂等 key tombstone 保留。
- [ ] **Step 6：配置默认值。** Settings/.env.example 增加 REPORT_JOBS_ENABLED=False、REPORT_JOBS_ACCEPTING=False、REPORT_LEGACY_SSE_ENABLED=True；ENABLED 控制新任务执行能力，两开关都 True 才受理新任务。查询/取消/历史读取不因暂停受理关闭；排空维护只设 ACCEPTING=False，不关闭 ENABLED。期限默认 heartbeat=10、lease=45、sweep=15、queue=600、run=300、load=60、prediction=120 秒；并发=1、queued_limit=20、user_active_limit=2。配置校验 heartbeat<lease、sweep<=lease、阶段<=run，非法启动失败。所有存储期限由 DB 时钟计算。
- [ ] **Step 7：验证通过。** 受理 key 重放先于病例读取；同 key 竞争/不同 body；flush/commit 故障；标准 helper rollback 不污染事务；case edit/delete/archived/disabled；超容量；跨账号404；cancel/finish race。建议提交：`feat: admit and cancel report jobs atomically`。

## B4：独立 Worker、可终止执行与真实终态发布

**Depends:** A1～A5、B1～B3。

**Files:**
- Create: `backend/app/workers/__init__.py`
- Create: `backend/app/workers/report_worker.py`
- Create: `backend/app/workers/report_execution.py`
- Create: `backend/app/workers/report_process_control.py`
- Test: `backend/tests/test_report_worker.py`
- Test: `backend/tests/test_report_worker_process.py`
- Extend: `backend/tests/integration/test_report_generation_jobs.py`

**Interfaces:** `execute_report(input_payload: dict, send_message) -> None`（spawn 子进程顶层函数）；`run_worker_once(session_factory, registry_root, owner: str) -> bool`（有领取返回 True）；CLI `python -m app.workers.report_worker [--once|--sweep-only]`。`send_message` 只接受下列进程内 JSON 消息，不向浏览器直接发送。

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict
from app.schemas.report_document import Publication

class ExecutionMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['phase', 'publication', 'error']
    phase: Literal['model_loading', 'prediction', 'standard_evidence', 'rendering', 'persistence']
    publication: Publication | None = None
    code: str | None = None
```

父进程验证 kind/phase 的对应组合：phase 消息不得有 publication/code；publication 只在最后且 phase=persistence；error 只接受白名单 code、无结果。消息非预期/过大标记 execution_protocol_invalid，不解析任意 pickle 作为任务请求。

- [ ] **Step 1：编写实际进程测试。** 用测试子函数阻塞 30 秒，deadline 缩至 0.3 秒；验证子进程结束且状态 failed。另用完整 mock 模型子函数生成 Publication，publish 返回 False 时不得宣称完成。用 injectable execution target 仅在 Python 测试注入，不通过环境/公网 API 提供任意模块路径。

```python
import time
from app.workers.report_process_control import supervise_execution

def blocked_target(payload, send_message):
    send_message({'kind': 'phase', 'phase': 'prediction'})
    time.sleep(30)

def test_timeout_terminates_real_child():
    result = supervise_execution(
        blocked_target, {}, maximum_seconds=0.3,
        lease_check=lambda: True, on_phase=lambda phase: None,
        phase_limits={'prediction': 0.3},
    )
    assert result.code == 'run_timeout'
    assert result.child_alive is False
```

`supervise_execution(target, payload, *, maximum_seconds, lease_check, on_phase, phase_limits) -> ExecutionOutcome`，返回 dataclass `ExecutionOutcome(publication: Publication|None, code: str|None, child_alive: bool)`；租约失效 code=lease_lost，父级只读取真实终态，不另写失败覆盖取消。

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_worker.py tests/test_report_worker_process.py -q`。
- [ ] **Step 3：实现 spawn 通信与硬终止。** `multiprocessing.get_context('spawn')`；子进程按顶层函数入口创建自己的 session_factory（如需证据查询），没有 session/pipeline 对象跨进程传递。Pipe 传 JSON bytes，限制每条至 8 MiB；父进程循环 poll 100ms，读取 phase 后更新短事务状态，按 10 秒心跳独立检查租约。不能先 join 再 recv 导致大结果阻塞；父进程逐消息收取。收到 publication 后重新验证 schema/hash，再交仓储提交。

```python
def stop_child(process):
    if process.is_alive():
        process.terminate()
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
    if process.is_alive():
        raise RuntimeError('child_termination_failed')
```

生产 systemd 配置 KillMode=control-group，避免父进程被杀后留下模型子进程。Windows 本地 harness 使用 Win32 Job Object，设置 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE，并把 worker/子进程纳入同一任务对象；句柄不继承到子进程。若宿主 Job Object 嵌套不支持则启动检查失败并清晰报告，不能无监督地执行。process_control 将平台相关逻辑单独封装 `managed_process_tree()` context manager；加入父进程强杀后子进程 PID 消失的实际测试。

- [ ] **Step 4：实现限时分阶段执行。** 子进程执行顺序：验证 input/context hash → phase model_loading → B1 pinned loader → phase prediction → A2 audited prediction → phase standard_evidence → B1 pinned evidence → 原 attach_signal_interpretation → 把 sources 固定进 payload → phase rendering → A3 builder + A5 publication → phase persistence + publication。所有预测数据来自 input_payload.snapshot，禁止重新 get 当前病例。规范化 prediction 用现有 prediction_result_to_dict。

父进程用 monotonic 度量本地耗时，同时每次 DB 心跳检查 DB run_deadline；阶段限制 min(配置上限, 剩余总期限)。model_loading 60s、prediction 120s；证据查询沿用各自 SQL timeout 并设整个 evidence 阶段 30s、rendering 30s、persistence DB statement timeout 5s；总运行 300s。相同阶段重复消息不得重置阶段起点。父进程在 close/cancel/lease_lost/timeout 时执行 stop_child 并释放管道。

- [ ] **Step 5：主循环与恢复。** 领取前每 15 秒 reap_expired；空队列最多 1 秒等待，处理退出信号；`--once` 仅处理最多一份任务后退出，`--sweep-only` 只巡检一次。关停停止领取，终止当前子进程，仍持有效租约时写 worker_interrupted/failed；若已失租约只退出。工作进程崩溃由 systemd 自动重启，下次 reap 将已过期 running 收敛。既有队列正常领取，绝不自动重试中断 running。
- [ ] **Step 6：发布与提交不确定性。** 只有 `publish_completed=True` 后对外持久状态才 completed；API/SSE 不监听进程内临时 publication。commit 连接丢失时用新 session 查同 report_id/job/token：已完成则接受真实完成；仍 running 时待 DB 恢复/租约巡检处理；未知状态不猜测成功也不重复创建报告。一般模型失败由白名单错误收敛，绝不保存 traceback。
- [ ] **Step 7：验证通过。** 真进程 timeout/cancel/phase limit/消息畸形/大 payload/父进程强杀，真 PG 崩溃过期/提交不确定/旧 token 晚到/两 worker 竞争；检查 worker import 没有 BGE 初始化。建议提交：`feat: supervise durable report execution and recovery`。

## B5：受理、查询、SSE 与旧入口统一

**Files:**
- Create: `backend/app/api/operator_report_jobs.py`
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/schemas/report_generation.py`
- Test: `backend/tests/test_operator_report_jobs_api.py`
- Test: `backend/tests/test_report_generation_sse.py`
- Create: `backend/tests/integration/test_operator_report_jobs_api.py`

**Interfaces:** 下表 API 路径相对于 `/api/v1`；JWT 继续 require_ai_operator，每次访问以 report.user_id 校验。

| 方法/路径 | 请求/结果 |
|---|---|
| POST `/operator/longitudinal-cases/{case_id}/report-jobs` | UUID Idempotency-Key，JSON `{model_options:{}}`，202 JobAccepted |
| GET `/operator/reports/{id}/generation-status` | GenerationStatus，轻量无病例全文 |
| GET `/operator/reports/{id}/events` | fetch SSE Bearer，state 事件 + 注释心跳 |
| POST `/operator/reports/{id}/cancel` | 幂等显式取消，200 真实 GenerationStatus |
| POST 原 `/operator/longitudinal-cases/{case_id}/reports` | 兼容 SSE，必须委托同一 submit 服务，支持相同 key |

- [ ] **Step 1：写 owner/状态协议测试。**

下面用例写入新增的 integration API 测试文件，复用 integration/conftest 的 client(user_id)；saved_cancelled_report fixture 也定义在 integration/conftest。普通 API 单测使用项目现有依赖覆盖。

```python
def test_completed_status_is_not_invented_by_sse(client, saved_cancelled_report):
    owner = client(1)
    response = owner.get(f'/api/v1/operator/reports/{saved_cancelled_report}/events')
    assert response.status_code == 200
    assert '"status":"cancelled"' in response.text.replace(' ', '')
    assert '"status":"completed"' not in response.text.replace(' ', '')
    assert client(2).get(
        f'/api/v1/operator/reports/{saved_cancelled_report}/generation-status'
    ).status_code == 404
```

saved_cancelled_report fixture 使用 B2 job/report 配对终态，不能只 mock SSE 文本。API 单测可使用项目既有 dependency override，真权限用 integration client。

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_operator_report_jobs_api.py tests/test_report_generation_sse.py -q`。
- [ ] **Step 3：实现请求验证/错误协议。** 新 JobRequest 为 extra=forbid，model_options 仅空 dict，非法 key422；owner404，病例准入409/标准服务503，容量429 + Retry-After10，关闭受理503。错误统一 `{code,message,field?,report_id?}`；不返回驱动原始异常。重复已受理 key 可在暂停新受理期间重放，不触发新任务。
- [ ] **Step 4：SSE 只读持久状态。** 首连接先同步 owner check，否则 HTTP404；连接后每1秒用新短 session 读取 job/report，退出即 close session，不能在整条流持有 DB 事务。state 事件 JSON 为 GenerationStatus；id 格式 `batch_uuid:revision`；注释 heartbeat 每15秒；revision 增加才发新状态；终态立即发并关闭。断线不调用 cancel；无执行上下文时不创建任务。SSE 推荐响应头 `Cache-Control: no-store`、`X-Accel-Buffering: no`。

```python
import json

def encode_state(state):
    body = json.dumps(state.model_dump(mode='json'), ensure_ascii=False, separators=(',', ':'))
    identity = str(state.batch_id) if state.batch_id else f'legacy-report-{state.report_id}'
    event_id = f'{identity}:{state.revision}'
    return f'id: {event_id}\nevent: state\ndata: {body}\n\n'
```

不依赖 Last-Event-ID 重放字节；新连接始终发送当前状态，客户端 revision 去重。不存在的报告流中删除/撤权以安全 error 事件关闭。长连接达到 JWT 过期时关闭并返回 auth_expired 事件，客户端走原重新登录机制，不无限401轮询。
- [ ] **Step 5：旧 POST SSE 适配。** 受理得到 job 后订阅持久状态；完成时从 DB 获取已验证正文，按旧 prediction/evidence/delta/done 合同发送；非 completed 只发真实安全 error，不在 cancelled 发 done。缺 key 的旧请求生成服务端 UUID，仅保障同病例单活动任务，文档明确不能识别“完成后再次 HTTP 重试”；响应加 Deprecation 提示。本次新前端一律带 key。`REPORT_LEGACY_SSE_ENABLED=False` 时原路由返回410；无论 flag 如何都不调用旧请求内 generate_longitudinal_report。Jobs 未启用时新旧写入口都503，读取历史仍可用。
- [ ] **Step 6：验证通过。** 首事件真实状态，owner404，EOF/取消不修改任务，失效 lease 从无 completed 事件，旧路由仍走同 quotas/idempotency，终态兼容读；运行本任务 tests、旧 operator API/报告生成回归。建议提交：`feat: expose resumable report job status and events`。

## B6：前端任务状态、刷新恢复和显式取消

**Depends:** B5、A6。

**Files:**
- Create: `frontend/src/api/report-generation.ts`
- Create: `frontend/src/stores/report-generation.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/components/LongitudinalReportView.vue`
- Modify: `frontend/src/components/OperatorSidebar.vue`
- Create: `frontend/src/api/__tests__/report-generation.spec.ts`
- Create: `frontend/src/stores/__tests__/report-generation.spec.ts`
- Extend: `frontend/src/views/__tests__/OperatorView.spec.ts`

**Interfaces:** api 文件提供 submitReportJob(caseId,key)、getGenerationStatus(reportId)、subscribeReportJob(reportId,onState,onDisconnect)、cancelReportJob(reportId)；types 对齐 B2。store 公开 submit(caseId)、observe(reportId)、detach()、cancel()、retryDetail()。独立 generation store 不重复病例编辑数据，原 operator store 继续病例工作区；原 generateLongitudinalReport 导向新 store 或移除所有调用后删掉，不能保留旧请求内执行分支。

页面状态：`idle/submitting/queued/running/reconnecting/loading_completed/completed/load_failed/failed/cancelled`。最后五种基于真实状态/读取结果区分，generating boolean 不再同时代表连接存活与报告执行。

- [ ] **Step 1：写完成读取空档测试。**

```typescript
import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useReportGenerationStore } from '@/stores/report-generation'

describe('report generation state', () => {
  it('detaches observation without requesting cancellation', async () => {
    setActivePinia(createPinia())
    const store = useReportGenerationStore()
    const cancel = vi.spyOn(store, 'cancel')
    store.detach()
    expect(cancel).not.toHaveBeenCalled()
    expect(store.viewState).toBe('idle')
  })
})
```

再用 `vi.mock('@/api/report-generation')`、可手动 resolve 的 getReport Promise 测试 received completed 后保持 loading_completed，详情成功才 completed；详情失败 load_failed，retryDetail 只调用 GET，不 submit。

- [ ] **Step 2：运行失败。** `npm run test:unit -- src/api/__tests__/report-generation.spec.ts src/stores/__tests__/report-generation.spec.ts`。
- [ ] **Step 3：实现 API 与流解析。** 沿用现有 request 统一错误与401处理；SSE fetch 取 Bearer，UTF-8 TextDecoder streaming，兼容 CRLF、多段 data、跨 chunk 和末尾 buffer。只处理 state/error；EOF 未终态调用 onDisconnect；AbortError 只停止订阅，不调用服务端 cancel。所有响应只传安全错误，过期认证停止重试。
- [ ] **Step 4：实现 key 与报告身份隔离。** 用户主动开始生成时创建 `crypto.randomUUID()`；受理响应不确定时保留原 key 供重试，确定已受理后保存 report_id；新生成按钮在终态创建新 key。sessionStorage 只保存用户作用域、case_id、key、受理后 report_id，不存 notes/options 临床内容；退出登录清理。state 接收以本地 observationEpoch、report_id、batch_id、revision 校验，旧响应丢弃。

```typescript
export function acceptsRevision(
  current: {report_id: number; batch_id: string; revision: number} | null,
  next: {report_id: number; batch_id: string; revision: number},
) {
  return current === null || (
    current.report_id === next.report_id && current.batch_id === next.batch_id &&
    next.revision > current.revision
  )
}
```

初始 report_id 要与正在观察的路由 ID 相同；上函数仅负责已选身份下去重，不得以 current=null 接受任意任务事件。

该 revision helper 用于新任务非空 batch；legacy=True 的终态状态直接按 report_id + observationEpoch 获取旧详情，不进入新任务重连逻辑。legacy generating 的409显示旧任务待处置，无自动生成重试。

- [ ] **Step 5：路由与轮询。** 使用现有 `/operator?reportId=17` query，刷新优先 observe 报告，不要求关联病例还存在。参数必须正整数，鉴权完成后 GET status。断线显示“连接中断，正在查询生成状态”，2s/5s/10s 退避，之后10s；focus/online 立即一次刷新；成功建立 SSE 停止轮询；组件卸载停止 listeners/计时器/流，不能 cancel。429 遵循 Retry-After；401/403/404 停止自动重连并显示相应状态，不复用其他用户缓存。
- [ ] **Step 6：界面接入。** queued“等待生成”、running 中文阶段、load_failed“报告已生成，加载失败，可重试”；只在真实 completed 且 verified detail 可读时启用下载。cancel 按钮单独调用 API；返回病例/历史导航只 detach。历史列表显示任务实际状态，正在生成报告不能删除，取消至终态后才允许原删除操作。保留病例会话 revision 防止读取新病例时旧响应覆盖。
- [ ] **Step 7：验证通过。** Fake timers 测 EOF/no terminal、2/5/10、重复/乱序事件、abort 不取消、完成详情慢/失败、刷新 query、病例已删、取消race、提交响应丢失原 key 重试、跨用户 cache 清理；旧病例新建导航隔离测试必须继续通过。运行本任务 Vitest、原工作区 store/OperatorView tests、`npm run build`。建议提交：`feat: restore report progress after refresh and disconnect`。

## B7：真实环境验收、只读门禁与部署恢复

**Files:**
- Create: `scripts/check_operator_report_generation_readonly.py`
- Create: `scripts/tests/test_check_operator_report_generation_readonly.py`
- Modify: `scripts/run_operator_case_e2e.ps1`
- Create: `scripts/seed_operator_report_e2e.py`
- Create: `backend/tests/e2e/test_operator_report_generation.py`
- Modify: `backend/tests/e2e/conftest.py`
- Extend: `backend/tests/integration/test_report_generation_jobs.py`
- Create: `deploy/systemd/surgery-report-worker.service`
- Create: `deploy/systemd/surgery-report-sweep.service`
- Create: `deploy/systemd/surgery-report-sweep.timer`
- Modify: `docs/DEPLOY.md`
- Modify: `docs/ALIYUN_DEPLOYMENT_RUNBOOK.md`
- Modify: `docs/AI操作者流程核查.md`

**Interfaces:** 只读脚本 `--phase preflight|postflight`，输出 JSON、exit=0 PASS/exit=1 FAIL；不得读取生产配置值到 stdout。worker/sweep service 使用本机部署路径与限制，迁移实际环境单独执行。

- [ ] **Step 1：写门禁失败测试。**

```python
from scripts.check_operator_report_generation_readonly import evaluate_gate

def test_postflight_rejects_stale_running_and_missing_worker():
    result = evaluate_gate({
        'schema_ready': True, 'context_invalid': 0, 'terminal_mismatch': 0,
        'expired_jobs': 1, 'legacy_generating': 0,
        'worker_ready': False, 'accepting': True,
    }, phase='postflight')
    assert result['status'] == 'FAIL'
    assert set(result['failed_checks']) == {'expired_jobs', 'worker_ready'}
```

`evaluate_gate(checks: dict, phase: str) -> dict` 是纯函数，collect_checks(connection, phase) 只做数据库读取；worker_ready 来源单独的本地监督检查/参数，不从无任务时没有 heartbeat 推断 worker 已死。

- [ ] **Step 2：实现只读门禁。** 检查 revision/新列/唯一与部分索引/CHECK、job/report 终态对应、过期 queued/running、legacy generating、context/input/doc hash 抽样或分页完整校验。preflight 允许新结构未迁移但明确报告预期；postflight 强制 head、标准/参考既有门禁、worker ready 与无过期/不一致。数据库 session 显式 READ ONLY + timeout，不能 reap/update/stamp；输出 ID/数量/原因，不输出 JSON 临床内容。
- [ ] **Step 3：修复独立 E2E harness。** 现有脚本仅启动前后端，未提供两用户 token 与 E2E_BASE_URL，不能据此宣称 E2E 通过。新流程先验证 Docker `_test` 容器，再迁移 → seed 真实测试用户/两病种合法病例/批准标准/参考窗口 → 启动 worker/backend/frontend → 设置 E2E_BASE_URL 与两账号 token 只传子进程环境 → 运行 workspace 和 report_generation E2E。seeder 复用现有导入服务，不自动批准未经审核来源；测试标准仅在 `_test` 环境建立。禁止 stdout 打印 token、用生产 URL，失败时退出非0；finally 恢复修改过的环境变量并停止本次启动进程。
- [ ] **Step 4：执行强制场景。** 两病种各完成一次实际页面生成/刷新/历史/PDF；断 SSE 不取消；取消与完成race；双标签重复key；杀 worker 后等待 lease+sweep 收敛，重启继续 queued；修改当前病例/切换 active 后旧已受理任务内容固定；运行超时杀子进程。前端 route 不能连接任意生产地址；记录匿名 report_id 与测试截图。
- [ ] **Step 5：配置 systemd。** worker service 运行现有部署账户、环境文件与虚拟环境，配置内容如下；User 使用部署时验证的服务账户，不能把测试账户写入生产模板。

```ini
[Unit]
Description=Surgery RAG report worker
After=network.target postgresql.service

[Service]
Type=simple
WorkingDirectory=/opt/surgery-rag/backend
EnvironmentFile=/opt/surgery-rag/backend/.env
ExecStart=/opt/surgery-rag/backend/venv/bin/python -m app.workers.report_worker
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

部署人员安装前将 service 的 User/Group 设为当前后端实际服务账户并核查模型/环境文件最小读权限；不得默认推断为 root。另建 sweep oneshot，ExecStart 相同加 `--sweep-only`，timer OnBootSec=15/OnUnitActiveSec=15/AccuracySec=1；独立巡检在 worker 不可用时仍能收敛，但必须告警 worker 缺失。重复 sweeper 由 B2 锁/条件保证安全。
- [ ] **Step 6：运维和容量验收。** 监测 queued/running/expired 数、最长队龄、每阶段耗时、失败原因计数、worker process readiness；日志只 report_id/batch/task/reason/耗时，禁止 traceback/原始模型错误。4GiB 基线并发1；观察整体RSS和其他服务，设内存预算并在压测记录，不凭空宣称可承载并发。Nginx 仅对新 events 路径关闭 buffering，普通接口不无限延长 timeout。
- [ ] **Step 7：具体发布顺序。** 备份并只读 preflight → 暂停新报告入口 → 排空旧请求/停止旧执行进程 → 明确范围后将 legacy generating 条件置 failed(error_stage=worker_interrupted)并记处置数量 → 按实际 Alembic head 升级0023/0024及前置缺失迁移 → 既有标准/参考窗口准备 → 发布新后端/前端但 ACCEPTING=False → 启动worker/sweep → 真库集成/双疾病/PDF/故障演练 → postflight PASS → ACCEPTING=True。暂停期间历史查询下载保持。旧 SSE 兼容 flag 初开，确认旧入口调用量为0并强制前端更新后关闭为410。
- [ ] **Step 8：回滚和验证。** 先 ACCEPTING=False → 取消或排空新任务 → 停worker，保留新列/新报告/任务记录。应用回滚仅回到认识 v2 指纹与新 document 的兼容版本；更早版本必须关闭新报告读取/下载并以安全升级提示响应，不能跳过完整性。不得为了回滚删除文档列或批量改 completed。隔离库演练迁移/回滚后数据保留。
- [ ] **Step 9：运行通过并记录。** 根目录 `python -m pytest scripts/tests/test_check_operator_report_generation_readonly.py -q`；backend 真 PG integration、E2E；根目录运行完善后的 PowerShell harness；PDF 逐页记录与总计划 P1。关键跳过/缺环境记为未达门禁。建议提交：`test: verify report recovery and production deployment gates`。

## 模块 B 完成门槛

- 所有实际生成入口委托同一任务服务，无法绕过幂等/配额/快照/租约发布。
- DB 条件更新失败没有虚假 completed；失联不等于取消，执行中断不自动重算。
- 真 PostgreSQL/浏览器/进程故障/PDF 门禁全部记录；不复用历史测试数字作为本次结果。
- 模块 A 同时完成后，执行总计划 P1 并更新核查状态。
