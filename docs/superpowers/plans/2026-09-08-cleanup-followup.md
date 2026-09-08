# 清理后续修复计划

> 使用 subagent-driven-development 执行独立任务；用户已在本次会话授权修复上一轮审查的问题和清理确认无用的代码。

**Goal:** 修复结构清理审查发现的功能缺口与验证盲点，清除确认不可达的旧实现。

**Architecture:** 保持持久化报告生成、当前模型 release set 和病例聚合保存接口；补齐现有接口的页面调用，统一特征输入和测试入口。

**Tech Stack:** Python 3.11、pytest、FastAPI、Vue 3、TypeScript、Vitest、Node.js 22、PowerShell。

## Global Constraints

- 不修改业务数据库、上传数据、模型制品、release set 或审计记录；不访问外部 LLM。
- 不删除独立训练入口、历史兼容 schema、仍使用的 PDF 服务或原始数据。
- UI 遵循 `docs/DESIGN_SPEC.md`，复用现有工作区和接口。
- 工作基线 `3ee0c5d`，本地分支 `codex/cleanup-followup-fixes`；改动留待用户审阅，不提交或推送。
- 真实缺陷先加行为回归并确认失败，修复后运行覆盖测试；低影响文本清理不新增同义测试。
- 多个任务的文件所有权分开；全套验证由主代理统一执行。

## Task 1: 阶段输入与模型冒烟

**Files:** `backend/app/services/longitudinal_features.py`、`backend/tests/test_longitudinal_prediction_contract.py`、`scripts/smoke_longitudinal_registry.py`、`scripts/tests/test_smoke_longitudinal_registry.py`。

- [x] 以真实 stage metadata 验证 `baseline_stage` 必须成为 `current_stage`，缺值仍拒绝推理。
- [x] 在特征映射加入 `"current_stage": case.get("baseline_stage")`，保持排序、缺失校验和审计契约。
- [x] 正常 smoke 场景要求结局、阶段、必需趋势 available，失败时返回非零退出码；不确定阶段继续禁止结局分数。
- [x] 运行针对测试及 `python scripts/smoke_longitudinal_registry.py --registry-dir backend/app/ml_models --data-root data/generated`。

## Task 2: 病例页面接线与前端旧链清理

**Files:** `frontend/src/views/OperatorView.vue`、`frontend/src/components/operator-case/*.vue`、`frontend/src/stores/operator.ts`、`frontend/src/api/operator.ts`、相关 `*.spec.ts`、现存 `frontend/tests/*.test.mjs`（标准管理恢复文件归 Task 4）。

- [x] 对搜索、删除确认、归档/恢复、停用疾病只读增加行为回归，记录修复前失败。
- [x] 绑定 query 和筛选请求，保持晚到响应不能覆盖新选择的会话隔离。
- [x] 接入现有 `removeLongitudinalCase` / `changeLongitudinalCaseStatus`，删除明确保留历史报告；归档和停用状态禁止写操作并给出原因。
- [x] 删除无人调用的旧 SSE 生成器、专属解析器、回调和旧生成状态；同步迁移依赖旧字符串的契约。
- [x] 只清理确认不适用的样式，当前报告所需样式保持在实际渲染组件。
- [x] 运行覆盖组件/store测试、Node契约和构建。

## Task 3: 可复现验证入口

**Files:** `scripts/verify_baseline.ps1`、`scripts/check_dev_environment.ps1`（如确有需要）、`scripts/tests/test_baseline_scripts.ps1`、`scripts/tests/test_generate_fatty_liver_longitudinal.py`、`docs/DEVELOPMENT.md`、`docs/DEPLOY.md`、`backend/requirements.txt`（仅测试运行所需依赖）。

- [x] 日常验证改用 pytest 覆盖 backend 与 scripts，排除显式数据库/浏览器验收；前端同时运行 Vitest 和 Node 契约。
- [x] 数据库只读检查指定 `--phase postflight`，更新现行文档命令。
- [x] 原始 DOCX 数据验收改为显式可选，缺少文件给出清晰 skip；纯解析与生成回归使用受控 fixture，避免把原始资料缺失伪装成通过。
- [x] 运行脚本契约及数据生成测试，验证环境恢复入口安装所需测试依赖。

## Task 4: 后端旧实现、有效测试和文档收尾

**Files:** `backend/app/api/operator.py`、`backend/app/services/longitudinal_prediction.py`、`backend/app/services/longitudinal_evidence.py`、其旧测试、`frontend/tests/standard-management-ui-contract.test.mjs`、`.gitignore`、`README.md`、真实数据采集规范。

- [x] 恢复标准管理仍有效的十项测试；剔除仅针对已删除旧组件的最后一项检查，保留现行报告与病例行为回归。
- [x] 清除旧证据服务及仅服务它的 import/测试，清除 `_risk_from_registry`、`_safe_report_title` 和旧 ownership helper；保持现行权限与证据行为测试。
- [x] 去重 ignore，标明旧采集规范历史用途并指向当前数据输入契约，更新 README 项目树。
- [x] 不新增目录白名单类无行为测试；现有清理检查随真实边界更新。

## Final verification

- [x] `python -m pytest backend/tests scripts/tests --ignore=backend/tests/integration --ignore=backend/tests/e2e -q`。
- [x] 前端 Vitest、全部 Node 契约、`npm run build`。
- [x] 当前模型 smoke 正常场景阶段可用；模型及数据 Git 内容未改变。
- [x] 独立最终审查修复/清理的行为边界与测试质量，处理重要发现。
- [x] `git diff --check`，报告通过数、跳过原因和未覆盖边界。

## 执行结果

- 修复 `baseline_stage` 到 `current_stage` 的输入映射；真实 registry 冒烟中脂肪肝两个确定阶段、AD MCI 的结局、阶段和必需趋势均可用。不确定阶段仍不提供结局分数。
- 补齐病例搜索、状态筛选、删除、带原因归档/恢复和只读限制；列表刷新保留当前查询，搜索及晚到初始化请求不覆盖新建草稿。
- 清除旧 SSE 报告链、重复报告状态、不可达预测摘要组件、旧证据服务和无调用辅助函数；保留当前历史报告、证据/PDF 与模型训练入口。
- 恢复十项有效标准管理契约；基线改用 pytest，补齐前端两套测试，原始 DOCX 验收显式启用，可移植生成与判定测试默认执行。

| 验证 | 结果 |
|---|---|
| 后端及 scripts 完整非集成测试 | 1313 passed，58 skipped，24 subtests passed |
| 前端 Vitest | 84 passed |
| 前端 Node 契约 | 30 passed |
| TypeScript 检查与生产构建 | 通过 |
| PowerShell 基线脚本契约 | 通过 |
| 当前真实模型制品冒烟 | 通过 |
| 模拟 API 浏览器操作 | 草稿搜索保留、搜索清空、归档/恢复原因及筛选、只读、删除取消/确认通过 |
| Git 差异及删除符号引用检查 | 通过 |
| 独立代码审查 | Spec approved；Quality approved，已关闭全部发现 |

58 项跳过测试依赖未提供的 AD / 脂肪肝原始 DOCX。未执行数据库集成、真实数据库检查和外部 LLM 请求；本轮 Python 测试使用本机已有 Python 3.11 环境，未重建 `.venv` 或完整执行环境恢复命令。构建仍有既有大包及依赖注释警告，后端仍有既有弃用警告。

模型制品、生成数据、数据库结构与上传文件未改变。所有改动保留在工作区，未提交或推送。

### 原始资料补验收

用户提供移动后的四份 DOCX 路径后，已确认文件存在，并将 AD 测试中的旧桌面硬编码改为 `AD_DOC_A` / `AD_DOC_B`，与脂肪肝验收一致。开发文档已补充四个环境变量的配置方式。

- 脂肪肝：31 passed（28 项原始资料验收 + 3 项可移植测试）。
- AD：30 passed。
- 上表先前跳过的 58 项现已全部执行通过；未修改原始文档、生成器、正式数据或模型。
