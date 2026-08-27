# 项目结构清理设计

日期：2026-08-27

状态：用户已确认清理边界，待书面规格复核

仓库定位：保留完整开发、训练、数据生成、模型审计与运行能力的开发主仓库

## 1. 目标

在不影响当前“纵向病例 → 模型套件推理 → 结构化报告 → PDF”主链路、训练可复现性、数据库迁移能力和上传数据的前提下，删除已经确认无用的临时产物、重复工具配置、历史输出、已完成设计规格、旧 SQL 迁移资料，以及已被新版纵向报告链路取代的即时风险评估实现。

本次清理不以压缩仓库体积为唯一目标。判断优先级依次为：

1. 不破坏当前纵向报告生成链路；
2. 保留模型训练和数据生成的可复现性；
3. 保留当前激活模型的完整版本、评审和激活审计；
4. 删除重复、可再生或已经失去调用者的内容；
5. 使 README、数据库说明和实际目录结构一致。

## 2. 不在本次范围内

本次不进行以下操作：

- 不重构新版纵向预测服务、模型注册表或报告模板；
- 不改变数据库业务表，不新增用于删除历史表的迁移；
- 不删除 `case_records`，因为相似病例证据、数据发布和训练数据构建仍依赖该表；
- 不删除 `research/` 源码和测试；
- 不删除 150/300 例生成数据；
- 不删除当前模型套件、数据集 manifest、release set、active pointer、review 或 activation log；
- 不删除上传文件、环境变量、前端依赖、前端构建产物或编译/测试缓存；
- 不做 Git 历史重写，不从历史提交中清除已删除文件；
- 不修改 AI 操作者端视觉风格。若实现中必须调整 UI，需先读取并遵守 `docs/DESIGN_SPEC.md`。

## 3. 直接删除范围

以下内容不参与当前应用运行，且已经由用户逐项确认删除。

### 3.1 本地工作过程产物

- `.tmp/`
- `.tmp-doc-review/`
- `.superpowers/`
- `research/outputs/`

其中 `.superpowers/` 仅包含旧 brainstorm 页面、端口状态和 SDD 过程包。正式计划仍保存在 `docs/superpowers/plans/`。

### 3.2 报告和视觉验收产物

- `tmp/pdfs/`
- `output/pdf/`
- `output/evidence/`

保留 `outputs/report_method_validation.md`，因为它是方法验证结论而非可再生的渲染产物。

### 3.3 重复开发工具配置

- `CLAUDE.md`
- `.claude/`

项目后续仅保留 Codex 使用的 `AGENTS.md` 和 `.agents/`。README 中对 `CLAUDE.md` 的链接同步删除。

### 3.4 过期部署和数据库资料

- 根目录 `DEPLOYMENT_PLAN.md`
- `database/migrations/`

保留：

- `docs/DEPLOY.md`
- `docs/ALIYUN_DEPLOYMENT_RUNBOOK.md`
- `backend/alembic/versions/`
- `database/schema.sql`
- `database/README.md`

`database/README.md` 必须删除旧 SQL 文件清单，并明确 Alembic 是唯一正式迁移入口。

### 3.5 阶段性文档记录

删除：

- `docs/superpowers/reviews/`
- `docs/superpowers/validation/`
- `docs/superpowers/notes/2026-08-21-reference-standard-pipeline-audit.md`
- `docs/superpowers/notes/2026-08-24-versioned-standard-rules-layer-recommendation.md`

保留：

- `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`
- `docs/superpowers/notes/2026-08-26-ad-stage-transition-future-design-note.md`

### 3.6 已完成设计规格

清理实施时，删除当前 `docs/superpowers/specs/` 下已经由代码、测试、迁移或相应实施计划证明完成的设计规格。不能仅依据文档内过时的“待实施”状态判断。

当前 27 份旧规格中，只保留尚未落地、仍作为真实数据采集契约使用的：

- `docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md`

本清理规格在执行和验收期间保留。清理完成后，项目演进由 `docs/superpowers/plans/`、Git 提交和最终 README 承接；是否随后删除本规格，应在清理验收完成时单独决定，不能在实施中提前删除。

## 4. 旧即时风险评估链路的安全拆除

旧链路是同步、非持久化的 `/operator/progression-predictions`，前端使用第二套访视录入表单展示单一风险分数。当前主链路已经改为保存纵向病例后，使用 active release set 中的结局、阶段和趋势模型生成持久化报告。

两条链路的模型制品不同：

- 旧链路读取 `backend/app/ml_models/{dataset}_progression_model.joblib` 和对应根级 metadata；
- 新链路读取 `active/` 指针、`release_sets/` 和 `bundles/`。

因此旧功能可以删除，但必须先解除新版模型注册服务对旧模块中 `MODEL_DIR` 常量的借用。

### 4.1 先迁移公共路径常量

新增一个不含旧预测行为的模型路径模块：

- `backend/app/services/model_paths.py`

该模块只负责导出：

```python
MODEL_DIR = Path(__file__).resolve().parents[1] / "ml_models"
```

更新以下调用者改从新模块导入：

- `backend/app/services/longitudinal_model_registry.py`
- `scripts/check_longitudinal_readiness.py`

在删除旧模块前，必须通过引用扫描确认生产代码不再导入 `progression_engine`。

### 4.2 删除后端旧链路

从 `backend/app/api/operator.py` 删除：

- `predict_progression` 导入；
- 旧 progression schema 导入；
- `_PROGRESSION_DATASETS`；
- `POST /operator/progression-predictions` 路由。

删除：

- `backend/app/services/progression_engine.py`
- `backend/app/schemas/progression.py`
- `backend/tests/test_progression_engine.py`
- `backend/tests/test_progression_api.py`

保留新版纵向病例、报告、证据、模型注册、模型训练和 readiness 相关服务及测试。

### 4.3 删除前端旧链路

从 `frontend/src/views/OperatorView.vue` 删除重复的即时评估区域及其状态和辅助函数，包括：

- 第二套疾病选择和访视编辑器；
- “评估进展风险”操作；
- 旧风险分数、免责声明和特征摘要展示；
- `progressionDiseaseId`、`progressionVisits`、`progressionResult` 等页面状态；
- 仅供旧区域使用的图标、格式化函数和 CSS。

从 `frontend/src/stores/operator.ts` 删除：

- `progressionResult`；
- `progressionLoading`；
- `predictLongitudinalProgression()`；
- `clearProgression()`；
- 对旧 API 类型和函数的导入与导出。

从 `frontend/src/api/operator.ts` 删除：

- `ProgressionVisitInput`；
- `ProgressionPredictionRequest`；
- `ProgressionFeatureSummary`；
- `ProgressionPredictionOut`；
- `predictProgression()`。

删除旧 `frontend/tests/progression-ui-contract.test.mjs`，并在纵向 UI 契约测试或新的清理契约中增加反向断言，确保旧端点、旧状态和重复表单不会重新出现。

### 4.4 删除旧训练入口和制品

删除：

- `scripts/train_progression_model.py`
- `scripts/tests/test_train_progression_model.py`
- `backend/app/ml_models/ad_progression_model.joblib`
- `backend/app/ml_models/ad_progression_model.meta.json`
- `backend/app/ml_models/fatty_liver_progression_model.joblib`
- `backend/app/ml_models/fatty_liver_progression_model.meta.json`
- `scripts/tests/fixtures/model-artifact-baseline.json`

如果 fixture 还承担新版模型不可变性检查，应先把该检查改为校验 active release set 和 bundle manifest，不能直接删除有效保护。

### 4.5 必须保留的关联能力

以下内容名称接近旧预测功能，但属于当前主链路，禁止删除：

- `backend/app/services/longitudinal_prediction.py`
- `backend/app/services/longitudinal_features.py`
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_*_training.py`
- `backend/app/services/longitudinal_report_generator.py`
- `backend/app/services/longitudinal_evidence.py`
- `backend/app/services/disease_progression.py`
- `scripts/train_longitudinal_*.py`
- `scripts/manage_longitudinal_registry.py`
- `scripts/manage_longitudinal_release_sets.py`
- `scripts/check_longitudinal_readiness.py`
- `case_records` 及其 CRUD，因为相似病例证据和训练数据仍使用该数据域。

## 5. Git 工作树和分支清理

清理目标：

- 工作树 `.worktrees/longitudinal-report-format-fix`
- 工作树 `.worktrees/versioned-standard-rules-2026-08-24`
- 未注册残留 `.worktrees/standard-documents-001`
- 本地分支 `codex/longitudinal-report-format-fix`
- 本地分支 `codex/versioned-standard-rules-2026-08-24`
- 本地分支 `claude/ai-operator-001`

执行前必须重新核验：

1. 两个注册工作树对应分支都已被 `main` 包含；
2. 工作树中没有未提交修改；
3. `standard-documents-001` 不再由 Git 注册，且目录内没有唯一未提交成果；
4. 所有目标解析后的绝对路径都位于项目 `.worktrees/` 内。

删除注册工作树必须使用 `git worktree remove`，随后运行 `git worktree prune`；不能把注册工作树当普通目录直接递归删除。分支只在确认已合并后使用非强制方式删除。

## 6. 明确保留范围

### 6.1 本地依赖和缓存

按用户要求保留：

- `frontend/node_modules/`
- `frontend/dist/`
- 所有 `.pytest_cache/`
- 所有 `__pycache__/`
- 所有 `*.tsbuildinfo`

这些文件继续由 `.gitignore` 排除，不应被提交。

### 6.2 运行数据和密钥

保留：

- `backend/.env`
- `uploads/`
- `uploads/images/`

任何验证命令不得打印 `.env` 内容或上传文件内容。

### 6.3 数据与研究能力

保留：

- `research/` 源码、测试、README、requirements 和 pytest 配置；
- `data/generated/longitudinal_150/`；
- `data/generated/longitudinal_300/`；
- `data/generated/ad_longitudinal_150/`；
- `data/generated/ad_longitudinal_300/`；
- 数据生成、扩展、导入、数据集构建和训练脚本及对应测试。

150 例目录仍是扩展到 300 例脚本和测试的确定性基线，不能作为“旧数据”删除。

### 6.4 当前模型和审计

保留 `backend/app/ml_models/` 下：

- `datasets/`
- `bundles/`
- `release_sets/`
- `active/`
- `reviews/`
- `activation_log/`

新版报告通过这些文件解析当前模型版本。评审记录和激活日志属于模型治理审计，不是临时输出。

## 7. 文档和目录同步

实施完成后更新：

- `README.md`：删除 Claude 链接，补充 AI 操作者纵向报告主链路，更新项目树；
- `database/README.md`：删除旧 SQL 迁移说明；
- `.gitignore`：确保 `.tmp/`、`.tmp-doc-review/`、`.superpowers/`、`tmp/`、报告输出目录和本地 worktree 不会重新进入 Git；
- `backend/tests/test_cleanup_contracts.py`：加入本次已删除路径和旧预测符号的反向契约；
- `README.md`、`database/README.md`、`docs/DEPLOY.md`、`docs/ALIYUN_DEPLOYMENT_RUNBOOK.md`、两份保留 notes 和真实纵向数据采集规范中的现行入口引用；实施计划中的历史叙述除外。

对保留的实施计划，不要求为消除历史叙述而大规模改写。实施计划中的历史路径可以保留，前提是 README 和现行运维文档不再把已删除文件描述为当前入口。

## 8. 执行顺序

为降低不可恢复风险，执行必须按以下顺序进行：

1. 记录清理前 `git status`、分支、worktree 和关键文件清单；
2. 增加或调整清理契约，使旧链路删除要求先出现失败测试；
3. 迁移 `MODEL_DIR`，验证新版 registry/readiness 不再依赖旧模块；
4. 删除旧后端接口、服务、schema、训练入口和专属测试；
5. 删除旧前端界面、状态、API 和旧 UI 契约测试；
6. 运行旧符号引用扫描；
7. 删除直接清理范围中的 Git 跟踪文件并更新文档；
8. 安全移除 worktree 和已合并本地分支；
9. 删除已批准的忽略目录和本地临时目录；
10. 执行分层验证和最终目录检查。

如果第 3 至第 6 步验证失败，不得继续删除新版模型或数据来规避失败。

## 9. 验证矩阵

### 9.1 静态引用检查

必须确认生产代码中不存在：

- `progression_engine`
- `/operator/progression-predictions`
- `ProgressionPredictionOut`
- `predictProgression`
- `progressionResult`
- 根级 `*_progression_model.*` 路径引用
- `CLAUDE.md`
- `database/migrations/`

测试 fixture 中用于确认 legacy isolation 的文字样例，只有在语义仍有效时可以保留；不能让生产代码继续依赖旧文件。

### 9.2 后端专项验证

至少覆盖：

- 纵向病例 CRUD 和归属隔离；
- active model registry 与 release set 加载；
- readiness 检查；
- 纵向预测 v2/v3 契约；
- 信号解释；
- 报告生成、持久化、取消和失败状态；
- PDF 生成；
- 相似病例和参考标准证据；
- operator 权限；
- cleanup contract。

### 9.3 前端验证

必须运行：

- 纵向报告 UI 契约测试；
- 纵向病例同步/基线阶段契约测试；
- operator legacy cleanup 契约；
- `npm run build`。

构建使用用户要求保留的现有 `node_modules/`，不执行依赖删除或重装。

### 9.4 模型制品验证

必须确认：

- `active/fatty_liver.json` 和 `active/ad.json` 能解析；
- 两个 pointer 指向的 release set 存在且 hash 校验通过；
- release set 引用的 dataset manifest、model、metadata 和 evaluation 文件都存在；
- 根级旧模型删除后，当前纵向报告仍从 bundle 加载模型。

### 9.5 最终结构检查

最终确认：

- 所有批准删除路径不存在；
- 所有明确保留路径仍存在；
- `git worktree list` 只剩主工作区；
- 三个已确认本地分支不存在；
- Git 工作区只包含本次清理预期变更；
- `git diff --check` 通过。

## 10. 失败和回退原则

- Git 跟踪文件的删除在提交前可通过 Git 恢复；不得使用 `git reset --hard` 或覆盖用户文件；
- worktree 删除前必须检查未提交内容，一旦发现修改立即停止并报告；
- `backend/.env`、`uploads/` 和保留缓存不进入清理命令；
- 若新版报告测试因删除旧链路失败，先恢复或修正公共依赖边界，不恢复旧 UI 作为长期解决方案；
- 若 active release set 校验失败，停止清理，不删除任何模型 bundle、dataset、review 或 activation log；
- 清理完成之前不创建提交；验证通过后再由用户决定是否提交清理结果。

## 11. 完成标准

同时满足以下条件才可声明完成：

1. 用户批准的临时、历史输出、Claude 配置、旧部署文档和旧 SQL 资料均已删除；
2. 旧即时风险评估链路及根级旧模型已删除；
3. 当前纵向报告链的专项测试与前端构建通过；
4. 新版 active release set 和全部引用制品校验通过；
5. 训练数据、研究源码、上传数据、环境配置和用户要求保留的缓存完整存在；
6. README、数据库说明、清理契约与实际目录一致；
7. 主工作区之外的三个工作树目录和三个已合并本地分支已安全清理；
8. 没有通过删除测试、数据或审计记录来掩盖失败。
