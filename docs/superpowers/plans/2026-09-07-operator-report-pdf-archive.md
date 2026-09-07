# PDF 永久原件归档 Implementation Plan

## 执行状态（2026-09-07）

用户已选择直接在 main、本会话逐项执行。实际交付、命令和证据见 [实施记录](../notes/2026-09-07-operator-history-pdf-execution-log.md)。下文保留批准时的步骤和代码示意，原过程复选框不作为执行证据；未留存的逐条红灯过程不追补声称。

- [x] B1：仓库交付与本机隔离验收完成。
- [x] B2：仓库交付与本机隔离验收完成。
- [x] B3：仓库交付与本机隔离验收完成。
- [x] B4：仓库交付与本机隔离验收完成。
- [x] B5：仓库交付与本机隔离验收完成。
- [x] B6：仓库交付与本机隔离验收完成。

Git 检查点仅保留为建议；本次未提交、推送或部署。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首次准备成功后归档唯一 PDF 原件，后续同字节下载，支持故障审计、删除清理和同哈希备份恢复。

**Architecture:** PostgreSQL 保存归档/尝试/交付/清理状态，独立 worker 在可终止子进程渲染固定资源；文件先持久落位、再条件发布。API 只授权读取原件，不执行同步渲染；原件缺失或损坏不自动重新生成。

**Tech Stack:** 现有 SQLAlchemy/Alembic/PostgreSQL、Playwright/Chromium、PyMuPDF、multiprocessing、FastAPI、Vue/Pinia。

## Global Constraints

- 完整遵循[总计划](2026-09-07-operator-report-history-pdf-implementation.md)及[批准设计](../specs/2026-09-07-operator-report-history-pdf-archive-design.md)。前置 A1～A5。
- 首次成功导出的 PDF 永久归档，此后下载同一份文件。
- 主动删除报告时清理对应 PDF；删除病例仍保留报告与 PDF。
- ready 后即使客户端断线未收到文件，也已经形成归档原件；下次下载同一 SHA。
- 恢复只能从备份取回同 hash 文件，校验成功后恢复 ready。
- 原件不是缓存：不能 TTL/LRU 淘汰。
- 首版全局渲染并发 1、队列上限 20、每用户待处理上限 2；排队期限 600 秒、总渲染期限 120 秒、租约 45 秒、心跳 10 秒、巡检 15 秒。
- 生成报告和归档 PDF 是两个状态机。PDF 失败绝不修改报告 completed，也不修改原报告正文/指纹/updated_at。
- 文件根目录和精确renderer manifest由部署配置提供，不推断生产路径，不写公开 uploads，不把PDF文件加入Git。

## Task B1：归档/尝试/交付/清理数据合同

**Files**

- Create: `backend/alembic/versions/0026_report_pdf_archives.py`
- Create: `backend/app/schemas/report_pdf_archive.py`、`backend/app/services/report_pdf_errors.py`
- Modify: `backend/app/db/models.py`、`database/schema.sql`、`backend/app/core/config.py`、`backend/.env.example`
- Modify: `backend/tests/integration/conftest.py`、`backend/tests/test_alembic_contracts.py`、`backend/tests/test_database_baseline.py`
- Test: `backend/tests/test_report_pdf_schema.py`、`backend/tests/integration/test_report_pdf_constraints.py`

**Interfaces:** 下述 PdfArchiveStatus/PdfClaim/PdfCandidate/PdfError；attempt整数id复用现有幂等表resource_id，文件路径用额外随机UUID，不混用类型。

- [ ] **Step 1：先写资源与 ready 约束测试。**

```python
import pytest
from pydantic import ValidationError
from app.schemas.report_pdf_archive import PdfCandidate

def test_candidate_rejects_unbounded_or_invalid_metadata():
    with pytest.raises(ValidationError):
        PdfCandidate(object_key="../private",pdf_sha256="a"*64,
                     size_bytes=1,page_count=1)
    with pytest.raises(ValidationError):
        PdfCandidate(object_key="reports/17/11111111-1111-4111-8111-111111111111/document.pdf",
                     pdf_sha256="a"*64,size_bytes=67108865,page_count=1)
```

真库尝试插入ready但无hash、同report两个running、无原件identity的missing、覆写已发布hash、删除published attempt而保留archive必须失败。
- [ ] **Step 2：运行新schema测试红灯。** `python -m pytest backend/tests/test_report_pdf_schema.py -q`。
- [ ] **Step 3：建立 schema。**

```python
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class PdfCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_key: str = Field(pattern=r"^reports/[1-9][0-9]*/[0-9a-f-]{36}/document\.pdf$")
    pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1,le=64*1024*1024,strict=True)
    page_count: int = Field(ge=1,le=200,strict=True)

class PdfClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    attempt_id: int
    lease_token: UUID
    lease_owner: str
    run_deadline: datetime
    source_sha256: str
    renderer_sha256: str
    object_key: str

class PdfArchiveStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int
    state: Literal["not_requested","queued","rendering","ready","failed","missing","corrupt"]
    attempt_id: int | None = None
    revision: int
    phase: str | None = None
    code: str | None = None
    message: str
    can_retry: bool = False
    pdf_sha256: str | None = None
    size_bytes: int | None = None
    page_count: int | None = None
    archived_at: datetime | None = None
```

PdfArchiveStatus不得含object_key/lease_token/绝对路径。错误表集中在report_pdf_errors.py：`pdf_disabled(503)`、`pdf_capacity_exceeded(429)`、`report_not_exportable(409)`、`pdf_not_requested(409)`、`pdf_not_ready(409)`、`pdf_retry_forbidden(409)`、`pdf_source_changed(409)`、`pdf_renderer_unavailable(503)`、`pdf_font_unavailable(503)`、`pdf_render_failed(503)`、`pdf_render_timeout(503)`、`pdf_storage_unavailable(503)`、`pdf_storage_full(503)`、`pdf_original_missing(409)`、`pdf_original_corrupt(409)`、`pdf_range_not_supported(416)`及原幂等/404。未知错误映射pdf_render_failed；定义 `PdfError(code,status_code=None)` 提供code/message/status_code，绝不保存原异常文本。

- [ ] **Step 4：0026 SQL和同等 ORM。**

```sql
CREATE TABLE report_pdf_archives (
 report_id INTEGER PRIMARY KEY REFERENCES ai_reports(id) ON DELETE CASCADE,
 state VARCHAR(12) NOT NULL CHECK (state IN ('queued','rendering','ready','failed','missing','corrupt')),
 revision BIGINT NOT NULL DEFAULT 1 CHECK (revision>0),
 source_sha256 VARCHAR(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 source_integrity VARCHAR(16) NOT NULL CHECK (source_integrity IN ('valid','unverifiable')),
 renderer_sha256 VARCHAR(64) NOT NULL CHECK (renderer_sha256 ~ '^[0-9a-f]{64}$'),
 current_attempt_id INTEGER,
 published_attempt_id INTEGER,
 pdf_sha256 VARCHAR(64),
 size_bytes BIGINT,
 page_count INTEGER,
 archived_at TIMESTAMPTZ,
 delivery_count BIGINT NOT NULL DEFAULT 0 CHECK (delivery_count>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CONSTRAINT ck_pdf_published CHECK (
  (published_attempt_id IS NULL AND state IN ('queued','rendering','failed')
   AND pdf_sha256 IS NULL AND size_bytes IS NULL AND page_count IS NULL AND archived_at IS NULL)
  OR (published_attempt_id IS NOT NULL AND state IN ('ready','missing','corrupt')
   AND pdf_sha256 IS NOT NULL AND pdf_sha256 ~ '^[0-9a-f]{64}$'
   AND size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 67108864
   AND page_count IS NOT NULL AND page_count BETWEEN 1 AND 200
   AND archived_at IS NOT NULL))
);
CREATE TABLE report_pdf_attempts (
 id SERIAL PRIMARY KEY,
 report_id INTEGER NOT NULL REFERENCES report_pdf_archives(report_id) ON DELETE CASCADE,
 status VARCHAR(12) NOT NULL CHECK (status IN ('queued','running','completed','failed')),
 phase VARCHAR(24) NOT NULL CHECK (phase IN
 ('queued','source_validation','html','browser_launch','fonts','print','storage','publish','terminal')),
 object_key VARCHAR(180) NOT NULL UNIQUE,
 source_sha256 VARCHAR(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 renderer_sha256 VARCHAR(64) NOT NULL CHECK (renderer_sha256 ~ '^[0-9a-f]{64}$'),
 queued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 queue_deadline TIMESTAMPTZ NOT NULL,
 started_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ,
 heartbeat_at TIMESTAMPTZ,
 run_deadline TIMESTAMPTZ,
 lease_expires_at TIMESTAMPTZ,
 lease_owner VARCHAR(160),
 lease_token UUID,
 error_code VARCHAR(120),
 UNIQUE(report_id,id),
 CONSTRAINT ck_pdf_attempt_running CHECK (status!='running' OR
  (lease_token IS NOT NULL AND lease_owner IS NOT NULL AND run_deadline IS NOT NULL
   AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL)),
 CONSTRAINT ck_pdf_attempt_terminal CHECK (status NOT IN ('completed','failed') OR finished_at IS NOT NULL)
);
ALTER TABLE report_pdf_archives ADD CONSTRAINT fk_pdf_current_attempt
 FOREIGN KEY(report_id,current_attempt_id) REFERENCES report_pdf_attempts(report_id,id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE report_pdf_archives ADD CONSTRAINT fk_pdf_published_attempt
 FOREIGN KEY(report_id,published_attempt_id) REFERENCES report_pdf_attempts(report_id,id)
 DEFERRABLE INITIALLY DEFERRED;
CREATE UNIQUE INDEX uq_pdf_active_attempt ON report_pdf_attempts(report_id)
 WHERE status IN ('queued','running');
CREATE INDEX ix_pdf_queue ON report_pdf_attempts(queued_at,id) WHERE status='queued';
CREATE INDEX ix_pdf_lease ON report_pdf_attempts(lease_expires_at) WHERE status='running';
CREATE TABLE report_pdf_deliveries (
 delivery_id UUID PRIMARY KEY,
 report_id INTEGER NOT NULL REFERENCES report_pdf_archives(report_id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ix_pdf_deliveries_report ON report_pdf_deliveries(report_id);
CREATE TABLE report_file_cleanup_tasks (
 id BIGSERIAL PRIMARY KEY,
 report_id_snapshot INTEGER NOT NULL,
 object_key VARCHAR(180) NOT NULL UNIQUE,
 state VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','settling','done')),
 next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 not_before_final_check TIMESTAMPTZ NOT NULL,
 lease_token UUID,
 lease_expires_at TIMESTAMPTZ,
 failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count>=0),
 error_code VARCHAR(120),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 completed_at TIMESTAMPTZ
);
CREATE INDEX ix_pdf_cleanup_pending ON report_file_cleanup_tasks(next_attempt_at,id)
 WHERE state!='done';
CREATE TABLE report_deletion_tombstones (
 report_id_snapshot INTEGER PRIMARY KEY,
 deleted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
```

CHECK表达式中NULL三值逻辑必须显式加非空；object_key额外使用schema同等严格格式并验证UUID。ORM所有检查名称与迁移一致。清理表和删除墓碑**没有report/user外键**，保证账号删除后仍可清理/恢复删除事实。墓碑仅报告ID与删除时间，不保存病情/标题；覆盖未曾准备PDF的报告，避免恢复旧数据库时这些已删除报告复活。

扩展ck_operator_idempotency_keys_scope_resource只增加批准的两个PDF配对；scope命名见总计划。trigger `guard_pdf_original` 在OLD.published_attempt_id非空时禁止改变source/renderer/published/file属性；允许state健康变化、delivery_count/revision变化。禁止UPDATE delivery身份/时间，DELETE只允许业务删除级联。

- [ ] **Step 5：从首次可写 schema 起安装清理触发器。** 不等到B5再补，避免中间版本遗留文件。

```sql
CREATE FUNCTION enqueue_pdf_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO report_file_cleanup_tasks(report_id_snapshot,object_key,not_before_final_check)
 VALUES(OLD.report_id,OLD.object_key,
  GREATEST(clock_timestamp(),COALESCE(OLD.run_deadline,clock_timestamp()))+interval '60 seconds')
 ON CONFLICT(object_key) DO UPDATE SET
  state='pending',completed_at=NULL,
  next_attempt_at=clock_timestamp(),
  not_before_final_check=GREATEST(report_file_cleanup_tasks.not_before_final_check,EXCLUDED.not_before_final_check);
 RETURN OLD;
END $$;
CREATE TRIGGER report_pdf_attempt_cleanup BEFORE DELETE ON report_pdf_attempts
 FOR EACH ROW EXECUTE FUNCTION enqueue_pdf_cleanup();
CREATE FUNCTION remember_report_deletion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO report_deletion_tombstones(report_id_snapshot)
 VALUES(OLD.id) ON CONFLICT(report_id_snapshot) DO NOTHING;
 RETURN OLD;
END $$;
CREATE TRIGGER remember_report_deletion BEFORE DELETE ON ai_reports
 FOR EACH ROW EXECUTE FUNCTION remember_report_deletion();
```

单个attempt候选目录预登记，archive原件通过published_attempt指向该目录，attempt触发器覆盖ready/临时/所有失败尝试，不需要第二个重复archive触发器。若生产直接delete archive会cascade attempts，同样产生outbox；测试验证report和users级联。
- [ ] **Step 6：验收 schema。** 根目录 `python -m pytest backend/tests/test_report_pdf_schema.py backend/tests/test_alembic_contracts.py backend/tests/test_database_baseline.py -q` 和显式_test `python -m pytest backend/tests/integration/test_report_pdf_constraints.py -q`；0026 downgrade有任何原件/清理/交付/对应幂等历史均拒绝；空_test库上下迁移后schema一致。
- [ ] **Step 7：检查点。** 建议 `feat: add durable PDF archive and cleanup contracts`。

## Task B2：归档受理、状态查询、幂等与配额

**Files**

- Create: `backend/app/services/report_pdf_archive_service.py`、`backend/app/services/report_pdf_repository.py`
- Create: `backend/app/services/report_pdf_renderer_manifest.py`、`backend/app/api/operator_report_archives.py`
- Modify: `backend/app/main.py`、`backend/app/services/report_history_query.py`、`backend/app/services/report_read_service.py`
- Test: `backend/tests/test_report_pdf_admission.py`、`backend/tests/integration/test_report_pdf_admission.py`

**Interfaces:** prepare_pdf_archive/read_pdf_archive_status，空POST请求body且UUID Idempotency-Key必需；source digest 用下述函数。

- [ ] **Step 1：幂等/权限/源快照测试。** 使用A1服务生成source，测试同key同report重放、同key不同report409、不同key同report复用活动attempt、owner/admin/other隔离、failed report拒绝、legacy可导出但不能改为valid。

```python
def test_source_identity_changes_with_saved_content():
    from app.services.report_pdf_archive_service import source_digest
    from app.schemas.report_read_models import PdfSource
    source = PdfSource(report_id=1,batch_id=None,title="报告-1",
        anonymous_case_code=None,integrity_status="unverifiable",
        generation_fingerprint_version=None,generation_fingerprint=None,
        report_document_sha256=None,content="原文",prediction_result={},
        input_snapshot=None,evidence_snapshot=None,report_document=None)
    assert source_digest(source) != source_digest(source.model_copy(update={"content":"变化"}))
```

- [ ] **Step 2：运行 `python -m pytest backend/tests/test_report_pdf_admission.py -q`，确认红灯。**
- [ ] **Step 3：固定source hash/renderer。**

```python
import hashlib
import json

def source_digest(source):
    body = json.dumps(source.model_dump(mode="json"),ensure_ascii=False,
                      sort_keys=True,separators=(",",":"),allow_nan=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()

def request_digest(report_id, retry):
    body = {"version":"pdf_request.v1","report_id":report_id,"retry":retry}
    return hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":")).encode()).hexdigest()
```

manifest schema为`pdf_renderer.v1`，字段：template_sha256、chart_renderer_sha256、markdown_adapter_sha256、font_files（受控相对路径/hash/license）、playwright_version、chromium_version、platform、print_options。它不保存任意外部URL；`load_renderer_manifest(path)`先验证全部schema和资源hash再返回hash。source/manifest预读与大hash在锁外执行，受理锁内重新对比持久source身份，不能跨版本拼接。

- [ ] **Step 4：受理按同一事务实现以下顺序。**

```python
# 无外部副作用的状态决策，事务仓储只负责据此执行
def admission_action(archive, *, retry):
    if archive is None:
        return "create" if not retry else "reject_retry"
    if archive.published_attempt_id is not None:
        return "reject_retry" if retry else "replay"
    if archive.state in ("queued","rendering"):
        return "replay"
    return "retry" if retry and archive.state == "failed" else "replay"
```

先解析scope/key/digest，查询已存在幂等且已删除资源返回稳定墓碑错误。新受理ENABLED/ACCEPTING必须true；global advisory lock 73608→owned report行→archive行。比对source_sha，判断admission_action；create/retry时校验未发布原件且报告completed、队列<20、owner活动<2；生成UUID文件目录，创建attempt queued及deadline，用当前attempt ID写归档，写OperatorIdempotencyKey；commit后才返回202。replay已ready返回200、活动返回202，关闭受理也允许重放已有原件/任务。retry的新renderer固定当前已验证manifest，已有原件仍禁止。

只读状态先校验报告所有权，再查archive/attempt；无archive返回not_requested，不隐式受理。prepare正文未知字段422；retry不接受修改renderer/source。429返回Retry-After:10，稳定错误使用no-store。

- [ ] **Step 5：API和旧兼容。** 注册POST/GET `/reports/{id}/pdf-archive`、POST `/reports/{id}/pdf-archive/retry`；不添加公开object_key下载URL。A4查询LEFT JOIN archive获得pdf_status/delivery_count，A1 detail的download_count使用旧基数+新计数。
- [ ] **Step 6：验收。** `python -m pytest backend/tests/test_report_pdf_admission.py backend/tests/integration/test_report_pdf_admission.py -q --tb=short`；真库双session竞争、受理commit失败/响应丢失、删除墓碑、错误key均覆盖。任何失败不遗留孤立archive/attempt。
- [ ] **Step 7：检查点。** 建议 `feat: admit idempotent PDF archive preparation jobs`。

## Task B3：私有存储、固定渲染与独立 worker

**Files**

- Create: `backend/app/services/report_archive_storage.py`
- Create: `backend/app/workers/report_pdf_worker.py`、`backend/app/workers/report_pdf_execution.py`、`backend/app/workers/report_pdf_process_control.py`
- Create: `scripts/build_report_pdf_renderer_manifest.py`
- Modify: `backend/app/services/pdf_generator.py`、`backend/app/templates/report_pdf.html`、`backend/app/services/report_pdf_repository.py`
- Modify: `backend/app/workers/report_process_control.py`（仅抽取复用进程树基础设施，不改变Publication协议）
- Test: `backend/tests/test_report_archive_storage.py`、`backend/tests/test_report_pdf_worker_process.py`、`backend/tests/integration/test_report_pdf_worker.py`

**Interfaces:** `ArchiveStorage(root).candidate_path(key)`、`write_candidate(key, pdf_bytes) -> PdfCandidate`、`open_verified(key, sha256, size_bytes) -> BinaryIO`、`delete_attempt(key) -> bool`；`render_pdf_candidate(source, manifest_path, target, emit) -> PdfCandidate`；claim_pdf/heartbeat_pdf/publish_pdf/fail_pdf；worker CLI `--once`、`--sweep`。

- [ ] **Step 1：测试存储越界、文件不覆盖、超时回收。**

```python
import hashlib
import pytest
from app.services.report_archive_storage import ArchiveStorage

def test_storage_verifies_exact_bytes_and_rejects_traversal(tmp_path):
    storage=ArchiveStorage(tmp_path)
    key="reports/17/11111111-1111-4111-8111-111111111111/document.pdf"
    with pytest.raises(ValueError):
        storage.candidate_path("../escape.pdf")
    path=storage.candidate_path(key)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"%PDF-fixture")
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with storage.open_verified(key,digest,12) as stream:
        assert stream.read()==b"%PDF-fixture"
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        storage.open_verified(key,digest,12)
```

补目录符号链接/junction/reparse越界、相同key不可覆盖、目录权限错误、文件长度上限、已打开句柄校验后仍用同句柄。fake bytes只用于存储测试，worker测试必须用真实可解析PDF。
- [ ] **Step 2：运行上述新测试红灯。** 根目录 `python -m pytest backend/tests/test_report_archive_storage.py backend/tests/test_report_pdf_worker_process.py -q`。
- [ ] **Step 3：安全打开/校验的核心实现。**

```python
import hashlib
import re
from pathlib import Path
from uuid import UUID

class ArchiveStorage:
    def __init__(self, root):
        self.root=Path(root).resolve(strict=True)
    def candidate_path(self,key):
        match=re.fullmatch(r"reports/([1-9][0-9]*)/([0-9a-f-]{36})/document\.pdf",key)
        if not match:
            raise ValueError("pdf_object_key_invalid")
        UUID(match.group(2))
        path=self.root.joinpath(*key.split("/"))
        resolved=path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("pdf_object_key_invalid")
        return path
    def open_verified(self,key,sha256,size_bytes):
        path=self.candidate_path(key)
        stream=path.open("rb")
        try:
            digest=hashlib.sha256()
            size=0
            for chunk in iter(lambda:stream.read(1024*1024),b""):
                size+=len(chunk)
                if size>size_bytes:
                    raise ValueError("pdf_original_corrupt")
                digest.update(chunk)
            if size!=size_bytes or digest.hexdigest()!=sha256:
                raise ValueError("pdf_original_corrupt")
            stream.seek(0)
            return stream
        except BaseException:
            stream.close()
            raise
```

在上述路径边界之外，实现Linux受目录fd约束的openat/O_NOFOLLOW逐级打开，Windows拒绝重解析点并校验打开句柄真实路径；仅resolve检查不足以抵御校验/打开期间替换。目录仅服务账户可写，文件不接受客户端提供key。测试必须包含故意更换父目录场景。最终写入使用同卷唯一`.part`、flush/fsync、独占落位，不用可覆写的os.replace覆盖既有原件；Linux同步目录元数据，Windows使用平台文件同步实现并保留断电持久性验证边界。

- [ ] **Step 4：固定渲染制品与真正字体就绪。** 构建脚本接受`--font-dir`（包含Noto Sans CJK SC字体与授权）、`--output-dir`，调用实际安装Playwright读取Chromium版本，hash模板/图表/Markdown适配器/字体，输出manifest及SHA命名目录。字体缺失或授权文件缺失立即失败；资源来源从官方发布获得，实施时记录下载来源及制品hash，不在计划里杜撰hash。构建manifest作为可审阅制品，不在请求时“生成新manifest承认漂移”。

改造`generate_pdf`接受固定renderer配置、phase callback、总预算，旧单元测试默认参数仍可用；生产归档必须有manifest。控制渲染顺序：sanitize→Jinja→Chromium→fonts→print→PyMuPDF验证/页数→候选持久落位。

```python
# Playwright 内部渲染步骤，外部 watchdog 负责硬总期限
page.route("**/*", lambda route: route.abort())
page.set_content(full_html, timeout=30000)
page.evaluate("async () => { await document.fonts.ready; }")
if not page.evaluate("font => document.fonts.check(font, '脂肪肝阿尔茨海默病')", '16px "ReportCJK"'):
    raise ValueError("pdf_font_unavailable")
```

字体以受控内联data资源写入CSS，标题/页脚自己包含字体声明；不依赖外网。使用加载状态/FontFace集合明确核对指定字体，fonts.check不能单独证明没有fallback。browser/page在finally关闭；日志不含title/content/原异常/traceback。

- [ ] **Step 5：领取和发布仓储。** 全局锁73609约束跨worker并发1；发现候选后依次report→archive→attempt加锁，再检查queue_deadline、published为空。领取事务记录lease token/owner/run_deadline并提交；读取source/manifest后关闭session再启动child。heartbeat有界；失租/取消（报告删除）/超时都杀整个树。

发布必须重新校验下述谓词，DB时间在hash核对后再次读取；不满足返回False并登记候选清理，不输出ready：

```python
def claim_may_publish(report,archive,attempt,claim,now):
    return bool(report and report.status=="completed" and archive
        and archive.published_attempt_id is None
        and archive.current_attempt_id==claim.attempt_id
        and archive.source_sha256==claim.source_sha256
        and archive.renderer_sha256==claim.renderer_sha256
        and attempt and attempt.status=="running"
        and attempt.lease_token==claim.lease_token
        and attempt.lease_owner==claim.lease_owner
        and attempt.lease_expires_at>now and attempt.run_deadline>now)
```

父进程只接受schema有效的candidate metadata，object_key必须等于claim预留key；在锁外重新open_verified和验证页数，锁内验证source identity仍相同，再同时写attempt completed/archive ready/published/file身份。文件存在不等于已发布；提交不确定用新session读published_attempt/hash，禁止自动再渲染。

监督协议独立于模型Publication：`phase/error/candidate`，消息最大64KiB，错误code/phase白名单，阶段单调，重复消息不延期。复用managed_process_tree/stop_child的进程树逻辑，经原模型进程测试回归；不要用Python线程超时假装已终止Chromium。

- [ ] **Step 6：期限和清理候选。** sweep将queue超时/running失租落attempt failed、archive failed，已ready完全不动；失败尝试的object key登记清理outbox（不删除attempt审计）。队列未超时重启继续领取；running中断不自动重渲染，显式retry产生新attempt。领取后run总限120秒包含storage/publish，数据库阻塞也受watchdog制约。
- [ ] **Step 7：绿灯。** 新存储/进程专项和既有 `backend/tests/test_report_worker_process.py`、`backend/tests/test_pdf_generation.py`、`backend/tests/test_longitudinal_pdf_contract.py`、`backend/tests/test_report_document_pdf.py`；真库双worker/晚返回/提交响应丢失/磁盘满。进程测试验证父强杀后Chromium子孙退出。
- [ ] **Step 8：检查点。** 建议 `feat: render and publish immutable PDF originals in bounded workers`。

## Task B4：同句柄交付、原子计数与原件健康

**Files**

- Create: `backend/app/services/report_pdf_delivery.py`
- Modify: `backend/app/api/operator.py`（download替换）、`backend/app/services/report_read_service.py`、`backend/app/services/report_history_query.py`
- Test: `backend/tests/test_report_pdf_delivery.py`、`backend/tests/integration/test_report_pdf_delivery.py`

**Interfaces:** PdfDelivery(file:BinaryIO,filename:str,size_bytes:int,sha256:str)，prepare_delivery返回它；所有新下载都不调用generate_pdf。

- [ ] **Step 1：重复下载不渲染、同SHA及计数测试。** mock `generate_pdf` 为raise AssertionError；为ready原件执行两次GET，两次body hash等于archive，archive.delivery_count+2，AIReport.updated_at/原download_count/全部指纹不变。篡改源数据即使文件正确也409。
- [ ] **Step 2：运行 `python -m pytest backend/tests/test_report_pdf_delivery.py -q`，确认现有同步渲染路径不符合新断言。**
- [ ] **Step 3：两阶段准备交付。** 独立session owned read/完整性/source身份→释放session→open_verified；再短事务按report→archive加锁重查存在/ready/source/hash，写delivery和计数；commit后返回同一文件句柄。不跨文件hash持DB锁。若删除竞争先提交，关闭文件返回404；交付授权先提交则允许已授权stream完成，后续请求全部404。

```sql
WITH accepted AS (
 INSERT INTO report_pdf_deliveries(delivery_id,report_id)
 VALUES(:delivery_id,:report_id)
 ON CONFLICT(delivery_id) DO NOTHING RETURNING report_id
)
UPDATE report_pdf_archives SET delivery_count=delivery_count+1
WHERE report_id IN (SELECT report_id FROM accepted);
```

delivery_id由服务端本次逻辑交付生成；commit结果不确定在本次逻辑内复用同id重读，禁止重复计数。不能把同id冲突用于另一report。文件missing/corrupt用单独短事务健康标记，只在仍指向相同published_attempt/hash时更新state，不改原件身份。

- [ ] **Step 4：流式响应安全释放。**

```python
def delivery_chunks(delivery):
    try:
        while True:
            chunk=delivery.file.read(1024*1024)
            if not chunk:
                break
            yield chunk
    finally:
        delivery.file.close()
```

同步StreamingResponse附Content-Disposition安全ASCII fallback+UTF-8、Content-Length、Cache-Control private,no-store、X-Content-Type-Options nosniff、Accept-Ranges none。连接中断关闭句柄，不回滚交付计数。HEAD不注册；Range显式416并无文件body，不让绕过所有权/计数语义。
- [ ] **Step 5：验收。** 20个并发独立DB连接交付计数恰+20；文件/报告篡改、不存在、越权、未完成、未归档、坏文件、DB中断、下载中删除全部验收。`python -m pytest backend/tests/test_report_pdf_delivery.py backend/tests/integration/test_report_pdf_delivery.py -q`。
- [ ] **Step 6：检查点。** 建议 `feat: deliver verified PDF originals with atomic access accounting`。

## Task B5：删除补偿、原件恢复与清理 CLI

**Files**

- Create: `backend/app/services/report_archive_cleanup.py`、`backend/app/services/report_archive_recovery.py`
- Create: `scripts/manage_report_pdf_archives.py`
- Modify: `backend/app/services/report_generation_service.py`（delete调用）、`backend/app/api/operator.py`、`backend/app/api/user.py`（账号删除后立即清理）
- Test: `backend/tests/test_report_archive_cleanup.py`、`backend/tests/integration/test_report_archive_cleanup.py`、`scripts/tests/test_manage_report_pdf_archives.py`

**Interfaces:** DeleteReportResult(deleted:bool,cleanup_state:Literal['complete','pending'])；delete_owned_report；run_cleanup_once；restore_pdf_original。

- [ ] **Step 1：真库删除级联和事务rollback测试。** 准备ready及running两类，DELETE report后report/archive/attempt不可见而cleanup row保留；delete users也保留清理记录。人为使删除事务rollback，archive/file仍可读。模拟storage拒绝删除返回202、之后恢复存储sweep最终清理。
- [ ] **Step 2：运行 `python -m pytest backend/tests/test_report_archive_cleanup.py -q`，确认原删除逻辑缺补偿。**
- [ ] **Step 3：报告删除和清理顺序落地。** owned delete锁generation job→report→archive→attempt；generating仍409；事务删除报告由B1trigger登记所有对象。先commit，再立即对本次report_id_snapshot对应outbox执行清理；全部在线文件消失返回204，否则202 + `{deleted:true,cleanup_state:'pending',message:'报告已删除，文件清理中'}`。重试同一已删报告按既有404，不复活；清理不依赖用户会话。

清理过程只删除已登记attempt目录中的document.pdf和固定临时名，校验resolved路径和父目录不越root，禁止字符串拼接任意递归删除。进程可能晚写，第一次删除后状态settling，到not_before_final_check再检查一次；child终止未确认不写done。服务启动或定时整合扫描也须比对outbox/引用关系，不能仅按mtime删文件。

```python
def next_cleanup_delay(failure_count):
    return min(3600, 5 * (2 ** min(failure_count,10)))
```

清理重试以数据库next_attempt_at安排，lease失效后可重新领取；有界IO deadline，失败code固定pdf_storage_unavailable，不永久吞错。已published且仍被有效archive引用的key禁止作为普通孤儿删除，维护命令显式报告冲突。

- [ ] **Step 4：恢复 CLI 与同hash规则。** `manage_report_pdf_archives.py inspect --report-id N` 默认只读；`restore --report-id N --backup-file PATH --apply` 必须先展示预检哈希对比（工具安全日志只输出id/hash，不打印路径/连接），只有missing/corrupt且backup hash/长度/页数精确一致才写候选并安全落位。重新锁report/archive验证同一published identity后将state恢复ready；source报告invalid仍禁止下载，不能靠恢复文件掩盖源损坏。

```python
def restore_matches(candidate, archive):
    return (candidate.pdf_sha256==archive.pdf_sha256
            and candidate.size_bytes==archive.size_bytes
            and candidate.page_count==archive.page_count
            and archive.published_attempt_id is not None
            and archive.state in ("missing","corrupt"))
```

报告已删除一律拒绝restore；没有原件备份不调用renderer。cleanup CLI `cleanup --once`、`cleanup --sweep`，默认执行登记的删除补偿，不能扫描任意目录。生产使用需部署授权，本计划只在临时目录/_test演练。
- [ ] **Step 5：验收。** 覆盖Windows已打开句柄无法删除后的补偿、Linux已授权流/删除交错、worker晚写、磁盘故障恢复、wrong hash备份、账号级联、未知对象key。运行新三组测试；C3验证跨备份删除日志重放。
- [ ] **Step 6：检查点。** 建议 `feat: clean deleted report files and restore archived originals safely`。

## Task B6：前端准备/下载/重试与删除反馈

**Files**

- Create: `frontend/src/api/report-archive.ts`、`frontend/src/stores/report-archive.ts`
- Modify: `frontend/src/api/operator.ts`、`frontend/src/api/request.ts`（仅复用错误规范化工具）、`frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/components/LongitudinalReportView.vue`、`frontend/src/components/report/ReportHistoryWorkspace.vue`、`frontend/src/stores/auth.ts`
- Test: `frontend/src/api/__tests__/report-archive.spec.ts`、`frontend/src/stores/__tests__/report-archive.spec.ts`、`frontend/src/components/__tests__/ReportArchiveActions.spec.ts`

**Interfaces:** useReportArchiveStore `observe(reportId)/prepare()/retry()/download()/detach()/refreshConnection()`；ArchiveState跟PdfArchiveStatus；每report/request动作epoch独立，不能与模型generation.revision混用。

- [ ] **Step 1：写用户行为测试。** prepare成功202、刷新只GET不POST；连点只一个prepare、响应丢失复用key；ready反复下载不prepare；missing/corrupt没有retry按钮；账号切换后旧响应不产生blob下载；429重试遵守Retry-After；DELETE202显示清理中而不是“已全部删除”。
- [ ] **Step 2：frontend跑三组专项，确认新增行为先红灯。**
- [ ] **Step 3：API解析与同一请求key。** 使用现有ApiRequestError/parseRetryAfter处理fetch错误；localStorage仅Bearer token，sessionStorage保存`operator-pdf-request:{user_id}:{report_id}`的request key/action/attempt id，不保存病情/正文/blob/object key。网络不确定时保留key，明确4xx冲突才放弃；退出清除此前缀。轮询状态not_requested/ready/failed/missing/corrupt为终态，queued/rendering才退避轮询；GET网络错误显示重连，不能自动POST重试渲染。

```typescript
export function archiveAction(state: string, canRetry: boolean): string {
  if (state==='ready') return '下载 PDF'
  if (state==='not_requested') return '准备 PDF'
  if (state==='queued' || state==='rendering') return '正在准备，可离开页面'
  if (state==='failed' && canRetry) return '重新准备 PDF'
  if (state==='missing' || state==='corrupt') return '归档原件暂不可用'
  return '暂不可导出'
}
```

- [ ] **Step 4：下载句柄和页面连接。** fetch下载前捕获user/report/epoch，下载完成再检查相同身份后才创建blobURL/a.click；Content-Type必须application/pdf，解析服务端filename*并做本地安全文件名兜底，不接受路径分隔/控制字符。URL在浏览器触发后延迟安全revoke；finally清loading。AbortController在切换/卸载/注销时abort，不能把取消下载解释为取消后台归档。

详情只有completed且非invalid显示归档动作；legacy unverifiable旁保留警示但可首次准备。失败报告的“重新生成报告”仍走现有病例模型任务，不与“重新准备PDF”混淆。history返回保留筛选/滚动，不因每次poll刷新第一页。删除API返回`void | DeleteReportResult`，204/202分别提示；ElMessageBox的用户取消与HTTP异常分开catch。
- [ ] **Step 5：前端绿灯与构建。** frontend运行 `npm run test:unit`、`node --test tests/longitudinal-report-ui-contract.test.mjs`、`npm run build`。后端B2/B4API字段与TS一致；旧错误提示不出现`[object Object]`。
- [ ] **Step 6：检查点。** 建议 `feat: expose durable PDF preparation and original downloads`。
