# 合成历史候选接入（阶段四）实施与总验收记录

日期：2026-09-18（S1–S5 于 2026-09-16 完成）。范围：阶段四 S1–S6，继续合成先行，未接入真实资料。

## 结论口径

阶段四六步全部执行完毕，**实施 6／6**。S6 的隔离端到端验收实际调用真实 API、独立 worker、真实参考检索、真实 DeepSeek 与真实 Chromium 归档，最终一轮（`2026-09-18-v4`）`result.json` 为 `status=passed`、退出码 0。全部结果仍为 `is_synthetic=true`、`clinical_validity_claim=false`、`clinical_status=not_assessable`、`production_enabled=false`；**这不是临床有效性结论，也不授权业务库迁移、模型发布或部署**。

活动配置未改变：`NUMERIC_MODEL_BUNDLE` 仍指向旧 B 包，C 包只在验收进程内临时选择。旧 v1/v2 数值模块、旧 prompt、既有页面／PDF 工作和 `docker-compose.test.yml` 删除状态全部保留。

## 本步范围的实现

S6 新增：

- `scripts/run_numeric_history_acceptance.py`：默认只读预检；拒绝非精确 `surgery_rag_phase4_test`、URL 查询参数／fragment、libpq 重定向变量、已存在输出与占用端口；无 `--apply` 不连库、不启动服务、不写入。
- `scripts/numeric_history_acceptance_browser.py`：真实页面与归档场景。
- `scripts/tests/test_run_numeric_history_acceptance.py`：**51 项**。

S6 期间补齐的能力（均由本轮实际失败或独立复审暴露）：

- **浏览器失败诊断**：`run_scenarios` 失败时保存截图、页面 body 文本、page error 类型、错误位置与**已脱敏 URL**（去掉用户名／密码、查询串与 fragment），写入 `result.checks.browser_failure` 与 `browser-failure.json`；诊断本身失败只记录阶段与异常类型。此前失败只留下一个异常类型，无法定位。
- **条件等待替代隐式超时**：`open_case`／`open_history` 原以 `goto` 后直接 click、依赖 Playwright 默认 30 秒隐式超时。现由 `shell_locator()` + `wait_for_shell()` 显式等待**侧边栏导航按钮**再交互。
- 独立复审后的三项加固：`browser.close()` 异常不再顶替原始失败（记为 `checks.browser_close_errors`）；`safe_page_url()` 在解析失败分支同样剥离 userinfo 并正确处理 IPv6 与端口 0；新增 9 项回归（就绪定位器、URL 脱敏参数化、teardown 不顶替失败）。

## 实际验证

### 只读预检与 dry-run

dry-run 退出 0，报告 `database_connected=false`、`services_started=false`；无库、无服务、无 LLM。runner 测试 **51 passed**，含先前 3 项 RED（浏览器失败诊断）。

### 专用数据库集成（S6 第 3 项）

四个集成模块对专用 PostgreSQL `surgery_rag_phase4_test` 实际执行 **49 passed**，`external_llm=false`：0031 约束与 downgrade 保护、v3 双捕获与并发幂等、发布围栏（cancel／lease／deadline）、保存事实读取、Chromium 归档。其中 v3 worker 使用受控说明适配器、v3 PDF 由手工 publication 构造，**不代表真实外部链路**。

### 真实端到端验收（S6 第 4 项）

最终一轮命令（`.tmp/phase4-s6-apply-v4`，退出码 0，耗时 296.84 秒）：

```powershell
.\backend\.venv\Scripts\python.exe scripts/run_numeric_history_acceptance.py --source-dir outputs/synthetic-prediction-cases/2026-09-15-switch-v2 --legacy-bundle outputs/numeric-acceptance/2026-09-15/model-v2/bundle.json --history-bundle outputs/numeric-history-integration/2026-09-16-v1/bundle.json --renderer $env:REPORT_TEST_RENDERER_MANIFEST --output outputs/numeric-history-acceptance/2026-09-18-v4 --apply --allow-external-llm
```

5 份报告全部完成，对应 5 次真实说明生成：

| 报告 | 版本／场景 | 页数 | 检索条数 | 审计调用 | 归档原件与下载字节一致 |
| --- | --- | ---: | ---: | --- | --- |
| 8 | B／脂肪肝 | 2 | 7 | 1／1 | 是 |
| 9 | B／AD | 2 | 7 | 1／1 | 是 |
| 10 | C／AD | 3 | 7 | 1／1 | 是 |
| 11 | C／脂肪肝 | 2 | 7 | 1／1 | 是 |
| 12 | C／AD（无历史） | 2 | 7 | 1／1 | 是 |

- `external_llm`：`planned_reports=5`、`worker_invocations=5`、`completed_reports=5`、`audited_invocations=5`；每份报告持久审计中 `report_narrative` 恰好 1 次 `invocation_started` 与 1 次 `task_finished`（`result_state=available`）。该计数是**持久审计观察到的调用数**，不是独立监听供应商 HTTP 的计数；说明实现为 `max_retries=0`。
- PDF 摘要（下载即归档原件，SHA-256）：报告 8 `dfdb3b42…`、9 `6446f267…`、10 `b3476ba1…`、11 `36399f8b…`、12 `8f880993…`。5 份 `archive/reports/<id>/<uuid>/document.pdf` 与下载字节逐一相等。
- 版本切换：`checks.queued_v2_completed_with_c_selected=true`。B 下排队的旧 AD 任务在切换到 C 后仍以保存的 B 包完成 v5，并断言 `prompt_version=numeric_narrative.prompt.v1`、两条任务均为共享 Ridge 身份、`feature_names=['anchor_value']`。
- 取消：`checks.cancelled_report_id=13`，排队任务取消后状态为 `cancelled`，未调用 worker 或 LLM。
- 权限：5 份报告均验证非所有者详情／下载 404、doctor 详情／下载 403，幂等重放返回原报告。
- 旧历史保全：恢复 B 与选择不存在的当前包两阶段，保存事实（含 `sources`、`retrieval_meta`、`evidence_snapshot_sha256`、`report_document_sha256`、`generation_context`、`generation_audit`）与 PDF 原字节均不变。
- `checks.page_errors=[]`。

上一轮 `2026-09-18-v3` 在同一链路上先行通过（退出 0、357.44 秒）。`v4` 是独立复审三项加固之后的复跑，两者结论一致；记录以 `v4` 为准。

### 失败与修复过程（如实保留）

四次真实 apply，前两次失败均保留原产物，未覆盖、未原地修复：

- **v1（`2026-09-18-v1`，退出 1，42.42 秒）**：受理前浏览器点击超时，`worker_invocations=0`。API 日志仅有 `/health`、病例详情与 `/auth/me`——前端在 `/auth/me` 之后未挂载 OperatorView，点击依赖的隐式 30 秒超时耗尽。当时**没有留下任何页面证据**，这直接促成了失败诊断实现。
- **v2（`2026-09-18-v2`，退出 1，123.98 秒，1 次真实 LLM 调用）**：报告 1 完成，`open_history` 失败。新增诊断给出根因：首次 `wait_for_shell` 误用「病例列表 region」作为就绪条件，而报告完成后应用停在**报告详情**面板，该 region 不存在（诊断 body 文本同时含侧边栏导航与报告正文，可证）。改为等待侧边栏导航按钮后，用已完成报告单独复现（无 LLM、无 worker）确认 `shell_wait=ok`、`history_row` 可见、`.numeric-report` 可见、结果表 2 行且值为保存值（ALT 6 月 22.57／基线 22.80；12 月 20.00／基线 22.80）、`open_case=ok`、无页面错误。
- **v3／v4**：通过。

v1/v2 的失败产物、`api.log`、`frontend.log` 与 v2 的 `browser_failure` 诊断均保留在各自输出目录，未删除或改写。

### 独立复审与处理

对 runner、浏览器驱动与测试做只读独立复审，结论为无阻断项、**未削弱任何断言**（比对确认新 runner 相对旧 runner 只增不删，旧 runner／旧浏览器驱动源码未改动）。采纳三项加固（见上）；两项非阻断记录：`validate_prediction` 只在“存在两条可用基线 + 页面显示与 API 一致”层面断言，未在真实链路重算末次值独立性（该性质由无历史用例与单元层证据支持，本记录不作更强声明）；`body_text` 是诊断中唯一未结构化过滤的通道，已确认当前页面不会渲染令牌或原始异常文本。

### 回归

- 前端：`npm run test:unit` **23 个文件 / 168 项通过**；`npm run test:contracts` **30 通过、0 跳过**；`npm run build` 通过（1751 模块）。
- 后端非 integration／e2e 回归（`pytest tests ../scripts/tests --ignore=tests/integration --ignore=tests/e2e -q -rs`，从 backend 运行）：**2 failed、2290 passed、59 skipped、24 subtests passed，1137.68 秒**。2 项失败即下节列出的阶段二／三既有失败；跳过项为需显式提供原始资料或依赖符号链接的用例，与原口径一致。

## 已知失败（本步之前即存在）

后端非 integration 回归现存 **2 项**失败（修复 Playwright 污染后由 5 项降为 2 项），均可追溯到阶段二／三提交，**不是 S6 引入**：

- `tests/test_schema_contracts.py::test_clean_install_schema_contains_all_orm_business_columns`：ORM 已有 `operator_cases.engineering_source`（提交 `2650d27` 引入），而 `database/schema.sql` 未同步；工作区未修改该 SQL 文件。
- `tests/test_cleanup_contracts.py::test_only_current_cleanup_specs_remain`：`docs/superpowers/specs/` 新增的阶段一至四设计文档未登记进该测试的允许清单。

两项均属阶段二／三范围的遗漏，未在本步修改以免混入无关工作；需另行决定是否补齐。

（本轮另有一项**已修复**：`scripts/tests` 中依赖 Playwright 的两个用例在整仓回归里因 `backend/tests/test_pdf_generation.py` 向 `sys.modules` 安装 mock 后再 `pop`、使 `playwright` 包处于半导入状态而失败（`module 'playwright' has no attribute '_impl'`）。单文件运行时不复现。已改为在测试内先丢弃整个 `playwright.*` 层级再重新导入，模拟污染下 52 项通过。）

## 验收矩阵（S6 第 5 项）

| 场景 | 实际层级与证据 | 结果 |
| --- | --- | --- |
| AD／ALT 成功 | runner v4 真实 API／worker／RAG／DeepSeek／页面／PDF；C／AD 为 12 月 RF、6 月 Ridge，v6 完整发布且页面与 PDF 一致 | 通过（真实链路） |
| 历史不足 | runner v4 `c/ad_partial`：AD 12 月 `abstain`／`history_not_observed`，6 月与两条基线正常，页面与 PDF 均显示原因且披露模型未执行 | 通过（真实链路） |
| 计算 error／有限越界 | 纯推理与 stub worker 单测：单任务无有效值、有限 raw 仅审计、不裁剪不 fallback、另一时距与基线保留、LLM 与打印不泄露 raw | 通过（单元／stub，未在真实链路注入） |
| 损坏／缺 task／未知算法 | 严格 schema／loader 与 stub worker；`test_numeric_report_v3.py` 含显式未知 `model_id` mutation，断言受理／worker 在 publication 前失败且未调用检索 | 通过（单元／stub） |
| 排队后选择包改变 | runner v4 真实排队 + 切换 + 重放；旧 v2 以保存 prompt v1 与 Ridge 身份完成 | 通过（真实链路） |
| 保存参数篡改／runtime 或 prompt 漂移 | schema／stub worker 覆盖参数与 runtime、prompt、检索配置漂移；v6 篡改候选在 PG 事务内拒绝；旧 v2 排队漂移在调用前失败 | 通过（单元／PG 事务） |
| 检索双失败／LLM 失败／非法引用／数字 | 单元／stub：双失败、非法引用、禁止数字、LLM 失败均不发布；旧 v2 LLM 失败另有 PG 事务确认无 publication。runner v4 只覆盖**成功**链（两分支 complete 且有条目） | 成功链通过（真实）；故障为单元／stub |
| 幂等／取消／超时／租约 | runner v4 真实 HTTP 幂等重放 ×5 与真实排队取消；v6 cancel／lease／deadline 发布围栏为 PG 事务 | 通过（真实链路 + PG 事务） |
| 所有者／角色／病种 | runner v4 每份报告 404／403；病种权限由 PG admission 三类拒绝覆盖 | 通过（真实链路 + PG 事务） |
| 新旧历史／PDF | runner v4 恢复 B 与不存在当前包两阶段比较保存事实与 PDF 原字节；v3 另证当前包失效仍可下载原件 | 通过（真实链路） |
| 迁移及降级 | 专用库 fresh 升级至 0031、真实 v6 约束与 downgrade guard 通过；**既有 v5 行跨 upgrade 的保全未单独演练** | 部分：fresh upgrade + upgrade 后 v5 兼容 |

## 制品与记录

- 最终验收输出：`outputs/numeric-history-acceptance/2026-09-18-v4`（`result.json`、5 份 PDF、`archive/`、截图、queued／report JSON）；先行通过轮 `2026-09-18-v3`。
- 失败记录：`2026-09-18-v1`、`2026-09-18-v2`（含 `browser-failure.json` 与 `browser-failure.png`）。
- 冻结输入：来源 `3b333b09…`、B 包 `32b8069f…`、C 包 `a6816ed1…`、renderer `328b8668…`；本轮未修改任何冻结输入。
- 本机过程记录：`.tmp/phase4-s6-*`、`.tmp/diagnose-phase4-s6-*.py`。

`outputs/` 与 `.tmp/` 按仓库既有规则不入 Git；源码提交不会自动包含这些验收产物。
