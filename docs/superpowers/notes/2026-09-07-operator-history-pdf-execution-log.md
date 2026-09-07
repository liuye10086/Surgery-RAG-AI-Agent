# 第 7～9 项逐项实施记录

用户授权：直接在 main 分支、本会话逐项执行。保留已有设计与计划；未创建工作树或子代理，未提交、推送或部署。

代码基线：`main / 7a2e3e7`；迁移从 `0024` 扩展到 `0026`。生产数据库未连接、未读取或修改。以下“完成”指仓库交付与本机隔离验证，生产上线条件单列。

## 逐项交付

| 任务 | 状态 | 实际交付与验证 |
|---|---|---|
| P0 基线 | 完成 | 前端 52 项单元及 9 项 UI 契约通过；后端初跑 1080 通过、1 项文档清单失败，加入批准设计后复验通过 |
| A1 保存身份/读取 | 完成 | 新保存身份、严格读取 DTO、先校验后投影；v1/v2、畸形 JSON/NaN、失败快照、context hash、权限/no-store、病例删除后身份 |
| A2 审计 schema | 完成 | 0025、不可修改审计、256 事件/单项 256 KiB/总 8 MiB 硬上界、终态预留；真库回滚与级联 |
| A3 实际任务审计 | 完成 | 准备/调用/完成事件、IPC 有界及去重、last/failure phase、父监督和期限；未确认步骤不补写 |
| A4 历史查询 | 完成 | 所有者/筛选绑定 HMAC 游标、轻量 SQL、稳定排序及索引；10000 条完整分页、并发变化和 EXPLAIN |
| A5 历史工作区 | 完成 | 独立导航、筛选/滚动保留、账号与请求隔离、全终态保存详情、旧版完整快照；全文遵循 DESIGN_SPEC |
| B1 PDF 数据合同 | 完成 | 0026：archive、attempt、delivery、cleanup、删除墓碑；发布身份与终态尝试不可修改；级联触发器与 schema 一致 |
| B2 受理/查询 | 完成 | 固定 source/renderer、幂等重放、全局/用户配额、关闭受理后的已存在请求重放、安全 API |
| B3 存储/worker | 完成 | 私有目录、防越界/目录联接、原子候选不覆盖、固定字体/浏览器、独立监督渲染及发布、租约/期限/sweep |
| B4 原件交付 | 完成 | 同句柄校验后交付、服务器交付计数、20 连接并发及提交响应丢失、删除竞争；不更新原报告时间或指纹 |
| B5 删除/恢复 | 完成 | 事务 outbox、一次有界在线清理、延迟最终复查、账号级联、精确同 SHA 恢复、只读预览/显式 apply CLI |
| B6 PDF 前端 | 完成 | 准备/查询/重试/下载分离、刷新只 GET、幂等 key 持续、账号切换中止、Retry-After、结构化错误和 202 清理反馈 |
| C1 真库一致性 | 完成 | 独立 session 竞争、过期拒绝发布、已授权流与删除、删除后晚写最终清理、提交响应丢失、迁移和恢复 |
| C2 浏览器/PDF | 完成 | 两病种真实 API/模型 worker/PDF worker/清理/Vite；12 项浏览器流程、8 组共 375 页 PDF |
| C3 运维交付 | 完成 | 只读门禁、systemd 三职责、备份清单、删除事实单独导出与重放、真实 pg_dump/restore 演练；生产实测待上线窗口 |
| P1 交付复核 | 完成 | 最终回归、代码和文档核对；保留 main 未提交改动，明确生产边界 |

## 最终验证证据

命令从仓库根目录执行，前端命令在 frontend 执行。真库相关命令必须显式设置本机、数据库名以 `_test` 结尾的 `TEST_DATABASE_URL`，并指定已构建的 `REPORT_TEST_RENDERER_MANIFEST`；harness 不接受生产连接。

| 检查 | 最终结果 | 本地证据（outputs 下不提交） |
|---|---|---|
| `python -m pytest backend/tests --ignore=backend/tests/integration --ignore=backend/tests/e2e -q --tb=short` | 1135 passed，5 subtests passed | `outputs/operator-history-pdf/final-backend.log` |
| `python -m pytest backend/tests/integration -q --tb=short` | 57 passed，0 skipped；98.54 秒 | `outputs/operator-history-pdf/final-integration.log` |
| `npm run test:unit` | 69 passed，17 个测试文件 | `outputs/operator-history-pdf/final-frontend.log` |
| `node --test tests/longitudinal-report-ui-contract.test.mjs` | 9 passed，0 skipped | `outputs/operator-history-pdf/final-ui-contract.log` |
| `npm run build`（含 vue-tsc） | exit 0 | `outputs/operator-history-pdf/final-build.log` |
| 本次 5 组 scripts/tests 专项 | 16 passed | `outputs/operator-history-pdf/final-scripts.log` |
| `python scripts/run_operator_report_e2e.py` | exit 0；12 passed / 84.21 秒，随后全部 PDF 验证通过 | `outputs/operator-history-pdf/final-e2e.log` |
| 归档只读 `preflight --verify-files` | PASS，schema/renderer/storage ready；缺失/损坏/孤儿/来源/计数/审计/积压错误均为 0 | `outputs/operator-history-pdf/final-readonly.json` |
| 10000 条、limit 20、500 页 | 精确遍历，p50 9.09 ms / p95 15.28 ms / max 22.71 ms，无大字段及 N+1 | `outputs/operator-history-pdf/history-benchmark.json` |
| schema.sql 空库安装 vs Alembic | 列与 CHECK 一致，空库上下迁移通过，有历史事实时拒绝 downgrade 并保留事实 | `outputs/operator-history-pdf/migration-verification.json` |
| PDF 自动及视觉检查 | 8 组、375 页，中文及补充字体嵌入、无文字越界、跨页表头及长文本完整 | `outputs/operator-history-pdf/pdf/verification.json`、`visual-review.json`、逐页 PNG/contact sheet |

脚本专项为 `test_backup_report_archive_inventory.py`、`test_benchmark_report_history.py`、`test_check_operator_report_archives_readonly.py`、`test_manage_report_pdf_archives.py`、`test_report_pdf_verification.py`。不以普通单元测试替代 PostgreSQL、Chromium 或浏览器验收。

备份演练使用独立生成并严格验证名称的 `_test` 数据库：真正 pg_dump、恢复 DB 和 PDF 文件、重放较新报告删除事实、触发清理并验证恢复文件消失。临时恢复库和空库迁移比较库均在 finally 删除；未向业务库执行 restore 或 DROP。

只读 preflight 在 E2E 结束、harness 已停止服务后执行，因此 worker_ready 如实为 false。真实 postflight 正反分支由真库测试覆盖；未将 `--worker-ready` 人工伪装成生产服务验收。

## PDF 与资源记录

最终本机 renderer SHA：`6b34c4ea82f3b9e178fb331eb35e7238ac450f04106eb7726797d58ac3b611e6`。这只对应当前 Windows 制品；目标 Linux 必须使用同代码与批准资源重新构建并记录自己的 SHA。

| 样例 | 来源类型 | 页数 |
|---|---|---|
| fatty_liver | synthetic_layout_only（普通病例已在删除验收中删除，使用保存文档展示变体） | 55 |
| ad | archived_original | 29 |
| fatty_liver-catalog-10 | archived_original | 55 |
| ad-catalog-10 | archived_original | 37 |
| long-context | synthetic_layout_only | 57 |
| table-pressure（10×30） | synthetic_layout_only | 74 |
| legacy | synthetic_layout_only | 55 |
| partial-model | synthetic_layout_only | 13 |

全部为虚构软件验收资料，不是临床病例或模型有效性证明。展示压力变体不写入业务原件表。逐页 contact sheet 已查看，另放大核查全指标第 7 页、长上下文第 2 页和长表第 3 页；最后重跑的相同 renderer 保持布局并再次通过自动检查。

完整 CJK 字体在多页页眉/页脚重复加载曾导致本机进程树高内存，改为基于文档实际字符的受控内嵌子集，并加入 Noto Sans 覆盖 CJK 字体缺少的 U+2079（上标 9）。保留原单位 `10⁹/L`，未删正文或表格。FontTools、子集实现、字体、许可和 Chromium 均进入 renderer 校验。

最终独立 E2E 采样：API 峰值 615.8 MiB、模型 worker 进程树 398.2 MiB、PDF worker 进程树 1012.4 MiB、cleanup 152.4 MiB、Vite 189.1 MiB。各峰值不是同一时刻，不能相加推断生产峰值；不包含数据库/BGE/RAG 全服务联合负载。memory.json 中旧兼容字段 worker_tree_peak_mib 为 0，不作为采样结果使用。

## 实施中的调整与复核

- 按用户指令在 main 顺序执行，覆盖原计划工作树建议；未自动执行建议 Git 提交。
- 实际服务采用 session 参数及短事务，调用方负责 factory/session 生命周期；原计划代码块是接口示意，实际 API、schema、测试和本记录是交付依据。
- PDF 发布的文件校验和数据库提交也放入独立受监督子进程，与渲染共享剩余总期限，避免文件 IO/DB 阻塞绕过期限。
- Windows 用 Job Object 回收真实 Chromium 子孙；Linux 增加父死亡信号、启动前父 PID 复核和进程组守护，目标 Linux 实测仍属部署验收。
- 追加数据库约束保护尝试身份及终态；发布字段不可变规则不妨碍 missing/corrupt 的健康恢复。
- 删除事务已提交后，清理查询不可用返回 pending，保留成功删除的事实；对应测试先复现失败再修复通过。
- PDF 页数/字节配置允许收紧并实际执行，超限整体失败、不截断；新增边界测试通过。
- 审阅了保存来源隔离、锁顺序、lease fencing、幂等、提交不确定、同句柄交付、删除/恢复、字体资源和日志字段；没有调用模型补造旧资料。
- C2 使用真实浏览器验证主生命周期；账号切换/401/429/请求乱序等分支由前端单元与组件测试覆盖，并非每种故障都以浏览器断网方式重复。
- 原计划各个红灯步骤未全部单独留存日志，因此未追补声称逐条红灯过程；任务完成依据为实现、实际测试与产物。强杀 Chromium 与租约/文件/发布边界分别验证，不冒称已在生产逐点强杀。

## 已知环境限制与生产前置条件

旧资料生成脚本的宽范围回归曾得到 223 passed、30 skipped、30 errors；错误来自本机缺少外部 DOCX 夹具。未生成替代标准资料、未修改这些测试绕过。当前本次脚本专项通过，这不等于整个 scripts/tests 全绿。后端保留既有 Pydantic/FastAPI 弃用警告；前端构建保留现有较大 bundle 提示。

生产仍需在获准维护窗口执行 [报告运维手册](../../OPERATOR_REPORT_OPERATIONS.md)：

1. 备份一致的 DB、PDF、renderer、清理/删除事实；关闭受理及删除入口、排空写任务，备份窗口持续到整个集合完成。
2. preflight，升级 Alembic 至 0026，部署兼容前后端，配置至少 32 字节独立游标密钥、私有目录权限和目标 OS renderer 制品。
3. 启动 PDF worker、独立 sweep 和 cleanup，确认监督状态再执行 postflight；完成缺失原件同 SHA 恢复和较新删除日志重放演练。
4. 在目标 Linux 4 GiB 主机联合加载 PostgreSQL/Web/RAG/BGE/模型/PDF 服务，实测 RSS、p95、swap/OOM，再确定 systemd 内存预算、必要的重任务串行或扩容。
5. 部署记录明确 RPO、RTO、保留天数、删除日志备份间隔和负责人；门禁通过后开放 PDF 受理。

当前 PDF 开关默认关闭，未对运行中的业务服务开启功能。已授权的仓库实现和本机隔离验证完成，生产上线尚未执行。

最终静态检查：131 个新增/修改文件、86 个 Python 文件 AST 解析，UTF-8、本地文档链接及运行制品隔离检查通过，`git diff --check` 通过；两份旧部署文档原有 Markdown 行尾空格保持原样。本次独立端口 55439 的 PostgreSQL 测试集群已正常停止，数据目录与 ignored outputs 验收产物保留；E2E 自建 API、模型/PDF worker、清理和 Vite 进程已由 harness 收尾。
