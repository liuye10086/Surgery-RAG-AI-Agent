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
