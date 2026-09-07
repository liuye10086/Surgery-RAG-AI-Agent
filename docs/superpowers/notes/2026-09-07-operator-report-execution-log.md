# 第 6 项执行与验收记录

用户批准：本会话逐项执行，全部完成后统一提交。基线 `6f535e5`；隔离分支 `codex/operator-complete-report`；工作区 `.worktrees/r6`。本记录描述仓库交付和本机隔离验收，生产部署单独执行。

## 逐项结果

| 任务 | 仓库状态 | 实现与验证证据 |
|---|---|---|
| P0 隔离及基线 | 完成 | 隔离 worktree、保留批准设计和计划；初始专项后端 59、前端 19；不读取生产 .env |
| A1 文档契约 | 完成 | ReportDocument/InputAudit/ModelRunAudit/Context/Publication 严格 schema；schema 与 TypeScript 生成一致性 |
| A2 输入审计 | 完成 | 实际 DataFrame 输入边界、列序及哈希、零值/缺失/无效、调用与结果分别统计；真实模型和异常测试 |
| B1 固定上下文 | 完成 | metadata-only 准入、固定 release/catalog/standard/reference；标准规则哈希和只读可重复读；快照修改与规则篡改真库验证 |
| A4 确定性正文 | 完成 | 保存 DTO 转 Markdown、转义与统一显示；零值/False、中文原因、共享输入列附录 |
| A3 完整文档 | 完成 | 11 章、全部访视和上下文、条件解释、模型限制、人工复核与完整参考投影；两病种/部分模型失败语义测试 |
| A5 保存及指纹 | 完成 | 0023、发布工厂、v2 指纹、文档/来源完整性；未知版本和篡改拒绝；旧报告兼容 |
| B2 持久任务 | 完成 | 0024、单活动病例/全局并发、数据库时钟/租约/token、原子终态；竞争领取、锁等待失租、提交失败及提交响应丢失 |
| B3 准入取消 | 完成 | scoped key、相同请求重放、冲突与配额、快照固定、活动报告删除保护、取消竞争与幂等墓碑 |
| B4 独立 worker | 完成 | spawn、8 MiB JSON IPC、Windows Job、Linux 服务监督、阶段及总期限、阻塞心跳独立 watchdog；真实进程强杀/超时/失租/畸形消息 |
| B5 API 事件 | 完成 | 202/状态 GET/只读 SSE/cancel，用户归属与鉴权、旧入口适配、断流不取消；API/传输专项和真库验证 |
| A6 网页 PDF | 完成 | 保存文档渲染、真实日期图、invalid 遮蔽、旧报告兼容；前端语义测试、真实浏览器下载及 PDF 逐页核查 |
| B6 前端生命周期 | 完成 | epoch/revision/batch、刷新恢复、幂等重试、2/5/10 退避、Retry-After、详情加载空档、鉴权清理；Vitest 与浏览器 |
| B7 集成及运维 | 完成（仓库） | 独立 _test harness、pre/postflight、worker/sweep systemd、容量初始预算与采样、保留数据回滚演练；目标主机容量待部署 |
| P1 总验收 | 完成 | 下列最终回归、文档核查、diff 检查；统一一次本地提交 |

## 最终运行证据

测试依赖采用本机 Python 3.11、现有项目 Node 依赖、PostgreSQL 18 + pgvector。独立数据库仅监听回环测试端口，库名以 `_test` 结尾；未连接业务数据库。Docker Desktop 引擎不可用后改用独立本机 PostgreSQL cluster。所有病例为虚构软件测试数据；真实 operator API、模型加载、标准服务、参考查询、持久 worker 和浏览器均未用 mock 替代。测试 HTTP host 只省略无关聊天/RAG 预热。

| 工作目录与命令 | 最终结果 |
|---|---|
| 根：`python -m pytest backend/tests --ignore=backend/tests/integration --ignore=backend/tests/e2e -q --tb=short` | 1081 passed，5 subtests，6 warnings；32.70 秒 |
| 根：显式 TEST_DATABASE_URL 后 `python -m pytest backend/tests/integration -q --tb=short` | 27 passed，3 warnings；34.95 秒，关键集成无 skip |
| 根：`scripts/run_operator_case_e2e.ps1 -TestDatabaseUrl <独立本机_test连接>` | 10 passed；55.81 秒，无 skip；finally 清理本次 API/worker/Vite 进程 |
| frontend：`npm run test:unit` | 52 passed / 12 files |
| frontend：`node --test tests/longitudinal-report-ui-contract.test.mjs` | 9 passed |
| frontend：`npm run build` | vue-tsc 与 Vite 构建通过 |
| 根：`python -m pytest scripts/tests/test_check_operator_report_generation_readonly.py -q` | 3 passed |
| 根：对比 `scripts.generate_report_document_types.generate()` 与生成文件 | 完全一致 |
| 根：Ruff 新增/修改 Python 的 F821/F823 检查，`git diff --check` | 通过 |

已保留的非阻断提示：Pydantic class Config 与 FastAPI on_event 弃用提示；篡改测试故意将 UUID 改为字符串引起序列化提示；Vite 既有依赖 PURE 注释和大 chunk 提示。没有用 skip 掩盖新报告关键测试。

浏览器覆盖：双病种页面生成→刷新→保存详情→下载 PDF→返回历史；每病种 10 次随访、所有目录指标；跨用户 404；相同 key 重放与显式取消；杀 worker 后租约到期、独立 sweep 收敛 failed、重启继续 queued。独立进程专项另覆盖父 worker 强杀后子进程退出、期限终止、重复阶段不能续期、心跳阻塞仍终止子进程、失租和超限 JSON。

真实库演练：在存在报告幂等记录的隔离库执行 `alembic downgrade 0023`，预期 CheckViolation 拒绝；前后报告 ID/状态/指纹、任务数量、幂等记录数量与 Alembic 0024 均不变。实际启动专用 worker、关闭受理后执行只读 preflight/postflight，均 PASS：无过期任务、无 legacy generating、无终态/上下文/输入/文档完整性错误，schema 与标准/参考窗口就绪。

## PDF 与浏览器证据

实际生成命令：`python scripts/verify_operator_report_pdf.py`，只允许读取显式本机 `_test` 数据库。产物位于 `outputs/operator-report-verification/`，体积较大且为运行产物，不进入 Git。

- `fatty_liver-report.png`、`ad-report.png`：真实报告页面截图。
- `fatty_liver-browser.pdf`、`ad-browser.pdf`：通过页面下载的已保存报告。
- `pdf/`：双病种普通报告、长上下文、10×30 展示压力、旧版兼容、部分模型失败；各 PDF 逐页 PNG 与 contact sheet。
- 检查中文字体、连续表格重复表头、跨页原文、日期比例、页眉页脚与横纵文本边界。普通前三章与技术附录分开组织；重复派生缺失提示归并为原指标问题，相同输入列序共享附录，原始审计信息仍完整保存。

最终 PDF 页数与采样值见本记录末尾；截图是虚构软件验收数据，不能用作医学结论。

## 审查发现及处置

1. Windows Git core.autocrlf 会损坏部分发布 JSON 的字节哈希。核对 34 个 metadata/evaluation 文件，差异仅 CRLF/LF，恢复原始发布字节；所有模型参数和声明 SHA 保持。`.gitattributes` 对不可变模型/数据/标准身份禁用文本转换，CRLF 不作为空白错误。
2. 真实参考查询暴露原窗口投影缺 unit/unit_state。新增参考专用投影与配置身份 `reference_history.units.v1`，未改变模型数值特征；部署时必须重建参考窗口，保留旧身份。
3. 补齐标准规则及来源绑定哈希，锁等待后重新检查租约，数据库语句/锁/连接/池等待有界；独立 watchdog 防止心跳连接阻塞使执行进程超期。
4. 受理响应丢失沿用 key；发布提交响应丢失读取数据库事实；数据库 CAS 不接受时不发送虚假 completed。详情加载失败只重读，不再生成。
5. 前端 429 重试必须遵守 Retry-After，focus 不得绕过；回归测试先证实旧逻辑提前请求，再验证修复。
6. 畸形保存数据返回 invalid 而非异常；新旧指纹、来源投影和 PDF 下载保持失败关闭。
7. 清理测试以前要求未追踪的 .env/运行资产；改为验证受版本管理的契约。输入校验单元测试移除无关启动预热；旧生成入口测试改为验证其委托持久服务。测试行为变更均对应新接口或原测试环境缺陷。

本会话按用户要求逐项执行与自审，没有创建额外任务或并行代理。审查依据为已批准设计、三个计划、实际变更和上述运行证据。

## 生产仍需单独验收

仓库完成不等于已上线。生产备份与迁移、明确范围的 legacy generating 处置、标准/参考版本门禁、窗口重建、systemd/Nginx 安装、Linux 4 GiB 主机全服务 RSS/容量和线上双病种冒烟，按 `docs/OPERATOR_REPORT_OPERATIONS.md` 执行。本机 Windows 采样包含测试 API/PDF 浏览器树，不能代表部署 RAG/BGE/PostgreSQL 的总内存。当前活动模型合成训练与未校准/无临床有效性声明不变；临床验证属于后续模型发布审计。

## 最终产物确认

| PDF | 页数 | 全页视觉与边界检查 |
|---|---:|---|
| fatty_liver | 37 | 全页通过 |
| ad | 29 | 全页通过 |
| long-context | 38 | 全页通过 |
| table-pressure | 55 | 全页通过 |
| legacy | 37 | 全页通过 |
| partial-model | 13 | 全页通过 |

实际窗口资源采样：测试 API 及其子进程峰值 1062.8 MiB；worker 执行树 398.0 MiB；Vite 187.8 MiB。采样不含整个部署服务组，不作为生产容量承诺。

最新 worker 专用连接版本再次启动后，preflight/postflight 均 PASS；安全计数保存在本机 `outputs/operator-report-verification/gates.json`。
