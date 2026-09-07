# 完整预测报告发布与恢复

本项迁移为 0023（结构化报告）和 0024（持久任务），必须沿当前 Alembic 迁移链升级。HTTP 受理只保存快照和任务，独立 worker 使用固定版本生成；页面刷新、断线和返回病例不会取消任务。服务重启后查询数据库状态，失去租约的执行只收敛为失败，不自动重算。

## 配置与容量

默认 `REPORT_JOBS_ENABLED=False`、`REPORT_JOBS_ACCEPTING=False`。启用 worker 需前者为 True；开放新受理还需后者为 True。关闭受理不影响历史读取、状态查询、取消和下载。

默认全局并发 1、队列上限 20、每用户活动任务 2、每病例活动任务 1；排队 600 秒、执行 300 秒、租约 45 秒、心跳 10 秒。各阶段预算见 `backend/.env.example`，阶段超时不能通过重复消息延长。新增部署不得提升并发绕过 4 GiB 主机资源基线。

systemd 模板位于 `deploy/systemd/`，沿用 `DEPLOY.md` 的 `surgery` 账户和 `/opt/surgery-rag/backend/venv`。安装前核对实际 User/Group、虚拟环境、目录和环境文件最小读取权限。模板中 worker 的 MemoryHigh 1536 MiB、MemoryMax 2048 MiB 是初始隔离预算，必须结合 PostgreSQL、Web、BGE 等其他服务的总 RSS 复核；本机 Windows 测试不能代替 Linux 4 GiB 主机容量验收。

worker 使用 `KillMode=control-group`，Windows CLI 使用 Job Object 的 KILL_ON_JOB_CLOSE。独立 sweep timer 每 15 秒执行一次，即使 worker 不可用也会收敛过期任务。监控必须单独检查 worker 服务状态，不能以无任务时没有心跳判断死亡。

执行期限按领取时数据库 run_deadline 的剩余预算计算；独立 watchdog 在数据库心跳回调阻塞时仍终止执行进程。worker 专用连接设置连接/语句 5 秒、锁等待 3 秒、池等待 5 秒及 TCP 存活检查；数据库不可达时不伪造终态，恢复后由独立 sweep 根据租约收敛。前端遵守 Retry-After，重连、窗口焦点恢复不能绕过限流等待。

## 发布顺序

1. 备份数据库和当前应用制品，关闭新报告入口，运行只读 preflight。旧版 generating 非零时门禁失败，先按下文处置。
2. 排空旧 SSE 请求并停止旧执行进程。维护人员明确旧报告 ID 范围后，条件更新无 job 的 generating 为 failed，error_stage/error_message 记为 worker_interrupted；记录 ID、数量和处置时间。不得自动重新生成。
3. 用部署环境的 Alembic 升级 head（0024），不允许 stamp 跳过迁移。运行既有正式标准来源、manifest 和参考窗口门禁。
4. 发布新后端/前端，保持 ACCEPTING=False，设置 ENABLED=True。启动 worker 和独立 sweep timer。
5. 在隔离环境完成真实数据库、双病种浏览器、PDF、强杀进程、超时、取消竞争验收；生产只执行获准的发布检查。
6. 确认 `systemctl is-active surgery-report-worker`，再运行 `python scripts/check_operator_report_generation_readonly.py --phase postflight --worker-ready`。该参数是监督检查的明确断言，不是自动推断。脚本显式 READ ONLY，输出计数和错误代码，不修改任务或打印数据库地址、原始输入。
7. postflight PASS 后开启 ACCEPTING=True 并重启读取配置的 HTTP 服务。旧 SSE 兼容开关初期保持开启；确认旧入口调用量为 0、前端更新完成后，关闭 `REPORT_LEGACY_SSE_ENABLED`，旧入口返回 410。

preflight 允许结构尚未迁移但仍输出 schema_ready=False；任何遗留任务、完整性错误均应先处置。postflight 要求完整结构、标准和参考版本可用、无过期任务或终态不一致、worker ready，且受理尚未开放。

## 故障处理与监测

- 监测 queued/running/expired、最长队龄、阶段耗时、失败原因、worker readiness 和整个服务组 RSS；日志只记 report_id、batch_id、阶段、安全原因代码与耗时。
- 断线只恢复观察；取消必须调用明确 cancel 接口。取消与完成竞争由数据库事务决定唯一终态。
- worker 失联后等待租约与独立 sweep 收敛；重启 worker 继续领取 queued，已失效的 running 不重算。
- 发布提交响应不确定时读取数据库事实，不覆盖 completed、不自动重试推理；幂等请求重试仍指向同一报告。
- 正在生成的报告禁止删除；终态删除保留幂等墓碑。重复原 key 返回资源已删除，需新 key 才能创建新报告。
- 哈希校验失败时屏蔽正文、图表与下载，不能用当前模型重新生成历史内容掩盖损坏。

Nginx 为 `/api/v1/operator/reports/<id>/events` 单独关闭代理 buffering，设置略高于 SSE 连接周期的 read timeout（例如 300s）；普通接口保持有界超时。不要给全部 HTTP 请求无限时限。

## 回滚

先关闭 ACCEPTING，取消或排空任务，再停 worker。保留新列、任务、报告和幂等记录。应用只能回滚到理解 v2 指纹与 report_document 的兼容版本；更早版本必须阻断新报告读取/下载并显示升级提示。禁止删除新列或批量把 completed 改成其他状态。0024 downgrade 遇到报告幂等记录会拒绝执行，防止静默丢失历史；生产应用回滚不执行破坏性 schema downgrade。

## 本机隔离验收

`scripts/run_operator_case_e2e.ps1` 接受显式的本机 `_test` 数据库；未传入时使用独立 Docker 测试库。流程为迁移、测试种子、启动真实 operator API/worker/Vite、两用户浏览器验收，并在 finally 停止本次启动的进程、恢复环境。测试 HTTP host 位于 tests/e2e，只省略无关聊天向量预热，不替换报告 API、推理、标准或持久化实现。

测试种子只使用已批准的两份标准 fixture 与 manifest，全部病例为软件验收虚构数据。不得指向生产数据库。


### 本次参考窗口修正

真实数据库验收发现旧窗口缺少单位，无法通过逐指标可比性检查。参考比较专用投影已保留 unit / unit_state，模型输入特征计算保持原契约。配置身份新增 reference_history.units.v1，因此发布时必须用既有 `build_reference_case_windows.py --dataset ... --apply` 重建两病种参考窗口；保留旧窗口和旧报告，不覆写旧配置身份。测试种子的参考病例模拟登记来源契约，is_synthetic=False 只用于测试分支覆盖；所有内容仍是虚构的软件验收数据，不能导入业务库。

生成上下文还固定正式标准规则及来源绑定的完整哈希，worker 在同一只读可重复读事务中验证后读取，避免批准版本下的规则值或原文绑定被改动而未被发现。


## 第 7～9 项：保存历史与永久 PDF 原件（0025 / 0026）

历史入口为 `GET /api/v1/operator/report-history`，使用独立、至少 32 字节的 `REPORT_HISTORY_CURSOR_SECRET`。更换密钥会使旧分页游标失效，页面重新读取第一页即可。列表只读取保存记录的标量摘要，不连接当前病例；详情验证已保存快照、生成上下文及报告指纹。失败/取消只展示已确认输入与阶段审计，不能称为完成报告。

PDF 是独立的持久任务：`POST /reports/{id}/pdf-archive` 准备，`GET` 查询，失败且从未发布才允许 `POST /retry`。POST 必须携带 UUID `Idempotency-Key`。`GET /reports/{id}/download` 只交付首次成功发布的原件，不调用模型、标准查询或 PDF renderer。缺失/损坏只能从同 SHA、同长度、同页数的备份恢复。所有历史与 PDF 响应为 `private, no-store`。

归档默认关闭：`REPORT_PDF_ENABLED=false`、`REPORT_PDF_ACCEPTING=false`。开放前配置绝对私有目录 `REPORT_ARCHIVE_ROOT`，例如 `/var/lib/surgery-rag/report-archives`，属主 surgery、目录 0700 / 文件 0600（Windows 使用仅服务账号和管理员可访问的 ACL）。不得放在 uploads、Nginx alias、网站静态目录或符号链接/目录联接下。必须是支持同卷原子替换和持久化写入的本地文件系统；网络盘和对象存储不属于当前适配器合同。

### 固定渲染制品

使用官方 [Noto Sans CJK 字体](https://github.com/notofonts/noto-cjk/blob/main/Sans/README.md) 的 Simplified Chinese Regular OTF，并保留 [SIL OFL 许可](https://github.com/notofonts/noto-cjk/blob/main/Sans/LICENSE)。在与生产相同的 OS / Python / Playwright / Chromium 环境构建，不把 Windows manifest 复制给 Linux：

```bash
python scripts/build_report_pdf_renderer_manifest.py --font-dir /opt/surgery-rag/pdf-fonts --output-dir /opt/surgery-rag/pdf-renderers
```

font-dir 内必须有 `NotoSansCJKsc-Regular.otf`、`LICENSE`，以及官方 [Noto Sans Regular](https://github.com/notofonts/noto-fonts/blob/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf) 的 `NotoSans-Regular.ttf` 和另存为 `LICENSE-latin` 的 [OFL 许可](https://github.com/notofonts/noto-fonts/blob/main/LICENSE)。补充字体覆盖 `10⁹/L` 等单位的上标字符，不改写报告原文。脚本验证字体族、许可、实际源码、FontTools、Chromium executable 及版本；输出以 manifest SHA 命名的目录。将其中 manifest.json 绝对路径配置为 `REPORT_PDF_RENDERER_MANIFEST`。发布源码、Playwright、Chromium、FontTools、模板或字体变化必须重建 manifest；运行时不自动认可漂移。旧 ready 原件持续读取原字节。资源包不可由 Web 用户写入，保留每个已发布版本与许可。

渲染时从已验证字体按文档实际字符生成内嵌子集，使用互不重叠的 unicode-range，避免多页页眉/页脚重复载入完整 CJK 字体导致内存放大。缺字返回安全错误，不使用系统字体静默替代。字体版本和子集实现均纳入 renderer 身份。

### 三个独立进程职责

部署本仓库 `deploy/systemd/surgery-report-pdf-worker.service`、`surgery-report-pdf-sweep.service/.timer`、`surgery-report-file-cleanup.service/.timer`。worker 执行渲染，独立 sweep 每 15 秒处理过期任务，独立 cleanup 每 15 秒处理一个到期文件补偿；worker 停机时两个 timer 仍运行。全部使用 `KillMode=control-group`、`TimeoutStopSec=15`、`UMask=0077`。PDF 候选必须位于专用持久目录，不依赖服务私有 /tmp。Windows 监督使用 Job Object 管理 Chromium 整棵进程树。

初始并发 1、全局排队 20、每用户活跃 2；排队 600 秒、总执行 120 秒、租约 45 秒、心跳 10 秒；上限 64 MiB、200 页。失败/失租显式重试产生新 attempt，running 不自动重渲染。队列与租约都由数据库时间决定，任务消息不能延长总期限。监测 queued/running、最老队龄、失租/超时、安全错误码、原件 missing/corrupt、cleanup 超一小时积压、磁盘余量和三个服务状态。无任务时不以“无心跳”判断 worker 不健康。

### 删除与恢复

删除病例保留历史报告和 PDF；删除报告先提交数据库删除并登记持久 outbox，再尝试一次有界在线清理。返回 204 表示在线文件已移除，202 表示“报告已删除，文件清理中”。两者之后报告均为 404。清理任务保留到执行期限后的最终复查，防止晚写；账号级联同样登记全部文件。不得手工删除 outbox、attempt 审计或 `report_deletion_tombstones`。

```bash
python scripts/manage_report_pdf_archives.py inspect --report-id 17
python scripts/manage_report_pdf_archives.py restore --report-id 17 --backup-file /private/backup/original.pdf
python scripts/manage_report_pdf_archives.py restore --report-id 17 --backup-file /private/backup/original.pdf --apply
python scripts/manage_report_pdf_archives.py cleanup --once
```

inspect 与 restore 无 --apply 默认只读。恢复命令先输出 report_id / hash 预检，精确匹配才落位；已删除报告、无 published identity、源内容校验失败一律拒绝。禁止调用 renderer 填补缺失原件。`cleanup --sweep` 为维护窗口连续补偿命令，只处理数据库登记的对象，不接受任意目录清空。

### 备份集合及删除事实重放

必须进入维护窗口：关闭新报告/PDF受理和所有删除入口，排空正在写文件的任务，暂停 cleanup；保持该窗口直到数据库、私有 PDF 目录、渲染制品、清理/删除事实的备份全部完成。不要只关闭 PDF_ACCEPTING 就宣称写入冻结。

```bash
python scripts/backup_report_archive_inventory.py inventory --snapshot-id reviewed-backup-set-id --maintenance-window --output /private/backup/inventory.json
```

inventory 独占创建文件，记录 backup_id、人工备份集合标识、数据库 snapshot 诊断身份、全部原件 key / SHA / 长度 / 页数 / renderer hash、清理及删除事实。逐件读取验证，前后重查事实摘要和活跃写任务；任何变化导致该备份集失败，需要重新备份。inventory 中的 pg_current_snapshot 不是可供 pg_dump 使用的 exported snapshot；外部 pg_dump 必须在同一持续维护窗口内执行。备份完成后继续维护窗口运行只读文件门禁，再恢复服务。

删除事实需要独立增量备份，覆盖每次删除；不能随着 PDF 清理成功一起删除。恢复旧 DB / 文件后保持所有业务访问关闭，先用较新的 inventory 删除日志进行 dry-run，再在明确命名的目标连接环境变量上 apply：

```bash
python scripts/backup_report_archive_inventory.py replay-deletions --inventory /private/backup/newer-inventory.json --target-env RESTORE_DATABASE_URL
python scripts/backup_report_archive_inventory.py replay-deletions --inventory /private/backup/newer-inventory.json --target-env RESTORE_DATABASE_URL --apply
```

独立删除日志可用 `python scripts/backup_report_archive_inventory.py export-deletions --output /private/backup/deletions-unique-id.json` 导出。该命令只读数据库，不依赖 PDF 文件或字体可用性，输出可直接作为 replay-deletions 的 inventory 输入；应由备份任务在每次删除后持久复制到独立备份位置。

重放报告删除会触发原生 outbox，包含没有 PDF 的报告。日志缺失或无法证明覆盖所选恢复时间点时，不开放下载。RPO、RTO、备份保留天数、删除日志增量间隔、负责人和恢复演练日期由部署记录填写，不能用本机测试值替代。

### 发布与回滚门禁

1. 备份和只读 preflight，关闭新受理、排空旧 worker；审核实际 Alembic head 后升级至 0026。
2. 部署兼容前后端、私有目录和目标 OS 构建的 renderer；启动 PDF worker、独立 sweep 和 cleanup。
3. 执行下列 postflight（--worker-ready 只能在运维实际确认服务健康后传入），完成恢复演练和目标 Linux 容量验收，再开放 PDF_ACCEPTING。

```bash
python scripts/check_operator_report_archives_readonly.py --phase preflight --verify-files
python scripts/check_operator_report_archives_readonly.py --phase postflight --verify-files --worker-ready
```

检查器只读，不标记健康状态、不清理、不自动修复。检查 schema、来源指纹、原件身份、交付计数、过期任务、审计数量、cleanup 积压、原件 SHA、未登记文件和 renderer 漂移。发现损坏先恢复，不通过重新生成历史绕过。

在真实 Linux 4 GiB 主机联合加载 PostgreSQL / Web / RAG / BGE / 模型 worker / PDF worker，以十次访视、全指标和长表压力样例采集整个服务组峰值 RSS、p95、swap/OOM。并发 1 不构成容量保证；实测后配置 systemd MemoryHigh / MemoryMax，超预算先串行重任务或扩容再验收。Windows 的本机内存采样仅记录参考，本次不宣称生产容量通过。

回滚先关闭受理、排空未发布尝试，保留新增表、原件、交付、审计、删除日志和清理服务。只回退支持归档协议的兼容应用；不得恢复同步渲染下载。0025/0026 downgrade 对已有事实拒绝破坏性回退。

本机验收需设置 `TEST_DATABASE_URL`（明确本机 _test）和 `REPORT_TEST_RENDERER_MANIFEST`，运行 `scripts/run_operator_case_e2e.ps1`。PDF 验证产物区分 archived_original 与 synthetic_layout_only，后者只测试排版，不写入业务原件。
