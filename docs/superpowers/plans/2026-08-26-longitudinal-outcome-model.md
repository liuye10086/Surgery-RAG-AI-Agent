# P0-04 纵向进展预测模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于 P0-03 `longitudinal_fixed_window_dataset.v1` 正式 JSONL，建立脂肪肝两个阶段任务和 AD 痴呆事件任务的可审计、患者级隔离、无未来泄漏训练与离线评估流程。

**Architecture:** P0-04 训练器只读取 P0-03 导出的 JSONL 与 `manifest.json`，先执行 schema、哈希、任务、真实数据和泄漏审计，再按疾病级 `group_id` 锁定测试集并在开发集执行 `StratifiedGroupKFold`。训练、评估、审计和 CLI 分成独立模块；训练结果默认只写明确指定的临时目录，产物状态固定为 `candidate`，不自动更新 registry 或生产模型目录。

**Tech Stack:** Python 3.11、Pydantic、scikit-learn 1.9.0、joblib 1.5.3、NumPy、pytest、现有 P0-03 schema/export/feature 能力。

## Global Constraints

- 只能读取 P0-03 已导出的 `longitudinal_fixed_window_dataset.v1` JSONL 和 `manifest.json`；不得从数据库、完整患者轨迹、旧 `outcome_label` 或旧 `build_prefixes` 重新构建训练数据。
- 正式训练、开发验证和锁定测试只使用 `is_synthetic=false` 的 `real_train.jsonl`；合成数据只能审计，正式指标中的合成计数必须为 0。
- 脂肪肝任务固定为 `pre_cirrhosis_to_progression` 与 `cirrhosis_to_hcc`；AD 固定为 `pre_dementia_to_dementia`，只使用 `dementia_date` 语义。
- 脂肪肝两个任务共享疾病级患者划分；所有划分、bootstrap 和互斥检查以 `group_id` 为单位，不以样本行代替患者。
- 训练器不得把 `group_id`、`patient_label`、`source_dataset`、`final_stage`、`confirmed`、`event_dates`、未来 CDR、未来访视或其他禁止字段作为模型特征。
- 预处理器、特征选择器、阈值和校准器只能在训练折/开发集拟合；锁定测试集只评估一次。
- 候选模型仅限正则化逻辑回归和限制复杂度随机森林；不引入 SMOTE、深度学习、XGBoost、LightGBM、CatBoost、AutoML 或大规模搜索。
- 主指标为 PR-AUC；必须同时记录 ROC-AUC、Brier、灵敏度、特异度、PPV、NPV、F1、混淆矩阵、每折波动和测试区间。
- 测试集缺少某一类别时，相关指标必须标记不可估计，不得填 0 或伪造结果。
- AUC/PR-AUC 异常高、完美分离、禁止字段命中、患者重叠或测试污染必须触发泄漏审查；审查未完成时状态保持 `candidate`。
- 当前实现不训练正式模型、不生成生产 artifact、不写正式业务数据库、不修改前端、P0-02、P0-03 语义、线上响应 schema 或旧 progression 链路。
- 旧脚本和旧 artifact 保留；P0-04 新入口不得调用它们。

---

## 文件与职责边界

### 新增文件

- `backend/app/schemas/longitudinal_model_training.py`：任务、划分、评估、审计和 metadata 的严格 Pydantic 契约。
- `backend/app/services/longitudinal_model_training.py`：JSONL/manifest 读取、输入校验、任务筛选、患者划分和 pipeline 构建。
- `backend/app/services/longitudinal_model_evaluation.py`：分层交叉验证、锁定测试评估、阈值、校准和患者级 bootstrap。
- `backend/app/services/longitudinal_model_audit.py`：禁止字段、重复、未来信息、集合重叠、异常高分和 metadata 完整性检查。
- `scripts/train_longitudinal_outcome_models.py`：默认只读审计、显式临时训练和 candidate metadata 导出 CLI。
- `backend/tests/test_longitudinal_model_training.py`：训练数据读取、任务筛选、划分、pipeline 测试。
- `backend/tests/test_longitudinal_model_evaluation.py`：指标、阈值、校准、不可估计和 bootstrap 测试。
- `backend/tests/test_longitudinal_model_audit.py`：泄漏和异常高分审查测试。
- `scripts/tests/test_train_longitudinal_outcome_models.py`：CLI 默认安全行为、错误输出和临时 artifact 测试。

### 允许小幅修改

- `backend/app/services/longitudinal_model_registry.py`：新增任务级 candidate/reviewed/enabled metadata 校验，保留旧键和旧加载行为。
- `scripts/check_model_artifacts.py`：复用现有 SHA-256 能力，新增 P0-04 metadata/manifest 检查入口但不改变旧 CLI 输出。

### 明确不修改

- `frontend/`、`backend/alembic/`、`backend/app/db/models.py`、`backend/app/schemas/prediction.py`、`backend/app/schemas/longitudinal_report.py`。
- `backend/app/services/disease_progression.py`、`backend/app/services/progression_engine.py`。
- `scripts/train_progression_model.py`、`scripts/train_longitudinal_models.py`。
- P0-02 医学标准、数据库 revision、P0-03 固定窗口数据集语义。

---

### Task 1: 定义 P0-04 严格训练契约

**Files:**
- Create: `backend/app/schemas/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `MODEL_TRAINING_SCHEMA_VERSION = "longitudinal_outcome_model_training.v1"`。
- Produces `TASK_SPECS` for the three exact tasks。
- Produces Pydantic models `TaskSpec`, `DatasetInput`, `GroupSplit`, `FoldMetrics`, `EvaluationSummary`, `LeakageAudit`, `ModelMetadata`。

- [ ] **Step 1: Write failing schema tests**

```python
def test_task_specs_are_exact_and_distinct():
    assert set(TASK_SPECS) == {
        "fatty_liver.pre_cirrhosis_to_progression",
        "fatty_liver.cirrhosis_to_hcc",
        "ad.pre_dementia_to_dementia",
    }
    assert TASK_SPECS["fatty_liver.pre_cirrhosis_to_progression"].target_event == "cirrhosis_or_hcc"
    assert TASK_SPECS["fatty_liver.cirrhosis_to_hcc"].target_event == "hcc"
    assert TASK_SPECS["ad.pre_dementia_to_dementia"].target_event == "dementia"


def test_metadata_rejects_non_candidate_status():
    with pytest.raises(ValidationError):
        ModelMetadata(
            **_valid_metadata_kwargs(
                schema_version=MODEL_TRAINING_SCHEMA_VERSION,
                task="ad.pre_dementia_to_dementia",
                status="enabled",
                production_enabled=True,
                clinical_validity_claim=True,
            )
        )


def test_evaluation_records_unestimable_metrics_without_zero_filling():
    metrics = FoldMetrics(
        fold=1,
        train_patient_count=4,
        validation_patient_count=2,
        positive_patient_count=0,
        negative_patient_count=2,
        pr_auc=None,
        roc_auc=None,
        unavailable_metrics=["pr_auc", "roc_auc"],
    )
    assert metrics.pr_auc is None
    assert "roc_auc" in metrics.unavailable_metrics
```

Define `_valid_metadata_kwargs(**overrides)` in the same test module before these tests. It must return a complete valid metadata dictionary with deterministic placeholder hashes consisting of 64 lowercase hexadecimal characters, a valid `candidate` status, `production_enabled=False`, `clinical_validity_claim=False`, empty leakage hits, and minimal valid split/evaluation structures; then apply `overrides` before constructing `ModelMetadata`.

- [ ] **Step 2: Run schema tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -q
```

Expected: collection fails because `backend.app.schemas.longitudinal_model_training` does not exist.

- [ ] **Step 3: Implement the strict schema**

Implement strict `extra="forbid"` models with these fixed values:

```python
TASK_SPECS = {
    "fatty_liver.pre_cirrhosis_to_progression": TaskSpec(
        task="fatty_liver.pre_cirrhosis_to_progression",
        disease="fatty_liver",
        current_state="pre_cirrhosis",
        target_event="cirrhosis_or_hcc",
        dataset_file="fatty_liver/real_train.jsonl",
    ),
    "fatty_liver.cirrhosis_to_hcc": TaskSpec(
        task="fatty_liver.cirrhosis_to_hcc",
        disease="fatty_liver",
        current_state="cirrhosis",
        target_event="hcc",
        dataset_file="fatty_liver/real_train.jsonl",
    ),
    "ad.pre_dementia_to_dementia": TaskSpec(
        task="ad.pre_dementia_to_dementia",
        disease="ad",
        current_state="pre_dementia",
        target_event="dementia",
        dataset_file="ad/real_train.jsonl",
    ),
}
```

`ModelMetadata` must require schema/data hashes, task definition, feature order hash, split summary, algorithm parameters, metrics, threshold, calibration, leakage audit, versions, artifact hashes and `status="candidate"`; validators must reject `production_enabled=True`, `clinical_validity_claim=True`, and any status other than `candidate` during this phase.

- [ ] **Step 4: Run schema tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -q
```

Expected: all schema tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add backend/app/schemas/longitudinal_model_training.py backend/tests/test_longitudinal_model_training.py
git commit -m "feat(model): define outcome training contract"
```

### Task 2: Add P0-03 JSONL and manifest reader with strict rejection

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `read_dataset_manifest(dataset_dir: Path) -> DatasetInput`。
- Produces `read_real_train_samples(dataset_dir: Path, disease: str) -> list[FixedWindowSample]`。
- Produces `audit_input_samples(samples: Sequence[FixedWindowSample], task: TaskSpec) -> InputAudit`。
- Consumes `FixedWindowSample` and `DATASET_SCHEMA_VERSION` from P0-03。

- [ ] **Step 1: Write failing reader and rejection tests**

```python
def test_reader_accepts_only_p003_real_train_and_manifest(tmp_path):
    _write_valid_p003_export(tmp_path)
    dataset = read_dataset_manifest(tmp_path)
    samples = read_real_train_samples(tmp_path, "fatty_liver")
    assert dataset.schema_version == "longitudinal_fixed_window_dataset.v1"
    assert samples
    assert all(not sample.identity.is_synthetic for sample in samples)


@pytest.mark.parametrize("bad_field", ["outcome_label", "confirmed", "final_stage", "event_dates"])
def test_reader_rejects_legacy_or_outcome_fields(tmp_path, bad_field):
    _write_valid_p003_export(tmp_path, extra_feature={bad_field: 1})
    with pytest.raises(ModelInputError, match="forbidden"):
        read_real_train_samples(tmp_path, "fatty_liver")


def test_reader_rejects_manifest_hash_mismatch(tmp_path):
    _write_valid_p003_export(tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["fatty_liver/real_train.jsonl"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ModelInputError, match="hash"):
        read_dataset_manifest(tmp_path)


def test_reader_rejects_insufficient_and_not_applicable_rows(tmp_path):
    _write_valid_p003_export(tmp_path, label_status="insufficient_observation")
    with pytest.raises(ModelInputError, match="trainable"):
        read_real_train_samples(tmp_path, "fatty_liver")
```

- [ ] **Step 2: Run reader tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "reader or legacy or manifest" -q
```

Expected: failures because the reader interfaces are missing.

- [ ] **Step 3: Implement reader and input audit**

Implementation requirements:

1. Read `manifest.json` and verify schema, horizon `365`, minimum visits `3`, every listed file hash, and `data_content_sha256`.
2. Read only the requested disease `real_train.jsonl`; reject missing files, malformed JSON, extra top-level fields and malformed Pydantic samples.
3. Reject any `is_synthetic=true`, non-binary label, non-trainable label status, wrong disease, wrong `target_event`, wrong `current_state`, missing/invalid `group_id`, or duplicate `(group_id, as_of)`.
4. Recursively scan the serialized sample and model feature projection for the forbidden names; event evidence may remain only under the sibling `label` audit object.
5. Return privacy-safe counts only; never include `patient_label` or raw identifiers in errors.

- [ ] **Step 4: Run reader tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "reader or legacy or manifest" -q
```

Expected: all reader tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add backend/app/services/longitudinal_model_training.py backend/tests/test_longitudinal_model_training.py
git commit -m "feat(model): enforce p003 dataset input"
```

### Task 3: Implement task filtering, stable features and patient-level splits

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `select_task_samples(samples: Sequence[FixedWindowSample], task_name: str) -> list[TrainingRow]`。
- Produces `build_feature_catalog(rows: Sequence[TrainingRow], task: TaskSpec) -> FeatureCatalog`。
- Produces `make_locked_group_split(rows: Sequence[TrainingRow], *, seed: int, test_fraction: float) -> GroupSplit`。
- Produces `make_preprocessor(feature_catalog: FeatureCatalog, *, scale_numeric: bool) -> ColumnTransformer`。

- [ ] **Step 1: Write failing task and split tests**

```python
def test_fatty_liver_tasks_filter_current_state_and_target():
    rows = _real_train_fixture_with_both_fatty_states()
    pre = select_task_samples(rows, "fatty_liver.pre_cirrhosis_to_progression")
    post = select_task_samples(rows, "fatty_liver.cirrhosis_to_hcc")
    assert {row.sample.identity.current_state for row in pre} == {"pre_cirrhosis"}
    assert {row.sample.identity.current_state for row in post} == {"cirrhosis"}
    assert {row.sample.identity.target_event for row in pre} == {"cirrhosis_or_hcc"}
    assert {row.sample.identity.target_event for row in post} == {"hcc"}


def test_fatty_liver_tasks_share_one_patient_split():
    rows = _real_train_fixture_with_cross_stage_patient()
    split = make_locked_group_split(rows, seed=42, test_fraction=0.2)
    train_groups = set(split.development_groups)
    test_groups = set(split.locked_test_groups)
    assert train_groups.isdisjoint(test_groups)
    assert split.group_overlap_check == "passed"


def test_same_patient_label_from_different_sources_is_not_merged():
    rows = _rows_with_same_label_different_source()
    assert len({row.sample.identity.group_id for row in rows}) == 2


def test_feature_catalog_excludes_identity_label_and_future_fields():
    rows = _real_train_fixture()
    catalog = build_feature_catalog(rows, TASK_SPECS["ad.pre_dementia_to_dementia"])
    serialized = " ".join(catalog.feature_names)
    for forbidden in ("group_id", "patient_label", "source_dataset", "final_stage", "event_dates", "confirmed", "future", "dementia_date"):
        assert forbidden not in serialized
```

- [ ] **Step 2: Run task/split tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "task or split or feature_catalog" -q
```

Expected: failures because task selection, feature catalog and group split interfaces are missing.

- [ ] **Step 3: Implement stable feature projection and split**

Implementation requirements:

1. For each task, filter only exact `current_state`, `target_event`, `label.status in {positive, negative}`, real samples, and matching disease.
2. Flatten only P0-03 `features` fields in deterministic sorted order; encode `sex` separately and never flatten identity or label fields.
3. For fatty liver, derive one union of `group_id` values across both tasks before splitting; apply the same development/test mapping to both task row sets.
4. Use a deterministic seeded group split; if either class is absent from the locked test set, preserve the split but mark test class coverage and metrics as unavailable.
5. Build `ColumnTransformer` with numeric median imputation plus missing indicators, optional scaling, and one-hot sex encoding. Do not fit it in this task; only construct the pipeline component.

- [ ] **Step 4: Run task/split tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "task or split or feature_catalog" -q
```

Expected: all task, feature and split tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add backend/app/services/longitudinal_model_training.py backend/tests/test_longitudinal_model_training.py
git commit -m "feat(model): add task filtering and grouped splits"
```

### Task 4: Add leakage audit and abnormal-score review

**Files:**
- Create: `backend/app/services/longitudinal_model_audit.py`
- Test: `backend/tests/test_longitudinal_model_audit.py`

**Interfaces:**
- Produces `run_input_leakage_audit(rows: Sequence[TrainingRow], split: GroupSplit) -> LeakageAudit`。
- Produces `review_scores(metrics: EvaluationSummary, audit: LeakageAudit) -> LeakageAudit`。
- Produces `assert_audit_allows_training(audit: LeakageAudit) -> None`。

- [ ] **Step 1: Write failing audit tests**

```python
def test_group_overlap_blocks_training():
    split = _split_with_overlap()
    audit = run_input_leakage_audit(_rows(), split)
    assert audit.group_overlap is True
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_forbidden_feature_blocks_training():
    rows = _rows_with_feature_name("final_stage")
    audit = run_input_leakage_audit(rows, _valid_split())
    assert "final_stage" in audit.forbidden_feature_hits
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)


def test_abnormal_auc_sets_review_required():
    metrics = _evaluation_with(roc_auc=0.99, pr_auc=0.99)
    audit = review_scores(metrics, _clean_audit())
    assert audit.leakage_review_required is True
    assert audit.high_score_warning is True


def test_test_selection_or_synthetic_usage_blocks_training():
    audit = _clean_audit(test_used_for_selection=True, synthetic_in_formal_metrics=True)
    with pytest.raises(LeakageBlockedError):
        assert_audit_allows_training(audit)
```

- [ ] **Step 2: Run audit tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_audit.py -q
```

Expected: collection or test failures because the audit module does not exist.

- [ ] **Step 3: Implement deterministic audit rules**

Implement checks for:

- development/test group overlap;
- duplicate `(group_id, as_of)` rows;
- forbidden feature names and nested fields;
- future date fields and AD future/final CDR;
- synthetic rows in formal metrics;
- test participation in preprocessing, model selection, threshold or calibration;
- manifest/sample count mismatch;
- abnormal score thresholds (`roc_auc >= 0.95`, `pr_auc >= 0.95`, perfect separation, or Brier near zero).

`assert_audit_allows_training` must block hard violations and allow a clean audit with `leakage_review_required=True` to remain candidate but not enabled.

- [ ] **Step 4: Run audit tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_audit.py -q
```

Expected: all audit tests pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add backend/app/services/longitudinal_model_audit.py backend/tests/test_longitudinal_model_audit.py
git commit -m "feat(model): add leakage and high-score audit"
```

### Task 5: Implement model factories and patient-level development CV

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `make_model_candidates(seed: int) -> dict[str, Pipeline]`。
- Produces `run_development_cv(rows: Sequence[TrainingRow], task: TaskSpec, *, seed: int) -> DevelopmentEvaluation`。

- [ ] **Step 1: Write failing model/CV tests**

```python
def test_model_candidates_are_limited_to_logistic_and_random_forest():
    candidates = make_model_candidates(seed=42)
    assert set(candidates) == {"logistic_regression", "random_forest"}
    assert candidates["logistic_regression"].named_steps["classifier"].class_weight == "balanced"


def test_development_cv_uses_grouped_stratified_folds():
    result = run_development_cv(_balanced_rows(), TASK_SPECS["ad.pre_dementia_to_dementia"], seed=42)
    for fold in result.folds:
        assert set(fold.train_groups).isdisjoint(fold.validation_groups)
    assert result.split_method == "StratifiedGroupKFold"


def test_small_positive_task_uses_three_folds_and_marks_unestimable_metrics():
    result = run_development_cv(_nine_positive_rows(), TASK_SPECS["fatty_liver.cirrhosis_to_hcc"], seed=42)
    assert result.requested_fold_count == 3
    assert all(metric.unavailable_metrics or metric.pr_auc is not None for metric in result.folds)
```

- [ ] **Step 2: Run model/CV tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "candidate or development_cv" -q
```

Expected: failures because model factories and CV are missing.

- [ ] **Step 3: Implement candidate pipelines and CV**

Use:

```python
Pipeline([
    ("preprocess", make_preprocessor(catalog, scale_numeric=True)),
    ("classifier", LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=seed)),
])

Pipeline([
    ("preprocess", make_preprocessor(catalog, scale_numeric=False)),
    ("classifier", RandomForestClassifier(
        n_estimators=200, max_depth=4, min_samples_leaf=3,
        class_weight="balanced", random_state=seed, n_jobs=1,
    )),
])
```

Use `StratifiedGroupKFold` with 5 folds for AD/pre-cirrhosis and 3 folds for cirrhosis→HCC. Fit each pipeline only on the training fold, collect out-of-fold probabilities, and preserve fold group lists. Never use `train_test_split`.

- [ ] **Step 4: Run model/CV tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "candidate or development_cv" -q
```

Expected: all model and CV tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add backend/app/services/longitudinal_model_training.py backend/tests/test_longitudinal_model_training.py
git commit -m "feat(model): add grouped development training"
```

### Task 6: Implement metrics, threshold selection, calibration and locked test evaluation

**Files:**
- Create: `backend/app/services/longitudinal_model_evaluation.py`
- Test: `backend/tests/test_longitudinal_model_evaluation.py`

**Interfaces:**
- Produces `compute_binary_metrics(y_true, probabilities, threshold) -> BinaryMetrics`。
- Produces `select_oof_f1_threshold(y_true, probabilities) -> ThresholdResult`。
- Produces `fit_sigmoid_calibrator(oof_probabilities, labels) -> Calibrator | None`。
- Produces `evaluate_locked_test(model, rows, split, threshold, calibrator=None) -> EvaluationSummary`。
- Produces `patient_bootstrap_ci(labels_by_group, probabilities_by_group, threshold, *, seed, iterations) -> ConfidenceInterval`。

- [ ] **Step 1: Write failing metric and boundary tests**

```python
def test_metrics_include_pr_auc_roc_auc_brier_and_threshold_metrics():
    metrics = compute_binary_metrics([0, 1, 0, 1], [0.1, 0.8, 0.2, 0.7], 0.5)
    assert metrics.pr_auc is not None
    assert metrics.roc_auc is not None
    assert metrics.brier_score is not None
    assert metrics.confusion_matrix == [[2, 0], [0, 2]]


def test_missing_class_marks_auc_unestimable():
    metrics = compute_binary_metrics([0, 0], [0.1, 0.2], 0.5)
    assert metrics.pr_auc is None
    assert metrics.roc_auc is None
    assert set(["pr_auc", "roc_auc"]).issubset(metrics.unavailable_metrics)


def test_threshold_is_selected_from_oof_only():
    result = select_oof_f1_threshold([0, 1, 1, 0], [0.2, 0.55, 0.8, 0.4])
    assert result.method == "oof_f1"
    assert 0.0 < result.threshold < 1.0


def test_bootstrap_resamples_groups_not_rows():
    ci = patient_bootstrap_ci(
        labels_by_group={"g1": [1, 0], "g2": [0, 0]},
        probabilities_by_group={"g1": [0.8, 0.7], "g2": [0.1, 0.2]},
        threshold=0.5,
        seed=42,
        iterations=100,
    )
    assert ci.unit == "group_id"
```

- [ ] **Step 2: Run evaluation tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_evaluation.py -q
```

Expected: failures because evaluation interfaces are missing.

- [ ] **Step 3: Implement evaluation functions**

Rules:

1. Use `average_precision_score` for PR-AUC and record the positive-rate baseline.
2. Use `roc_auc_score` only when both classes exist; otherwise return `None` and an explicit reason.
3. Compute Brier, sensitivity, specificity, PPV, NPV, F1 and confusion matrix at the supplied threshold.
4. Select the exploration threshold only from development out-of-fold probabilities; always retain baseline `0.5` metrics.
5. Fit sigmoid calibration only on development OOF predictions; return `None` for insufficient class coverage and never fit isotonic.
6. Evaluate locked test once using the already selected model, threshold and calibrator; never use test values to select them.
7. Bootstrap by sampling `group_id` and report unstable/unestimable intervals when class coverage is insufficient.

- [ ] **Step 4: Run evaluation tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_evaluation.py -q
```

Expected: all evaluation tests pass.

- [ ] **Step 5: Commit Task 6**

```powershell
git add backend/app/services/longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_evaluation.py
git commit -m "feat(model): add audited evaluation metrics"
```

### Task 7: Assemble metadata and temporary candidate artifact export

**Files:**
- Modify: `backend/app/services/longitudinal_model_training.py`
- Test: `backend/tests/test_longitudinal_model_training.py`

**Interfaces:**
- Produces `train_task_to_candidate(rows, task, dataset_input, output_dir, *, seed) -> CandidateResult`。
- Produces `write_candidate_artifact(result, output_dir) -> tuple[Path, Path]`。

- [ ] **Step 1: Write failing metadata/artifact tests**

```python
def test_candidate_artifact_has_task_specific_names_and_metadata(tmp_path):
    result = train_task_to_candidate(
        _real_train_fixture(),
        TASK_SPECS["ad.pre_dementia_to_dementia"],
        _dataset_input_fixture(),
        tmp_path,
        seed=42,
    )
    model_path, meta_path = write_candidate_artifact(result, tmp_path)
    assert model_path.name == "ad_pre_dementia_to_dementia_365d.joblib"
    assert meta_path.name == "ad_pre_dementia_to_dementia_365d.meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["status"] == "candidate"
    assert metadata["production_enabled"] is False
    assert metadata["dataset_manifest_sha256"]
    assert metadata["feature_order_sha256"]
    assert metadata["leakage_audit"]["synthetic_in_formal_metrics"] is False


def test_candidate_writer_refuses_existing_output_directory(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        write_candidate_artifact(_candidate_result_fixture(), existing)
```

- [ ] **Step 2: Run metadata tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "candidate_artifact or metadata" -q
```

Expected: failures because candidate assembly/export is missing.

- [ ] **Step 3: Implement candidate assembly/export**

The function must:

1. Run input audit before fitting and refuse hard leakage violations.
2. Build development split/CV, compare only the two candidates using development metrics, retain the selected model and record the rejected candidate metrics.
3. Record baseline 0.5 and OOF-F1 threshold results, calibration status, locked test metrics, patient counts, label counts, all fold groups, feature names/order hash, dataset hashes, package versions and leakage audit.
4. Write only to a caller-provided directory that does not already exist; never default to `backend/app/ml_models/`.
5. Write task-specific candidate filenames and calculate model/metadata SHA-256 after writing.
6. Never update registry, database or production state.

- [ ] **Step 4: Run metadata tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py -k "candidate_artifact or metadata" -q
```

Expected: all metadata and artifact tests pass.

- [ ] **Step 5: Commit Task 7**

```powershell
git add backend/app/services/longitudinal_model_training.py backend/tests/test_longitudinal_model_training.py
git commit -m "feat(model): export auditable candidate artifacts"
```

### Task 8: Add registry and artifact contract validation without changing legacy behavior

**Files:**
- Modify: `backend/app/services/longitudinal_model_registry.py`
- Modify: `scripts/check_model_artifacts.py`
- Test: `backend/tests/test_longitudinal_model_registry.py`
- Test: `scripts/tests/test_check_model_artifacts.py`

**Interfaces:**
- Produces `validate_candidate_metadata(model_path: Path, meta_path: Path, dataset_dir: Path) -> ArtifactValidation`。
- Extends `load_model_registry` with an optional task-aware validation path; existing legacy calls remain unchanged.

- [ ] **Step 1: Write failing compatibility tests**

```python
def test_legacy_progression_artifacts_remain_ignored_by_longitudinal_registry(tmp_path):
    _write_legacy_pair(tmp_path, "fatty_liver_progression_model")
    assert load_model_registry("fatty_liver", model_dir=tmp_path) == {}


def test_candidate_metadata_requires_dataset_and_feature_hashes(tmp_path):
    model_path, meta_path = _write_candidate_pair(tmp_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("dataset_manifest_sha256")
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    result = validate_candidate_metadata(model_path, meta_path, tmp_path / "dataset")
    assert result.valid is False
    assert "dataset_manifest_sha256" in result.missing_fields


def test_artifact_checker_does_not_execute_model_prediction(tmp_path):
    model_path, meta_path = _write_candidate_pair(tmp_path)
    result = validate_candidate_metadata(model_path, meta_path, tmp_path / "dataset")
    assert result.prediction_executed is False
```

- [ ] **Step 2: Run compatibility tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_registry.py scripts/tests/test_check_model_artifacts.py -q
```

Expected: failures because task-aware metadata validation is missing.

- [ ] **Step 3: Implement task-aware validation**

Validate without calling `predict` or `predict_proba`:

- model/meta pair exists and loads;
- task-specific filename matches metadata task;
- metadata status is candidate/reviewed/enabled according to validation mode;
- schema, task, disease, target, horizon, feature order hash and dataset hashes match;
- artifact and metadata SHA-256 match their recorded values;
- `production_enabled` is false for candidate artifacts;
- legacy `*_progression_model.*` remains ignored by the new outcome path.

Do not alter old `load_model_registry(dataset)` behavior for existing progression API consumers.

- [ ] **Step 4: Run compatibility tests and verify PASS**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_registry.py scripts/tests/test_check_model_artifacts.py -q
```

Expected: all compatibility tests pass.

- [ ] **Step 5: Commit Task 8**

```powershell
git add backend/app/services/longitudinal_model_registry.py scripts/check_model_artifacts.py backend/tests/test_longitudinal_model_registry.py scripts/tests/test_check_model_artifacts.py
git commit -m "feat(model): validate candidate artifact contracts"
```

### Task 9: Add safe P0-04 CLI

**Files:**
- Create: `scripts/train_longitudinal_outcome_models.py`
- Test: `scripts/tests/test_train_longitudinal_outcome_models.py`

**Interfaces:**
- Produces `build_error_payload(code: str) -> dict[str, object]`。
- Produces `run_audit(dataset_dir: Path) -> dict[str, object]`。
- Produces `run_training(dataset_dir: Path, output_dir: Path, *, seed: int) -> dict[str, object]`。
- Produces `main(argv: list[str] | None = None) -> int`。

- [ ] **Step 1: Write failing CLI safety tests**

```python
def test_default_cli_is_audit_only_and_does_not_train(cli, monkeypatch, tmp_path, capsys):
    calls = []
    monkeypatch.setattr(cli, "run_audit", lambda dataset_dir: calls.append(dataset_dir) or {"status": "audit_only"})
    monkeypatch.setattr(cli, "run_training", lambda *args, **kwargs: pytest.fail("training called"))
    assert cli.main(["--dataset-dir", str(tmp_path)]) == 0
    assert calls == [tmp_path]
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "audit_only"


def test_training_requires_train_and_output_dir(cli, tmp_path, capsys):
    assert cli.main(["--dataset-dir", str(tmp_path), "--train"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "output_dir_required"


def test_cli_sanitizes_errors_and_never_prints_patient_identity(cli, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run_audit", lambda dataset_dir: (_ for _ in ()).throw(ValueError("P001 password postgresql://secret")))
    assert cli.main(["--dataset-dir", str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert "P001" not in output
    assert "password" not in output
    assert "postgresql://" not in output
    assert "Traceback" not in output


def test_cli_never_auto_enables_registry(cli, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "run_training", lambda *args, **kwargs: {"status": "candidate"})
    assert cli.main(["--dataset-dir", str(tmp_path), "--train", "--output-dir", str(tmp_path / "out")]) == 0
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_outcome_models.py -q
```

Expected: collection fails because the CLI file does not exist.

- [ ] **Step 3: Implement CLI**

CLI rules:

1. Default mode is audit-only even when `--dataset-dir` is provided.
2. `--train` requires `--dataset-dir` and a non-existing `--output-dir`; it writes candidate artifacts only.
3. `--export-artifact` is rejected in this implementation unless an explicit future authorization flag is added; no production artifact is generated now.
4. No database imports or database writes; no registry update or enable operation.
5. Output exactly one sorted UTF-8 JSON document; errors use stable codes and sanitized messages.
6. Support `--seed` default `42`; do not expose synthetic-data training mode.

- [ ] **Step 4: Run CLI tests and verify PASS**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_outcome_models.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit Task 9**

```powershell
git add scripts/train_longitudinal_outcome_models.py scripts/tests/test_train_longitudinal_outcome_models.py
git commit -m "feat(model): add safe outcome training cli"
```

### Task 10: Run focused, regression and real-environment verification

**Files:**
- Modify: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`
- No production code changes in this task.

- [ ] **Step 1: Run focused P0-04 tests**

```powershell
python -m pytest backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py scripts/tests/test_train_longitudinal_outcome_models.py -q
```

Expected: all P0-04 tests pass; no formal artifact is written to `backend/app/ml_models/`.

- [ ] **Step 2: Run P0-03 and legacy regressions**

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_features.py scripts/tests/test_build_longitudinal_dataset.py scripts/tests/test_train_longitudinal_models.py scripts/tests/test_train_progression_model.py backend/tests/test_longitudinal_model_registry.py scripts/tests/test_check_model_artifacts.py scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: all selected regressions pass. If a pre-existing failure appears, stop and record it before unrelated changes.

- [ ] **Step 3: Run full project tests**

```powershell
python -m pytest -q
```

Expected: full suite passes with only the known project warning, or any pre-existing failure is explicitly recorded.

- [ ] **Step 4: Run default CLI twice and verify stable audit behavior**

```powershell
python scripts/build_longitudinal_dataset.py --output-dir .tmp/p003-p004-verification
python scripts/train_longitudinal_outcome_models.py --dataset-dir .tmp/p003-p004-verification
python scripts/train_longitudinal_outcome_models.py --dataset-dir .tmp/p003-p004-verification
```

Expected:

- P0-03 export is created only in the explicitly named disposable directory;
- the two P0-04 audit JSON documents are structurally identical apart from any explicitly documented timestamp field;
- no `.joblib` is created by default;
- output contains no `patient_label`, `group_id`, raw patient label, password, database URL or traceback.

- [ ] **Step 5: Run explicit training only in a disposable directory**

```powershell
python scripts/train_longitudinal_outcome_models.py --dataset-dir .tmp/p003-p004-verification --train --output-dir .tmp/p004-candidate-verification
```

Expected:

- three task-specific candidate artifacts and metadata are written only under `.tmp/p004-candidate-verification`;
- metadata status is `candidate`, `production_enabled=false`, `clinical_validity_claim=false`;
- metadata contains dataset/feature/model/metrics/threshold/calibration/leakage hashes;
- no registry update occurs;
- `backend/app/ml_models/` remains unchanged.

- [ ] **Step 6: Validate candidate artifacts without prediction execution**

```powershell
python scripts/check_model_artifacts.py --models-dir .tmp/p004-candidate-verification
```

Expected: hashes and metadata contract validate; checker does not call model prediction.

- [ ] **Step 7: Inspect sensitive-output and forbidden-field contracts**

```powershell
python scripts/train_longitudinal_outcome_models.py --dataset-dir .tmp/p003-p004-verification 2>$null | Select-String -Pattern 'patient_label|group_id|P001|A001|postgresql://|password|Traceback'
```

Expected: no matches.

- [ ] **Step 8: Record actual verification evidence**

Under `### P0-04：训练、评估并产出双疾病 365 天结局模型` in `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`, add actual counts, commands, test totals, candidate-only status and confirmation that no production artifact, database write or registry enable occurred. Do not hard-code expected metrics or claim clinical validity.

- [ ] **Step 9: Run documentation and diff checks**

```powershell
git diff --check
git status --short
```

Expected: only the approved P0-04 plan/spec, implementation files, tests and roadmap evidence are present; no frontend, migration, database model or old-chain deletion appears.

- [ ] **Step 10: Commit verification evidence**

```powershell
git add docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md
git commit -m "docs(model): record P0-04 verification"
```

## Completion Gate

Do not claim P0-04 complete until:

- all three tasks train independently from P0-03 JSONL only;
- fatty-liver tasks share a patient-level split and no group crosses sets;
- real/synthetic separation, future-visit checks and forbidden-feature checks pass;
- development CV and locked test are clearly separated;
- metrics, threshold, calibration, uncertainty and unestimable reasons are recorded;
- abnormal high scores trigger review and never auto-enable a model;
- candidate artifact metadata matches model, feature and dataset hashes;
- CLI defaults to read-only audit and never writes database/registry/production model paths;
- old scripts/artifacts remain intact and legacy regressions pass;
- actual verification evidence is recorded without claiming clinical validity.

通俗解释：只有三个任务都能从 P0-03 的正式训练表独立运行，患者没有跨集合、测试没有被偷看、结果和哈希都能复核，而且模型仍停留在人工审核前的 candidate 状态，P0-04 才算完成。
