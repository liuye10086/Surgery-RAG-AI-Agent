# 项目结构清理实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留当前纵向报告、模型训练、数据生成、模型审计、上传数据和开发环境的前提下，安全移除旧即时风险评估链路、历史输出、重复工具配置和已批准的过期资料，并使目录说明与实际结构一致。

**Architecture:** 先用清理契约固定删除和保留边界，再把新版模型注册所需的 `MODEL_DIR` 从旧预测模块迁移到独立路径模块。后端和前端旧链路分别拆除并独立回归；跟踪文件、本地临时目录、Git worktree 和分支放在功能回归之后清理，最后以 active release set smoke、readiness、前后端测试和构建共同验收。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、pytest、Vue 3、TypeScript、Pinia、Node.js 22、npm 10、PowerShell、Git worktree。

## Global Constraints

- 首次执行任何删除命令前必须向项目所有者展示最终删除清单，并取得一句明确的“开始执行”确认。
- 使用 PowerShell；Python 命令前设置 `$env:PYTHONPATH='backend;.'`。
- 所有 UI 代码删减必须遵守 `docs/DESIGN_SPEC.md`；本任务只移除重复旧界面，不改变保留界面的视觉风格。
- 不删除或改写主工作区中的 `backend/.env`、`uploads/`、`frontend/node_modules/`、`frontend/dist/`、任何 `.pytest_cache/`、任何 `__pycache__/` 或任何 `*.tsbuildinfo`。三个已单独批准移除的完整 worktree 根目录是唯一例外：其中的依赖、构建和缓存副本随 worktree 一并移除，不会被单独清理，也不会影响主工作区对应路径。
- 不删除 `research/` 源码与测试、四套 150/300 数据、`case_records`、新版训练脚本或新版模型注册文件。
- 不删除 `backend/app/ml_models/datasets/`、`bundles/`、`release_sets/`、`active/`、`reviews/` 或 `activation_log/`。
- 不修改数据库业务表，不新增删表迁移，不写业务数据库；readiness 检查必须保持只读。
- 注册 worktree 必须使用 `git worktree remove`；只有未注册残留目录可在绝对路径边界校验后使用 `Remove-Item`。
- 不使用 `git reset --hard`、`git checkout --` 或强制分支删除；只用 `git branch -d` 删除已合并分支。
- 旧 registry/readiness 中“忽略根级 legacy progression artifact”的隔离测试继续保留，它们保护新版模型选择边界。
- 每个代码任务先写失败测试并确认 RED，再做最小实现并确认 GREEN。
- 清理实施期间不创建中间提交；Tasks 1-7 全部验证通过后，向项目所有者展示最终状态，由项目所有者决定是否创建一个清理结果提交。
- 设计依据：`docs/superpowers/specs/2026-08-27-project-structure-cleanup-design.md`。

## 文件地图

### Create

- `backend/app/services/model_paths.py`：只定义当前模型注册根目录 `MODEL_DIR`，不包含任何预测逻辑。
- `backend/tests/test_model_paths.py`：验证模型目录解析稳定且不依赖旧预测模块。

### Modify

- `backend/app/services/longitudinal_model_registry.py`：改从 `model_paths` 导入 `MODEL_DIR`。
- `scripts/check_longitudinal_readiness.py`：改从 `model_paths` 导入 `MODEL_DIR`。
- `scripts/tests/test_check_longitudinal_readiness.py`：增加公共路径依赖契约。
- `backend/app/api/operator.py`：删除旧同步预测路由和导入，保留纵向病例/报告/疾病/参考病例 API。
- `backend/tests/test_operator_predictive_api.py` → `backend/tests/test_operator_catalog_and_reports_api.py`：保留疾病、病例、报告和路由注册测试，增加旧端点不存在契约。
- `backend/tests/test_cleanup_contracts.py`：固定本次删除与保留边界。
- `frontend/src/views/OperatorView.vue`：删除第二套即时预测表单和旧结果区，保留纵向病例编辑、报告阅读与病例库。
- `frontend/src/stores/operator.ts`：删除旧同步预测状态和 action。
- `frontend/src/api/operator.ts`：删除旧同步预测类型和请求函数。
- `frontend/tests/operator-legacy-cleanup.test.mjs`：增加旧同步预测符号的反向契约。
- `README.md`：更新文档入口、当前纵向报告主链路和项目树。
- `database/README.md`：删除旧 SQL 迁移资料说明，明确 Alembic 唯一入口。
- `.gitignore`：阻止已删除的临时目录和输出目录再次进入仓库。

### Delete: old synchronous progression chain

- `backend/app/services/progression_engine.py`
- `backend/app/services/risk_bands.py`
- `backend/app/schemas/progression.py`
- `backend/tests/test_progression_engine.py`
- `backend/tests/test_progression_api.py`
- `scripts/train_progression_model.py`
- `scripts/tests/test_train_progression_model.py`
- `scripts/tests/fixtures/model-artifact-baseline.json`
- `frontend/tests/progression-ui-contract.test.mjs`
- `backend/app/ml_models/ad_progression_model.joblib`
- `backend/app/ml_models/ad_progression_model.meta.json`
- `backend/app/ml_models/fatty_liver_progression_model.joblib`
- `backend/app/ml_models/fatty_liver_progression_model.meta.json`

### Delete: approved tracked cleanup

- `CLAUDE.md`
- `.claude/`
- `.superpowers/`
- `DEPLOYMENT_PLAN.md`
- `database/migrations/`
- `tmp/pdfs/`
- `output/pdf/`
- `output/evidence/`
- `docs/superpowers/reviews/`
- `docs/superpowers/validation/`
- `docs/superpowers/notes/2026-08-21-reference-standard-pipeline-audit.md`
- `docs/superpowers/notes/2026-08-24-versioned-standard-rules-layer-recommendation.md`
- 除 `2026-08-18-real-longitudinal-data-collection-spec.md` 和本次清理规格外的 26 份旧 `docs/superpowers/specs/*.md`

### Delete: approved ignored/local cleanup

- `.tmp/`
- `.tmp-doc-review/`
- `research/outputs/`
- `.worktrees/longitudinal-report-format-fix`
- `.worktrees/versioned-standard-rules-2026-08-24`
- `.worktrees/standard-documents-001`
- local branch `codex/longitudinal-report-format-fix`
- local branch `codex/versioned-standard-rules-2026-08-24`
- local branch `claude/ai-operator-001`

### Read Only / Must Not Modify

- `backend/.env`
- `uploads/`
- `frontend/node_modules/`
- `frontend/dist/`
- `data/generated/`
- `research/*.py`
- `research/tests/`
- `backend/app/ml_models/datasets/`
- `backend/app/ml_models/bundles/`
- `backend/app/ml_models/release_sets/`
- `backend/app/ml_models/active/`
- `backend/app/ml_models/reviews/`
- `backend/app/ml_models/activation_log/`
- `backend/app/db/models.py`
- `backend/alembic/versions/`
- `docs/superpowers/plans/`
- `docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md`

---

### Task 0: 记录执行基线并再次锁定删除边界

**Files:**
- Read only: repository status, branches, worktrees, approved delete paths, and preserved paths

**Interfaces:**
- Produces: a human-reviewed baseline in the execution transcript; no repository file is created or changed.
- Blocks: no code edit or deletion begins if the main worktree is unexpectedly dirty or a target resolves outside the repository.

- [ ] **Step 1: Record the Git baseline**

```powershell
$workspaceRoot = (Resolve-Path -LiteralPath '.').Path.TrimEnd('\')
git status --short --branch
git branch --show-current
git worktree list --porcelain
git branch --format='%(refname:short)'
```

Expected: current branch is `main`; only previously reviewed design/plan changes may exist. Any unrelated modification must be reported and preserved before continuing.

- [ ] **Step 2: Resolve every local destructive target inside its approved parent**

```powershell
$boundedTargets = @(
  @{ Path = '.tmp'; Parent = $workspaceRoot },
  @{ Path = '.tmp-doc-review'; Parent = $workspaceRoot },
  @{ Path = 'research/outputs'; Parent = "$workspaceRoot\research" },
  @{ Path = '.worktrees/longitudinal-report-format-fix'; Parent = "$workspaceRoot\.worktrees" },
  @{ Path = '.worktrees/versioned-standard-rules-2026-08-24'; Parent = "$workspaceRoot\.worktrees" },
  @{ Path = '.worktrees/standard-documents-001'; Parent = "$workspaceRoot\.worktrees" }
)
foreach ($item in $boundedTargets) {
  if (Test-Path -LiteralPath $item.Path) {
    $resolved = (Resolve-Path -LiteralPath $item.Path).Path
    if ([IO.Path]::GetDirectoryName($resolved) -ne $item.Parent) {
      throw "cleanup target escaped approved parent: $resolved"
    }
  }
}
```

Expected: no exception; no resolved target is the workspace root itself.

- [ ] **Step 3: Record preserved local assets without reading their contents**

```powershell
$preservedExact = @(
  'backend/.env',
  'uploads',
  'frontend/node_modules',
  'frontend/dist',
  'data/generated/longitudinal_150',
  'data/generated/longitudinal_300',
  'data/generated/ad_longitudinal_150',
  'data/generated/ad_longitudinal_300',
  'backend/app/ml_models/datasets',
  'backend/app/ml_models/bundles',
  'backend/app/ml_models/release_sets',
  'backend/app/ml_models/active',
  'backend/app/ml_models/reviews',
  'backend/app/ml_models/activation_log'
)
foreach ($path in $preservedExact) {
  if (-not (Test-Path -LiteralPath $path)) { throw "preserved path missing at baseline: $path" }
}
Get-ChildItem -LiteralPath '.' -Recurse -Force -Directory |
  Where-Object {
    $_.FullName -notlike "$workspaceRoot\.worktrees\*" -and
    $_.Name -in @('.pytest_cache', '__pycache__')
  } |
  Select-Object -ExpandProperty FullName
Get-ChildItem -LiteralPath '.' -Recurse -Force -File -Filter '*.tsbuildinfo' |
  Where-Object { $_.FullName -notlike "$workspaceRoot\.worktrees\*" } |
  Select-Object -ExpandProperty FullName
```

Expected: exact preserved assets exist. Cache and `*.tsbuildinfo` paths are displayed only for audit and are never fed into a deletion command.

---

### Task 1: 建立独立模型路径模块，解除新版 registry 对旧模块的借用

**Files:**
- Create: `backend/app/services/model_paths.py`
- Create: `backend/tests/test_model_paths.py`
- Modify: `backend/app/services/longitudinal_model_registry.py:37`
- Modify: `scripts/check_longitudinal_readiness.py:24`
- Modify: `scripts/tests/test_check_longitudinal_readiness.py`

**Interfaces:**
- Produces: `app.services.model_paths.MODEL_DIR: pathlib.Path`
- Consumes: `Path(__file__).resolve().parents[1] / "ml_models"`
- Later tasks may delete `progression_engine.py` only after all production imports use this interface.

- [ ] **Step 1: Write the failing model path tests**

Create `backend/tests/test_model_paths.py`:

```python
from pathlib import Path


def test_model_dir_points_to_backend_app_ml_models():
    from app.services.model_paths import MODEL_DIR

    expected = Path(__file__).resolve().parents[1] / "app" / "ml_models"
    assert MODEL_DIR == expected


def test_longitudinal_registry_does_not_import_legacy_progression_engine():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "longitudinal_model_registry.py"
    ).read_text(encoding="utf-8")
    assert "from app.services.model_paths import MODEL_DIR" in source
    assert "progression_engine" not in source
```

Append to `scripts/tests/test_check_longitudinal_readiness.py`:

```python
def test_checker_uses_shared_model_path_module():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "from app.services.model_paths import MODEL_DIR" in source
    assert "progression_engine" not in source
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_model_paths.py scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: FAIL because `app.services.model_paths` does not exist and both current consumers import `MODEL_DIR` from `progression_engine`.

- [ ] **Step 3: Create the focused path module**

Create `backend/app/services/model_paths.py`:

```python
"""Filesystem locations shared by longitudinal model services and tools."""

from pathlib import Path


MODEL_DIR = Path(__file__).resolve().parents[1] / "ml_models"
```

Change both consumers to:

```python
from app.services.model_paths import MODEL_DIR
```

Remove their imports from `app.services.progression_engine`.

- [ ] **Step 4: Run GREEN and registry regressions**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_model_paths.py scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: PASS. The two legacy-isolation tests that create fake root-level progression artifacts must remain green.

- [ ] **Step 5: Confirm the production import boundary**

Run:

```powershell
rg -n "from app\.services\.progression_engine|import app\.services\.progression_engine" backend/app scripts -g '!scripts/tests/**' -g '!scripts/train_progression_model.py'
```

Expected: only `backend/app/api/operator.py` may still import `predict_progression`; registry and readiness no longer appear.

- [ ] **Step 6: Review the scoped diff without committing**

```powershell
git diff --check
git diff -- backend/app/services/model_paths.py backend/app/services/longitudinal_model_registry.py backend/tests/test_model_paths.py scripts/check_longitudinal_readiness.py scripts/tests/test_check_longitudinal_readiness.py
```

Expected: no whitespace error; only the shared model path boundary and its tests changed. Leave all changes uncommitted until Task 7.

---

### Task 2: 移除后端旧同步预测 API、服务、训练入口和根级旧模型

**Files:**
- Modify/Rename: `backend/tests/test_operator_predictive_api.py` → `backend/tests/test_operator_catalog_and_reports_api.py`
- Modify: `backend/tests/test_cleanup_contracts.py`
- Modify: `backend/app/api/operator.py:38-54,91-133`
- Delete: all backend/script/model files listed under “Delete: old synchronous progression chain”, except the frontend test handled in Task 3

**Interfaces:**
- Preserves: `/operator/longitudinal-cases`, `/operator/reports`, `/operator/diseases`, `/operator/cases`, `/operator/reference-ranges`, `/operator/documents`
- Removes: `POST /operator/progression-predictions`
- Preserves: `load_active_model_registry(adapter.dataset)` and all report state transitions.

- [ ] **Step 1: Rename the still-valid API test module**

Rename the file and replace its module docstring with:

```python
"""Operator disease catalog, reference cases, reports, and router tests."""
```

Rename `test_predictive_endpoints_registered` to `test_catalog_and_report_endpoints_registered` and make the route contract explicit:

```python
def test_catalog_and_report_endpoints_registered(self):
    from app.api.operator import router

    paths = {route.path for route in router.routes}
    self.assertTrue(
        {
            "/operator/cases",
            "/operator/diseases",
            "/operator/reference-ranges",
            "/operator/documents",
            "/operator/longitudinal-cases",
            "/operator/reports",
        }.issubset(paths)
    )
    self.assertNotIn("/operator/progression-predictions", paths)
    self.assertNotIn("/operator/reference-ranges/sync", paths)
```

- [ ] **Step 2: Add failing cleanup contracts for the old backend chain**

Extend `test_removed_files_do_not_exist` with:

```python
"backend/app/services/progression_engine.py",
"backend/app/services/risk_bands.py",
"backend/app/schemas/progression.py",
"backend/tests/test_progression_engine.py",
"backend/tests/test_progression_api.py",
"scripts/train_progression_model.py",
"scripts/tests/test_train_progression_model.py",
"scripts/tests/fixtures/model-artifact-baseline.json",
"backend/app/ml_models/ad_progression_model.joblib",
"backend/app/ml_models/ad_progression_model.meta.json",
"backend/app/ml_models/fatty_liver_progression_model.joblib",
"backend/app/ml_models/fatty_liver_progression_model.meta.json",
```

Add a production-symbol contract:

```python
def test_old_progression_endpoint_and_imports_are_removed(self):
    operator_source = (
        PROJECT_ROOT / "backend/app/api/operator.py"
    ).read_text(encoding="utf-8")
    self.assertNotIn("/progression-predictions", operator_source)
    self.assertNotIn("schemas.progression", operator_source)
    self.assertNotIn("predict_progression", operator_source)
    self.assertNotIn("_PROGRESSION_DATASETS", operator_source)
```

- [ ] **Step 3: Run RED before any deletion**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_cleanup_contracts.py backend/tests/test_operator_catalog_and_reports_api.py -q
```

Expected: FAIL because the old route, modules, scripts, metadata and local joblib files still exist.

- [ ] **Step 4: Stop for the final deletion confirmation**

Show the user the exact Task 2, Task 4, Task 5 and Task 6 delete lists. Do not run `git rm`, `Remove-Item`, `git worktree remove` or `git branch -d` until the user replies with an explicit instruction to start execution.

- [ ] **Step 5: Remove the old route from `operator.py`**

Delete these imports:

```python
from app.schemas.progression import (
    LongitudinalPredictRequest,
    ProgressionPredictionOut,
)
from app.services.progression_engine import predict_progression
```

Delete `_PROGRESSION_DATASETS` and the complete `create_progression_prediction()` route. Do not alter `_verify_report_owner()` or any route beginning with `/longitudinal-cases`, `/reports`, `/diseases`, `/cases`, `/reference-ranges` or `/documents`.

- [ ] **Step 6: Delete tracked old backend files**

Run only after Step 4 approval:

```powershell
git rm -- `
  backend/app/services/progression_engine.py `
  backend/app/services/risk_bands.py `
  backend/app/schemas/progression.py `
  backend/tests/test_progression_engine.py `
  backend/tests/test_progression_api.py `
  scripts/train_progression_model.py `
  scripts/tests/test_train_progression_model.py `
  scripts/tests/fixtures/model-artifact-baseline.json `
  backend/app/ml_models/ad_progression_model.meta.json `
  backend/app/ml_models/fatty_liver_progression_model.meta.json
```

The root joblib files are ignored local files. Validate each resolved parent first, then delete only those two exact files:

```powershell
$modelRoot = (Resolve-Path -LiteralPath 'backend/app/ml_models').Path
$legacyModels = @(
  'backend/app/ml_models/ad_progression_model.joblib',
  'backend/app/ml_models/fatty_liver_progression_model.joblib'
)
foreach ($candidate in $legacyModels) {
  if (Test-Path -LiteralPath $candidate) {
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if ([IO.Path]::GetDirectoryName($resolved) -ne $modelRoot) {
      throw "legacy model escaped model root: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Force
  }
}
```

- [ ] **Step 7: Run backend GREEN**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest `
  backend/tests/test_cleanup_contracts.py `
  backend/tests/test_operator_catalog_and_reports_api.py `
  backend/tests/test_operator_permissions.py `
  backend/tests/test_longitudinal_case_service.py `
  backend/tests/test_longitudinal_model_registry.py `
  backend/tests/test_longitudinal_readiness_service.py `
  backend/tests/test_longitudinal_prediction_contract.py `
  backend/tests/test_longitudinal_report_persistence.py `
  backend/tests/test_longitudinal_end_to_end.py `
  scripts/tests/test_check_model_artifacts.py `
  scripts/tests/test_check_longitudinal_readiness.py `
  -q
```

Expected: PASS. No test may be removed merely because it exposes a current longitudinal regression.

- [ ] **Step 8: Confirm no production reference remains**

Run:

```powershell
rg -n "progression_engine|schemas\.progression|/operator/progression-predictions|predict_progression\(" backend/app scripts -g '!docs/**'
```

Expected: no output.

- [ ] **Step 9: Review the scoped diff without committing**

```powershell
git diff --check
git diff -- backend/app backend/tests scripts
```

Expected: the diff removes only the legacy synchronous backend chain, preserves the longitudinal services, and has no whitespace errors. Leave it uncommitted until Task 7.

---

### Task 3: 移除前端第二套即时预测界面和状态

**Files:**
- Modify: `frontend/tests/operator-legacy-cleanup.test.mjs`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/api/operator.ts`
- Delete: `frontend/tests/progression-ui-contract.test.mjs`

**Interfaces:**
- Preserves: `LongitudinalCaseEditor`, `LongitudinalPredictionSummary`, `LongitudinalReportView`, report SSE, history loading, PDF download and case library navigation.
- Removes: `predictProgression()`, `ProgressionPredictionOut`, `progressionResult`, `progressionLoading` and the duplicate raw visit form in `OperatorView.vue`.

- [ ] **Step 1: Strengthen the frontend negative contract**

Append to `frontend/tests/operator-legacy-cleanup.test.mjs`:

```javascript
const view = fs.readFileSync(new URL('../src/views/OperatorView.vue', import.meta.url), 'utf8')

for (const legacy of [
  '/v1/operator/progression-predictions',
  'function predictProgression(',
  'interface ProgressionPredictionOut',
  'ProgressionPredictionRequest',
]) {
  if (api.includes(legacy)) throw new Error(`legacy progression API still present: ${legacy}`)
}

for (const legacy of [
  'progressionResult',
  'progressionLoading',
  'predictLongitudinalProgression',
  'clearProgression',
]) {
  if (store.includes(legacy)) throw new Error(`legacy progression store state still present: ${legacy}`)
}

for (const legacy of [
  'progressionVisits',
  'handleProgressionPredict',
  '评估进展风险',
  'progression-risk-card',
]) {
  if (view.includes(legacy)) throw new Error(`duplicate progression UI still present: ${legacy}`)
}
```

- [ ] **Step 2: Run RED**

Run:

```powershell
Set-Location frontend
node --test tests/operator-legacy-cleanup.test.mjs
```

Expected: FAIL on the old API, store and view symbols.

- [ ] **Step 3: Reduce `OperatorView.vue` to the single longitudinal workflow**

The surviving non-report branch must be structurally equivalent to:

```vue
<div v-else class="progression-view">
  <div class="progression-inner">
    <div class="longitudinal-case-actions">
      <el-button @click="startNewLongitudinalCase">新建纵向病例</el-button>
      <el-select
        v-if="operatorStore.longitudinalCases.length"
        :model-value="operatorStore.currentLongitudinalCase?.id"
        placeholder="选择已保存病例"
        @update:model-value="selectLongitudinalCase"
      >
        <el-option
          v-for="item in operatorStore.longitudinalCases"
          :key="item.id"
          :label="item.patient_label"
          :value="item.id"
        />
      </el-select>
    </div>
    <LongitudinalCaseEditor
      :diseases="progressionDiseases"
      :model-value="operatorStore.currentLongitudinalCase"
      @saved="handleLongitudinalCaseSaved"
    />
    <LongitudinalPredictionSummary :prediction="operatorStore.longitudinalPrediction" />
  </div>
</div>
```

Remove imports used only by the deleted UI:

```typescript
import { WarningFilled, Plus, Delete } from '@element-plus/icons-vue'
import IndicatorRowsEditor from '@/components/IndicatorRowsEditor.vue'
```

Remove the local `ProgressionVisitForm`, `emptyVisit`, `nextVisitId`, raw visit state, validation computed, add/remove visit functions, synchronous prediction action and old score/slope formatters. Keep `isValidIndicator()` because `handleLongitudinalCaseSaved()` uses it.

Remove only these obsolete CSS groups:

```text
.progression-heading
.progression-form
.progression-disease-row
.visit-list
.visit-card
.visit-card-head
.visit-indicators
.progression-actions
.progression-result
.progression-disclosures
.progression-disclosure
.disclosure-title
.progression-risk-card
.progression-risk-label
.progression-risk-band
.progression-risk-score
.progression-summary
```

Keep `.progression-view`, `.progression-inner`, `.operator-*`, report Markdown styles and the mobile padding rule for `.progression-view`.

- [ ] **Step 4: Remove old store and API contracts**

In `frontend/src/stores/operator.ts`, remove the imports, refs, functions and returned properties for the old synchronous prediction. The store must still export:

```typescript
longitudinalCases,
currentLongitudinalCase,
longitudinalPrediction,
longitudinalReportContent,
fetchLongitudinalCases,
saveLongitudinalCase,
saveLongitudinalVisit,
generateLongitudinalReport,
```

In `frontend/src/api/operator.ts`, remove the four old progression interfaces and:

```typescript
export function predictProgression(
  data: ProgressionPredictionRequest,
): Promise<ProgressionPredictionOut>
```

Preserve `IndicatorInput`, because both longitudinal case editing and reference case management use it.

- [ ] **Step 5: Delete the obsolete positive legacy UI contract**

Run:

```powershell
git rm -- frontend/tests/progression-ui-contract.test.mjs
```

- [ ] **Step 6: Run frontend GREEN**

Run from `frontend/`:

```powershell
$tests = Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File
foreach ($test in $tests) {
  node --test $test.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
npm run build
```

Expected: every remaining contract test passes and `vue-tsc && vite build` exits 0 using the existing `node_modules/`.

- [ ] **Step 7: Confirm the deleted symbols are absent**

Run:

```powershell
Set-Location ..
rg -n "progression-predictions|ProgressionPredictionOut|predictProgression|progressionResult|progressionLoading|handleProgressionPredict|评估进展风险" frontend/src frontend/tests
```

Expected: no output.

- [ ] **Step 8: Review the scoped diff without committing**

```powershell
git diff --check
git diff -- frontend/src frontend/tests
```

Expected: the diff removes only the duplicate synchronous workflow and its obsolete contract; the retained longitudinal UI remains. Leave it uncommitted until Task 7.

---

### Task 4: 删除已批准的跟踪资料和输出，并同步现行文档

**Files:**
- Modify: `backend/tests/test_cleanup_contracts.py`
- Modify: `README.md`
- Modify: `database/README.md`
- Modify: `docs/DEPLOY.md`
- Modify: `.gitignore`
- Delete: all paths listed under “Delete: approved tracked cleanup”

**Interfaces:**
- Preserves: current deployment docs, Alembic, `database/schema.sql`, all plans, the real-data collection spec, two future-value notes and `outputs/report_method_validation.md`.
- Removes: Claude configuration, old SQL migration archive, rendered artifacts, completed specs, review/validation records and superseded notes.

- [ ] **Step 1: Add exact tracked-path cleanup contracts**

Extend `test_removed_files_do_not_exist` with:

```python
"CLAUDE.md",
".claude",
".superpowers",
"DEPLOYMENT_PLAN.md",
"database/migrations",
"tmp/pdfs",
"output/pdf",
"output/evidence",
"docs/superpowers/reviews",
"docs/superpowers/validation",
"docs/superpowers/notes/2026-08-21-reference-standard-pipeline-audit.md",
"docs/superpowers/notes/2026-08-24-versioned-standard-rules-layer-recommendation.md",
```

Add preservation assertions:

```python
def test_cleanup_preserves_development_and_runtime_assets(self):
    preserved = [
        "AGENTS.md",
        ".agents/skills/git-commit/SKILL.md",
        "backend/.env",
        "uploads",
        "frontend/node_modules",
        "frontend/dist",
        "data/generated/longitudinal_150",
        "data/generated/longitudinal_300",
        "data/generated/ad_longitudinal_150",
        "data/generated/ad_longitudinal_300",
        "research/main.py",
        "outputs/report_method_validation.md",
        "backend/app/ml_models/active/fatty_liver.json",
        "backend/app/ml_models/active/ad.json",
        "docs/superpowers/plans",
        "docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md",
    ]
    for relative_path in preserved:
        self.assertTrue((PROJECT_ROOT / relative_path).exists(), relative_path)
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_cleanup_contracts.py -q
```

Expected: FAIL on approved tracked paths that still exist.

- [ ] **Step 3: Delete the exact tracked paths**

Use `git rm -r --` only with this reviewed list:

```powershell
$trackedCleanup = @(
  'CLAUDE.md',
  '.claude',
  '.superpowers',
  'DEPLOYMENT_PLAN.md',
  'database/migrations',
  'tmp/pdfs',
  'output/pdf',
  'output/evidence',
  'docs/superpowers/reviews',
  'docs/superpowers/validation',
  'docs/superpowers/notes/2026-08-21-reference-standard-pipeline-audit.md',
  'docs/superpowers/notes/2026-08-24-versioned-standard-rules-layer-recommendation.md',
  'docs/superpowers/specs/2026-07-24-project-cleanup-and-alembic-design.md',
  'docs/superpowers/specs/2026-07-24-security-and-versioned-indexing-design.md',
  'docs/superpowers/specs/2026-07-27-ai-operator-module-design.md',
  'docs/superpowers/specs/2026-07-27-development-baseline-design.md',
  'docs/superpowers/specs/2026-07-28-department-filter-design.md',
  'docs/superpowers/specs/2026-08-06-progression-rule-mining-loop-design.md',
  'docs/superpowers/specs/2026-08-18-fatty-liver-case-constrained-data-generation-design.md',
  'docs/superpowers/specs/2026-08-18-fatty-liver-longitudinal-300-extension-design.md',
  'docs/superpowers/specs/2026-08-19-ad-case-constrained-longitudinal-generation-design.md',
  'docs/superpowers/specs/2026-08-19-ad-longitudinal-300-extension-design.md',
  'docs/superpowers/specs/2026-08-20-longitudinal-import-design.md',
  'docs/superpowers/specs/2026-08-20-longitudinal-progression-prediction-design.md',
  'docs/superpowers/specs/2026-08-20-prediction-patient-dedup-design.md',
  'docs/superpowers/specs/2026-08-24-longitudinal-prediction-report-design.md',
  'docs/superpowers/specs/2026-08-24-longitudinal-report-normalization-design.md',
  'docs/superpowers/specs/2026-08-24-versioned-standard-rules-layer-design.md',
  'docs/superpowers/specs/2026-08-25-dedicated-standard-documents-design.md',
  'docs/superpowers/specs/2026-08-25-longitudinal-readiness-design.md',
  'docs/superpowers/specs/2026-08-25-longitudinal-standards-design.md',
  'docs/superpowers/specs/2026-08-25-standard-management-docx-upload-design.md',
  'docs/superpowers/specs/2026-08-26-fixed-window-longitudinal-dataset-design.md',
  'docs/superpowers/specs/2026-08-26-longitudinal-outcome-model-design.md',
  'docs/superpowers/specs/2026-08-26-longitudinal-registry-design.md',
  'docs/superpowers/specs/2026-08-27-longitudinal-model-data-migration-design.md',
  'docs/superpowers/specs/2026-08-27-longitudinal-report-template-design.md',
  'docs/superpowers/specs/2026-08-27-longitudinal-signal-interpreter-design.md'
)
git rm -r -- $trackedCleanup
```

Do not include either preserved spec or any file below `docs/superpowers/plans/`.

- [ ] **Step 4: Update `.gitignore`**

Add a project-local generated content section:

```gitignore
# Project-local temporary and generated outputs
/.tmp/
/.tmp-doc-review/
/.superpowers/
/.claude/
/tmp/
/output/
/research/outputs/
```

Keep all existing rules for `node_modules/`, `dist/`, `.pytest_cache/`, `__pycache__/`, `*.tsbuildinfo`, worktrees and uploads.

- [ ] **Step 5: Update the README current architecture**

Remove the Claude row. Add an AI operator workflow section containing:

```markdown
### AI 操作者纵向报告

1. 保存操作者自有纵向病例和按日期排列的访视指标。
2. 根据疾病和基线阶段选择当前激活的结局、阶段与趋势模型套件。
3. 解析当前批准的参考标准，并选择带来源标记的相似病例证据。
4. 生成严格结构化预测结果，再由确定性模板渲染 Markdown 报告。
5. 持久化输入快照、模型版本、证据、报告正文，并支持历史查看和 PDF 导出。
```

Replace the obsolete database/docs portion of the project tree with:

```text
├── data/generated/         # 双疾病 150/300 例可复现纵向数据
├── database/               # schema.sql 参考快照；正式迁移位于 backend/alembic
├── docs/
│   ├── superpowers/plans/  # 保留的实施计划
│   └── superpowers/specs/  # 尚未落地的采集规范与本次清理规格
├── research/               # 独立方法验证子项目
├── scripts/                # 数据生成、训练、registry、readiness 和诊断工具
├── standard_manifests/     # 双疾病标准 manifest
├── outputs/                # 保留的方法验证结论
└── uploads/                # 运行时上传文件，不进入 Git
```

Change the final database paragraph to:

```markdown
Alembic 是业务表结构的唯一正式迁移入口。`database/schema.sql` 仅作为当前结构参考快照；LangChain 的 `langchain_pg_collection`、`langchain_pg_embedding` 两张内部表仍由 `langchain-postgres` 管理。
```

- [ ] **Step 6: Update `database/README.md`**

Replace “本目录文件职责” with:

```markdown
## 本目录文件职责

| 文件 | 作用 |
| --- | --- |
| `schema.sql` | 当前业务结构的人工核对参考快照，不是正式建库入口 |

所有正式版本变更都位于 `backend/alembic/versions/`。如参考快照与 Alembic 迁移链不一致，以 Alembic 最新 head 为准，并同步修正快照。
```

Delete the instructions that require the removed 006/007/008 SQL archive. Keep the warning that an existing database must be inspected and stamped only at the revision matching its real schema before `alembic upgrade head`; do not claim every legacy database can always stamp `0001`.

- [ ] **Step 7: Update the current deployment guide**

In `docs/DEPLOY.md`, replace the paragraph that describes `database/migrations/` as retained history with:

```markdown
`database/schema.sql` 是当前业务结构的参考快照，不是正式迁移入口。所有正式版本变更均位于 `backend/alembic/versions/`，部署和升级统一使用 Alembic。
```

Do not alter unrelated deployment commands or environment examples.

- [ ] **Step 8: Run document and cleanup GREEN**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_cleanup_contracts.py -q
$currentSpecs = @('docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md')
rg -n "CLAUDE\.md|database/migrations/|DEPLOYMENT_PLAN\.md" README.md database/README.md docs/DEPLOY.md docs/ALIYUN_DEPLOYMENT_RUNBOOK.md docs/superpowers/notes $currentSpecs
```

Expected: cleanup test PASS. The reference scan has no output from current operational docs. Historical implementation plans and the cleanup design itself are intentionally excluded because they preserve the approved deletion record.

- [ ] **Step 9: Review the scoped diff without committing**

```powershell
git diff --check
git diff -- .gitignore README.md database docs/DEPLOY.md docs/superpowers backend/tests/test_cleanup_contracts.py CLAUDE.md .claude .superpowers DEPLOYMENT_PLAN.md tmp output
```

Expected: the diff contains the exact approved documentation/output deletion plus current-document updates, with no plan deletion and no whitespace errors. Leave it uncommitted until Task 7.

---

### Task 5: 安全移除已合并 worktree 和本地分支

**Files:**
- Delete worktrees and local branches listed under “Delete: approved ignored/local cleanup”

**Interfaces:**
- No application interface.
- Final `git worktree list` must contain only the main workspace.

- [ ] **Step 1: Re-check merge ancestry and registered worktree status**

```powershell
$branches = @(
  'codex/longitudinal-report-format-fix',
  'codex/versioned-standard-rules-2026-08-24',
  'claude/ai-operator-001'
)
foreach ($branch in $branches) {
  git merge-base --is-ancestor $branch main
  if ($LASTEXITCODE -ne 0) { throw "branch is not merged into main: $branch" }
}
git -C '.worktrees/longitudinal-report-format-fix' status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'cannot inspect longitudinal report worktree' }
git -C '.worktrees/versioned-standard-rules-2026-08-24' status --porcelain
if ($LASTEXITCODE -ne 0) { throw 'cannot inspect standard rules worktree' }
$longitudinalIgnored = @(git -C '.worktrees/longitudinal-report-format-fix' ls-files --others --ignored --exclude-standard)
$rulesIgnored = @(git -C '.worktrees/versioned-standard-rules-2026-08-24' ls-files --others --ignored --exclude-standard)
"longitudinal-report-format-fix ignored files: $($longitudinalIgnored.Count)"
"versioned-standard-rules ignored files: $($rulesIgnored.Count)"
git worktree list --porcelain
```

Expected: both `status --porcelain` commands have no output and both branches are ancestors of `main`. The ignored-file counts document the disposable dependency/build/cache copies that will leave with the two approved worktrees; the corresponding main-workspace paths remain protected by Tasks 0 and 6.

- [ ] **Step 2: Inspect the unregistered residual directory**

```powershell
$workspaceRoot = (Resolve-Path -LiteralPath '.').Path.TrimEnd('\')
$worktreeRoot = (Resolve-Path -LiteralPath '.worktrees').Path.TrimEnd('\')
$residual = (Resolve-Path -LiteralPath '.worktrees/standard-documents-001').Path
if ([IO.Path]::GetDirectoryName($residual) -ne $worktreeRoot) {
  throw "residual directory escaped .worktrees: $residual"
}
$generatedPattern = '\\frontend\\(?:node_modules|dist)\\|\\(?:__pycache__|\.pytest_cache)\\|\.tsbuildinfo$'
$uniqueResidualFiles = foreach ($file in Get-ChildItem -LiteralPath $residual -Force -Recurse -File) {
  if ($file.FullName -match $generatedPattern) { continue }
  $relative = $file.FullName.Substring($residual.Length).TrimStart('\')
  $blob = (git hash-object -- $file.FullName).Trim()
  git cat-file -e "$blob`^{blob}" 2>$null
  if ($LASTEXITCODE -eq 0) { continue }
  $mainFile = Join-Path $workspaceRoot $relative
  if ((-not (Test-Path -LiteralPath $mainFile)) -or
      ((Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash -ne
       (Get-FileHash -Algorithm SHA256 -LiteralPath $mainFile).Hash)) {
    $relative
  }
}
if ($uniqueResidualFiles) {
  $uniqueResidualFiles
  throw 'residual directory contains files not preserved in Git history or the main workspace'
}
```

Expected: no unique source/document file is reported. Dependency, build and cache copies inside this already-approved residual are excluded from uniqueness classification; the root `frontend/node_modules/`, `frontend/dist/` and caches are not targeted.

- [ ] **Step 3: Remove registered worktrees through Git**

```powershell
git worktree remove '.worktrees/longitudinal-report-format-fix'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git worktree remove '.worktrees/versioned-standard-rules-2026-08-24'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
git worktree prune
```

- [ ] **Step 4: Remove the validated residual directory**

```powershell
if (Test-Path -LiteralPath $residual) {
  Remove-Item -LiteralPath $residual -Recurse -Force
}
```

- [ ] **Step 5: Delete only merged local branches**

```powershell
git branch -d codex/longitudinal-report-format-fix
git branch -d codex/versioned-standard-rules-2026-08-24
git branch -d claude/ai-operator-001
```

- [ ] **Step 6: Verify worktree and branch cleanup**

```powershell
git worktree list --porcelain
git branch --format='%(refname:short)'
Get-ChildItem -LiteralPath '.worktrees' -Force -ErrorAction SilentlyContinue
```

Expected: only the main worktree remains; none of the three branch names or three target directories appears. No source commit is needed for worktree/branch metadata cleanup.

---

### Task 6: 删除已批准的本地临时目录，同时证明保留目录未受影响

**Files:**
- Delete local ignored: `.tmp/`, `.tmp-doc-review/`, `research/outputs/`
- Read only: all preserved local paths

**Interfaces:**
- No source-code interface.
- Produces a local workspace without approved transient directories.

- [ ] **Step 1: Verify the exact cleanup roots**

```powershell
$workspaceRoot = (Resolve-Path -LiteralPath '.').Path.TrimEnd('\')
$localTargets = @('.tmp', '.tmp-doc-review', 'research/outputs')
foreach ($target in $localTargets) {
  if (Test-Path -LiteralPath $target) {
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if ($resolved -ne "$workspaceRoot\$($target -replace '/', '\')") {
      throw "unexpected cleanup target: $resolved"
    }
  }
}
```

Expected: no exception. None of the resolved paths equals the workspace root.

- [ ] **Step 2: Assert preserved local assets before deletion**

```powershell
$preserved = @('backend/.env', 'uploads', 'frontend/node_modules', 'frontend/dist')
foreach ($path in $preserved) {
  if (-not (Test-Path -LiteralPath $path)) { throw "preserved path missing before cleanup: $path" }
}
$cacheSnapshot = @(
  Get-ChildItem -LiteralPath '.' -Recurse -Force -Directory |
    Where-Object {
      $_.FullName -notlike "$workspaceRoot\.worktrees\*" -and
      $_.Name -in @('.pytest_cache', '__pycache__')
    } |
    ForEach-Object { $_.FullName }
)
$tsbuildSnapshot = @(
  Get-ChildItem -LiteralPath '.' -Recurse -Force -File -Filter '*.tsbuildinfo' |
    Where-Object { $_.FullName -notlike "$workspaceRoot\.worktrees\*" } |
    ForEach-Object { $_.FullName }
)
```

- [ ] **Step 3: Delete only the approved local targets**

```powershell
foreach ($target in $localTargets) {
  if (Test-Path -LiteralPath $target) {
    Remove-Item -LiteralPath $target -Recurse -Force
  }
}
```

- [ ] **Step 4: Verify deletion and preservation**

```powershell
foreach ($target in $localTargets) {
  if (Test-Path -LiteralPath $target) { throw "local target still exists: $target" }
}
foreach ($path in $preserved) {
  if (-not (Test-Path -LiteralPath $path)) { throw "preserved path was removed: $path" }
}
foreach ($path in $cacheSnapshot + $tsbuildSnapshot) {
  if (-not (Test-Path -LiteralPath $path)) { throw "preserved cache/build-info path was removed: $path" }
}
git status --short --ignored
```

Expected: approved targets absent; root dependencies, build output, environment, uploads, caches and build-info files still exist. No commit is needed because these targets are ignored or already removed from Git in Task 4.

---

### Task 7: 全链路验证和最终结构验收

**Files:**
- Verify only; fix only failures caused by Tasks 1-6

**Interfaces:**
- Confirms the current longitudinal reporting workflow still loads active model suites, predicts, renders, persists and builds through focused service, persistence, API-contract and frontend tests. It does not call an external LLM or write a live database.
- Confirms the approved delete list is absent and the preserve list is intact.

- [ ] **Step 1: Run static legacy reference scans**

```powershell
rg -n "progression_engine|schemas\.progression|/operator/progression-predictions|ProgressionPredictionOut|predictProgression|progressionResult|progressionLoading|handleProgressionPredict" backend/app frontend/src scripts
$currentSpecs = @('docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md')
rg -n "CLAUDE\.md|database/migrations/|DEPLOYMENT_PLAN\.md" README.md database/README.md docs/DEPLOY.md docs/ALIYUN_DEPLOYMENT_RUNBOOK.md docs/superpowers/notes $currentSpecs
```

Expected: no output. Historical plans and the cleanup design are excluded because their literal old-path lists are intentional audit context, not current entrypoint documentation.

- [ ] **Step 2: Run the focused backend and tooling suite**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest `
  backend/tests/test_cleanup_contracts.py `
  backend/tests/test_model_paths.py `
  backend/tests/test_operator_catalog_and_reports_api.py `
  backend/tests/test_operator_permissions.py `
  backend/tests/test_longitudinal_case_service.py `
  backend/tests/test_longitudinal_evidence.py `
  backend/tests/test_longitudinal_model_registry.py `
  backend/tests/test_longitudinal_model_release.py `
  backend/tests/test_longitudinal_release_set.py `
  backend/tests/test_longitudinal_readiness_service.py `
  backend/tests/test_longitudinal_prediction_contract.py `
  backend/tests/test_longitudinal_signal_interpreter.py `
  backend/tests/test_longitudinal_report_generator.py `
  backend/tests/test_longitudinal_report_persistence.py `
  backend/tests/test_longitudinal_report_acceptance.py `
  backend/tests/test_longitudinal_end_to_end.py `
  backend/tests/test_longitudinal_pdf_contract.py `
  backend/tests/test_pdf_generation.py `
  scripts/tests/test_check_model_artifacts.py `
  scripts/tests/test_check_longitudinal_readiness.py `
  scripts/tests/test_smoke_longitudinal_registry.py `
  -q
```

Expected: PASS. Framework deprecation warnings may remain, but there must be no failure.

- [ ] **Step 3: Run active registry and prediction smoke tests**

```powershell
$env:PYTHONPATH='backend;.'
python scripts/check_model_artifacts.py --registry-dir backend/app/ml_models
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/smoke_longitudinal_registry.py --registry-dir backend/app/ml_models --data-root data/generated
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python scripts/check_longitudinal_readiness.py
$readinessExit = $LASTEXITCODE
if (@(0, 1) -notcontains $readinessExit) { exit $readinessExit }
```

Expected:

- model artifact checker returns valid JSON without a registry exception;
- smoke output has `"status": "passed"` and covers fatty-liver pre-cirrhosis, fatty-liver cirrhosis, AD MCI and uncertain-stage behavior;
- readiness exits 0 for available/degraded or 1 only for an explicit business-level blocked result, never 2; it must not expose a connection string or traceback. This command is inspection-only and must not write the database.

- [ ] **Step 4: Run all remaining frontend contracts and build**

```powershell
Set-Location frontend
$tests = Get-ChildItem -LiteralPath 'tests' -Filter '*.test.mjs' -File
foreach ($test in $tests) {
  node --test $test.FullName
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
```

Expected: all tests PASS; frontend build succeeds without reinstalling dependencies.

- [ ] **Step 5: Run the remaining research fast suite**

```powershell
Set-Location research
$env:PYTHONPATH='.'
python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Set-Location ..
$env:PYTHONPATH='backend;.'
```

Expected: default research suite PASS with its configured slow and acceptance exclusions.

- [ ] **Step 6: Verify exact delete and preserve boundaries**

```powershell
$deleted = @(
  'CLAUDE.md', '.claude', '.superpowers', 'DEPLOYMENT_PLAN.md',
  'database/migrations', 'tmp/pdfs', 'output/pdf', 'output/evidence',
  '.tmp', '.tmp-doc-review', 'research/outputs',
  'backend/app/services/progression_engine.py',
  'backend/app/services/risk_bands.py',
  'backend/app/schemas/progression.py',
  'scripts/train_progression_model.py',
  'frontend/tests/progression-ui-contract.test.mjs'
)
foreach ($path in $deleted) {
  if (Test-Path -LiteralPath $path) { throw "approved delete path still exists: $path" }
}

$preserved = @(
  'AGENTS.md', '.agents', 'backend/.env', 'uploads',
  'frontend/node_modules', 'frontend/dist',
  'data/generated/longitudinal_150', 'data/generated/longitudinal_300',
  'data/generated/ad_longitudinal_150', 'data/generated/ad_longitudinal_300',
  'research/main.py', 'research/tests',
  'backend/app/ml_models/datasets', 'backend/app/ml_models/bundles',
  'backend/app/ml_models/release_sets', 'backend/app/ml_models/active',
  'backend/app/ml_models/reviews', 'backend/app/ml_models/activation_log',
  'outputs/report_method_validation.md',
  'docs/superpowers/plans',
  'docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md',
  'docs/superpowers/specs/2026-08-27-project-structure-cleanup-design.md'
)
foreach ($path in $preserved) {
  if (-not (Test-Path -LiteralPath $path)) { throw "preserved path missing: $path" }
}
```

Expected: no exception.

- [ ] **Step 7: Run Git integrity checks**

```powershell
git diff --check
git status --short --branch
git worktree list --porcelain
git branch --format='%(refname:short)'
```

Expected:

- `git diff --check` exits 0;
- only expected cleanup changes exist;
- only the main worktree remains;
- the three approved local branches are absent;
- the current branch is ahead of `origin/main` only by the previously approved design commit; implementation changes remain uncommitted until the owner reviews this evidence.

- [ ] **Step 8: Show final status and request commit confirmation**

Present the owner with:

- the exact removed paths and retained critical paths;
- test/build/smoke results, including the readiness exit status;
- `git status --short --branch`, `git diff --stat`, worktree list and remaining branch list;
- any warnings or skipped checks.

Do not commit yet. Ask whether to create the single cleanup result commit.

- [ ] **Step 9: Create one cleanup commit only after explicit confirmation**

If the owner confirms, stage the reviewed repository changes and commit:

```powershell
git add -A
git diff --cached --check
git status --short
git commit -m "chore: clean obsolete project structure"
```

Expected: the commit contains only Tasks 1-4 source/document changes and tracked deletions. Ignored local directory, worktree and local branch cleanup does not enter the commit. Do not push.

- [ ] **Step 10: Commit verification-only fixes if required after owner review**

If the final owner review exposes a cleanup-caused issue after the main commit and a minimal fix is necessary, re-run the affected verification, show the exact diff, and create a focused follow-up commit only after confirmation. If no fix is necessary, do not create an empty commit.

## Final Review Checklist

- [ ] Every design requirement maps to a task above.
- [ ] The old synchronous progression chain is absent while the active release-set chain remains operational.
- [ ] Disease/reference-case/report coverage remains after renaming the misleading predictive API test module.
- [ ] Registry and readiness still reject fake legacy root artifacts.
- [ ] The retained frontend uses one longitudinal case-entry workflow and the existing design tokens.
- [ ] The exact 26 completed old specs are deleted; the real-data collection spec and cleanup spec remain.
- [ ] All plans, four generated datasets, research source, current model audit trail, `.env`, uploads, dependencies, build output and caches remain.
- [ ] Worktree and branch deletion occurred only after clean/merged checks.
- [ ] No database writes, external LLM calls, model downloads, retraining or pushes occurred.
