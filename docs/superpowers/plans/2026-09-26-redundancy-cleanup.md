# 冗余清理执行记录

> 执行方式：并行处理互不重叠的前端、后端范围，再独立复核和整体验证。依据为本轮全仓审查及用户的清理授权。

**目标：** 删除已证实无调用的实现、重复类型依赖和失效临时记录，保持现有业务行为。

**范围与约束：** 保留当前报告全部版本、历史读取、归档原件、模型和数据制品、权限与审计。不修改冻结源码身份，不写业务数据库、不调用外部 LLM、不训练或发布模型。不提交或推送。

## 执行清单

- [x] 前端：删除全局图标注册、未触发的下载事件链、未用标准 API 封装与类型、未用 prop/CSS；通过 npm 删除重复的 `@types/dompurify` 依赖。保留图标库、净化和归档下载。
- [x] 后端：删除图片授权旧包装、两项未用 schema、两项旧 readiness 包装、两项未用训练函数及专属导入。
- [x] 脚本：删除 `check_model_artifacts.py` 中旧 `ArtifactValidation`、`validate_candidate_metadata` 及专属导入。
- [x] 文档：将临时来源完整性修复记录中的有效规则核对到现有代码及文档后，删除该临时记录。
- [x] 用户已确认旧参考范围同步模块及专属测试退役、三份失效计划直接删除并保留 Git 历史；均已执行。
- [x] 检查本地临时依赖副本是否仍使用，再提出具体清理范围；不整体删除 `.tmp`、`.superpowers`、`outputs`。
- [x] 独立复核删除边界、动态引用、冻结身份和权限路径，无需修复项。
- [x] 验证并记录实际结果；两项本地缓存删除已获用户确认，但工具策略仍阻止执行。

## 验证方式

先运行各改动对应的已有行为测试；纯删除不新增名称存在性测试。然后执行：

```powershell
# backend
.\.venv\Scripts\python.exe -m pytest tests ../scripts/tests --ignore=tests/integration --ignore=tests/e2e

# frontend
npm run test:unit
npm run test:contracts
npm run build
```

检查前端实际页面及图标、报告归档下载入口的适用状态；不对业务数据发起生成或删除。真实数据库/worker/归档链路未发生行为变更时不启动写库验收；若后续改动超出此边界，重新确认隔离环境后验证。

## 本次保留

- 旧病例写入层仍有 seed 和集成测试调用，需专门迁移与隔离数据库验收后再退役。
- 未接入的训练审计、失效配置字段、后端依赖精简暂不处理，避免改变安全能力、环境配置或依赖恢复契约。
- 阶段二长文档包含有效决策和待条件，暂不截断；训练构造器和其他仍在使用的重复逻辑不在本次删除范围。

## 结果

代码和文档清理已完成，实际验证如下。

- 后端全量本地测试（排除 integration/E2E）：2499 passed、59 skipped、45 warnings、24 subtests passed，耗时 1041.46 秒，退出码 0。跳过项不计为通过；未执行真实数据库集成或 E2E 验收。
- 前端修改前定向 Vitest：82 passed。修改后 `test:unit`：175 passed；`test:contracts`：30 passed；`build`：成功。npm 有依赖 engine 警告，构建有现有注释位置及大 chunk 警告，未升级依赖或改阈值。
- 后端修改前相关回归：204 passed，图片安全另 5 passed。修改后定向回归：191 passed；追加标准 API、查询接口和 ORM 检查：50 passed、3 subtests passed。均无失败，仅既有警告。
- `scripts/tests/test_check_model_artifacts.py` 修改前后均 4 passed、2 warnings。
- 浏览器使用本机构建产物和完全拦截的虚构 API 响应：登录、操作者空状态/图标/折叠、保存报告、归档下载入口、PDF 加载及失败状态、失败报告禁用下载、管理员空状态通过；无页面脚本异常、无真实后端请求。首轮验证脚本误用了 `.login-view`，核对实际 `.login-page` 后修正并全部通过。这不构成真实数据库、worker 或归档原件链路验收。
- 实现与质量独立复核均通过；未修改冻结的模型/PDF 源码身份，未改业务断言。

本地目录核查纠正了初次容量统计：`.tmp/node_modules` 是指向 Codex 共享运行时的 Junction，其约 335 MB 不属于项目可释放空间。排除该目标后，三个本地目录合计约 1.77 GB。仅 `.superpowers/p2/ocr-venv` 与 `.superpowers/startup-prep/wheels` 两个普通目录被列为清理对象，合计 549,328,462 字节；可读进程未发现使用，部分系统进程信息不可读。用户已明确确认删除这两个目录。再次执行前已核对绝对路径在项目内、目标及祖先无重解析点、目录内无重解析点；自动审批仍拒绝递归删除，仅返回 `blocked by policy`，未提供更具体原因。执行后只读复查确认两个目录仍存在，未释放上述空间；没有改用其他工具绕过限制。

已核对来源约束仍由 `standard_source_binding.py`、`standard_manifest_import.py`、`standard_lifecycle.py` 和 `check_database_readonly.py` 保留：完整四字段定位（含 null）、批准 manifest 规则 ID 精确集合、版本归属、实际源文件 SHA-256，以及发布前绑定校验失败即阻断。对应来源、导入、发布、修复 dry-run/apply 和只读核查回归测试仍在；本次清理未改变标准内容、发布配置或历史报告，删除的临时报告内 112/119 passed 仅属历史记录。

## 追加老旧文件清理（2026-09-26）

用户再次要求检查老旧文件，并明确确认旧标准 resolver、旧 v1 模型候选生成能力、08-27 清理档案退役。本轮与上面的首次清理、同日逻辑去重区分统计；保留已有未提交修改，不提交或推送。

### 删除范围与保留依据

- 删除 8 份历史文档，共 4,796 行：`plans/2026-07-24-project-cleanup-and-alembic-implementation.md`、`plans/2026-07-27-development-baseline-implementation.md`、`plans/2026-07-28-ai-operator-implementation.md`、`plans/2026-08-20-longitudinal-progression-prediction.md`、`plans/2026-09-08-manual-test-fixes.md`、`plans/2026-09-15-numeric-report-presentation.md`、`plans/2026-08-27-project-structure-cleanup.md`、`specs/2026-08-27-project-structure-cleanup-design.md`（均位于 `docs/superpowers/`）。前六份是无外部入链的失效实施模板或已被结果记录承接的步骤清单；后两份经用户确认成组删除。清理契约只移除这份旧规格的两处保留条目，其他资产保护不变。
- 删除旧 `standard_resolver.py` 及专属测试，把冲突规则和版本归属的安全断言迁至当前标准证据流程。保留标准证据、来源绑定、发布、查询接口和历史报告版本。
- 删除未被正式调用的 `evaluate_numeric_v3_readiness`、`build_rule_candidates`、`transition_version`。测试改为验证现行 dispatcher、审核/发布入口，解析内容测试保留。
- 退役旧 v1 训练候选生成/导出函数及专属测试，保留 v2 训练和旧制品读取、校验、registry、release。审查时纠正初步候选：`_make_fitted_candidates` 仍被 v2 使用，连同预处理、特征 DataFrame、版本记录等共享实现全部保留；旧制品文件不删除或重建。
- 删除 `.tmp/fix-f2-record.py`、`fix-renderer-notes.py`、`run-phase4-s3-regression.py`、`run-phase4-s4-regression.py`、`run-phase4-s6-regressions.py` 五个一次性包装脚本，共 5,929 字节；修复已落地，原测试、历史 JSON/log 与验收记录保留。

旧迁移预检、任意 DOCX 标准初始化、单项训练入口仍有独立用途，继续保留。未接入的异常高分审计没有完整替代，保留。阶段路线图、模型/数据来源、PDF 原件身份、真实验收记录和含未决事项的文档不按日期删除。用户已放弃的两个缓存目录不再尝试清理，共享 Junction 不处理。

### 本轮验证

- 清理前相关标准/数值/冻结身份：128 passed；两个薄包装相关测试另 55 passed；旧训练测试 19 passed。这些仅为本轮修改前基线。
- 清理后两个薄包装相关测试：54 passed（移除 1 项纯包装测试），原有 Pydantic 弃用警告仍在。
- 清理后训练、registry、release、审计、分组、CLI 编排及制品检查：91 passed、30 warnings；警告来自既有 Pydantic 测试夹具。v2 及共享的 26 个顶层定义与本轮修改前 AST 完全相同，候选范围和禁止覆盖断言迁至现行实现。
- 文档删除后的清理契约：7 passed。标准证据/context/API/冻结身份定向回归：66 passed、3 subtests passed、5 warnings；审核/发布/标准校验：70 passed、2 warnings。
- 新增 4 个安全场景在现行入口通过；三次仅在独立测试进程内存中屏蔽冲突、预检归属、固定版本归属检查，均被相应断言捕获。这些刻意制造的失败用于验证断言有效，不修改生产文件。
- 三路独立交叉复核无可行动发现；活跃代码无已删符号引用。4 个局部清理模块的所有保留顶层定义 AST 不变，72 个受跟踪模型资产逐字节未变，35 个冻结文件身份检查通过。前后差异与引用检查通过。
- 本轮后端完整本地回归（排除 integration/E2E）已完成：2516 passed、59 skipped、46 warnings、24 subtests passed，pytest 耗时 1024.38 秒，进程退出码 0。跳过项为 58 项未配置原始 DOCX 的验收、1 项当前环境无法创建符号链接的测试；跳过不计通过。日志为 `.tmp/older-cleanup-20260926/backend-tests.log`，进程结果为同目录 `backend-tests-result.json`。2026-09-27 恢复会话后核对并补录，没有把此前轮次结果作为本轮验证。

本轮不连接业务数据库、不执行训练 CLI、不调用外部 LLM、不下载模型；测试只使用既有本地单元测试及其临时虚构夹具。真实数据库集成/E2E 未执行。前端本轮未修改。

## 实施计划文档精简（2026-09-27）

用户确认按上一轮建议删除 17 份实施计划，共 5,828 行：3 份早期安全/标准/模板计划、6 份年龄/疾病权限/状态/附录计划，以及 8 份已被独立结果记录承接的合成/数值报告计划。`docs/superpowers` 从 104 份减至 87 份（42 plans、23 specs、22 notes）；保留原文的 Git 历史。本轮未新增项目文档。

同步更新总领文档、阶段二计划及 5 份 notes 的导航引用；日期、验收数字、失败记录、真实资料待条件与来源/制品身份保持。稳定性实验 design 原字节保留，当前业务源码、测试与制品相对本轮开始的哈希未变化，已有未提交修改保留。

实际验证：清理契约与冻结源码身份测试合计 10 passed、退出码 0；17 份目标均不存在，删除行数与批准清单一致；无残留目标引用、无新增本地失效链接，`git diff --check` 通过。纯文档变更未重跑完整前后端套件、数据库集成或 E2E。扫描发现 `2026-08-20-longitudinal-import.md` 原有链接指向已不存在的导入 design，未混入本轮修改。
