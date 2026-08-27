# 旧模型与数据迁移并恢复完整模型更新链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task in the current workspace. This plan must be executed by one Agent only. Do not dispatch subagents and do not create a worktree. Use `test-driven-development` for every implementation task, `systematic-debugging` for unexpected failures, and `verification-before-completion` before any completion claim.

**Goal:** 在当前 `main` 上为脂肪肝和 AD 建成可重复更新、可追溯、可审核、可原子切换和回退的结局＋阶段＋趋势模型链路，使 AI 操作者的新报告真实使用完整模型组，同时保持历史报告、PDF、旧 progression API 和现有 P0 功能不变。

**Architecture:** 训练面以版本化数据 release 和疾病级患者划分为共同输入，分别训练结局、阶段和趋势模型，并输出不可变 bundle。发布面把同一疾病的全部 bundle 组装为 disease release set，经 review、预加载 smoke 后原子切换一个活动指针；在线报告在开始时固定该 release set，分别执行三类模型并持久化结构化结果、正文和来源身份。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、PostgreSQL、Pydantic v2、pandas、NumPy、scikit-learn、joblib、pytest、Vue 3、TypeScript、Element Plus、Node test runner、Playwright PDF。

## Global Constraints

- 只支持脂肪肝和 AD；只做电脑端；不开始 P1；不扩展通用多疾病模型管理平台。
- 直接使用当前工作区和当前 `main`；不创建 git worktree；全程单 Agent。
- 实施前确认 HEAD 仍为用户批准的基线；不得覆盖用户在实施期间新增的改动。
- 每个实现任务先运行明确的失败测试，再完成对应实现，再运行专项回归。
- 不运行全量 pytest，除非所有专项验证完成后用户再次明确批准；默认交付以脂肪肝、AD、数据、训练、registry、推理、报告、历史、PDF、旧 API 和前端专项验证为准。
- 不自动 commit、push、上线、切换生产模型或更新正式数据。计划中的“检查点”只记录建议提交边界，不执行提交。
- 旧 `.tmp/p005-*` 仅作为回归基线，不进入正式 release。
- 不迁移可识别患者身份；不输出数据库 URL、密码、本机绝对路径或 traceback。
- 不调用 LLM 生成模型事实、临床结论或训练标签。
- 不修改数据库 schema 或 Alembic migration；如果任务 2 证明现有 JSONB 无法安全实现版本切换，停止并向用户申请批准。
- 历史报告正文不得重新计算；新模型只影响新生成报告；PDF只使用保存正文和保存预测结果。
- 观察事实、标准解释、结局预测、阶段预测和趋势预测必须分开。
- 未通过校准验证的分数只称 `model_score`，不得称为临床概率。
- 旧 `/progression-predictions` 及 `fatty_liver_progression_model.*`、`ad_progression_model.*` 不得被新 registry 读取或覆盖。
- 生产切换必须在候选模型和完整验收证据交付后再次获得用户明确批准。

---

## File Structure and Responsibility Map

### 新建文件

- `backend/app/schemas/longitudinal_model_suite.py`：结局、阶段、趋势通用 artifact/evaluation/release-set 严格契约。
- `backend/app/services/longitudinal_data_release.py`：基于现有 `case_metadata` 的数据 release 导入、活动版本选择和事务切换。
- `backend/app/services/longitudinal_group_split.py`：疾病级统一患者划分、划分持久化和跨任务泄漏审计。
- `backend/app/services/longitudinal_stage_training.py`：阶段样本构造、训练、评估和候选 bundle。
- `backend/app/services/longitudinal_trend_training.py`：趋势样本构造、指标容差、训练、评估和候选 bundle。
- `backend/app/services/longitudinal_release_set.py`：疾病级 release set review、预加载、活动指针原子切换和回退。
- `scripts/train_longitudinal_model_suite.py`：双疾病完整模型组的 audit/train CLI，只生成 candidate。
- `scripts/manage_longitudinal_release_sets.py`：review、enable、rollback CLI，不隐式执行任何操作。
- `backend/tests/test_longitudinal_data_release.py`：数据版本、幂等导入和回滚测试。
- `backend/tests/test_longitudinal_group_split.py`：疾病级统一划分和泄漏测试。
- `backend/tests/test_longitudinal_stage_training.py`：阶段训练和评估测试。
- `backend/tests/test_longitudinal_trend_training.py`：趋势训练和评估测试。
- `backend/tests/test_longitudinal_release_set.py`：完整模型组切换和回退测试。
- `scripts/tests/test_train_longitudinal_model_suite.py`：完整训练 CLI 合约测试。
- `scripts/tests/test_manage_longitudinal_release_sets.py`：发布 CLI 安全边界测试。

### 主要修改文件

- `scripts/import_longitudinal.py`：接入数据 release，不再用破坏式 reset 作为正式更新方式。
- `backend/app/services/longitudinal_evidence.py`：相似病例只读取活动数据 release。
- `backend/app/services/longitudinal_dataset.py`：训练读取活动 release，并保留只读事务。
- `backend/app/services/longitudinal_dataset_export.py`：写入 run、来源、文件和划分追溯信息。
- `backend/app/schemas/longitudinal_model_training.py`：修正数据文件哈希并补充锁定测试结果契约。
- `backend/app/services/longitudinal_model_training.py`：结局模型疾病级划分、模型选择和锁定测试。
- `backend/app/services/longitudinal_model_evaluation.py`：补充多分类评估和基线比较。
- `backend/app/services/longitudinal_model_audit.py`：跨任务、未来信息、来源家族和近重复审计。
- `backend/app/schemas/longitudinal_model_registry.py`：兼容现有 outcome bundle，并接入通用 suite 契约。
- `backend/app/services/longitudinal_model_registry.py`：由单任务 release 加载升级为 disease release set 加载。
- `backend/app/services/longitudinal_model_release.py`：保留旧函数兼容，委托新的 release-set 服务。
- `backend/app/services/longitudinal_features.py`：训练与在线共享的阶段/趋势特征。
- `backend/app/services/disease_progression.py`：指标容差和趋势标签配置，不承担 artifact 选择。
- `backend/app/schemas/longitudinal_report.py`：新增 v3 release/model identity 和逐趋势模型状态。
- `backend/app/services/longitudinal_prediction.py`：三类模型独立推理和安全降级。
- `backend/app/services/longitudinal_report_generator.py`：渲染真实阶段和趋势预测，保持历史正文边界。
- `backend/app/api/operator.py`：固定 release set 并保存其身份；历史和 PDF 仍读取保存内容。
- `backend/app/services/pdf_generator.py`：仅按保存的 v3 结果绘制，不进行预测。
- `backend/app/services/longitudinal_readiness.py`：报告完整模型组和活动 release 状态。
- `scripts/smoke_longitudinal_registry.py`：验证结局、阶段、趋势和 release identity。
- `frontend/src/api/operator.ts`：严格的 v3 TypeScript 类型。
- `frontend/src/components/LongitudinalPredictionSummary.vue`：展示三类模型结果和状态。
- `frontend/src/components/LongitudinalReportView.vue`：展示模型组身份和保存结果。
- `frontend/tests/longitudinal-report-ui-contract.test.mjs`：电脑端展示合约。

---

### Task 1: 固定现有 P0 保护基线

**Files:**
- Test: `backend/tests/test_longitudinal_report_persistence.py`
- Test: `backend/tests/test_longitudinal_report_acceptance.py`
- Test: `backend/tests/test_progression_api.py`
- Test: `backend/tests/test_longitudinal_model_registry.py`
- Test: `frontend/tests/longitudinal-report-ui-contract.test.mjs`

**Interfaces:**
- Consumes: 当前 `main` 的 P0-05 至 P0-07 行为。
- Produces: 后续每个任务必须重复运行的保护测试清单和真实基线结果。

- [ ] **Step 1: 确认 Git 基线且不清理用户文件**

Run:

```powershell
git status --short --branch
git log -1 --oneline --decorate
git diff --check
```

Expected: 分支为 `main`；已跟踪实现没有未解释修改；允许保留用户已有的 `.superpowers/`、`tmp/` 和已批准设计/计划文档。

- [ ] **Step 2: 运行后端保护性专项测试**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_report_persistence.py backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_progression_api.py -q
```

Expected: PASS。若出现既有失败，使用 `systematic-debugging` 定位并记录，不能为了继续计划而修改断言。

- [ ] **Step 3: 运行现有数据、训练和发布专项测试**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py backend/tests/test_longitudinal_model_release.py scripts/tests/test_build_longitudinal_dataset.py scripts/tests/test_train_longitudinal_outcome_models.py scripts/tests/test_import_longitudinal.py -q
```

Expected: PASS，或如实记录与已知全量测试失败相同的既有失败；本步骤不运行全量测试。

- [ ] **Step 4: 运行电脑端合约与构建基线**

Run:

```powershell
node --test frontend/tests/longitudinal-report-ui-contract.test.mjs frontend/tests/progression-ui-contract.test.mjs frontend/tests/longitudinal-case-sync.test.mjs frontend/tests/longitudinal-baseline-stage.test.mjs
npm --prefix frontend run build
```

Expected: Node 合约 PASS，Vue TypeScript 检查和 Vite build PASS。

- [ ] **Step 5: 记录检查点，不提交**

Run:

```powershell
git status --short
```

Expected: 没有测试产生的已跟踪修改。记录建议检查点：`baseline: protect P0 longitudinal workflow`，但不执行 commit。

---

### Task 2: 建立不改 schema 的版本化数据 release

**Files:**
- Create: `backend/app/services/longitudinal_data_release.py`
- Create: `backend/tests/test_longitudinal_data_release.py`
- Modify: `scripts/import_longitudinal.py`
- Modify: `scripts/tests/test_import_longitudinal.py`
- Modify: `backend/app/services/longitudinal_evidence.py`
- Modify: `backend/tests/test_longitudinal_evidence.py`
- Modify: `backend/app/services/longitudinal_dataset.py`
- Modify: `backend/tests/test_longitudinal_dataset_builder.py`

**Interfaces:**
- Consumes: `CaseRecord.case_metadata` JSONB、现有 `import_dataset()` 和只读训练查询。
- Produces:
  - `DataReleaseSpec(logical_dataset, release_id, data_content_sha256, generated_at)`
  - `import_data_release(db, dataset, release, patients, visits, source_documents) -> DataReleaseResult`
  - `activate_data_release(db, logical_dataset, release_id) -> DataReleaseSwitchResult`
  - `active_release_filter(query, logical_dataset)`

- [ ] **Step 1: 编写幂等、共存和回滚失败测试**

Add to `backend/tests/test_longitudinal_data_release.py`:

```python
def test_new_release_coexists_and_only_one_is_active(db_session):
    first = import_data_release(db_session, "fatty_liver", release("fl-v1", "a" * 64), patients_v1(), visits_v1(), {})
    second = import_data_release(db_session, "fatty_liver", release("fl-v2", "b" * 64), patients_v2(), visits_v2(), {})
    activate_data_release(db_session, "longitudinal_300", second.release_id)
    rows = db_session.query(CaseRecord).all()
    assert {row.case_metadata["dataset_release_id"] for row in rows} == {first.release_id, second.release_id}
    assert {row.case_metadata["dataset_release_id"] for row in rows if row.case_metadata["dataset_active"]} == {second.release_id}


def test_failed_switch_rolls_back_without_changing_active_release(db_session, monkeypatch):
    first = seeded_active_release(db_session, "fl-v1")
    monkeypatch.setattr(db_session, "flush", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
    with pytest.raises(RuntimeError):
        activate_data_release(db_session, "longitudinal_300", "fl-v2")
    db_session.rollback()
    assert active_release_ids(db_session, "longitudinal_300") == {first.release_id}
```

Add to `scripts/tests/test_import_longitudinal.py`:

```python
def test_release_signature_includes_dataset_release_id(self):
    first = self.importer.import_dataset(self.db, "fatty_liver", patients=self.patients, visits=self.visits, dataset_release_id="fl-v1", data_content_sha256="a" * 64)
    second = self.importer.import_dataset(self.db, "fatty_liver", patients=self.patients, visits=self.visits, dataset_release_id="fl-v2", data_content_sha256="b" * 64)
    self.assertEqual(first["inserted"], second["inserted"])
```

- [ ] **Step 2: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_data_release.py scripts/tests/test_import_longitudinal.py::ImportLongitudinalTests::test_release_signature_includes_dataset_release_id -q
```

Expected: FAIL，因为 release 类型、导入参数和活动切换尚不存在。

- [ ] **Step 3: 实现数据 release 契约和事务切换**

Create the core interface in `backend/app/services/longitudinal_data_release.py`:

```python
@dataclass(frozen=True)
class DataReleaseSpec:
    logical_dataset: str
    release_id: str
    data_content_sha256: str
    generated_at: datetime


def release_metadata(base: dict[str, Any], spec: DataReleaseSpec) -> dict[str, Any]:
    return {
        **base,
        "logical_dataset": spec.logical_dataset,
        "dataset_release_id": spec.release_id,
        "data_content_sha256": spec.data_content_sha256,
        "dataset_active": False,
    }


def activate_data_release(db, logical_dataset: str, release_id: str) -> DataReleaseSwitchResult:
    rows = scoped_release_rows(db, logical_dataset)
    if release_id not in {metadata(row).get("dataset_release_id") for row in rows}:
        raise DataReleaseError("release_missing")
    for row in rows:
        value = dict(row.case_metadata or {})
        value["dataset_active"] = value.get("dataset_release_id") == release_id
        row.case_metadata = value
    db.flush()
    return DataReleaseSwitchResult(logical_dataset, release_id, len(rows))
```

Update import signatures so idempotency is `(logical_dataset, dataset_release_id, patient_label, visit_date)`. Preserve legacy calls in tests by deriving a deterministic legacy release ID when the new arguments are omitted; formal CLI calls must require manifest-derived `release_id` and `data_content_sha256`.

- [ ] **Step 4: 让训练和相似病例只读取活动 release**

Implement a compatibility rule:

```python
def select_active_release_rows(rows: Sequence[CaseRecord], logical_dataset: str) -> list[CaseRecord]:
    scoped = [row for row in rows if metadata(row).get("logical_dataset", metadata(row).get("source_dataset")) == logical_dataset]
    explicit = [row for row in scoped if metadata(row).get("dataset_active") is True]
    return explicit if explicit else [row for row in scoped if "dataset_active" not in metadata(row)]
```

Use the SQL equivalent in production queries. Legacy rows without the field remain readable until the first explicit release is activated. Never return both legacy and explicit active rows together.

- [ ] **Step 5: 运行数据 release 与相关回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_data_release.py scripts/tests/test_import_longitudinal.py backend/tests/test_longitudinal_evidence.py backend/tests/test_longitudinal_dataset_builder.py -q
```

Expected: PASS；现有 reset 测试继续通过，但正式更新 CLI 默认走 release 导入，`--reset` 保留为显式维护选项且不能由训练脚本调用。

- [ ] **Step 6: 检查 schema 边界并停在必要审批点**

Run:

```powershell
git diff -- backend/alembic backend/app/db/models.py
```

Expected: 无变化。如果实现无法在 JSONB 内保证互斥活动版本，停止任务并请求用户批准 schema 变更。

- [ ] **Step 7: 记录检查点，不提交**

记录建议检查点：`feat: add versioned longitudinal data releases`，不执行 commit。

---

### Task 3: 修复 manifest 哈希并生成疾病级统一患者划分

**Files:**
- Create: `backend/app/services/longitudinal_group_split.py`
- Create: `backend/tests/test_longitudinal_group_split.py`
- Modify: `backend/app/services/longitudinal_dataset_export.py`
- Modify: `backend/tests/test_longitudinal_dataset_export.py`
- Modify: `backend/app/schemas/longitudinal_model_training.py`
- Modify: `backend/app/services/longitudinal_model_training.py`
- Modify: `backend/tests/test_longitudinal_model_training.py`
- Modify: `scripts/build_longitudinal_dataset.py`
- Modify: `scripts/tests/test_build_longitudinal_dataset.py`

**Interfaces:**
- Consumes: P0-03 `manifest.json` 和每个疾病的 `real_train.jsonl`。
- Produces:
  - `DatasetInput.file_sha256_by_path: dict[str, str]`
  - `DiseaseGroupSplit(schema_version, disease, seed, development_train_groups, development_validation_groups, locked_test_groups, sha256)`
  - `make_disease_group_split(samples, disease, seed, validation_fraction, test_fraction)`
  - `write_group_splits(dataset_dir, splits) -> Path`

- [ ] **Step 1: 编写训练文件哈希精确绑定测试**

Add to `backend/tests/test_longitudinal_model_training.py`:

```python
def test_manifest_reader_returns_hash_for_requested_training_file(tmp_path):
    root = write_dataset_fixture(tmp_path)
    dataset = read_dataset_manifest(root)
    assert dataset.file_sha256("ad/real_train.jsonl") == sha256_file(root / "ad/real_train.jsonl")
    assert dataset.file_sha256("fatty_liver/real_train.jsonl") == sha256_file(root / "fatty_liver/real_train.jsonl")
    assert dataset.file_sha256("ad/real_train.jsonl") != dataset.file_sha256("ad/real_audit.jsonl")
```

- [ ] **Step 2: 编写跨任务统一划分测试**

Add to `backend/tests/test_longitudinal_group_split.py`:

```python
def test_fatty_liver_tasks_share_one_disease_split(samples):
    split = make_disease_group_split(samples, "fatty_liver", seed=42, validation_fraction=0.2, test_fraction=0.2)
    pre = task_groups(samples, "fatty_liver.pre_cirrhosis_to_progression", split)
    hcc = task_groups(samples, "fatty_liver.cirrhosis_to_hcc", split)
    assert pre.locked_test_groups <= set(split.locked_test_groups)
    assert hcc.locked_test_groups <= set(split.locked_test_groups)
    assert not (set(split.development_train_groups) & set(split.locked_test_groups))


def test_same_patient_never_crosses_outcome_stage_or_trend_partitions(samples):
    split = make_disease_group_split(samples, "ad", seed=42, validation_fraction=0.2, test_fraction=0.2)
    assignments = materialize_all_task_assignments(samples, split)
    assert all(len(partitions) == 1 for partitions in assignments.values())
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py::test_manifest_reader_returns_hash_for_requested_training_file backend/tests/test_longitudinal_group_split.py -q
```

Expected: FAIL，暴露当前 `file_sha256` 取 manifest 第一个哈希的问题，并证明尚无疾病级统一划分。

- [ ] **Step 4: 实现精确哈希映射和划分契约**

Change `DatasetInput` to preserve the complete mapping:

```python
class DatasetInput(StrictModel):
    dataset_dir: str
    schema_version: str
    manifest_sha256: str
    data_content_sha256: str
    file_sha256_by_path: dict[str, str]

    def file_sha256(self, relative_path: str) -> str:
        try:
            return self.file_sha256_by_path[relative_path]
        except KeyError as exc:
            raise ValueError("training_file_missing_from_manifest") from exc
```

Implement deterministic stratified group assignment using one row per `group_id`, with stable SHA-256 tie-breaking and explicit class-coverage validation. The split file must contain group IDs only, never patient labels or source document names.

- [ ] **Step 5: 将 run、来源和 split 哈希写入 manifest**

Extend export manifest with exact keys:

```json
{
  "run_id": "dataset-<content-prefix>",
  "source_provenance": [{"source_id": "source-<sha-prefix>", "sha256": "..."}],
  "group_split_file": "group_splits.json",
  "group_split_sha256": "...",
  "files": {"ad/real_train.jsonl": "..."}
}
```

Do not include absolute paths or original source filenames.

- [ ] **Step 6: 运行数据、哈希和划分回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_group_split.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_model_training.py scripts/tests/test_build_longitudinal_dataset.py -q
```

Expected: PASS；固定 seed 重复生成的 split 文件字节一致；不同 seed 的 `run_id` 或 split 哈希可区分。

- [ ] **Step 7: 记录检查点，不提交**

记录建议检查点：`fix: bind training artifacts to exact data files and shared splits`，不执行 commit。

---

### Task 4: 建立三类模型通用 artifact 与 evaluation 契约

**Files:**
- Create: `backend/app/schemas/longitudinal_model_suite.py`
- Create: `backend/tests/test_longitudinal_model_suite_schema.py`
- Modify: `backend/app/schemas/longitudinal_model_registry.py`
- Modify: `backend/app/services/longitudinal_model_registry.py`
- Modify: `backend/tests/test_longitudinal_model_registry.py`
- Modify: `backend/app/services/longitudinal_model_evaluation.py`
- Modify: `backend/tests/test_longitudinal_model_evaluation.py`

**Interfaces:**
- Consumes: 现有 outcome `FeatureContract`、`DatasetContract`、`ModelContract`。
- Produces:
  - `ArtifactMetadataV2`
  - `EvaluationArtifact`
  - `MulticlassMetrics`
  - `ArtifactType = outcome | stage | trend`
  - `validate_bundle_files(model_path, metadata_path, evaluation_path, manifest_path)`

- [ ] **Step 1: 编写三类 metadata 和哈希链失败测试**

Add to `backend/tests/test_longitudinal_model_suite_schema.py`:

```python
@pytest.mark.parametrize("artifact_type", ["outcome", "stage", "trend"])
def test_v2_metadata_requires_evaluation_and_split_hashes(artifact_type):
    payload = valid_metadata(artifact_type)
    payload["evaluation_sha256"] = None
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)


def test_uncalibrated_scores_cannot_claim_probability():
    payload = valid_metadata("stage")
    payload["score_contract"]["semantics"] = "calibrated_probability"
    payload["calibration"] = {"status": "not_calibrated", "method": None}
    with pytest.raises(ValidationError):
        ArtifactMetadataV2.model_validate(payload)


def test_bundle_validation_rejects_training_hash_not_found_in_manifest(bundle):
    bundle.metadata["dataset_contract"]["training_file_sha256"] = "f" * 64
    assert validate_bundle_files(**bundle.paths).status.reason_code == "training_file_hash_mismatch"
```

- [ ] **Step 2: 编写多分类评估测试**

Add to `backend/tests/test_longitudinal_model_evaluation.py`:

```python
def test_multiclass_metrics_include_macro_f1_balanced_accuracy_and_fixed_matrix():
    metrics = compute_multiclass_metrics(
        labels=["rising", "stable", "falling", "rising"],
        predictions=["rising", "falling", "falling", "stable"],
        class_order=["rising", "stable", "falling"],
    )
    assert metrics.class_order == ["rising", "stable", "falling"]
    assert len(metrics.confusion_matrix) == 3
    assert metrics.macro_f1 is not None
    assert metrics.balanced_accuracy is not None
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_suite_schema.py backend/tests/test_longitudinal_model_evaluation.py -q
```

Expected: FAIL，因为 v2 通用契约、多分类指标和 evaluation 文件校验尚不存在。

- [ ] **Step 4: 实现通用严格契约**

Define:

```python
class ArtifactMetadataV2(StrictModel):
    schema_version: Literal["longitudinal_model_artifact.v2"]
    artifact_type: Literal["outcome", "stage", "trend"]
    task: str
    dataset: Literal["fatty_liver", "ad"]
    target: str
    horizon: dict[str, Any]
    feature_contract: FeatureContract
    dataset_contract: DatasetContractV2
    split_sha256: Sha256
    evaluation_sha256: Sha256
    model_contract: ModelContract
    output_contract: OutputContract
    calibration: CalibrationContract
    audit: ArtifactAuditContractV2
    status: Literal["candidate"]
    production_enabled: Literal[False]
    created_at: datetime
```

`OutputContract` must define binary class/threshold for outcome, ordered class list for stage, and `rising/stable/falling` for trend. Keep the current outcome v1 parser for historical candidate inspection, but new training writes v2 only.

- [ ] **Step 5: 实现 evaluation artifact 和校验**

`evaluation.json` must contain dataset/split hashes, selection metrics, locked-test metrics, baselines, class support and an explicit `locked_test_used_for_selection=false`. Registry validation recalculates all four hashes: model, metadata, evaluation and referenced manifest/training file.

- [ ] **Step 6: 运行契约与旧 registry 兼容测试**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_suite_schema.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_registry.py -q
```

Expected: PASS；旧 progression artifacts 继续被忽略；旧 outcome v1 candidate 可检查但不得进入新 disease release set。

- [ ] **Step 7: 记录检查点，不提交**

记录建议检查点：`feat: define complete longitudinal model artifact contracts`，不执行 commit。

---

### Task 5: 修复并完成三个结局模型训练、选择和锁定测试

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Modify: `backend/app/services/longitudinal_model_audit.py`
- Modify: `backend/app/schemas/longitudinal_model_training.py`
- Modify: `backend/tests/test_longitudinal_model_training.py`
- Modify: `backend/tests/test_longitudinal_model_audit.py`
- Modify: `scripts/train_longitudinal_outcome_models.py`
- Modify: `scripts/tests/test_train_longitudinal_outcome_models.py`

**Interfaces:**
- Consumes: `DiseaseGroupSplit`、`DatasetInput.file_sha256(relative_path)`、通用 v2 bundle 契约。
- Produces: `train_outcome_task(rows, task, split, dataset_input, output_dir, seed) -> TrainedCandidateBundle`。

- [ ] **Step 1: 编写锁定测试不参与选择的失败测试**

Add to `backend/tests/test_longitudinal_model_training.py`:

```python
def test_outcome_selection_never_reads_locked_test_until_candidate_is_frozen(monkeypatch, training_fixture):
    calls = []
    monkeypatch.setattr(training, "evaluate_locked_test", lambda *args, **kwargs: calls.append("locked") or locked_metrics())
    result = train_outcome_task(**training_fixture)
    assert result.selection_trace[-1] == "candidate_frozen"
    assert calls == ["locked"]
    assert result.evaluation.locked_test_used_for_selection is False


def test_fatty_liver_outcome_tasks_use_identical_disease_split(split, samples):
    first = prepare_outcome_task(samples, TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"], split)
    second = prepare_outcome_task(samples, TASK_SPECS["fatty_liver.cirrhosis_to_hcc"], split)
    assert first.split_sha256 == second.split_sha256 == split.sha256
```

- [ ] **Step 2: 编写准确训练文件哈希测试**

```python
def test_outcome_metadata_binds_its_actual_real_train_file(candidate_bundle, dataset_dir):
    metadata = ArtifactMetadataV2.model_validate_json(candidate_bundle.metadata_path.read_text("utf-8"))
    expected = sha256_file(dataset_dir / TASK_CONTRACTS[metadata.task].dataset_file)
    assert metadata.dataset_contract.training_file_sha256 == expected
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_audit.py -q
```

Expected: 至少新增测试 FAIL；旧实现会在全量行拟合、缺少完整锁定测试顺序或写错训练文件哈希。

- [ ] **Step 4: 实现开发训练/验证、候选冻结和锁定测试**

Implement this sequence exactly:

```python
development = rows_for_groups(rows, split.development_train_groups + split.development_validation_groups)
locked = rows_for_groups(rows, split.locked_test_groups)
cv_results = evaluate_candidates_on_development(development, candidates, seed=seed)
selected = select_candidate(cv_results, primary="pr_auc", tie_breakers=("roc_auc", "model_name"))
threshold = select_threshold_from_development_oof(selected.oof_labels, selected.oof_scores)
frozen = fit_selected_candidate(selected.spec, development, seed=seed)
locked_metrics = evaluate_locked_test(frozen, locked, threshold)
```

Do not refit after reading locked metrics. If the final deployment policy later fits on development only, record that explicitly; locked test remains untouched.

- [ ] **Step 5: 强化泄漏与异常高分审计**

Block on group overlap, future visits, forbidden features, synthetic rows in formal metrics, cross-task split mismatch and near-duplicate source-family leakage. High ROC/PR AUC triggers `review_required`, not silent pass.

- [ ] **Step 6: 写出三个 v2 candidate bundle**

Each task directory contains exactly one `.joblib`, one `.meta.json`, one `.evaluation.json`. Existing output directory remains no-overwrite. CLI returns only relative paths, task IDs, hashes and safe summaries.

- [ ] **Step 7: 运行 outcome 专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py scripts/tests/test_train_longitudinal_outcome_models.py -q
```

Expected: PASS；三任务均使用正确训练文件哈希；脂肪肝两任务 split SHA 相同；CLI 不生成 review/release。

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: train audited longitudinal outcome candidates`，不执行 commit。

---

### Task 6: 完成脂肪肝和 AD 下一阶段模型

**Files:**
- Create: `backend/app/services/longitudinal_stage_training.py`
- Create: `backend/tests/test_longitudinal_stage_training.py`
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/tests/test_longitudinal_features.py`
- Modify: `backend/app/services/disease_progression.py`

**Interfaces:**
- Consumes: 活动数据 release、`DiseaseGroupSplit`、固定窗口历史特征。
- Produces:
  - `build_stage_rows(timelines, disease, split) -> list[StageTrainingRow]`
  - `train_stage_candidate(rows, split, dataset_input, output_dir, seed) -> TrainedCandidateBundle`
  - tasks `fatty_liver.next_stage` and `ad.next_stage`。

- [ ] **Step 1: 编写阶段标签未来窗口和泄漏测试**

Add to `backend/tests/test_longitudinal_stage_training.py`:

```python
def test_stage_label_uses_only_next_365_days_and_can_preserve_current_stage():
    rows = build_stage_rows(stage_timeline_fixture(), "fatty_liver", split_fixture())
    assert label_at(rows, "p1", "2024-01-01") == "cirrhosis"
    assert label_at(rows, "p2", "2024-01-01") == "stay_pre_cirrhosis"
    assert row_at(rows, "p1", "2024-01-01").max_feature_date <= date(2024, 1, 1)


def test_stage_training_excludes_label_copy_features():
    catalog = build_stage_feature_catalog(stage_rows())
    assert not ({"final_stage", "event_dates", "dementia_date", "cirrhosis_date", "hcc_date"} & set(catalog.feature_names))


def test_ad_cdr_copy_risk_requires_review():
    audit = audit_stage_label_copy(ad_rows_with_deterministic_cdr())
    assert audit.status == "review_required"
    assert "cdr_label_copy_risk" in audit.reason_codes
```

- [ ] **Step 2: 编写阶段评估和类别不足测试**

```python
def test_stage_candidate_reports_ordered_metrics(stage_candidate):
    metrics = stage_candidate.evaluation.locked_test
    assert metrics.macro_f1 is not None
    assert metrics.balanced_accuracy is not None
    assert metrics.ordered_error is not None
    assert metrics.class_order == stage_candidate.metadata.output_contract.classes


def test_stage_training_refuses_missing_required_class(rows_without_hcc, split):
    with pytest.raises(StageTrainingError, match="stage_class_support_insufficient"):
        train_stage_candidate(rows_without_hcc, split, dataset_input(), output_dir(), seed=42)
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_stage_training.py backend/tests/test_longitudinal_features.py -q
```

Expected: FAIL，因为正式阶段样本、训练器和 bundle 尚不存在。

- [ ] **Step 4: 实现阶段样本与共享特征**

Use an explicit stage target resolver:

```python
def resolve_stage_target(patient: PatientTimeline, as_of: date, horizon_days: int = 365) -> str | None:
    current = stage_at(patient, as_of)
    future = stage_at(patient, as_of + timedelta(days=horizon_days))
    if current is None or future is None or not fully_observed(patient, as_of, horizon_days):
        return None
    return stay_label(current) if future == current else normalized_stage(future)
```

Feature creation must call the same historical feature builder used online. Current stage may be an allowed categorical input; target event dates and final stage are forbidden.

- [ ] **Step 5: 实现模型选择和锁定测试**

Use deterministic candidates suitable for small ordered multiclass data, initially multinomial logistic regression and class-balanced random forest. Select by development macro F1, then balanced accuracy, then stable model name. Report ordered absolute stage-distance error.

- [ ] **Step 6: 写出两个 stage candidate bundle**

Expected artifact stems:

```text
fatty_liver_next_stage_365d
ad_next_stage_365d
```

Output classes use normalized internal codes; report rendering maps them to approved Chinese labels.

- [ ] **Step 7: 运行阶段模型专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_stage_training.py backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_schema_contracts.py -q
```

Expected: PASS。若真实数据类别支持不足，本测试仍验证明确拒绝路径；正式候选生成阶段必须将不足证据交给用户，不能降低门槛或伪造类别。

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: add audited next-stage models`，不执行 commit。

---

### Task 7: 完成关键指标下一次访视趋势方向模型

**Files:**
- Create: `backend/app/services/longitudinal_trend_training.py`
- Create: `backend/tests/test_longitudinal_trend_training.py`
- Modify: `scripts/train_longitudinal_trend_models.py`
- Modify: `scripts/tests/test_train_longitudinal_trend_models.py`
- Modify: `backend/app/services/disease_progression.py`
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/tests/test_longitudinal_trend_prediction.py`

**Interfaces:**
- Consumes: 活动数据 release、疾病级 split、历史特征和指标专属容差。
- Produces:
  - `TREND_CONTRACTS[(disease, indicator)]`
  - `build_trend_rows(timelines, contract, split) -> list[TrendTrainingRow]`
  - `train_trend_candidate(rows, contract, split, dataset_input, output_dir, seed)`。

- [ ] **Step 1: 编写指标容差和未来信息隔离测试**

Add to `backend/tests/test_longitudinal_trend_training.py`:

```python
@pytest.mark.parametrize(
    ("current", "following", "tolerance", "expected"),
    [(100.0, 104.9, 0.05, "stable"), (100.0, 105.1, 0.05, "rising"), (100.0, 94.9, 0.05, "falling")],
)
def test_direction_boundaries_are_versioned(current, following, tolerance, expected):
    assert direction_label(current, following, tolerance) == expected


def test_next_visit_value_is_label_only_and_never_a_feature():
    row = build_trend_rows(trend_timeline_fixture(), TREND_CONTRACTS[("ad", "mmse")], split_fixture())[0]
    assert row.label == "falling"
    assert "next_value" not in row.features
    assert row.max_feature_date < row.label_visit_date
```

- [ ] **Step 2: 编写丰富历史特征和患者分组测试**

```python
def test_trend_features_are_not_latest_value_only():
    names = set(build_trend_feature_catalog(trend_rows()).feature_names)
    assert {"visit_count", "observation_span_days", "days_since_previous_visit", "mmse.first", "mmse.last", "mmse.time_slope_per_day", "mmse.missing_ratio"} <= names


def test_trend_rows_reuse_disease_split_for_every_indicator(all_trend_rows, split):
    assert {row.partition for row in all_trend_rows if row.group_id in split.locked_test_groups} == {"locked_test"}
```

- [ ] **Step 3: 编写缺类和 direction-only 输出契约测试**

```python
def test_trend_training_refuses_missing_direction_class(rows_without_stable, contract, split):
    with pytest.raises(TrendTrainingError, match="trend_class_support_insufficient"):
        train_trend_candidate(rows_without_stable, contract, split, dataset_input(), output_dir(), seed=42)


def test_direction_only_artifact_never_outputs_future_value(trend_candidate):
    assert trend_candidate.metadata.output_contract.projected_value_supported is False
    assert trend_candidate.metadata.output_contract.prediction_interval_supported is False
```

- [ ] **Step 4: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_trend_training.py backend/tests/test_longitudinal_trend_prediction.py scripts/tests/test_train_longitudinal_trend_models.py -q
```

Expected: FAIL；当前只有单值训练行助手，没有完整训练、评估或 bundle。

- [ ] **Step 5: 实现指标合同和趋势训练器**

Declare explicit contracts for the approved indicators. Each contract contains disease, indicator, tolerance, class order, unit policy and minimum class/patient support. Build rows from prefixes ending before the label visit. Use development macro F1 and balanced accuracy to select between multinomial logistic regression and class-balanced random forest.

- [ ] **Step 6: 写出每指标独立 bundle 和安全摘要**

Artifact stem format:

```text
<dataset>_next_visit_trend_<indicator>
```

Each bundle records its indicator-specific training row count, patient count, class support and tolerance version. Unsupported indicators produce an audit result, not a fake model.

- [ ] **Step 7: 运行趋势专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_trend_training.py backend/tests/test_longitudinal_trend_prediction.py scripts/tests/test_train_longitudinal_trend_models.py backend/tests/test_longitudinal_features.py -q
```

Expected: PASS；线上没有模型时仍返回空趋势预测，不把观察斜率冒充未来预测。

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: add audited next-visit trend models`，不执行 commit。

---

### Task 8: 建立疾病级 release set、原子切换和回退

**Files:**
- Create: `backend/app/services/longitudinal_release_set.py`
- Create: `backend/tests/test_longitudinal_release_set.py`
- Create: `scripts/manage_longitudinal_release_sets.py`
- Create: `scripts/tests/test_manage_longitudinal_release_sets.py`
- Modify: `backend/app/services/longitudinal_model_release.py`
- Modify: `backend/app/services/longitudinal_model_registry.py`
- Modify: `backend/app/schemas/longitudinal_model_registry.py`
- Modify: `backend/tests/test_longitudinal_model_release.py`
- Modify: `backend/tests/test_longitudinal_model_registry.py`

**Interfaces:**
- Consumes: outcome、stage、trend v2 candidate bundles。
- Produces:
  - `DiseaseReleaseSet`
  - `review_release_set(candidate_manifest, registry_root, reviewer, reviewed_at, note)`
  - `enable_release_set(review_path, registry_root, enabled_by, enabled_at)`
  - `rollback_release_set(dataset, target_release_set_id, registry_root, actor, changed_at)`
  - `load_disease_release_set(dataset, registry_root) -> LoadedDiseaseModelSuite`

- [ ] **Step 1: 编写完整模型组和原子指针测试**

Add to `backend/tests/test_longitudinal_release_set.py`:

```python
def test_release_set_requires_all_declared_outcome_stage_and_supported_trend_bundles(tmp_path):
    candidate = release_set_candidate(tmp_path, missing={"ad.next_stage"})
    with pytest.raises(ReleaseSetError, match="required_bundle_missing"):
        review_release_set(candidate, tmp_path / "registry", reviewer="owner", reviewed_at=NOW, note="review")


def test_failed_preload_does_not_change_active_pointer(tmp_path, monkeypatch):
    old = enabled_release_set(tmp_path, "ad", "ad-set-v1")
    new = reviewed_release_set(tmp_path, "ad", "ad-set-v2")
    monkeypatch.setattr(release_sets, "preload_release_set", lambda *args: (_ for _ in ()).throw(ReleaseSetError("preload_failed")))
    with pytest.raises(ReleaseSetError):
        enable_release_set(new.review_path, tmp_path, enabled_by="owner", enabled_at=NOW)
    assert read_active_pointer(tmp_path, "ad").release_set_id == old.release_set_id
```

- [ ] **Step 2: 编写回退与并发快照测试**

```python
def test_rollback_atomically_restores_previous_release_set(tmp_path):
    first = enabled_release_set(tmp_path, "fatty_liver", "fl-set-v1")
    second = enabled_release_set_after(tmp_path, first, "fl-set-v2")
    rollback_release_set("fatty_liver", first.release_set_id, tmp_path, actor="owner", changed_at=NOW)
    assert read_active_pointer(tmp_path, "fatty_liver").release_set_id == first.release_set_id


def test_loaded_suite_remains_immutable_after_pointer_switch(tmp_path):
    first = enabled_release_set(tmp_path, "ad", "ad-set-v1")
    loaded = load_disease_release_set("ad", tmp_path)
    enable_release_set(reviewed_release_set(tmp_path, "ad", "ad-set-v2").review_path, tmp_path, enabled_by="owner", enabled_at=NOW)
    assert loaded.release_set_id == first.release_set_id
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_release_set.py scripts/tests/test_manage_longitudinal_release_sets.py -q
```

Expected: FAIL，因为 disease release set 和活动指针不存在。

- [ ] **Step 4: 实现不可变 release set 和活动指针**

Registry layout:

```text
registry/
  bundles/<model_id>/...
  release_sets/<dataset>/<release_set_id>.json
  reviews/<review_id>.json
  active/<dataset>.json
  activation_log/<activation_id>.json
```

`active/<dataset>.json` is written with exclusive temporary file creation, `fsync`, and `Path.replace`. It contains only release-set identity and hash. Bundle and release-set records are immutable.

- [ ] **Step 5: 实现预加载和完整性验证**

Preload all required bundles, verify model/metadata/evaluation/manifest/split hashes, validate model interfaces, and run one disease-specific safe inference fixture. Only then replace the active pointer.

- [ ] **Step 6: 实现显式 review/enable/rollback CLI**

Commands:

```powershell
python scripts/manage_longitudinal_release_sets.py review --candidate-manifest <path> --registry-dir <path> --reviewer <id> --note <text> --reviewed-at <iso>
python scripts/manage_longitudinal_release_sets.py enable --review-file <path> --registry-dir <path> --enabled-by <id> --enabled-at <iso>
python scripts/manage_longitudinal_release_sets.py rollback --dataset ad --target-release-set <id> --registry-dir <path> --actor <id> --changed-at <iso>
```

Missing explicit paths or identities return safe JSON error codes. No command infers a registry directory or auto-enables after training.

- [ ] **Step 7: 运行 release-set 和旧 registry 回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_release_set.py backend/tests/test_longitudinal_model_release.py backend/tests/test_longitudinal_model_registry.py scripts/tests/test_manage_longitudinal_release_sets.py scripts/tests/test_manage_longitudinal_registry.py -q
```

Expected: PASS；旧单任务 release loader remains readable only for historical diagnostics and is not selected when an active disease release set exists.

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: add atomic disease model release sets`，不执行 commit。

---

### Task 9: 接入结局、阶段和趋势在线推理

**Files:**
- Modify: `backend/app/schemas/longitudinal_report.py`
- Modify: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/app/services/disease_progression.py`
- Modify: `backend/app/services/longitudinal_model_registry.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`
- Modify: `backend/tests/test_longitudinal_trend_prediction.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`
- Modify: `backend/tests/test_longitudinal_schema_contracts.py`

**Interfaces:**
- Consumes: `LoadedDiseaseModelSuite` and shared feature builders.
- Produces: `LongitudinalPredictionResultV3` with release identity, outcome, stage, per-indicator trends and independent statuses.

- [ ] **Step 1: 编写 v3 三类模型成功测试**

Add to `backend/tests/test_longitudinal_prediction_contract.py`:

```python
def test_v3_result_uses_one_release_set_for_outcome_stage_and_trends(complete_ad_suite):
    result = run_longitudinal_prediction(ad_case(), ad_visits(), AD_ADAPTER, complete_ad_suite)
    assert result.schema_version == "longitudinal_prediction.v3"
    assert result.release_set.release_set_id == complete_ad_suite.release_set_id
    assert result.model_status.outcome.status == "available"
    assert result.model_status.stage.status == "available"
    assert result.outcome_prediction.stage_projection.status == "available"
    assert result.trend_predictions
    assert {item.model_status.status for item in result.trend_predictions} == {"available"}
```

- [ ] **Step 2: 编写分模型安全降级测试**

```python
def test_one_broken_trend_model_does_not_remove_other_predictions(complete_fatty_liver_suite):
    complete_fatty_liver_suite.trends["alt"].model = RaisingModel()
    result = run_longitudinal_prediction(fl_case(), fl_visits(), FATTY_LIVER_ADAPTER, complete_fatty_liver_suite)
    by_indicator = {item.indicator: item for item in result.trend_predictions}
    assert by_indicator["alt"].model_status.reason_code == "prediction_failed"
    assert by_indicator["ast"].forecast.direction is not None
    assert result.outcome_prediction.risk_score is not None
    assert result.outcome_prediction.stage_projection.likely_next_stage is not None


def test_incompatible_stage_model_emits_no_stage_guess_but_keeps_outcome_and_trends(suite_with_bad_stage):
    result = run_longitudinal_prediction(ad_case(), ad_visits(), AD_ADAPTER, suite_with_bad_stage)
    assert result.model_status.stage.status == "incompatible"
    assert result.outcome_prediction.stage_projection.status == "not_estimated"
    assert result.outcome_prediction.risk_score is not None
    assert result.trend_predictions
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_trend_prediction.py backend/tests/test_longitudinal_schema_contracts.py -q
```

Expected: 新增 v3 测试 FAIL；当前 stage/trend 固定 missing/empty。

- [ ] **Step 4: 扩展 v3 schema**

Add exact persisted identity:

```python
class ReleaseSetIdentity(StrictModel):
    dataset: Literal["fatty_liver", "ad"]
    release_set_id: str
    release_set_sha256: str
    data_release_id: str
    split_sha256: str


class TrendPredictionV3(TrendPrediction):
    model_status: ModelRuntimeStatus
```

V3 validators require no output from unavailable models but permit other model families to remain available. Keep V1/V2 parsing unchanged for history.

- [ ] **Step 5: 实现三类推理器**

Use separate functions:

```python
run_outcome_inference(route, suite.outcomes[route.task], case, visits)
run_stage_inference(suite.stage, case, visits)
run_trend_inference(indicator, suite.trends[indicator], case, visits)
```

Catch only expected model/contract exceptions at each boundary and convert them to stable reason codes. Do not catch report persistence errors as model incompatibility.

- [ ] **Step 6: 验证观察事实与预测不混合**

The observation block continues to come only from `summarize_observation`. Trend forecast basis must name the trend model, not `observed_slope_and_longitudinal_model`; when the trend model is unavailable, no forecast row is emitted for v3.

- [ ] **Step 7: 运行推理和端到端专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_trend_prediction.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_progression_api.py -q
```

Expected: PASS；旧 progression API tests remain unchanged and pass.

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: run complete longitudinal model suites online`，不执行 commit。

---

### Task 10: 把三类预测写入完整报告、历史和 PDF

**Files:**
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/services/pdf_generator.py`
- Modify: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_report_acceptance.py`
- Modify: `backend/tests/test_longitudinal_report_persistence.py`
- Modify: `backend/tests/test_longitudinal_pdf_contract.py`
- Modify: `backend/tests/test_pdf_generation.py`

**Interfaces:**
- Consumes: `LongitudinalPredictionResultV3` and fixed `LoadedDiseaseModelSuite` identity.
- Produces: 保存的正文、prediction result、input snapshot、evidence snapshot 和 release identity；历史/PDF只读这些保存值。

- [ ] **Step 1: 编写完整报告内容测试**

Add to `backend/tests/test_longitudinal_report_acceptance.py`:

```python
def test_complete_v3_report_separates_observation_outcome_stage_and_trend(complete_prediction_v3):
    content = render_longitudinal_markdown(complete_prediction_v3.model_dump(mode="json"), sources())
    assert "已观察到的纵向变化" in content
    assert "未来 365 天进展风险" in content
    assert "下一疾病阶段预测" in content
    assert "下一次访视指标趋势预测" in content
    assert "模型分数，不代表临床概率" in content
    assert "已观察方向" in content and "模型预测方向" in content
```

- [ ] **Step 2: 编写历史不重算和旧版本兼容测试**

Add to `backend/tests/test_longitudinal_report_persistence.py`:

```python
@pytest.mark.parametrize("prediction_result", [historical_v1(), historical_v2(), complete_v3()])
def test_history_and_pdf_never_recalculate_any_prediction(prediction_result, monkeypatch):
    report = saved_report(prediction_result=prediction_result, content="生成时正文")
    monkeypatch.setattr("app.services.longitudinal_prediction.run_longitudinal_prediction", fail_if_called)
    assert get_report(report.id, db=db_for(report), current_user=owner()).content == "生成时正文"
    with patch("app.api.operator.generate_pdf", return_value=b"%PDF") as generate:
        download_report_pdf(report.id, db=db_for(report), current_user=owner())
    generate.assert_called_once_with("生成时正文", report.title, prediction_result)
```

- [ ] **Step 3: 编写 release set 固定测试**

```python
async def test_report_generation_persists_the_suite_loaded_at_start(db, first_suite, second_suite):
    stream = generate_longitudinal_report(db, report_id(), snapshot(), visits(), AD_ADAPTER, model_registry=first_suite, sources=[])
    switch_active_suite_to(second_suite)
    await consume(stream)
    saved = db.query(AIReport).filter(AIReport.id == report_id()).one()
    assert saved.prediction_result["release_set"]["release_set_id"] == first_suite.release_set_id
```

- [ ] **Step 4: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_longitudinal_report_persistence.py backend/tests/test_longitudinal_pdf_contract.py -q
```

Expected: 新增完整 stage/trend/release identity 测试 FAIL。

- [ ] **Step 5: 更新报告渲染**

Keep the approved P0-07 sections and add explicit subsections inside sections 5 and 6. Render stage candidates with score semantics, trend rows with observed and predicted direction, and per-model limitation text. Do not display internal task IDs as clinical labels.

- [ ] **Step 6: 固定并持久化 release identity**

`create_longitudinal_report()` loads one `LoadedDiseaseModelSuite` before starting the stream. The generator persists its identity inside `prediction_result`; no schema migration is needed because the column is JSON.

- [ ] **Step 7: 保持历史和 PDF 为保存结果视图**

Do not call model registry, feature builders, standard resolution or prediction from `get_report()` or `download_report_pdf()`. PDF charts may read saved observation/trend data only.

- [ ] **Step 8: 运行报告、历史和 PDF 专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_longitudinal_report_persistence.py backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_pdf_generation.py backend/tests/test_operator_predictive_api.py -q
```

Expected: PASS；PDF error remains the safe message and contains no local details.

- [ ] **Step 9: 记录检查点，不提交**

记录建议检查点：`feat: persist and render complete longitudinal predictions`，不执行 commit。

---

### Task 11: 更新 readiness 和双疾病 smoke

**Files:**
- Modify: `backend/app/schemas/longitudinal_readiness.py`
- Modify: `backend/app/services/longitudinal_readiness.py`
- Modify: `backend/tests/test_longitudinal_readiness_schema.py`
- Modify: `backend/tests/test_longitudinal_readiness_service.py`
- Modify: `scripts/check_longitudinal_readiness.py`
- Modify: `scripts/tests/test_check_longitudinal_readiness.py`
- Modify: `scripts/smoke_longitudinal_registry.py`
- Modify: `scripts/tests/test_smoke_longitudinal_registry.py`

**Interfaces:**
- Consumes: activity data release and disease model release set.
- Produces: safe readiness JSON and smoke summary for all required model types.

- [ ] **Step 1: 编写完整能力 readiness 测试**

```python
def test_readiness_reports_data_and_model_release_identities(ready_context):
    report = collect_longitudinal_readiness(**ready_context)
    assert report.datasets["ad"].active_release_id
    assert report.models["ad"].release_set_id
    assert report.models["ad"].outcome.available
    assert report.models["ad"].stage.available
    assert report.models["ad"].trend.available_count == report.models["ad"].trend.required_count
```

- [ ] **Step 2: 编写 smoke 安全输出测试**

```python
def test_smoke_summary_contains_no_paths_or_patient_identity(complete_registry, data_root):
    payload = run_smoke(complete_registry, data_root)
    assert_safe_payload(payload)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert ":\\Users\\" not in rendered
    assert "source_document" not in rendered
    assert "patient_label" not in rendered
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py scripts/tests/test_smoke_longitudinal_registry.py -q
```

Expected: 新字段和完整模型组 smoke 测试 FAIL。

- [ ] **Step 4: 实现 readiness 和 smoke**

Readiness must distinguish `missing`, `incompatible`, `reviewed`, `enabled`, `data_release_missing`, `release_set_incomplete`, and `ready`. Smoke runs one fatty-liver pre-cirrhosis case, one fatty-liver cirrhosis case, and one AD pre-dementia case, then confirms outcome, stage, expected supported trends and release identity.

- [ ] **Step 5: 运行专项回归**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py scripts/tests/test_smoke_longitudinal_registry.py -q
```

Expected: PASS；JSON 输出不含数据库连接、绝对路径、患者标签或 traceback。

- [ ] **Step 6: 记录检查点，不提交**

记录建议检查点：`feat: verify complete longitudinal release readiness`，不执行 commit。

---

### Task 12: 完成电脑端三类模型展示

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/components/LongitudinalPredictionSummary.vue`
- Modify: `frontend/src/components/LongitudinalReportView.vue`
- Modify: `frontend/tests/longitudinal-report-ui-contract.test.mjs`
- Modify: `frontend/tests/progression-ui-contract.test.mjs`
- Reference: `docs/DESIGN_SPEC.md`

**Interfaces:**
- Consumes: persisted `LongitudinalPredictionResultV1 | V2 | V3`.
- Produces: 电脑端结局、阶段、趋势、模型状态和 release identity 展示；旧报告仍能渲染。

- [ ] **Step 1: 重新完整阅读 UI 规范**

Run:

```powershell
Get-Content -Raw docs/DESIGN_SPEC.md
```

Expected: 在修改 Vue/CSS 前确认使用现有暖杏蓝变量、间距、圆角和电脑端布局规则。

- [ ] **Step 2: 编写前端合约失败测试**

Extend `frontend/tests/longitudinal-report-ui-contract.test.mjs`:

```javascript
test('complete prediction summary exposes outcome stage and trend without probability wording', () => {
  const source = readFileSync(resolve('frontend/src/components/LongitudinalPredictionSummary.vue'), 'utf8')
  for (const text of ['未来 365 天结局', '下一疾病阶段', '下一次访视趋势', '模型分数', '不代表临床概率']) {
    assert.ok(source.includes(text), text)
  }
  assert.ok(!source.includes('临床概率：'))
})

test('historical reports do not require v3 fields', () => {
  const api = readFileSync(resolve('frontend/src/api/operator.ts'), 'utf8')
  assert.ok(api.includes("schema_version: 'longitudinal_prediction.v1' | 'longitudinal_prediction.v2' | 'longitudinal_prediction.v3'"))
})
```

- [ ] **Step 3: 运行测试确认当前失败**

Run:

```powershell
node --test frontend/tests/longitudinal-report-ui-contract.test.mjs
```

Expected: FAIL，因为当前类型宽泛且摘要未展示真实 stage/trend 内容。

- [ ] **Step 4: 增加严格 TypeScript 联合类型**

Define interfaces for release identity, runtime status, stage candidates and trend model status. Keep V1/V2 fields optional through a discriminated union; do not make historical API responses fail type checking.

- [ ] **Step 5: 更新摘要和报告视图**

Display:

- outcome score/band/version/semantics；
- current and likely next stage with candidate scores；
- trend table: indicator, observed direction, predicted direction, status；
- ordinary Chinese degradation messages；
- release set ID in technical details, not as a prominent clinical label。

Use existing CSS variables only. Do not add mobile-specific behavior beyond preserving the existing responsive fallback.

- [ ] **Step 6: 运行 Node 合约、类型检查和构建**

Run:

```powershell
node --test frontend/tests/longitudinal-report-ui-contract.test.mjs frontend/tests/progression-ui-contract.test.mjs frontend/tests/operator-legacy-cleanup.test.mjs frontend/tests/longitudinal-case-sync.test.mjs frontend/tests/longitudinal-baseline-stage.test.mjs
npm --prefix frontend run build
```

Expected: 全部 PASS；现有 progression UI 合约不变。

- [ ] **Step 7: 记录检查点，不提交**

记录建议检查点：`feat: show complete longitudinal model results on desktop`，不执行 commit。

---

### Task 13: 建立完整模型组训练 CLI 并生成隔离 candidate

**Files:**
- Create: `scripts/train_longitudinal_model_suite.py`
- Create: `scripts/tests/test_train_longitudinal_model_suite.py`
- Modify: `scripts/train_longitudinal_outcome_models.py`
- Modify: `scripts/train_longitudinal_trend_models.py`
- Modify: `scripts/build_longitudinal_dataset.py`

**Interfaces:**
- Consumes: versioned dataset directory, exact manifest, disease group split and all three trainers.
- Produces: one candidate manifest per disease, never review/enable files.

- [ ] **Step 1: 编写 CLI 安全和完整性测试**

Add to `scripts/tests/test_train_longitudinal_model_suite.py`:

```python
def test_suite_cli_never_reviews_or_enables(tmp_path, monkeypatch):
    output = tmp_path / "candidate"
    assert cli.main(["--dataset-dir", str(dataset_fixture(tmp_path)), "--output-dir", str(output), "--disease", "all", "--seed", "42"]) == 0
    assert list(output.glob("fatty_liver/*.candidate-set.json"))
    assert list(output.glob("ad/*.candidate-set.json"))
    assert not list(output.rglob("review-*.json"))
    assert not list(output.rglob("release-*.json"))
    assert not list(output.rglob("active/*.json"))


def test_suite_cli_refuses_nonempty_output(tmp_path):
    output = tmp_path / "candidate"
    output.mkdir()
    (output / "existing").write_text("keep", encoding="utf-8")
    assert cli.main(["--dataset-dir", "dataset", "--output-dir", str(output), "--disease", "ad"]) == 2
```

- [ ] **Step 2: 运行测试确认当前失败**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_model_suite.py -q
```

Expected: FAIL，因为完整 suite CLI 尚不存在。

- [ ] **Step 3: 实现 audit/train CLI**

Supported commands are audit-only by default and training only with `--train`. The CLI validates manifest/split first, trains all required models for the requested disease, writes a candidate-set manifest with relative paths and hashes, and returns safe JSON. It never accepts an `--enable` flag.

- [ ] **Step 4: 运行 CLI 单测**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_model_suite.py scripts/tests/test_train_longitudinal_outcome_models.py scripts/tests/test_train_longitudinal_trend_models.py -q
```

Expected: PASS。

- [ ] **Step 5: 在新的隔离目录重新生成数据集**

Choose a new path under ignored `.tmp/` and never overwrite prior evidence:

```powershell
python scripts/build_longitudinal_dataset.py --output-dir .tmp/longitudinal-migration-20260827/dataset
```

Expected: safe JSON reports success; generated manifest contains run ID, exact file hashes and split hash. If current CLI syntax differs after Task 3, use the explicit documented equivalent from `--help`; do not omit the output directory.

- [ ] **Step 6: 运行完整候选训练**

Run:

```powershell
python scripts/train_longitudinal_model_suite.py --train --dataset-dir .tmp/longitudinal-migration-20260827/dataset --output-dir .tmp/longitudinal-migration-20260827/candidates --disease all --seed 42
```

Expected: creates fatty-liver and AD candidate-set manifests, all estimable bundle files and evaluation artifacts; no review/release/active files.

- [ ] **Step 7: 审计正式数据支持情况**

For every planned stage and trend model, classify the result as:

- candidate produced and evaluation complete；
- blocked by leakage；
- not estimable because a required class/patient support is absent。

Do not change thresholds after seeing locked-test results. If any mandatory model is not estimable, stop before release-set review and present the evidence to the user.

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`feat: orchestrate complete longitudinal model candidate training`，不执行 commit。

---

### Task 14: 执行候选 registry、双疾病 smoke 和完整报告验收

**2026-08-27 补充实施步骤（用户已批准合成演示数据）：**

- 新增显式 `synthetic_demonstration` 构建命令，默认真实数据构建契约保持不变。
- 先通过类别覆盖测试，保证两疾病每个疾病级分区都覆盖强制阶段和趋势类别，再训练候选模型。
- review 必须在写 review 记录前校验源文件和哈希，并把数据 manifest、manifest 声明文件和 bundle 不可变复制到隔离 registry。
- enable 前逐 bundle 验证 artifact、metadata、evaluation、训练文件、疾病级 split 和模型反序列化；任何失败不得修改 active 指针。
- smoke 必须验证阶段单调约束，防止当前肝硬化回退到肝硬化前或当前 MCI 回退到正常。

**Files:**
- Modify only if a failing test exposes a defect: files from Tasks 8–12.
- Evidence output: ignored `.tmp/longitudinal-migration-20260827/verification/`

**Interfaces:**
- Consumes: complete candidate sets from Task 13.
- Produces: isolated reviewed/released test registry, smoke evidence and report/PDF acceptance evidence; does not touch production registry.

- [ ] **Step 1: 在隔离 registry review candidate sets**

Run explicit review commands for both diseases using `.tmp/longitudinal-migration-20260827/registry`. Use non-sensitive audit identities and ISO timestamps. Never point this step at `backend/app/ml_models`.

Expected: review files and copied immutable bundles exist; no active pointers yet.

- [ ] **Step 2: 在隔离 registry enable 并运行 preload**

Run explicit enable commands for both reviewed sets.

Expected: activity pointers exist only inside the isolated registry; preload validates all hashes and model interfaces.

- [ ] **Step 3: 运行双疾病 registry smoke**

Run:

```powershell
python scripts/smoke_longitudinal_registry.py --registry-dir .tmp/longitudinal-migration-20260827/registry --data-root data/generated
```

Expected: fatty-liver pre-cirrhosis, fatty-liver cirrhosis and AD cases all return release identity, outcome, stage and supported trend summaries; output contains no patient label, source filename, path, secret or traceback.

- [ ] **Step 4: 运行后端完整专项测试**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_data_release.py backend/tests/test_longitudinal_group_split.py backend/tests/test_longitudinal_model_suite_schema.py backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_stage_training.py backend/tests/test_longitudinal_trend_training.py backend/tests/test_longitudinal_release_set.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_longitudinal_report_persistence.py backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_progression_api.py -q
```

Expected: PASS。

- [ ] **Step 5: 生成脂肪肝与 AD 桌面端验收报告**

Use the existing local desktop acceptance workflow with the isolated registry configured for the running backend. Create one fatty-liver report for each outcome route and one AD report. Confirm each saved report contains observation, outcome, stage, trend, evidence, limitations and release identity.

Expected: new reports use the isolated new release sets. Do not modify or delete historical reports.

- [ ] **Step 6: 验证旧报告和 PDF 不变**

Open previously saved P0-07 reports, compare stored content before/after, and download PDFs. Confirm the saved body bytes/text are unchanged and PDF uses saved content. Do not trigger regeneration.

- [ ] **Step 7: 验证故障降级和回退**

Against copied isolated registries, test:

- missing model file；
- metadata mismatch；
- evaluation hash mismatch；
- feature version mismatch；
- prediction exception；
- activity pointer switch failure；
- rollback to previous set。

Expected: affected model safely degrades, unrelated predictions remain, pointer failure keeps the previous set, rollback restores prior identities.

- [ ] **Step 8: 运行电脑端合约和构建**

Run:

```powershell
node --test frontend/tests/*.test.mjs
npm --prefix frontend run build
```

If PowerShell wildcard expansion is unsuitable, enumerate files with `Get-ChildItem frontend/tests -Filter *.test.mjs | ForEach-Object FullName` and pass the resulting explicit list to `node --test` without shell-crossing destructive operations.

Expected: Node contracts and build PASS。

- [ ] **Step 9: 记录检查点，不提交**

记录建议检查点：`test: verify complete longitudinal model workflow`，不执行 commit。

---

### Task 15: 数据库备份演练、生产候选报告和用户审批门

**Files:**
- Evidence output: ignored `.tmp/longitudinal-migration-20260827/verification/`
- No production mutation before approval.

**Interfaces:**
- Consumes: verified candidate data releases and model release sets.
- Produces: user-facing migration report, exact production switch commands and exact rollback commands.

- [ ] **Step 1: 验证备份工具和目标，不输出秘密**

Resolve database connection internally from existing settings. Print only a redacted host class, database logical name hash and backup destination. Confirm the backup target is an explicit file under the verification directory, never a workspace root or home directory.

- [ ] **Step 2: 创建正式更新前数据库备份**

Use the documented custom-format PostgreSQL backup process from `docs/DEPLOY.md`. Do not include the command with password or URL in captured evidence. Record backup file SHA-256, size, timestamp and PostgreSQL tool version.

- [ ] **Step 3: 在隔离数据库验证恢复**

Restore the backup into an explicitly isolated test database, run readonly counts for diseases, case records, operator cases, visits and AI reports, and compare with the source summaries. Never restore over the current database during rehearsal.

- [ ] **Step 4: 生成生产候选对比报告**

Report for each disease/model:

- data run and split hashes；
- development and locked-test metrics；
- class/patient support；
- legacy baseline comparison；
- leakage audit；
- artifact/evaluation hashes；
- isolated smoke result；
- report/history/PDF/frontend/old API verification；
- exact production data activation, model activation and rollback sequence。

Do not include patient data, DB URL, password, absolute path or traceback.

- [ ] **Step 5: 停止并请求生产切换批准**

Do not run production data activation or point `backend/app/ml_models` at the new registry. Ask one question only: whether the user approves the presented data release and disease release-set IDs for production activation.

- [ ] **Step 6: 获批后才执行数据和模型切换**

If approved, activate data releases inside one database transaction per disease, preload the corresponding disease release set, then atomically switch its active pointer. Activate fatty liver and AD separately so either can be rolled back independently.

Implementation clarification for the approved `synthetic_demonstration` profile: its data release is immutable training provenance copied into the model registry, not a reference-case release. Do not import it into `case_records` and do not activate it as similar-case evidence. Because production currently has no v3 active pointer, the first-release rollback command must use the audited `deactivate` operation to restore the legacy registry fallback; do not delete pointer files manually.

- [ ] **Step 7: 切换后立即运行只读 smoke**

Run readiness, three routing smoke cases, one new report per disease, history retrieval and PDF download. On any release-integrity or inference regression, execute the documented pointer rollback and data release rollback, then report the incident without hiding failures.

- [ ] **Step 8: 记录检查点，不提交**

记录建议检查点：`ops: activate verified longitudinal data and model releases`，不执行 commit。生产切换本身不授权 commit 或 push。

---

### Task 16: 最终专项回归、全量测试决策和交付

**Files:**
- All modified files from Tasks 2–13.
- No new functionality in this task; only fixes for demonstrated defects.

**Interfaces:**
- Consumes: completed implementation and, if separately approved, production activation evidence.
- Produces: final evidence-backed completion report and uncommitted working-tree handoff.

- [ ] **Step 1: 运行保护范围和格式检查**

Run:

```powershell
git diff --check
git status --short
git diff -- backend/alembic
git diff -- backend/app/services/progression_engine.py backend/app/api/operator.py
```

Expected: no whitespace errors; no Alembic changes; operator changes are limited to complete model suite loading/persistence; legacy progression code remains functionally unchanged.

- [ ] **Step 2: 运行完整后端专项回归**

Run the union of all backend and script test files listed in Tasks 1–14, including both diseases, registry faults, reports, history, PDF and old progression API.

Expected: PASS。Do not summarize a partial subset as all backend tests.

- [ ] **Step 3: 运行完整前端验证**

Run:

```powershell
node --test frontend/tests/*.test.mjs
npm --prefix frontend run build
```

Expected: PASS。

- [ ] **Step 4: 评估全量 pytest，但默认不运行**

根据专项测试覆盖范围、既有全量测试在约 64% 时的耗时和失败记录，整理是否值得运行全量 pytest、预计耗时和可获得的额外覆盖。本步骤默认停止在评估结论，不执行下面命令：

```powershell
python -m pytest -q
```

只有用户在看到评估结论后再次明确批准，才执行该命令。如果获批后运行时间过长，可以有序中止，记录耗时、进度、通过数量和失败测试名称，不输出敏感 traceback。命令没有成功退出时不得声称全量通过。

- [ ] **Step 5: 使用 verification-before-completion 复核证据**

Confirm fresh outputs for:

- exact data hashes and split；
- all estimable outcome/stage/trend models；
- release-set preload/switch/rollback；
- fatty liver and AD reports；
- old report unchanged；
- PDF consistency；
- old progression API；
- frontend contracts/build；
- `git diff --check`；
- full pytest decision；若用户另行批准执行，则记录真实运行状态。

- [ ] **Step 6: 交付未提交工作区**

Summarize changed files, model/data outputs, verification results, any non-estimable model evidence, production activation state and rollback state. Explicitly state that no commit or push was performed. Ask for commit/push only if the user wants it; do not invoke `git-commit` without that explicit request.

---

## Plan Self-Review Checklist

- [x] 覆盖设计中的数据来源、隐私、版本和数据库回滚。
- [x] 覆盖脂肪肝两个结局任务和 AD 一个结局任务。
- [x] 覆盖脂肪肝与 AD 阶段模型。
- [x] 覆盖两疾病关键指标趋势方向模型。
- [x] 覆盖统一患者划分、锁定测试、未来信息和近重复泄漏。
- [x] 覆盖 artifact、metadata、evaluation 和 manifest 哈希闭环。
- [x] 覆盖疾病级 release set、原子切换和回退。
- [x] 覆盖在线分模型降级、报告、历史和 PDF。
- [x] 覆盖旧 progression API 和电脑端。
- [x] 覆盖生产切换前再次审批。
- [x] 无自动 commit、push、worktree 或子 Agent 步骤。
- [x] 无 `TBD`、`TODO` 或将关键设计留到实施阶段的步骤。
