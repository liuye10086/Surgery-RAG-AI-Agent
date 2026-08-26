# P0-05 纵向模型 Registry、状态与推理契约 Implementation Plan

> 日期：2026-08-26  
> 状态：已获项目所有者审批并按计划实施；实际验证结果记录于路线图 P0-05  
> 依据：`docs/superpowers/specs/2026-08-26-longitudinal-registry-design.md`
>
> **For agentic workers:** 本计划必须由单 Agent 在当前工作区执行；禁止创建 git worktree、子 Agent、自动 commit 或 push。步骤使用 checkbox（`- [ ]`）跟踪。设计和计划均获项目所有者明确批准后，才可进入 Task 1。

**Goal:** 建立唯一、严格、任务感知的纵向模型 registry、发布状态和推理契约，使 AI 操作者报告能够准确说明每个模型是否实际参与本次预测、使用了哪个任务和版本，以及不能使用的稳定原因。

**Architecture:** 使用共享严格 schema 定义三个正式 outcome 任务、artifact 生命周期、运行时状态和稳定 reason code；任务路由、artifact 验证、review/enable、readiness、artifact checker 和线上推理全部复用同一契约。P0-04 训练器重新导出完整 candidate bundle，文件式 registry 保存不可变 review/enable 记录；新纵向报告使用 `longitudinal_prediction.v2`，旧 progression API 与旧 artifact 完全隔离。

**Tech Stack:** Python 3.11、Pydantic 2.10、scikit-learn 1.9.0、joblib 1.5.3、NumPy 2.3.5、pandas 3.0.3、FastAPI、pytest、Vue 3、TypeScript、Element Plus、Node 内置测试运行器、PowerShell。

## Global Constraints

- 全程单 Agent，在当前工作区直接工作，不创建 git worktree。
- 不自动 commit 或 push；所有计划中的阶段性检查只使用 `git diff`、`git status` 和测试命令。
- 开始实现前再次确认项目所有者已明确通过本实施计划。
- 严格 TDD：每个能力先写失败测试，运行并记录 RED，再实现，再运行 GREEN 和相关回归。
- 不做占位实现、模拟概率、伪造 metadata、重命名旧 artifact 或只满足测试的最小验证实现。
- artifact 生命周期只能是 `candidate | reviewed | enabled`；运行时加载状态只能是 `available | missing | incompatible | disabled`，不得混用。
- 生产推理只允许完整契约通过、有效生命周期为 `enabled` 且有效 `production_enabled=true` 的 artifact。有效状态由不可变链条计算：candidate metadata 为 `candidate/false`，review record 为 `reviewed/false`，release record 为 `enabled/true`；不得回写或改造模型及 candidate metadata。
- 脂肪肝任务固定为 `fatty_liver.pre_cirrhosis_to_progression` 和 `fatty_liver.cirrhosis_to_hcc`；AD 固定为 `ad.pre_dementia_to_dementia`。
- AD 继续只做明确 `dementia_date` 的 365 天二分类，不建立多阶段 CDR 模型。
- 不训练 stage/trend 模型；缺少它们时准确报告状态，不让整份报告失败。
- 不修改数据库 schema、Alembic migration 或 ORM 列；前端基线阶段控件复用现有 `baseline_stage`。
- 不新增 age 字段，不从患者标签、notes、指标、疾病名称或参考病例猜年龄。
- 训练 CLI 不得 review、enable、更新生产 registry 或自动写入 `backend/app/ml_models/`。
- 未经项目所有者批准具体 candidate，不把任何新 artifact 或发布记录写入生产目录。
- 新 registry 明确忽略 `*_progression_model.*`；旧 `/progression-predictions` 和 `progression_engine.py` 既有语义保持不变。
- artifact 静态检查不得调用 `predict` 或 `predict_proba`。
- 对外错误不得包含绝对路径、患者身份、数据库 URL、密码或 traceback。
- 所有 Python 验证命令在 PowerShell 中先设置 `$env:PYTHONPATH='backend;.'`。
- UI 修改前必须遵循已读取的 `docs/DESIGN_SPEC.md`，优先使用现有 CSS 变量、Element Plus 组件和无障碍规范。
- 保留工作区已有用户改动 `outputs/report_method_validation.md`，不覆盖、不暂存、不删除。
- 不删除 `.superpowers/sdd`、outputs、旧脚本或旧模型以规避测试失败。

---

## 文件与职责边界

### 新增文件

- `backend/app/schemas/longitudinal_model_registry.py`：任务、阶段路由、artifact metadata、发布记录、运行时状态和 reason code 的唯一严格 schema。
- `backend/app/services/longitudinal_task_routing.py`：疾病感知的 `baseline_stage` 归一化、冲突检测和任务选择。
- `backend/app/services/longitudinal_model_release.py`：candidate review、enable 和不可变文件式 registry 写入。
- `scripts/manage_longitudinal_registry.py`：显式 review/enable CLI，输出安全 JSON。
- `backend/tests/test_longitudinal_task_routing.py`：脂肪肝/AD 路由、疑似、未知、冲突和终末阶段测试。
- `backend/tests/test_longitudinal_model_release.py`：review/enable、hash、冲突、路径安全和不可覆盖测试。
- `scripts/tests/test_manage_longitudinal_registry.py`：CLI 参数、安全输出和非生产默认行为测试。
- `frontend/tests/longitudinal-baseline-stage.test.mjs`：疾病感知阶段选项、保存和疾病切换清理契约。

### 主要修改文件

- `backend/app/schemas/longitudinal_model_training.py`：使 P0-04 candidate metadata 能表达 P0-05 所需完整字段，同时训练阶段仍只允许 candidate。
- `backend/app/services/longitudinal_model_training.py`：导出完整、可 hash 验证的 candidate bundle，不写生产 registry。
- `scripts/train_longitudinal_outcome_models.py`：保持 audit/train 边界，返回完整 candidate 摘要。
- `backend/app/services/longitudinal_model_registry.py`：替换为任务级发现、静态验证和受控加载实现。
- `scripts/check_model_artifacts.py`：复用共享验证器，增加 P0-05 registry/bundle 检查模式。
- `backend/app/services/longitudinal_readiness.py`：移除独立的旧 outcome 校验规则，复用 registry 验证结果。
- `backend/app/schemas/longitudinal_readiness.py`：按任务表达 outcome readiness，同时兼容既有 readiness 顶层结构。
- `backend/app/services/longitudinal_features.py`：增加与 P0-04 fixed-window 一致的线上特征映射接口。
- `backend/app/services/longitudinal_prediction.py`：使用任务路由、registry 状态和严格输入契约执行 outcome 推理。
- `backend/app/services/disease_progression.py`：将无模型时的观察斜率从“未来预测”中分离，保留纯观察能力。
- `backend/app/schemas/longitudinal_report.py`：新增 `longitudinal_prediction.v2` 和 outcome/stage/trend 独立状态。
- `backend/app/services/longitudinal_report_generator.py`：根据 v2 状态渲染准确文字并安全处理异常，同时兼容 v1 历史结果。
- `backend/app/api/operator.py`：在创建报告前传递任务路由和任务级 registry，不改变旧 progression route。
- `backend/app/schemas/longitudinal_case.py`：仅收紧/记录受控 `baseline_stage` 输入的后端兼容行为，不增加数据库列。
- `frontend/src/components/LongitudinalCaseEditor.vue`：增加疾病感知的基线阶段 `el-select`。
- `frontend/src/views/OperatorView.vue`：保存时传递 `baseline_stage`。
- `frontend/src/api/operator.ts`：增加阶段规范类型和 v2 prediction 类型。
- `frontend/src/stores/operator.ts`：保留并提交 `baseline_stage`。
- 相关 backend、scripts、frontend 测试文件。

### 明确不修改

- `backend/alembic/`
- `backend/app/db/models.py`
- `backend/app/schemas/progression.py`
- `backend/app/services/progression_engine.py` 的既有语义和旧文件名
- `scripts/train_progression_model.py`
- `scripts/train_longitudinal_models.py`
- `backend/app/ml_models/` 中的现有文件
- P0-03 数据集标签语义和三个 P0-04 任务定义

---

### Task 1: 定义唯一 Registry、发布和运行时状态契约

**Files:**
- Create: `backend/app/schemas/longitudinal_model_registry.py`
- Modify: `backend/app/schemas/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_registry.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `REGISTRY_SCHEMA_VERSION = "longitudinal_model_registry.v1"`。
- Produces `ARTIFACT_METADATA_SCHEMA_VERSION = "longitudinal_outcome_artifact.v1"`。
- Produces `RELEASE_RECORD_SCHEMA_VERSION = "longitudinal_model_release.v1"`。
- Produces `ArtifactLifecycle`, `RuntimeLoadStatus`, `ArtifactType`, `TaskName`, `RoutingStatus` literal aliases。
- Produces `TASK_CONTRACTS: dict[TaskName, RegistryTaskContract]`。
- Produces strict models `FeatureContract`, `PackageCompatibility`, `ScoreContract`, `CalibrationContract`, `ArtifactMetadata`, `ReviewRecord`, `ReleaseRecord`, `ModelRuntimeStatus`, `LoadedModelEntry`, `LongitudinalModelRegistry`。
- `ModelRuntimeStatus` is the shared result consumed by readiness, prediction, checker and report schema tasks。

- [ ] **Step 1: Write failing schema and vocabulary tests**

Add tests with exact assertions:

```python
from pydantic import ValidationError

from app.schemas.longitudinal_model_registry import (
    ARTIFACT_METADATA_SCHEMA_VERSION,
    TASK_CONTRACTS,
    ArtifactMetadata,
    ModelRuntimeStatus,
)


def test_registry_task_contracts_are_exact():
    assert set(TASK_CONTRACTS) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "ad.pre_dementia_to_dementia",
    }
    assert TASK_CONTRACTS["fatty_liver.cirrhosis_to_hcc"].target == "hcc"
    assert TASK_CONTRACTS["ad.pre_dementia_to_dementia"].horizon_days == 365


def test_runtime_status_does_not_accept_lifecycle_values():
    with pytest.raises(ValidationError):
        ModelRuntimeStatus(
            artifact_type="outcome",
            status="candidate",
            reason_code="lifecycle_not_enabled",
        )


def test_candidate_metadata_cannot_claim_reviewed_or_enabled_lifecycle():
    payload = _valid_artifact_metadata()
    payload.update(status="enabled", production_enabled=True)
    with pytest.raises(ValidationError):
        ArtifactMetadata.model_validate(payload)


def test_review_and_release_records_own_later_lifecycle_states():
    review = ReviewRecord.model_validate(_valid_review_record())
    release = ReleaseRecord.model_validate(_valid_release_record())
    assert (review.status, review.production_enabled) == ("reviewed", False)
    assert (release.status, release.production_enabled) == ("enabled", True)


def test_training_metadata_still_rejects_reviewed_or_enabled_output():
    from app.schemas.longitudinal_model_training import ModelMetadata
    with pytest.raises(ValidationError):
        ModelMetadata(**_valid_metadata_kwargs(status="reviewed"))
```

`_valid_artifact_metadata()` must include the exact task, disease, current state, target, horizon, feature schema/version, ordered features, order SHA-256, missing-feature policy, dataset hashes, model SHA-256, model identity/version, package versions, score semantics, calibration status, lifecycle and timestamps. Use 64 lowercase hexadecimal characters for every SHA-256 fixture.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_model_training.py -q
```

Expected: collection fails because `app.schemas.longitudinal_model_registry` does not exist.

- [ ] **Step 3: Implement strict registry schemas**

Use `ConfigDict(extra="forbid")` for every persisted or returned contract. Define exact literals:

```python
ArtifactLifecycle = Literal["candidate", "reviewed", "enabled"]
RuntimeLoadStatus = Literal["available", "missing", "incompatible", "disabled"]
ArtifactType = Literal["outcome", "stage", "trend"]
RoutingStatus = Literal["selected", "not_estimable"]
TaskName = Literal[
    "fatty_liver.pre_cirrhosis_to_progression",
    "fatty_liver.cirrhosis_to_hcc",
    "ad.pre_dementia_to_dementia",
]
```

`ArtifactMetadata` must require:

```python
schema_version: Literal["longitudinal_outcome_artifact.v1"]
artifact_type: Literal["outcome"]
task: TaskName
dataset: Literal["fatty_liver", "ad"]
disease: Literal["脂肪肝", "阿尔茨海默病"]
current_state: Literal["pre_cirrhosis", "cirrhosis", "pre_dementia"]
target: Literal["cirrhosis_or_hcc", "hcc", "dementia"]
horizon_days: Literal[365]
feature_contract: FeatureContract
dataset_contract: DatasetContract
model_contract: ModelContract
score_contract: ScoreContract
calibration: CalibrationContract
audit: ArtifactAuditContract
status: Literal["candidate"]
production_enabled: Literal[False]
created_at: datetime
```

Validators must compare all task-owned fields with `TASK_CONTRACTS` and reject uncalibrated metadata whose score semantics claims clinical probability. `ReviewRecord` alone owns `status="reviewed"` and `production_enabled=false`. `ReleaseRecord` owns `status="enabled"` and a required boolean `production_enabled`; the management service may only create it as `true`, while the loader must safely report a tampered/administratively disabled `false` record as `disabled/production_disabled`. `ModelRuntimeStatus.lifecycle_status` reports the effective lifecycle reached by the validated chain, not merely the candidate metadata field.

`ModelRuntimeStatus` must include nullable `task`, `lifecycle_status`, `model_id`, `model_name`, `model_version`, `artifact_sha256`, `target`, `horizon_days`, `feature_version`, `score_semantics`, `calibration_status`, plus `status` and `reason_code`. Add a validator that prevents identity fields from being populated for `missing` unless they came from a valid release record.

- [ ] **Step 4: Make P0-04 training metadata consume the shared contract without allowing publication**

Update `ModelMetadata` so the writer can construct a complete candidate `ArtifactMetadata`, but retain a validator that rejects any training output with `status != "candidate"` or `production_enabled=true`. Re-export `TASK_SPECS` from the existing training schema for current P0-04 callers; do not duplicate task values independently.

- [ ] **Step 5: Run focused tests and verify GREEN**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_model_training.py -q
```

Expected: all schema/vocabulary tests pass; existing legacy registry-empty tests still pass until Task 4 replaces the loader.

- [ ] **Step 6: Review diff without committing**

```powershell
git diff --check
git status --short
```

Expected: only approved P0-05 schema/test files plus the pre-existing `outputs/report_method_validation.md` modification are present.

### Task 2: 实现严格、不可猜测的基线阶段任务路由

**Files:**
- Create: `backend/app/services/longitudinal_task_routing.py`
- Create: `backend/tests/test_longitudinal_task_routing.py`
- Modify: `backend/app/schemas/longitudinal_case.py`
- Test: `backend/tests/test_longitudinal_case_service.py`

**Interfaces:**
- Consumes `TASK_CONTRACTS`, `TaskName`, `RoutingStatus` from Task 1。
- Produces `BaselineStageRoute` strict model。
- Produces `normalize_baseline_stage(dataset: str, raw_stage: object) -> BaselineStageRoute`。
- Produces `route_outcome_task(dataset: str, raw_stage: object) -> BaselineStageRoute`。
- `BaselineStageRoute` fields: `dataset`, `routing_status`, `normalized_stage`, `task`, `reason_code`。

- [ ] **Step 1: Write failing route tests**

```python
@pytest.mark.parametrize(
    ("stage", "task"),
    [
        ("pre_cirrhosis", "fatty_liver.pre_cirrhosis_to_progression"),
        ("未肝硬化", "fatty_liver.pre_cirrhosis_to_progression"),
        ("cirrhosis", "fatty_liver.cirrhosis_to_hcc"),
        ("肝硬化", "fatty_liver.cirrhosis_to_hcc"),
    ],
)
def test_fatty_liver_routes_by_confirmed_baseline(stage, task):
    result = route_outcome_task("fatty_liver", stage)
    assert result.routing_status == "selected"
    assert result.task == task
    assert result.reason_code == "task_selected"


def test_suspected_cirrhosis_is_recognized_but_not_guessed():
    result = route_outcome_task("fatty_liver", "疑似肝硬化")
    assert result.routing_status == "not_estimable"
    assert result.normalized_stage == "suspected_cirrhosis"
    assert result.reason_code == "baseline_stage_uncertain"
    assert result.task is None


@pytest.mark.parametrize("stage", ["normal", "mci", "pre_dementia", "认知正常", "轻度认知障碍"])
def test_ad_pre_dementia_stages_route_to_one_task(stage):
    assert route_outcome_task("ad", stage).task == "ad.pre_dementia_to_dementia"


@pytest.mark.parametrize(
    ("dataset", "stage", "reason"),
    [
        ("fatty_liver", None, "baseline_stage_missing"),
        ("fatty_liver", "S1", "baseline_stage_unknown"),
        ("fatty_liver", "hcc", "task_not_applicable_terminal_stage"),
        ("ad", "dementia", "task_not_applicable_terminal_stage"),
        ("ad", "肝硬化", "baseline_stage_disease_conflict"),
        ("fatty_liver", "未肝硬化/肝硬化", "baseline_stage_conflict"),
    ],
)
def test_non_routable_baselines_have_stable_reasons(dataset, stage, reason):
    result = route_outcome_task(dataset, stage)
    assert result.routing_status == "not_estimable"
    assert result.reason_code == reason
    assert result.task is None
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_task_routing.py backend/tests/test_longitudinal_case_service.py -q
```

Expected: route module tests fail because interfaces do not exist.

- [ ] **Step 3: Implement controlled aliases and conflict detection**

Create explicit maps, not substring classification:

```python
FATTY_LIVER_ALIASES = {
    "pre_cirrhosis": "pre_cirrhosis",
    "fatty_liver": "pre_cirrhosis",
    "脂肪肝": "pre_cirrhosis",
    "未肝硬化": "pre_cirrhosis",
    "非肝硬化": "pre_cirrhosis",
    "cirrhosis": "cirrhosis",
    "肝硬化": "cirrhosis",
    "suspected_cirrhosis": "suspected_cirrhosis",
    "疑似肝硬化": "suspected_cirrhosis",
    "hcc": "hcc",
    "肝癌": "hcc",
    "肝细胞癌": "hcc",
}
AD_ALIASES = {
    "normal": "normal",
    "认知正常": "normal",
    "mci": "mci",
    "轻度认知障碍": "mci",
    "pre_dementia": "pre_dementia",
    "痴呆前": "pre_dementia",
    "dementia": "dementia",
    "痴呆": "dementia",
}
```

Normalize whitespace, lowercase English and convert spaces/hyphens to underscores. Detect multiple explicit values separated by `/`, `|`, `,`, `，`, `;`, `；`; if they map to more than one normalized stage, return `baseline_stage_conflict`. Do not log or include raw values in the returned reason.

- [ ] **Step 4: Preserve backend input compatibility**

Keep `baseline_stage: str | None` in the API schema because existing records may contain legacy text. Add only a length/trim validator and tests proving canonical frontend values round-trip while `S1` remains storable but becomes `baseline_stage_unknown` at routing time. Do not add a database enum or migration.

- [ ] **Step 5: Run route and case tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_task_routing.py backend/tests/test_longitudinal_case_service.py -q
```

Expected: all tests pass.

### Task 3: 重新导出契约完整的 P0-04 Candidate Bundle

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Modify: `scripts/train_longitudinal_outcome_models.py`
- Modify: `backend/tests/test_longitudinal_model_training.py`
- Modify: `scripts/tests/test_train_longitudinal_outcome_models.py`
- Test: `scripts/tests/test_check_model_artifacts.py`

**Interfaces:**
- Consumes `ArtifactMetadata` and task contracts from Task 1。
- Produces `CandidateBundleResult` containing `bundle_dir`, `model_path`, `metadata_path`, validated metadata and hashes。
- Produces `write_candidate_bundle(result, bundle_root: Path) -> CandidateBundleResult`。
- Candidate layout: `<output-dir>/<task-stem>/<task-stem>.joblib` and `<output-dir>/<task-stem>/<task-stem>.meta.json`。

- [ ] **Step 1: Write failing full-metadata tests**

```python
def test_candidate_bundle_contains_complete_p005_metadata(tmp_path):
    result = _train_small_candidate(tmp_path)
    bundle = write_candidate_bundle(result, tmp_path / "bundles")
    metadata = ArtifactMetadata.model_validate_json(
        bundle.metadata_path.read_text(encoding="utf-8")
    )
    assert metadata.status == "candidate"
    assert metadata.production_enabled is False
    assert metadata.artifact_type == "outcome"
    assert bundle.model_path.name == "fatty_liver_pre_cirrhosis_to_progression_365d.joblib"
    assert bundle.metadata_path.name == "fatty_liver_pre_cirrhosis_to_progression_365d.meta.json"
    assert metadata.horizon_days == 365
    assert metadata.model_contract.artifact_sha256 == sha256_file(bundle.model_path)
    assert metadata.feature_contract.feature_names[-1] == "sex"
    assert "age" in metadata.feature_contract.allowed_missing_features
    assert metadata.feature_contract.input_container == "pandas_dataframe"
    assert metadata.score_contract.semantics == "model_score"
    assert metadata.calibration.status == "not_calibrated"


def test_candidate_bundle_is_task_scoped_and_never_overwrites(tmp_path):
    result = _candidate_result_fixture("ad.pre_dementia_to_dementia")
    first = write_candidate_bundle(result, tmp_path / "bundles")
    assert first.bundle_dir.name == "ad_pre_dementia_to_dementia_365d"
    with pytest.raises(FileExistsError):
        write_candidate_bundle(result, tmp_path / "bundles")


def test_training_cli_never_creates_review_or_release_records(tmp_path):
    payload = run_training(DATASET_DIR, tmp_path / "candidate-output", seed=42)
    assert payload["status"] == "candidate"
    assert not list((tmp_path / "candidate-output").rglob("review*.json"))
    assert not list((tmp_path / "candidate-output").rglob("release*.json"))
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_training.py scripts/tests/test_train_longitudinal_outcome_models.py scripts/tests/test_check_model_artifacts.py -q
```

Expected: failures because current metadata is incomplete and bundle writer does not exist.

- [ ] **Step 3: Build metadata from actual fitted pipeline and dataset contract**

After fitting, collect exact runtime/build information with `sys.version_info`, `sklearn.__version__`, `joblib.__version__`, `numpy.__version__`, `pandas.__version__`. Set:

```python
feature_schema = "longitudinal_fixed_window_features.v1"
feature_version = "longitudinal_fixed_window_features.v1"
input_container = "pandas_dataframe"
required_features = ["visit_count", "observation_span_days", "days_since_previous_visit"]
allowed_missing_features = [name for name in feature_names if name not in required_features]
numeric_imputation = "median_add_indicator"
categorical_imputation = "most_frequent"
positive_class = 1
score_semantics = "model_score"
calibration_status = "not_calibrated"
```

Derive `feature_order_sha256` from compact UTF-8 JSON of the ordered list. Write the task-named `.joblib` first, calculate its SHA-256, then validate and write the task-named `.meta.json` through `ArtifactMetadata`. Generate a stable model ID from task and model SHA-256 prefix; generate a timestamped model version that is recorded, not inferred from filename. Assert the two filenames map back to `metadata.task`; never accept generic outcome names or legacy `*_progression_model.*` names.

- [ ] **Step 4: Keep the training CLI candidate-only**

Update `run_training()` to create three task subdirectories and return filenames, task, model ID/version and hashes. Retain `--export-artifact` rejection. Do not add review/enable flags to this CLI.

- [ ] **Step 5: Run P0-04 training/export tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py scripts/tests/test_train_longitudinal_outcome_models.py scripts/tests/test_check_model_artifacts.py -q
```

Expected: all tests pass and no files are written to `backend/app/ml_models/`.

### Task 4: 实现唯一静态 Artifact 验证器和任务级 Registry 加载器

**Files:**
- Rewrite: `backend/app/services/longitudinal_model_registry.py`
- Modify: `backend/tests/test_longitudinal_model_registry.py`

**Interfaces:**
- Consumes `ArtifactMetadata`, `ReleaseRecord`, `ModelRuntimeStatus`, `LoadedModelEntry`, `TASK_CONTRACTS`。
- Produces `validate_candidate_bundle(bundle_dir: Path, *, inspect_model: bool = True) -> ArtifactValidationResult`。
- Produces `validate_release_record(release_path: Path, registry_root: Path) -> ArtifactValidationResult`。
- Produces `load_task_model(task: TaskName, registry_root: Path, *, production: bool = True) -> LoadedModelEntry`。
- Produces `load_model_registry(dataset: str, registry_root: Path = MODEL_DIR, *, production: bool = True) -> LongitudinalModelRegistry`。
- Produces `empty_optional_model_status(artifact_type: Literal["stage", "trend"], reason_code: str) -> ModelRuntimeStatus`。

- [ ] **Step 1: Write failing validation matrix tests**

Add parametrized tests that mutate one valid bundle/release at a time:

```python
@pytest.mark.parametrize(
    ("mutation", "expected_status", "reason"),
    [
        ("model_missing", "missing", "artifact_missing"),
        ("metadata_missing", "missing", "metadata_missing"),
        ("release_missing", "missing", "release_record_missing"),
        ("metadata_json_broken", "incompatible", "metadata_invalid"),
        ("schema_wrong", "incompatible", "metadata_schema_mismatch"),
        ("artifact_type_wrong", "incompatible", "artifact_type_mismatch"),
        ("filename_task_wrong", "incompatible", "filename_task_mismatch"),
        ("task_wrong", "incompatible", "task_mismatch"),
        ("dataset_wrong", "incompatible", "dataset_mismatch"),
        ("disease_wrong", "incompatible", "disease_mismatch"),
        ("target_wrong", "incompatible", "target_mismatch"),
        ("horizon_wrong", "incompatible", "horizon_mismatch"),
        ("feature_version_wrong", "incompatible", "feature_schema_mismatch"),
        ("feature_names_duplicate", "incompatible", "feature_names_invalid"),
        ("feature_order_wrong", "incompatible", "feature_order_mismatch"),
        ("dataset_hash_wrong", "incompatible", "dataset_hash_mismatch"),
        ("artifact_hash_wrong", "incompatible", "artifact_hash_mismatch"),
        ("metadata_hash_wrong", "incompatible", "metadata_hash_mismatch"),
        ("review_hash_wrong", "incompatible", "integrity_chain_broken"),
        ("package_wrong", "incompatible", "package_incompatible"),
        ("score_semantics_wrong", "incompatible", "score_semantics_invalid"),
        ("calibration_wrong", "incompatible", "calibration_contract_invalid"),
        ("candidate_without_review", "disabled", "lifecycle_not_enabled"),
        ("reviewed_without_release", "disabled", "lifecycle_not_enabled"),
        ("release_production_false", "disabled", "production_disabled"),
    ],
)
def test_static_validation_returns_stable_status_and_reason(valid_release, mutation, expected_status, reason):
    _apply_mutation(valid_release, mutation)
    result = validate_release_record(valid_release.release_path, valid_release.registry_root)
    assert result.status.status == expected_status
    assert result.status.reason_code == reason
```

Also add:

```python
def test_static_validation_never_executes_prediction(valid_release, monkeypatch):
    valid_release.replace_model_with_serialized_spy_that_raises_on_prediction()
    result = validate_release_record(valid_release.release_path, valid_release.registry_root)
    assert result.prediction_executed is False


def test_multiple_enabled_release_records_reject_the_whole_task(tmp_path):
    _write_enabled_release(tmp_path, version="v1")
    _write_enabled_release(tmp_path, version="v2")
    entry = load_task_model("ad.pre_dementia_to_dementia", tmp_path)
    assert entry.status.status == "incompatible"
    assert entry.status.reason_code == "multiple_enabled_artifacts"
    assert entry.model is None


def test_legacy_progression_artifacts_are_ignored(tmp_path):
    _write_legacy_progression_pair(tmp_path)
    registry = load_model_registry("fatty_liver", tmp_path)
    assert registry.outcomes["fatty_liver.pre_cirrhosis_to_progression"].status.reason_code == "release_record_missing"
```

- [ ] **Step 2: Run registry tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_registry.py -q
```

Expected: failures because task-aware validator and returned types do not exist.

- [ ] **Step 3: Implement path-safe release discovery and static validation**

Registry layout:

```text
<registry-root>/bundles/<model-id>/<task-stem>.joblib
<registry-root>/bundles/<model-id>/<task-stem>.meta.json
<registry-root>/reviews/<review-id>.json
<registry-root>/releases/<task-stem>/<release-id>.json
```

Resolve every release-relative path with `Path.resolve()` and verify it is under `registry_root.resolve()` before reading. Discover only `releases/<task-stem>/*.json`; never glob arbitrary joblib files. Sort only for deterministic error reporting, not for selection.

Run all JSON/schema/task/hash/package checks before `joblib.load`. When `inspect_model=true`, deserialize only after those checks and perform the same static interface inspection used by production loading; never call `predict` or `predict_proba`. Candidate bundle validation reports effective lifecycle `candidate`; a valid review without release reports `reviewed`; a valid enabled release reports `enabled`. Package compatibility policy for v1: Python major/minor, sklearn, joblib, NumPy and pandas must exactly match metadata; return `package_incompatible` on mismatch. This conservative policy can be loosened only in a later approved design.

- [ ] **Step 4: Load only validated enabled artifacts**

After static checks pass, call `joblib.load(model_path)`. Verify:

```python
callable(model.predict_proba)
hasattr(model, "classes_")
set(model.classes_) == {0, 1}
pipeline has a named "preprocess" step
pipeline has a named "classifier" step
```

Do not invoke prediction. Convert load/interface errors to `artifact_load_failed` or `model_interface_incompatible` without returning exception text.

Verify the fitted preprocessing contract as static object inspection: `preprocess` must consume the exact numeric/categorical feature lists in metadata; numeric imputation must be `median` with missing indicators enabled; sex imputation must be `most_frequent` followed by `OneHotEncoder(handle_unknown="ignore")`. A mismatching pipeline is `model_interface_incompatible`. Add dedicated corrupted-joblib and wrong-interface tests for `artifact_load_failed` and `model_interface_incompatible`.

For the current phase, create explicit stage status `missing/stage_model_missing` and a disease-level trend status `missing/trend_model_missing`; do not scan or load unapproved legacy trend files as P0-05 models.

- [ ] **Step 5: Run registry tests and verify GREEN**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_registry.py -q
```

Expected: complete validation matrix passes, including no prediction execution.

### Task 5: 实现不可变 Review/Enable 流程和安全管理 CLI

**Files:**
- Create: `backend/app/services/longitudinal_model_release.py`
- Create: `scripts/manage_longitudinal_registry.py`
- Create: `backend/tests/test_longitudinal_model_release.py`
- Create: `scripts/tests/test_manage_longitudinal_registry.py`

**Interfaces:**
- Consumes `validate_candidate_bundle`, `validate_release_record`, `ReviewRecord`, `ReleaseRecord`。
- Produces `review_candidate(bundle_dir: Path, registry_root: Path, *, reviewer: str, reviewed_at: datetime, note: str) -> ReviewRecord`。
- Produces `enable_review(review_path: Path, registry_root: Path, *, enabled_by: str, enabled_at: datetime) -> ReleaseRecord`。
- Produces CLI subcommands `review` and `enable`。

- [ ] **Step 1: Write failing review/enable tests**

```python
def test_review_requires_identity_time_note_and_matching_hashes(valid_bundle, tmp_path):
    record = review_candidate(
        valid_bundle.bundle_dir,
        tmp_path / "registry",
        reviewer="owner-1",
        reviewed_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        note="P0-05 temporary contract review",
    )
    assert record.model_sha256 == sha256_file(valid_bundle.model_path)
    assert record.metadata_sha256 == sha256_file(valid_bundle.metadata_path)
    assert record.reviewer == "owner-1"


def test_enable_revalidates_review_and_refuses_conflicting_task(valid_review, tmp_path):
    first = enable_review(
        valid_review.path,
        tmp_path / "registry",
        enabled_by="owner-1",
        enabled_at=datetime(2026, 8, 26, 1, tzinfo=timezone.utc),
    )
    assert first.status == "enabled"
    with pytest.raises(ModelReleaseError) as error:
        enable_review(valid_review.path, tmp_path / "registry", enabled_by="owner-2", enabled_at=datetime.now(timezone.utc))
    assert error.value.code == "multiple_enabled_artifacts"


def test_review_and_enable_never_overwrite_existing_records(valid_bundle, tmp_path):
    first = _review_with_fixed_id(valid_bundle, tmp_path)
    with pytest.raises(ModelReleaseError) as error:
        _review_with_fixed_id(valid_bundle, tmp_path)
    assert error.value.code == "record_already_exists"


def test_release_rejects_paths_outside_registry(valid_review, tmp_path):
    tampered = _rewrite_review_path(valid_review, "../../outside/model.joblib")
    with pytest.raises(ModelReleaseError) as error:
        enable_review(tampered, tmp_path / "registry", enabled_by="owner", enabled_at=datetime.now(timezone.utc))
    assert error.value.code == "registry_path_escape"
```

- [ ] **Step 2: Run release tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_release.py scripts/tests/test_manage_longitudinal_registry.py -q
```

Expected: collection fails because release service and CLI do not exist.

- [ ] **Step 3: Implement immutable file writes**

Copy the reviewed candidate bundle into `registry_root/bundles/<model-id>/` only if the destination does not exist. Verify source and copied hashes match. Write JSON to a sibling `.tmp` file opened with exclusive creation, flush and `os.fsync`, then rename to the final path; refuse if the final path already exists. Do not modify metadata lifecycle in place. Lifecycle progression is represented by review and release records referencing immutable candidate metadata.

Review IDs and release IDs must be deterministic from task, model SHA-256, metadata SHA-256 and action timestamp; sanitize reviewer/enabler identifiers to bounded audit strings and reject empty values.

- [ ] **Step 4: Implement safe JSON CLI**

Required invocations:

```powershell
python scripts/manage_longitudinal_registry.py review --bundle-dir <dir> --registry-dir <dir> --reviewer <id> --note <text> --reviewed-at <ISO8601>
python scripts/manage_longitudinal_registry.py enable --review-file <file> --registry-dir <dir> --enabled-by <id> --enabled-at <ISO8601>
```

No registry directory default is allowed. Output exactly one sorted UTF-8 JSON document. Map service errors to stable codes. Never print raw exception strings or paths.

- [ ] **Step 5: Run release and CLI tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_model_release.py scripts/tests/test_manage_longitudinal_registry.py -q
```

Expected: review/enable audit, conflict, immutability, path safety and sanitized output tests pass.

### Task 6: 让 Artifact Checker 和 Readiness 复用唯一 Registry 验证器

**Files:**
- Modify: `scripts/check_model_artifacts.py`
- Modify: `scripts/tests/test_check_model_artifacts.py`
- Modify: `backend/app/services/longitudinal_readiness.py`
- Modify: `backend/app/schemas/longitudinal_readiness.py`
- Modify: `backend/tests/test_longitudinal_readiness_service.py`
- Modify: `backend/tests/test_longitudinal_readiness_schema.py`
- Modify: `scripts/tests/test_check_longitudinal_readiness.py`

**Interfaces:**
- Consumes `validate_candidate_bundle`, `load_model_registry`, `ModelRuntimeStatus`。
- Produces checker functions `check_bundle(bundle_dir: Path) -> dict[str, object]` and `check_registry(registry_dir: Path) -> dict[str, object]`。
- Replaces readiness `check_outcome_artifact(dataset, model_dir)` with `check_outcome_tasks(dataset, registry_root) -> dict[TaskName, ArtifactReadiness]` while preserving `LongitudinalReadinessReport.schema_version == "longitudinal_readiness.v1"`。

- [ ] **Step 1: Write failing shared-validation tests**

```python
def test_artifact_checker_uses_shared_reason_codes_and_no_prediction(valid_bundle, monkeypatch):
    monkeypatch.setattr(valid_bundle.model, "predict_proba", lambda rows: pytest.fail("prediction called"))
    payload = check_bundle(valid_bundle.bundle_dir)
    assert payload["status"] == "disabled"
    assert payload["reason_code"] == "lifecycle_not_enabled"


def test_readiness_reports_each_fatty_liver_task_independently(tmp_path):
    registry = _registry_with_only_pre_cirrhosis_enabled(tmp_path)
    tasks = check_outcome_tasks("fatty_liver", registry)
    assert tasks["fatty_liver.pre_cirrhosis_to_progression"].status == "available"
    assert tasks["fatty_liver.cirrhosis_to_hcc"].status == "missing"


def test_readiness_no_longer_accepts_old_disease_level_outcome_pair(tmp_path):
    _write_old_disease_level_pair(tmp_path)
    tasks = check_outcome_tasks("fatty_liver", tmp_path)
    assert all(item.status == "missing" for item in tasks.values())
```

- [ ] **Step 2: Run checker/readiness tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest scripts/tests/test_check_model_artifacts.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: failures because checker/readiness still implement independent disease-level validation.

- [ ] **Step 3: Replace checker validation with shared services**

Retain `sha256_file()` and `sha256_manifest()` for backward-compatible checksum use. Add mutually exclusive CLI modes:

```text
--bundle-dir <candidate bundle>
--registry-dir <file registry>
--models-dir <legacy checksum manifest mode>
```

Bundle/registry modes output validation status, reason code and non-sensitive model identity. They may deserialize only after all non-executable contract, hash and package checks pass so the shared validator can inspect the pipeline interface; neither mode may call `predict` or `predict_proba`. This makes checker, review, enable and production load use the same complete validation boundary.

- [ ] **Step 4: Replace readiness outcome checks and preserve top-level compatibility**

Extend `ArtifactReadiness` with optional `task`, `reason_code`, lifecycle/model identity fields. Change `ModelReadiness.outcome` to a task mapping while adding a compatibility summary property/field if existing consumers require one. Update capabilities so disease `outcome_365d` is available when at least one applicable task has an available artifact; missing tasks remain explicit reasons for their task without erasing the available one. Stage/trend stay optional degraded capabilities.

Do not change database queries or the readiness CLI read-only transaction behavior.

- [ ] **Step 5: Run checker/readiness tests and regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest scripts/tests/test_check_model_artifacts.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: all tests pass; checker never calls patient prediction; readiness remains `longitudinal_readiness.v1`.

### Task 7: 构建与 P0-04 一致的线上特征输入并安全调用模型

**Files:**
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/tests/test_longitudinal_features.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:**
- Consumes `BaselineStageRoute`, `LoadedModelEntry`, `ArtifactMetadata`。
- Produces `build_fixed_window_inference_features(case: Mapping[str, Any], visits: Sequence[Mapping[str, Any]], metadata: ArtifactMetadata) -> pandas.DataFrame`。
- Produces `InferenceContractError(code: str)` with privacy-safe codes。
- Produces `_run_outcome_model(route, entry, case, visits) -> OutcomeInferenceResult`。

- [ ] **Step 1: Write failing real-input tests**

```python
def test_inference_features_match_metadata_order_and_container(enabled_entry):
    frame = build_fixed_window_inference_features(
        {"sex": "female", "baseline_stage": "pre_cirrhosis"},
        _three_fatty_liver_visits(),
        enabled_entry.metadata,
    )
    assert list(frame.columns) == enabled_entry.metadata.feature_contract.feature_names
    assert frame.shape == (1, len(frame.columns))
    assert frame.loc[0, "visit_count"] == 3
    assert frame.loc[0, "observation_span_days"] == 365
    assert frame.loc[0, "alt.time_slope_per_day"] is not None


def test_online_age_is_missing_and_never_guessed(enabled_entry):
    frame = build_fixed_window_inference_features(
        {"patient_label": "年龄70岁的病例", "sex": "male", "notes": "患者约70岁"},
        _three_fatty_liver_visits(),
        enabled_entry.metadata,
    )
    assert pandas.isna(frame.loc[0, "age"])


def test_age_missing_is_allowed_only_when_metadata_and_pipeline_allow_it(enabled_entry):
    allowed = _run_outcome_model(_selected_route(), enabled_entry, _case(), _three_fatty_liver_visits())
    assert allowed.status.status == "available"
    blocked_entry = _entry_with_required_feature(enabled_entry, "age")
    blocked = _run_outcome_model(_selected_route(), blocked_entry, _case(), _three_fatty_liver_visits())
    assert blocked.status.status == "incompatible"
    assert blocked.status.reason_code == "required_feature_missing"
    assert blocked.risk_score is None


def test_outcome_requires_three_visits_but_observation_still_exists(enabled_entry):
    result = run_longitudinal_prediction(_case(), _two_visits(), FATTY_LIVER_ADAPTER, _registry(enabled_entry))
    assert result.observation["visit_count"] == 2
    assert result.outcome_prediction.risk_score is None
    assert result.model_status.outcome.reason_code == "insufficient_visits"
```

- [ ] **Step 2: Run feature/prediction tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_prediction_contract.py -q
```

Expected: failures because fixed-window inference builder and status-driven outcome execution do not exist.

- [ ] **Step 3: Implement fixed-window inference feature mapping**

Call `summarize_fixed_window_history(visits)` and flatten exactly the same stats used by `select_task_samples()`. Add `case.get("sex")`, explicit `age=None`, and derived visit timing fields. Validate:

```text
metadata feature list is non-empty and unique
computed frame columns exactly equal metadata order
required features are present and non-missing
allowed missing features are the only missing columns
input values supplied by the case/visits are finite
input container is pandas_dataframe
```

Do not reject NaN values representing approved missing features; do reject positive/negative infinity and values that cannot be represented by the declared feature type.

- [ ] **Step 4: Implement safe model call**

Before calling `predict_proba`, require selected route task equals entry metadata task and entry status is `available`. Call once with the DataFrame. Validate two classes, locate metadata positive class, require a finite score in `[0, 1]`, and convert exceptions to `prediction_failed` without exception text. Use the approved threshold contract for risk band; keep `score_semantics="model_score"` for uncalibrated artifacts.

- [ ] **Step 5: Run focused prediction tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_prediction_contract.py -q
```

Expected: fixed-window order, age missing, required feature, insufficient visits, finite-score and safe failure tests pass.

### Task 8: 升级结构化预测结果为 v2，并保证报告部分可用

**Files:**
- Modify: `backend/app/schemas/longitudinal_report.py`
- Modify: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/app/services/disease_progression.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`
- Modify: `backend/tests/test_longitudinal_trend_prediction.py`
- Modify: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`

**Interfaces:**
- Produces `LongitudinalPredictionResultV2` with `schema_version="longitudinal_prediction.v2"`。
- Produces `PredictionModelStatus` with `outcome`, `stage`, `trend`。
- Produces v1-compatible rendering helper `normalize_prediction_for_render(prediction: Mapping[str, Any]) -> dict[str, Any]`。
- Changes `predict_indicator_trends()` so no-model observed slopes stay in observation only and do not become forecast rows。

- [ ] **Step 1: Write failing v2 and partial-availability tests**

```python
def test_v2_records_outcome_stage_and_trend_statuses():
    result = run_longitudinal_prediction(_case("pre_cirrhosis"), _three_visits(), FATTY_LIVER_ADAPTER, _registry_with_enabled_outcome())
    assert result.schema_version == "longitudinal_prediction.v2"
    assert result.model_status.outcome.task == "fatty_liver.pre_cirrhosis_to_progression"
    assert result.model_status.outcome.status == "available"
    assert result.model_status.stage.reason_code == "stage_model_missing"
    assert result.model_status.trend.reason_code == "trend_model_missing"


def test_unavailable_outcome_emits_no_risk_but_keeps_observation_and_evidence():
    result = run_longitudinal_prediction(_case(None), _three_visits(), FATTY_LIVER_ADAPTER, _empty_registry())
    assert result.outcome_prediction.risk_score is None
    assert result.outcome_prediction.risk_band is None
    assert result.observation["indicators"]["alt"]["last"] == 30
    assert result.evidence == {}


def test_missing_trend_model_does_not_turn_observed_slope_into_future_prediction():
    result = run_longitudinal_prediction(_case("pre_cirrhosis"), _three_visits(), FATTY_LIVER_ADAPTER, _empty_registry())
    assert result.observation["indicators"]["alt"]["slope"] > 0
    assert result.trend_predictions == []
    assert result.model_status.trend.status == "missing"


def test_renderer_accepts_historical_v1_payload():
    markdown = render_longitudinal_markdown(_historical_v1_prediction())
    assert "纵向进展预测报告" in markdown
```

- [ ] **Step 2: Run prediction/report tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_trend_prediction.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py -q
```

Expected: failures because v2 model status and rendering compatibility are missing.

- [ ] **Step 3: Implement v2 strict models**

Keep the existing outcome/trend payload fields used by consumers, add top-level `model_status`, and enforce:

```text
outcome status != available => risk_score and risk_band are null
stage status != available => likely_next_stage and candidates are empty
trend status != available => trend_predictions is empty
uncalibrated score semantics is model_score
```

Do not make one Pydantic model accept both schema literals. Define explicit v1 compatibility parsing only inside the rendering layer; new prediction creation always returns v2.

- [ ] **Step 4: Separate observation from forecast and render accurate status text**

Remove observation-slope fallback from `predict_indicator_trends()`. Keep observed slopes in `observation.indicators`. Render model statuses in the final report using stable user-facing messages, including:

```text
365 天结局模型：未启用，因此未计算风险分数。
阶段模型：尚未配置，因此未预测下一阶段。
趋势模型：尚未配置，仅展示已观察到的指标变化。
```

When outcome is available, render task, model version, horizon, score semantics and calibration status in the technical appendix. Never label uncalibrated scores as probability.

- [ ] **Step 5: Run prediction/report/end-to-end tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_trend_prediction.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py -q
```

Expected: v2, v1 render compatibility and partial-report tests pass.

### Task 9: 接入 Operator 报告路由并清理敏感错误输出

**Files:**
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`
- Modify: `backend/tests/test_safe_stream.py`
- Modify: `backend/tests/test_security_contracts.py`
- Modify: `backend/tests/test_progression_api.py`

**Interfaces:**
- Consumes `route_outcome_task()` and task-level `load_model_registry()`。
- Produces `safe_longitudinal_error(code: str) -> tuple[str, str]` returning safe persisted/user messages。
- Operator longitudinal report route passes input snapshot, route result and registry to the generator; old progression route remains untouched。

- [ ] **Step 1: Write failing route and sensitive-output tests**

```python
def test_longitudinal_report_route_loads_task_registry_without_touching_old_progression(monkeypatch):
    calls = []
    monkeypatch.setattr("app.api.operator.load_model_registry", lambda dataset: calls.append(dataset) or _registry())
    response = _create_longitudinal_report_request(baseline_stage="cirrhosis")
    assert response.status_code == 200
    assert calls == ["fatty_liver"]


@pytest.mark.parametrize(
    "secret",
    [
        r"C:\\private\\model.joblib",
        "P001",
        "postgresql://user:password@localhost/private",
        "Traceback (most recent call last)",
    ],
)
def test_prediction_failure_does_not_leak_sensitive_details(secret):
    events, report = _run_generator_with_failure(RuntimeError(secret))
    serialized = "".join(events) + str(report.error_message)
    assert secret not in serialized
    assert "longitudinal_prediction_failed" in serialized


def test_legacy_progression_endpoint_response_is_unchanged(client, monkeypatch):
    monkeypatch.setattr("app.api.operator.predict_progression", lambda *args: PREDICTION)
    response = client.post("/api/v1/operator/progression-predictions", json=REQUEST)
    assert response.status_code == 200
    assert response.json() == PREDICTION
```

- [ ] **Step 2: Run API/security tests and verify RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_end_to_end.py backend/tests/test_safe_stream.py backend/tests/test_security_contracts.py backend/tests/test_progression_api.py -q
```

Expected: sensitive-output tests fail because generator currently returns and persists `str(exc)`.

- [ ] **Step 3: Wire task-aware registry into report generation**

Continue loading the disease registry once per report, but the registry must contain task entries and statuses rather than one disease-level model. The prediction service performs the final baseline route before selecting an entry. A routing failure is a completed partial report, not an HTTP error or failed report.

Do not catch registry errors by replacing them with `{}`; `load_model_registry()` itself must return structured missing/incompatible statuses. Reserve exception handling for unexpected programming/runtime failures.

- [ ] **Step 4: Sanitize unexpected failures**

Persist `report.error_message="longitudinal_prediction_failed"` and emit:

```json
{"message":"纵向预测暂时无法完成","code":"longitudinal_prediction_failed"}
```

Log an internal error code and report ID, but do not log `patient_label`, database URL or raw exception text in the structured message. Preserve cancellation handling.

- [ ] **Step 5: Run API/security/legacy tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_end_to_end.py backend/tests/test_safe_stream.py backend/tests/test_security_contracts.py backend/tests/test_progression_engine.py backend/tests/test_progression_api.py -q
```

Expected: security tests and old API regressions pass.

### Task 10: 增加疾病感知的基线阶段前端选择框

**Files:**
- Modify: `frontend/src/components/LongitudinalCaseEditor.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Create: `frontend/tests/longitudinal-baseline-stage.test.mjs`
- Modify: `frontend/tests/longitudinal-case-sync.test.mjs`

**Interfaces:**
- Produces TypeScript `BaselineStage` union: `pre_cirrhosis | cirrhosis | suspected_cirrhosis | hcc | normal | mci | pre_dementia | dementia`。
- Produces disease-aware stage option map in `LongitudinalCaseEditor.vue`。
- Persists `baseline_stage` through view → store → API using the existing backend field。

- [ ] **Step 1: Write failing source-contract tests**

Use Node's built-in test runner and actual source reads:

```javascript
test('editor exposes disease-aware canonical baseline stages', async () => {
  const editor = await readFile(editorPath, 'utf8')
  assert.match(editor, /pre_cirrhosis/)
  assert.match(editor, /suspected_cirrhosis/)
  assert.match(editor, /cirrhosis/)
  assert.match(editor, /hcc/)
  assert.match(editor, /normal/)
  assert.match(editor, /mci/)
  assert.match(editor, /pre_dementia/)
  assert.match(editor, /dementia/)
  assert.match(editor, /aria-label="基线阶段"/)
})

test('case save persists baseline_stage', async () => {
  const [view, store, api] = await Promise.all([
    readFile(viewPath, 'utf8'),
    readFile(storePath, 'utf8'),
    readFile(apiPath, 'utf8'),
  ])
  assert.match(view, /baseline_stage:\s*draft\.baseline_stage/)
  assert.match(store, /baseline_stage\?:/)
  assert.match(api, /export type BaselineStage/)
})

test('changing disease clears an incompatible selected stage', async () => {
  const editor = await readFile(editorPath, 'utf8')
  assert.match(editor, /watch\(\(\) => draft\.disease_id/)
  assert.match(editor, /draft\.baseline_stage = null/)
})
```

- [ ] **Step 2: Run frontend contract tests and verify RED**

```powershell
node --test frontend/tests/longitudinal-baseline-stage.test.mjs frontend/tests/longitudinal-case-sync.test.mjs
```

Expected: failures because the editor has no baseline stage selector and the view does not submit it.

- [ ] **Step 3: Implement the Element Plus selector using approved design variables**

Add `baseline_stage` to `toDraft()`. Compute options from the selected disease name/key; fatty liver labels are“未肝硬化 / 已肝硬化 / 疑似肝硬化 / 已肝癌”，AD labels are“认知正常 / 轻度认知障碍（MCI） / 其他痴呆前状态 / 已痴呆”. Use `<el-select clearable>` with `aria-label="基线阶段"` in the existing `.editor-grid`.

Use existing `--space-*`, `--radius-*`, `--text-*`, `--border-*` variables only. Do not introduce new colors, layout systems or animation. Add a concise helper text explaining that uncertain stage will not generate a risk score; use `--text-secondary` and `--text-xs`.

Watch `draft.disease_id`; if the selected canonical stage is not in the new disease option set, set it to `null`. Do not map it automatically.

- [ ] **Step 4: Pass the field through view, store and API**

Add the typed field to create/update payloads and pass:

```typescript
baseline_stage: draft.baseline_stage || null
```

Do not add age. Preserve the existing atomic visit replacement workflow.

- [ ] **Step 5: Run frontend tests and build**

```powershell
node --test frontend/tests/*.test.mjs
Set-Location frontend
npm run build
Set-Location ..
```

Expected: all Node contract tests pass; `vue-tsc` and Vite build succeed.

### Task 11: 完成双疾病临时 Review/Enable/Load/Inference Smoke Test

**Files:**
- Create: `scripts/smoke_longitudinal_registry.py`
- Create: `scripts/tests/test_smoke_longitudinal_registry.py`
- Modify only if a smoke test exposes a defect: the responsible P0-05 implementation and its focused test
- No production artifact or registry writes

**Interfaces:**
- Uses P0-03 builder/export CLI, P0-04 candidate training CLI, P0-05 management CLI, checker and prediction service。
- Produces `load_online_smoke_case(dataset: str, patients_csv: Path, visits_csv: Path, scenario: str) -> tuple[dict[str, object], list[dict[str, object]]]` with no patient identifier in the returned case。
- Produces `run_smoke(registry_dir: Path, data_root: Path) -> dict[str, object]` covering three selected routes and suspected cirrhosis。
- Produces a CLI requiring explicit `--registry-dir` and `--data-root`; it prints one path-free, patient-free JSON result。
- Produces disposable verification directories under a newly named `.tmp/p005-*` path and machine-readable evidence captured for final documentation。

- [ ] **Step 1: Snapshot production model directory before smoke testing**

```powershell
$env:PYTHONPATH='backend;.'
$verificationRoot = Join-Path '.tmp' ('p005-verification-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $verificationRoot | Out-Null
Get-ChildItem 'backend/app/ml_models' -File | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{
    name = $_.Name
    sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  }
} | ConvertTo-Json | Set-Content (Join-Path $verificationRoot 'production-models-before.json') -Encoding utf8
```

Expected: snapshot contains only current production files; no files are modified.

- [ ] **Step 2: Build a fresh P0-03 export and P0-04 candidate bundles**

```powershell
python scripts/build_longitudinal_dataset.py --output-dir (Join-Path $verificationRoot 'dataset')
python scripts/train_longitudinal_outcome_models.py --dataset-dir (Join-Path $verificationRoot 'dataset') --train --output-dir (Join-Path $verificationRoot 'candidates')
```

Expected: three task-scoped candidate bundles, all `candidate` and `production_enabled=false`; no review/release files.

- [ ] **Step 3: Check every candidate without prediction execution**

```powershell
Get-ChildItem (Join-Path $verificationRoot 'candidates') -Directory | ForEach-Object {
  python scripts/check_model_artifacts.py --bundle-dir $_.FullName
  if ($LASTEXITCODE -ne 0) { throw "candidate check failed" }
}
```

Expected: each candidate is contract-valid but runtime-disabled because lifecycle is candidate; checker output contains no patient identity or path details.

- [ ] **Step 4: Review and enable all three tasks only in the disposable registry**

```powershell
$registryDir = Join-Path $verificationRoot 'registry'
$reviewedAt = (Get-Date).ToUniversalTime().ToString('o')
Get-ChildItem (Join-Path $verificationRoot 'candidates') -Directory | ForEach-Object {
  $reviewJson = python scripts/manage_longitudinal_registry.py review --bundle-dir $_.FullName --registry-dir $registryDir --reviewer 'p005-smoke-reviewer' --note 'temporary P0-05 contract smoke review' --reviewed-at $reviewedAt | ConvertFrom-Json
  $reviewFile = Join-Path $registryDir $reviewJson.review_file
  python scripts/manage_longitudinal_registry.py enable --review-file $reviewFile --registry-dir $registryDir --enabled-by 'p005-smoke-enabler' --enabled-at ((Get-Date).ToUniversalTime().ToString('o'))
  if ($LASTEXITCODE -ne 0) { throw "temporary enable failed" }
}
```

Expected: immutable review/release files are created only under `$registryDir`; each task has exactly one enabled release.

- [ ] **Step 5: Run real load and inference smoke for both diseases**

Add or use a tested Python smoke entry that loads the temporary registry and performs:

```text
fatty_liver + pre_cirrhosis → pre_cirrhosis_to_progression
fatty_liver + cirrhosis → cirrhosis_to_hcc
ad + mci → pre_dementia_to_dementia
```

Use the repository's existing generated longitudinal source rows rather than trying to reverse aggregated P0-03 JSONL features:

```text
fatty liver patients: data/generated/longitudinal_300/patients.csv
fatty liver visits:   data/generated/longitudinal_300/visits.csv
AD patients:          data/generated/ad_longitudinal_300/patients.csv
AD visits:            data/generated/ad_longitudinal_300/visits.csv
```

First write `scripts/tests/test_smoke_longitudinal_registry.py` and verify RED. Then implement the smoke helper so it:

1. selects deterministic patients whose prediction prefix contains at least three dated visits;
2. converts the selected patient row and visit prefix into the same case/visit shape accepted by online prediction;
3. supplies `sex`, leaves online `age` missing, and derives the smoke case's explicit `baseline_stage` only from the dataset's known event dates and the prefix cutoff (never from indicator values or model output);
4. covers `fatty_liver + pre_cirrhosis`, `fatty_liver + cirrhosis`, and `ad + mci` with their respective task routes;
5. uses the newly trained joblib artifacts from `$verificationRoot`, not legacy `*_progression_model.*` files;
6. excludes patient identifiers from returned results, captured CLI output and assertion messages.

Assert every available outcome records task, model version, artifact hash, 365-day target, feature version and uncalibrated model-score semantics. Also assert suspected cirrhosis returns no score while observation remains present.

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest scripts/tests/test_smoke_longitudinal_registry.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_end_to_end.py -k "temporary_registry or dual_disease or task_route or smoke" -q
python scripts/smoke_longitudinal_registry.py --registry-dir $registryDir --data-root data/generated | Tee-Object -FilePath (Join-Path $verificationRoot 'inference-smoke.json')
if ($LASTEXITCODE -ne 0) { throw "temporary inference smoke failed" }
```

Expected: both diseases and both fatty-liver stages load and infer from the temporary registry.

- [ ] **Step 6: Verify production model directory is byte-for-byte unchanged**

```powershell
Get-ChildItem 'backend/app/ml_models' -File | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{
    name = $_.Name
    sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
  }
} | ConvertTo-Json | Set-Content (Join-Path $verificationRoot 'production-models-after.json') -Encoding utf8

$before = Get-Content -Raw (Join-Path $verificationRoot 'production-models-before.json')
$after = Get-Content -Raw (Join-Path $verificationRoot 'production-models-after.json')
if ($before -ne $after) { throw 'backend/app/ml_models changed during P0-05 smoke test' }
```

Expected: exact match.

- [ ] **Step 7: Scan smoke outputs for sensitive information**

```powershell
rg -n "postgresql://|password|Traceback|C:\\Users\\|patient_label|P001|A001" $verificationRoot
```

Expected: no matches in CLI/checker/error outputs. If dataset artifacts themselves intentionally contain internal training identities, restrict the scan to captured CLI/report/error JSON and document that scope explicitly rather than deleting evidence.

### Task 12: 运行专项、分层回归、完整测试并记录实际证据

**Files:**
- Modify after all implementation and verification pass: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`
- Do not modify completion status before the gate passes

**Interfaces:**
- Produces final P0-05 verification evidence and only then updates roadmap status。

- [ ] **Step 1: Run P0-05 focused backend and script tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_task_routing.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_model_release.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py scripts/tests/test_manage_longitudinal_registry.py scripts/tests/test_check_model_artifacts.py scripts/tests/test_smoke_longitudinal_registry.py -q
```

Expected: all P0-05 focused tests pass.

- [ ] **Step 2: Run frontend focused tests and build**

```powershell
node --test frontend/tests/*.test.mjs
Set-Location frontend
npm run build
Set-Location ..
```

Expected: all frontend contract tests and production build pass.

- [ ] **Step 3: Run longitudinal prediction, report, readiness and security regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_trend_prediction.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_safe_stream.py backend/tests/test_security_contracts.py -q
```

Expected: all pass.

- [ ] **Step 4: Run P0-03 and P0-04 regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_features.py scripts/tests/test_build_longitudinal_dataset.py backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py scripts/tests/test_train_longitudinal_outcome_models.py -q
```

Expected: all pass; P0-03 labels and P0-04 task definitions remain unchanged.

- [ ] **Step 5: Run legacy training and progression regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest scripts/tests/test_train_longitudinal_models.py scripts/tests/test_train_progression_model.py backend/tests/test_progression_engine.py backend/tests/test_progression_api.py -q
node --test frontend/tests/progression-ui-contract.test.mjs
```

Expected: old model engine, endpoint and frontend disclosure contract remain unchanged.

- [ ] **Step 6: Run the complete Python suite**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest -q
```

Expected: full suite passes. If the known `test_cleanup_contracts` failure occurs because `.superpowers/sdd` exists, record the exact failing assertion and command output; do not delete the directory or mark the suite as passed.

- [ ] **Step 7: Run final diff and scope checks**

```powershell
git diff --check
git status --short
git diff --name-only
```

Expected:

- no Alembic, DB model, old progression model/script deletion or production artifact changes;
- `outputs/report_method_validation.md` remains the user's pre-existing modification unless the user separately changed it;
- only approved P0-05 implementation, tests, design/plan and final roadmap evidence are new changes.

- [ ] **Step 8: Record actual verification evidence and only then mark P0-05 complete**

Under `### P0-05：统一模型 registry、状态和推理契约` record:

- exact focused/regression/full commands and actual pass/fail totals;
- frontend test/build result;
- temporary registry path and the three smoke-tested tasks;
- candidate → reviewed → enabled → load → inference evidence;
- confirmation that checker did not execute prediction;
- confirmation that `backend/app/ml_models/` hashes were unchanged;
- legacy progression API regression result;
- sensitive-output scan result;
- any known full-suite failure with exact evidence.

Set P0-05 to completed only if every required gate is satisfied. Do not claim clinical validity or production enablement of any candidate.

## Completion Gate

P0-05 is complete only when all conditions are true:

- one shared task contract owns the three exact outcome tasks;
- lifecycle and runtime statuses are structurally separate and tested;
- task routing handles both fatty-liver stages, AD, missing, unknown, suspected, conflict and terminal stages without guessing;
- P0-04 can export complete candidate bundles but cannot review or enable them;
- review/enable are explicit, immutable, path-safe and auditable;
- only one enabled release per task is accepted;
- artifact validation checks all approved fields/hashes/packages before deserialization and never predicts during static checks;
- candidate/reviewed/disabled/missing/incompatible/available behavior is fully tested;
- online inference uses P0-04 fixed-window feature semantics and exact metadata order;
- age remains missing online and is used only through the artifact's verified imputation contract;
- unavailable outcome emits no score/band, unavailable stage emits no guess, unavailable trend emits no forecast;
- observations, standards and evidence survive optional-model failures;
- new reports persist `longitudinal_prediction.v2`, while historical v1 payloads remain renderable;
- unexpected errors are sanitized across SSE, persistence and CLI;
- baseline stage can be selected and saved in the existing operator UI without DB changes;
- old progression artifacts, engine, endpoint and frontend contract remain unchanged;
- disposable dual-disease review/enable/load/inference smoke passes;
- production model directory is unchanged without explicit owner approval;
- focused, regression and full verification evidence is recorded accurately;
- roadmap is not marked completed before all gates pass.
