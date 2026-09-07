# 历史与 PDF 原件联合验收 Implementation Plan

## 执行状态（2026-09-07）

用户已选择直接在 main、本会话逐项执行。实际交付、命令和证据见 [实施记录](../notes/2026-09-07-operator-history-pdf-execution-log.md)。下文保留批准时的步骤和代码示意，原过程复选框不作为执行证据；未留存的逐条红灯过程不追补声称。

- [x] C1：仓库交付与本机隔离验收完成。
- [x] C2：仓库交付与本机隔离验收完成。
- [x] C3：仓库交付与本机隔离验收完成。
- [ ] 生产发布：目标 Linux 联合容量、服务安装、生产迁移、postflight 与实际备份保留/RPO/RTO 验收，待获准部署窗口执行。

Git 检查点仅保留为建议；本次未提交、推送或部署。


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用真实数据库、浏览器、PDF 文件和故障演练证明第 7～9 项合同，交付可执行的发布/回滚/恢复门禁。

**Architecture:** 扩充现有独立本机 `_test` harness，分别验证数据库竞争、页面生命周期和固定PDF原件；只读检查器与备份清单支撑部署，独立服务监督PDF和清理任务。

**Tech Stack:** PostgreSQL 18/pgvector、pytest、Playwright、PyMuPDF、Vitest、现有 PowerShell/Python harness、Linux systemd。

## Global Constraints

- 前置 A1～A5、B1～B6，接口与状态名称以[总计划](2026-09-07-operator-report-history-pdf-implementation.md)为准。
- 关键真库/E2E/故障测试无skip才能标记隔离验收完成；没有环境时记录阻断，不使用mock替代结论。
- 本轮仅编写计划。以下数据库、进程和文件操作在实施时运行，测试只能使用明确本机 `_test` 库和本次临时存储目录。
- 仓库、本机隔离验收、生产上线分别记录；生产迁移、真实容量或恢复演练缺一，不标记生产完成。
- 不把本机 Windows 内存测试替代 Linux 4 GiB 全服务容量。

## Task C1：数据库竞争、读取规模和删除/恢复一致性

**Files**

- Modify: `backend/tests/integration/conftest.py`
- Create: `backend/tests/integration/report_archive_fixtures.py`
- Create: `backend/tests/integration/test_report_archive_lifecycle.py`
- Extend: A2/A4/B1/B2/B3/B4/B5 各精确integration测试文件
- Create: `scripts/benchmark_report_history.py`、`scripts/tests/test_benchmark_report_history.py`

**Interfaces:** fixture `archive_session_factory` 返回独立sessionmaker；`completed_report` 返回真实持久报告ID；每个并发任务自己创建/关闭session，禁止多个线程共享现有client/db fixture的同一session。

- [ ] **Step 1：强化测试环境守卫并补清理新表。**

```python
from scripts.seed_operator_report_e2e import require_test_database

def assert_isolated_database(url: str):
    require_test_database(url)
```

在integration_engine连接和任何TRUNCATE前调用；仅host=localhost/127.0.0.1且db后缀_test。新增cleanup/删除墓碑表无级联，fixture必须显式清理它们；每test的tmp_path archive root不同，避免TRUNCATE删除事实但遗留文件影响下一test。不打印连接字符串。

- [ ] **Step 2：建立完整报告夹具。**

```python
import pytest
from sqlalchemy.orm import sessionmaker
from app.db.models import AIReport
from app.services.report_document_builder import build_report_document
from app.services.report_publication import build_publication
from app.services.report_integrity import compute_input_snapshot_sha256
from backend.tests.report_document_fixtures import demo_inputs

@pytest.fixture
def archive_session_factory(integration_engine):
    return sessionmaker(bind=integration_engine,expire_on_commit=False)

@pytest.fixture
def completed_report(db):
    snapshot,context,audited,evidence=demo_inputs()
    report=AIReport(user_id=1,disease_id=1,query="software-test",
        status="generating",analysis_type="longitudinal_predictive",
        input_snapshot=snapshot,input_snapshot_sha256=compute_input_snapshot_sha256(snapshot),
        generation_batch_id=snapshot["generation_batch_id"])
    db.add(report)
    db.flush()
    db.refresh(report)
    document=build_report_document(report.id,report.created_at,snapshot,context,
                                   audited.prediction,audited.model_runs,evidence)
    publication=build_publication(snapshot,audited.prediction,evidence,document)
    for name,value in publication.model_dump(mode="json").items():
        setattr(report,name,value)
    report.status="completed"
    db.commit()
    return report.id
```

该夹具只用于测试已有完成记录；实际模型任务发布事务仍由既有test验证，不能把直接写fixture当作真实worker验收。B2受理使用临时测试renderer manifest，B3真实renderer另由C2验证。

- [ ] **Step 3：在真实DB建立竞争屏障。** 使用 `ThreadPoolExecutor` + `threading.Barrier`，每线程独立factory；在受理/claim/publish/delivery/delete commit边界注入延迟/故障。测试必须断言最终数据库行，不只检查HTTP状态。

```python
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
from app.services.report_pdf_archive_service import prepare_pdf_archive

def test_concurrent_prepare_reuses_one_attempt(archive_session_factory,completed_report):
    barrier=Barrier(2)
    def submit():
        barrier.wait(timeout=5)
        return prepare_pdf_archive(archive_session_factory,1,completed_report,str(uuid4()))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(submit) for _ in range(2)]
        results=[f.result(timeout=15) for f in futures]
    assert len({r.attempt_id for r in results})==1
```

测试前monkeypatch启用归档并安装固定临时manifest/root；每个test结束关闭。每个竞争矩阵：

| 场景 | 强制边界 | 必须结果 |
|---|---|---|
| 相同/不同key双受理 | 插入前并发 | 同report单active attempt，幂等记录合法 |
| 两worker领取 | 同时claim | 同一attempt只有一token；全局运行≤1 |
| 失租旧worker晚发布 | 先令lease过期/sweep | 发布False，ready不得被旧结果写入 |
| commit响应丢失 | commit成功后抛异常 | 重读原attempt/原件，不能新渲染或重复计数 |
| 下载与删除 | open_verified前后屏障 | 删除先提交则404；授权先提交允许原stream，后续404 |
| render→file→publish各点强杀 | 分别暂停后杀进程 | 无半ready；候选登记且最终清理 |
| 账号级联删除 | 不调用报告删除service | trigger仍写outbox，清理不依赖user行 |
| 源/原件损坏 | ready后单字段改变 | invalid/missing/corrupt，拒绝下载/普通retry |
| 备份恢复 | wrong/correct SHA | 错hash无写入；同hash恢复ready及同bytes |
| 失败审计 | stage/error/kill | last/failure phase保留，未知步骤不称完成 |

- [ ] **Step 4：10000条历史规模与查询计划。** benchmark脚本仅_test库，批量插入虚构匿名报告，保留有大document的样本；匿名筛选/病种/日期/状态组合，单次limit20/100。用SQL监听确认无完整大字段及N+1，记录EXPLAIN(ANALYZE,BUFFERS)与p50/p95/max。schema测试与查询字段检查是确定断言，p95<1秒是目标机门禁，不在共享CI硬编码毫秒阈值。
- [ ] **Step 5：运行真库全部回归。** 根目录：

```powershell
python -m pytest backend/tests/integration -q --tb=short
python scripts/benchmark_report_history.py --rows 10000 --page-size 20 --output outputs/operator-history-pdf/history-benchmark.json
```

必须由显式TEST_DATABASE_URL提供测试连接；benchmark只连接该变量，不回退DATABASE_URL。预期关键集成0失败0skip，分页集合一致且规模证据写JSON。
- [ ] **Step 6：检查点。** 建议 `test: verify report history and PDF archive database races`。

## Task C2：双病种浏览器、固定原件和 PDF 逐页验证

**Files**

- Modify: `scripts/run_operator_report_e2e.py`、`scripts/run_operator_case_e2e.ps1`
- Create: `backend/tests/e2e/test_operator_history_pdf_archive.py`
- Modify: `scripts/verify_operator_report_pdf.py`
- Create: `scripts/tests/test_report_pdf_verification.py`
- Modify: `backend/tests/e2e/report_test_server.py`（注册真实新router，不替换业务实现）

**Interfaces:** 沿用browser_page/operator_tokens fixture；新harness创建REPORT_ARCHIVE_ROOT、构建renderer manifest、启动真实PDF worker/sweep/cleanup，运行完成finally只关闭本次创建进程树。

- [ ] **Step 1：升级harness进程管理。** 不再用进程数组位置硬编码`api/worker/frontend`采样；用dict(name→Popen)增加pdf_worker/pdf_sweep/cleanup。Start-Process若使用必须Hidden。测试使用临时archive目录和虚构测试病例，失败保留诊断产物，不清理业务目录。
- [ ] **Step 2：真实UI完成以下顺序。** 每病种独立：创建病例→报告生成→历史筛选定位→打开保存详情→准备PDF→等待ready→下载→刷新→再次下载→修改病例/停用疾病→仍可从历史下载同原件→删除病例→报告/PDF仍可读→删除报告→历史不可见且文件清理完成。

```python
import hashlib

def downloaded_sha(page, label):
    with page.expect_download() as event:
        page.get_by_role("button",name=label,exact=True).click()
    download=event.value
    with open(download.path(),"rb") as stream:
        return hashlib.file_digest(stream,"sha256").hexdigest()
```

相邻两次下载hash必须相同，服务端attempt数量不增加。准备PDF是POST，下载是GET；用browser request监听断言第二次下载没有调用prepare或模型生成。禁用模型/标准服务后旧ready下载仍能工作；source完整性校验保留。

- [ ] **Step 3：覆盖非成功路径。** 跨user和admin 404；关闭页面/刷新/断网仅停止观察，queued可恢复；两个标签prepare同attempt；401清旧状态；429/focus不提前重试；failed报告打开具体阶段及保存context；missing/corrupt只能提示维护恢复；DELETE202显示清理中；页面没有英文阶段裸码/`[object Object]`。
- [ ] **Step 4：PDF实物与最大输入。** modify verify_operator_report_pdf.py 对新完成报告走归档API/存储读取原件；旧纯generate_pdf helper仅用于隔离的展示压力变体，并清楚标记非业务原件。两病种普通、10次全目录指标、长上下文、10×30压力、旧版、部分模型失败逐页验证。

```python
import fitz

def pdf_layout_findings(pdf_bytes):
    document=fitz.open(stream=pdf_bytes,filetype="pdf")
    problems=[]
    for index,page in enumerate(document):
        for x0,y0,x1,y1,text,*rest in page.get_text("blocks"):
            if text.strip() and (x0 < -1 or y0 < -1 or x1 > page.rect.width+1 or y1 > page.rect.height+1):
                problems.append({"page":index+1,"code":"text_outside_page"})
    return problems
```

自动边界检查不代替视觉检查。提取font信息确认受控中文字体嵌入，按页输出PNG/contact-sheet，人工查看长表跨页、重复表头、页眉页脚、无空白异常页、真实日期比例、零/False、原文溯源不丢。记录全部页数，不只第一页。B3固定版本更新后即使布局改变，也必须确认已ready原件SHA不变。

- [ ] **Step 5：运行命令。** 根目录：

```powershell
scripts/run_operator_case_e2e.ps1
python scripts/verify_operator_report_pdf.py --output-dir outputs/operator-history-pdf/pdf
```

第二条只允许明确_test DATABASE_URL，并要求新脚本守卫先于Session创建；不从生产.env回退。字体制品在harness启动前构建，路径从本机测试配置提供。没有字体/浏览器不skip字体门禁，应报明确环境准备失败。

- [ ] **Step 6：检查点。** 建议 `test: verify persistent PDF originals in operator browser flows`。

## Task C3：只读门禁、服务监督、备份恢复与发布回滚

**Files**

- Create: `scripts/check_operator_report_archives_readonly.py`、`scripts/tests/test_check_operator_report_archives_readonly.py`
- Create: `scripts/backup_report_archive_inventory.py`、`scripts/tests/test_backup_report_archive_inventory.py`
- Create: `deploy/systemd/surgery-report-pdf-worker.service`
- Create: `deploy/systemd/surgery-report-pdf-sweep.service`、`deploy/systemd/surgery-report-pdf-sweep.timer`
- Create: `deploy/systemd/surgery-report-file-cleanup.service`、`deploy/systemd/surgery-report-file-cleanup.timer`
- Modify: `docs/OPERATOR_REPORT_OPERATIONS.md`、`docs/DEPLOY.md`、`docs/ALIYUN_DEPLOYMENT_RUNBOOK.md`、`scripts/check_database_readonly.py`
- Modify: `docs/AI操作者流程核查.md`、`docs/superpowers/notes/2026-09-07-operator-history-pdf-execution-log.md`

**Interfaces:** 只读检查CLI `--phase preflight|postflight --verify-files --worker-ready`；备份inventory生成相同report/archive/key/hash清单，恢复按删除日志排除已删资源。

- [ ] **Step 1：为只读门禁写失败测试。** fake DB spy记录执行SQL，必须在任何查询前`SET TRANSACTION READ ONLY`；若发现UPDATE/DELETE/INSERT或尝试自动修复则测试失败。数据库缺schema、invalid报告、ready缺文件、hash错误、过期attempt、cleanup积压、renderer漂移、服务未就绪分别FAIL稳定code。
- [ ] **Step 2：实现真正只读检查。**

```sql
SET TRANSACTION READ ONLY;
SELECT count(*) FROM report_pdf_archives a
JOIN ai_reports r ON r.id=a.report_id
WHERE r.status!='completed';
SELECT count(*) FROM report_pdf_attempts
WHERE (status='queued' AND queue_deadline<=clock_timestamp())
 OR (status='running' AND
     (lease_expires_at<=clock_timestamp() OR run_deadline<=clock_timestamp()));
SELECT count(*) FROM report_file_cleanup_tasks
WHERE state!='done' AND next_attempt_at<clock_timestamp()-interval '1 hour';
```

还需检查published身份/计数与delivery行一致、孤立文件/缺文件、存在report的有效引用不得进入done清理、context/audit界限。verify-files只打开并hash，不能设置missing/corrupt或清理。preflight允许新增schema尚未存在但记录schema_ready=False；postflight所有结构/服务/存储/资源条件齐全才PASS。输出聚合数量和safe code，避免病情/连接/文件绝对路径。

- [ ] **Step 3：安装有界监督配置（先写模板，本期不在生产运行）。** worker模板核心：

```ini
[Unit]
Description=Surgery report PDF archive worker
After=network.target postgresql.service

[Service]
Type=simple
User=surgery
Group=surgery
WorkingDirectory=/opt/surgery-rag/backend
EnvironmentFile=/opt/surgery-rag/backend/.env
ExecStart=/opt/surgery-rag/backend/venv/bin/python -m app.workers.report_pdf_worker
Restart=on-failure
RestartSec=5
TimeoutStopSec=15
KillMode=control-group
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=multi-user.target
```

MemoryHigh/MemoryMax不照搬模型worker预算；目标Linux联合压测后写实测配置。`PrivateTmp`要求候选与原件均在专用持久卷，不跨服务/tmp传文件。sweep每15秒独立执行`python -m app.workers.report_pdf_worker --sweep`；cleanup timer执行根目录`python scripts/manage_report_pdf_archives.py cleanup --once`，即使PDF worker停机仍运行。检查worker死亡与无任务分别处理，不能用无心跳推断空闲服务失败。

- [ ] **Step 4：配套备份与删除日志。** inventory命令在维护窗口关闭新归档/删除、排空文件写入后生成：backup_id、数据库快照身份、created_at、每原件report_id/published_attempt_id/object_key/SHA/长度、renderer hash和清理/删除日志检查点。文件备份与DB备份同一集合；不可只备DB。完成后再次检查无新发布/删除，发现漂移则该备份集无效重做。

删除日志使用B1的report_deletion_tombstones，文件清理事实另保留outbox；两者不能随清理成功被永久删除，独立增量备份并确保恢复点覆盖。恢复旧DB备份时先重放较新的报告删除事实（包括没有PDF的报告），删除相应report/归档关系并登记清理，再核对文件hash；缺失删除日志时不开启下载，防已删资料复活。

在_test演练：备份ready→删除报告→恢复旧DB/文件到另一_test库→应用备份后删除日志→原报告必须仍不可读取。恢复工具需指定`--apply`和目标库，默认dry-run，不能自动连接生产。RPO/RTO/保留天数在部署记录填写真实运维选择，不在代码中虚构。

- [ ] **Step 5：容量与上线次序。** 真实Linux4GiB加载DB/Web/RAG/BGE、模型worker及PDF worker，用10次访视/长报告测试联合峰值和p95；PDF初值并发1并不保证全服务够用。若超预算，采用统一重任务槽串行模型/PDF或扩容，并再次验收；禁止删报告内容或禁用完整性hash过门禁。

发布：备份/只读preflight→关闭受理并排空旧worker→upgrade实际head→安装renderer字体私有目录→部署兼容前后端→启动worker/sweep/cleanup→postflight/恢复演练/容量PASS→开放归档。已ready下载不依赖ACCEPTING。回滚关闭新受理并排空未发布尝试，保留新增表/原件/审计/清理，仅回退兼容应用；永不恢复旧同步重渲染下载旁路。

- [ ] **Step 6：最终命令与证据。** 根目录：

```powershell
python -m pytest backend/tests --ignore=backend/tests/integration --ignore=backend/tests/e2e -q --tb=short
python -m pytest backend/tests/integration -q --tb=short
python -m pytest scripts/tests/test_check_operator_report_archives_readonly.py scripts/tests/test_backup_report_archive_inventory.py scripts/tests/test_manage_report_pdf_archives.py -q
git diff --check
```

frontend目录：

```powershell
npm run test:unit
node --test tests/longitudinal-report-ui-contract.test.mjs
npm run build
```

E2E和PDF命令见C2，容量/只读/备份结果写执行日志。迁移校验包括schema.sql与Alembic0019～0026链一致。旧模型/参考病例/标准测试保留；无skip掩盖关键新场景。
- [ ] **Step 7：更新核查状态与交付。** 区分仓库完成、本机隔离完成、生产未部署；运行数据存在outputs目录不提交。建议检查点 `docs: document PDF archive operations and release gates`，最后回总计划P1。
