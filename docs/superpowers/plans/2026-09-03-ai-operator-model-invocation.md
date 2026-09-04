# AI 操作者第 4 项：调用当前疾病模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让脂肪肝和 AD 的 active release set 按稳定生产链路运行，统一校验所有模型输入，确保模型组完整、缓存按版本失效，并在报告中保留真实审计提示。

**Architecture:** active 指针授权当前 release set；加载器先验证完整 bundle 和哈希链，再按 registry root 隔离并通过 `(dataset, release_set_id, release_set_sha256)` 缓存不可变模型组。结局、阶段、趋势模型全部复用同一个 metadata-ordered 特征构造器，输入契约失败只禁用对应模型，运行审计信息进入结构化结果和报告警告。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、joblib、pandas、pytest、asyncio。

## Global Constraints

- 仅覆盖 AI 操作者、脂肪肝和阿尔茨海默病（AD）、电脑端报告流程。
- active 指针是当前运行授权来源；当前 artifact 的 `production_enabled=false` 不作为运行阻断条件。
- 合成数据、未校准分数和 `clinical_validity_claim=false` 必须如实进入报告提示，不得表述为临床验证结论。
- release set 缺失任一必需 bundle、病种不匹配或哈希链失败时，禁止部分加载。
- 阶段和趋势模型必须执行 metadata 的 `required_features` / `allowed_missing_features` 契约。
- 历史报告读取保存的正文、预测结果和输入快照，不重新调用模型。
- 本计划不新增数据库字段或 Alembic 迁移。
- 前端视觉样式不在本计划范围内；API 错误继续使用稳定 `code`、`message`、`field`/`issues`，不得泄露内部路径和堆栈。

---

## 文件结构

- Modify: `backend/app/services/longitudinal_features.py` — 统一生成所有 artifact type 的 metadata-ordered 输入 DataFrame，并暴露稳定契约错误。
- Modify: `backend/app/services/longitudinal_prediction.py` — 阶段/趋势复用统一特征入口，保留单模型失败隔离，并添加模型审计警告。
- Modify: `backend/app/services/longitudinal_model_registry.py` — release set 完整性、active 运行授权和线程安全缓存。
- Modify: `backend/app/services/operator_case_readiness.py` — 使用完整 release set 加载结果生成稳定 readiness 阻断。
- Modify: `backend/tests/test_longitudinal_features.py` — 阶段/趋势必填特征契约测试。
- Modify: `backend/tests/test_longitudinal_prediction_contract.py` — 阶段/趋势不调用缺失输入、审计警告和失败隔离测试。
- Modify: `backend/tests/test_longitudinal_model_registry.py` — release set 完整性与缓存测试。
- Modify: `backend/tests/test_operator_case_readiness.py` — 不完整活动模型组 readiness 测试。
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py` — 端到端生成失败状态回归。
- Modify: `docs/AI操作者流程核查.md` — 同步第 4 项已完成内容、剩余部署门禁和当前模型审计状态。

### Task 1: 统一阶段/趋势模型输入契约

**Files:**
- Modify: `backend/app/services/longitudinal_features.py:393-453`
- Modify: `backend/app/services/longitudinal_prediction.py:213-423`
- Test: `backend/tests/test_longitudinal_features.py`
- Test: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:**
- Consumes: `ArtifactMetadataV2.feature_contract`、`case: dict[str, Any]`、`visits: Iterable[dict[str, Any]]`。
- Produces: `build_fixed_window_inference_features(case, visits, metadata) -> pandas.DataFrame` 对 outcome/stage/trend 三类 metadata 均执行同一契约；`InferenceContractError.code` 使用 `required_feature_missing`、`non_finite_feature`、`feature_order_mismatch` 等既有稳定码。

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_longitudinal_features.py` 增加：

```python
def test_stage_metadata_required_feature_is_rejected_before_model_call():
    from app.services.longitudinal_features import (
        InferenceContractError,
        build_fixed_window_inference_features,
    )
    metadata = _suite_metadata("stage", required_features=["current_stage"])
    visits = [_visit("2024-01-01", 20), _visit("2024-06-01", 21)]
    with pytest.raises(InferenceContractError) as error:
        build_fixed_window_inference_features(
            {"baseline_stage": None, "age": 65, "sex": "female"},
            visits,
            metadata,
        )
    assert error.value.code == "required_feature_missing"


def test_trend_metadata_rejects_non_allowed_missing_feature():
    from app.services.longitudinal_features import (
        InferenceContractError,
        build_fixed_window_inference_features,
    )
    metadata = _suite_metadata("trend", required_features=["visit_count", "mmse.last"])
    visits = [{"visit_date": "2024-01-01", "indicators": []}]
    with pytest.raises(InferenceContractError) as error:
        build_fixed_window_inference_features(
            {"age": 65, "sex": "female"}, visits, metadata
        )
    assert error.value.code == "required_feature_missing"
```

在测试文件中新增 `_suite_metadata(artifact_type, required_features)` 辅助函数：复用现有 `backend.tests.test_longitudinal_model_suite_schema.valid_metadata`，设置 `task` 为 `ad.next_stage` 或 `ad.next_visit_trend.mmse`，将 `required_features` 写入 feature contract，并将其余 feature names 写入 `allowed_missing_features`，最后返回 `ArtifactMetadataV2.model_validate(payload)`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_longitudinal_features.py::test_stage_metadata_required_feature_is_rejected_before_model_call backend/tests/test_longitudinal_features.py::test_trend_metadata_rejects_non_allowed_missing_feature -q`

Expected: FAIL because the current stage/trend path is not routed through the metadata contract for all required fields.

- [ ] **Step 3: Implement the minimal unified feature path**

在 `longitudinal_prediction.py` 删除 `_suite_frame` 内部手工拼接逻辑，改为：

```python
def _suite_frame(case: dict[str, Any], visits: list[dict[str, Any]], metadata):
    return build_fixed_window_inference_features(case, visits, metadata)
```

保留 `build_fixed_window_inference_features` 的现有顺序、有限数值和允许缺失检查；只补充对 V2 metadata 的类型注解兼容，不放宽任何必填规则。`_run_suite_stage` 和 `_run_suite_trend` 分别捕获 `InferenceContractError`，将状态设置为 `incompatible`、`reason_code=error.code`，而不是笼统使用 `prediction_failed`；真实 `predict`/`predict_proba` 异常仍使用 `prediction_failed`。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_prediction_contract.py -q`

Expected: PASS，且既有 outcome、stage、trend、单模型失败隔离测试全部通过。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/longitudinal_features.py backend/app/services/longitudinal_prediction.py backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_prediction_contract.py
git commit -m "fix: enforce model input contracts for all tasks"
```

### Task 2: 强制 active release set 完整性

**Files:**
- Modify: `backend/app/services/longitudinal_model_registry.py:895-963`
- Modify: `backend/app/services/operator_case_readiness.py:82-168`
- Test: `backend/tests/test_longitudinal_model_registry.py`
- Test: `backend/tests/test_operator_case_readiness.py`

**Interfaces:**
- Consumes: `load_disease_release_set(dataset, root)`、`REQUIRED_TASKS[dataset]`、`_suite_entry_from_bundle`。
- Produces: `load_disease_model_suite(dataset, registry_root) -> LoadedDiseaseModelSuite`；完整性失败统一抛出 `ValueError`，错误码为 `release_set_dataset_mismatch`、`release_set_lifecycle_invalid`、`required_bundle_missing`、`duplicate_bundle_task` 或 `release_set_bundle_mismatch`。

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_longitudinal_model_registry.py` 增加：先把现有 `test_active_release_set_loads_one_immutable_suite`（约 553–644 行）中的 v3 release-set 构造代码提取为 `_write_active_suite_fixture(root) -> Path`，返回 registry root；以下测试复用该 helper。

```python
def test_active_suite_rejects_missing_required_bundle(tmp_path):
    root = tmp_path / "registry"
    _write_active_suite_fixture(root)
    release_path = root / "release_sets" / "ad" / "ad-set-v1.json"
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    payload["bundles"] = payload["bundles"][:-1]
    release_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="required_bundle_missing"):
        load_disease_model_suite("ad", root)


def test_active_suite_rejects_duplicate_task(tmp_path):
    root = tmp_path / "registry"
    _write_active_suite_fixture(root)
    release_path = root / "release_sets" / "ad" / "ad-set-v1.json"
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    payload["bundles"].append(dict(payload["bundles"][0]))
    release_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate_bundle_task"):
        load_disease_model_suite("ad", root)
```

测试使用现有 v3 active-suite helper 生成完整链路；修改 release record 后同步写入 active pointer 的 record SHA，确保失败原因来自 bundle 集合而不是较早的指针哈希错误。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_longitudinal_model_registry.py::test_active_suite_rejects_missing_required_bundle backend/tests/test_longitudinal_model_registry.py::test_active_suite_rejects_duplicate_task -q`

Expected: FAIL because `load_disease_model_suite` 当前只检查 stage 是否存在，没有要求任务集合完全等于 `REQUIRED_TASKS`。

- [ ] **Step 3: Implement complete-set validation**

在 `load_disease_model_suite` 构造 entries 前执行以下逻辑：

```python
expected_tasks = REQUIRED_TASKS[dataset]
actual_tasks = [str(bundle.get("task", "")) for bundle in release_set.bundles]
if any(not task for task in actual_tasks):
    raise ValueError("required_bundle_missing")
if len(actual_tasks) != len(set(actual_tasks)):
    raise ValueError("duplicate_bundle_task")
if set(actual_tasks) != expected_tasks:
    raise ValueError("required_bundle_missing")
if release_set.dataset != dataset:
    raise ValueError("release_set_dataset_mismatch")
if release_set.status not in {"reviewed", "enabled"}:
    raise ValueError("release_set_lifecycle_invalid")
```

构造 entries 后再次确认每个 entry 的 task、artifact type 和 trend indicator 与 bundle 一致；任何 mismatch 都抛出稳定码。active 指针仍是运行授权，不因 metadata 的 `production_enabled=false` 拒绝加载。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_longitudinal_model_registry.py backend/tests/test_operator_case_readiness.py -q`

Expected: PASS，且现有 active release set、旧 registry 兼容和 readiness 测试不回归。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/longitudinal_model_registry.py backend/app/services/operator_case_readiness.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_operator_case_readiness.py
git commit -m "fix: reject incomplete active model suites"
```

### Task 3: 增加按 release-set 身份失效的线程安全缓存

**Files:**
- Modify: `backend/app/services/longitudinal_model_registry.py:895-963`
- Test: `backend/tests/test_longitudinal_model_registry.py`

**Interfaces:**
- Consumes: `read_active_pointer`、`load_disease_model_suite`。
- Produces: `load_active_model_registry(dataset, registry_root=None) -> LoadedDiseaseModelSuite | LongitudinalModelRegistry`，行为保持兼容；缓存按 registry root 隔离，并在命名空间内通过键 `(dataset, release_set_id, release_set_sha256)` 查找。

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_longitudinal_model_registry.py` 增加：复用 `_write_active_suite_fixture(root)` 构造带 active pointer 的完整 v3 release set，再加入以下测试：

```python
def test_active_suite_cache_loads_same_pointer_once(tmp_path, monkeypatch):
    root = tmp_path / "registry"
    _write_active_suite_fixture(root)
    calls = 0
    original = registry.load_disease_model_suite

    def counted(dataset, registry_root):
        nonlocal calls
        calls += 1
        return original(dataset, registry_root)

    monkeypatch.setattr(registry, "load_disease_model_suite", counted)
    first = registry.load_active_model_registry("ad", root)
    second = registry.load_active_model_registry("ad", root)
    assert first is second
    assert calls == 1


def test_active_suite_cache_misses_when_pointer_hash_changes(tmp_path, monkeypatch):
    root = tmp_path / "registry"
    _write_active_suite_fixture(root)
    first = registry.load_active_model_registry("ad", root)
    pointer_path = root / "active" / "ad.json"
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["release_set_sha256"] = "f" * 64
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(Exception):
        registry.load_active_model_registry("ad", root)
    assert first is not None
```

并发测试使用 `ThreadPoolExecutor(max_workers=8)` 同时调用同一 root，断言底层 suite loader 只执行一次。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_longitudinal_model_registry.py -k "cache" -q`

Expected: FAIL because当前每次调用都会重新加载 release set 和所有 joblib 文件。

- [ ] **Step 3: Implement cache and single-flight loading**

在 `longitudinal_model_registry.py` 模块级增加：

```python
from threading import RLock

_SUITE_CACHE: dict[tuple[str, str, str], LoadedDiseaseModelSuite] = {}
_SUITE_CACHE_LOCK = RLock()


def _load_cached_suite(dataset: str, root: Path):
    pointer = read_active_pointer(root, dataset)
    key = (dataset, pointer.release_set_id, pointer.release_set_sha256)
    with _SUITE_CACHE_LOCK:
        cached = _SUITE_CACHE.get(key)
        if cached is not None:
            return cached
        suite = load_disease_model_suite(dataset, root)
        _SUITE_CACHE[key] = suite
        stale = [item for item in _SUITE_CACHE if item[0] == dataset and item != key]
        for item in stale:
            _SUITE_CACHE.pop(item, None)
        return suite
```

`load_active_model_registry` 在 active pointer 为 inactive 时继续走兼容 legacy registry；active pointer 为正常状态时调用缓存加载路径。读取 pointer、校验哈希和加载 suite 全部置于同一把锁内，保证首次并发请求只执行一次；异常不写入缓存。加载完成后必须复核 suite 的 release-set ID 和 SHA-256 与首次读取的 pointer 一致，否则返回 `active_pointer_changed`。不同 registry root 即使模型身份相同也不得复用对象。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_longitudinal_model_registry.py -k "cache or active" -q`

Expected: PASS，包含同指针命中、指针变化失效和 8 线程单飞测试。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/longitudinal_model_registry.py backend/tests/test_longitudinal_model_registry.py
git commit -m "perf: cache active longitudinal model suites"
```

### Task 4: 贯通审计提示、readiness 和报告 API

**Files:**
- Modify: `backend/app/services/longitudinal_prediction.py:425-518`
- Modify: `backend/app/services/operator_case_readiness.py:82-168`
- Modify: `backend/app/services/longitudinal_report_generator.py:450-540`
- Test: `backend/tests/test_longitudinal_prediction_contract.py`
- Test: `backend/tests/test_operator_catalog_and_reports_api.py`

**Interfaces:**
- Consumes: `ArtifactMetadataV2.audit`、`ArtifactMetadataV2.calibration`、`ModelRuntimeStatus`。
- Produces: `LongitudinalPredictionResultV3.warnings` 中稳定的审计提示；模型加载/输入契约/运行异常继续通过现有 SSE 安全错误和报告状态收敛。

- [ ] **Step 1: Write the failing tests**

在 `backend/tests/test_longitudinal_prediction_contract.py` 增加：

```python
def test_synthetic_suite_emits_audit_warnings_without_blocking_prediction():
    from app.services.disease_progression import AD_ADAPTER
    result = run_longitudinal_prediction(
        {"baseline_stage": "mci", "age": 65, "sex": "female"},
        _ad_visits(),
        AD_ADAPTER,
        _complete_ad_suite(),
    )
    assert result.outcome_prediction.risk_score is not None
    assert any("合成" in warning for warning in result.warnings)
    assert any("临床有效性" in warning for warning in result.warnings)
    assert any("未校准" in warning for warning in result.warnings)
```

在同文件为 stage/trend model 使用 `CountingModel`，传入缺失 `current_stage` 或必需指标，断言 `calls == 0` 且 reason code 为 `required_feature_missing`。

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_longitudinal_prediction_contract.py -k "audit or required_feature" -q`

Expected: FAIL because当前 suite warning 只来自 adapter，metadata audit 没有进入结果，且 stage/trend 缺失契约尚未统一。

- [ ] **Step 3: Implement audit warning aggregation and readiness integration**

在 prediction service 增加纯函数：

```python
def _audit_warnings(suite: LoadedDiseaseModelSuite) -> list[str]:
    warnings = ["当前活动模型使用合成演示数据"]
    metadata_items = [
        entry.metadata for entry in [*suite.outcomes.values(), suite.stage, *suite.trends.values()]
        if entry is not None and entry.metadata is not None
    ]
    if any(item.audit.clinical_validity_claim is False for item in metadata_items):
        warnings.append("当前模型没有临床有效性声明，不构成医学诊断依据")
    if any(item.calibration.status == "not_calibrated" for item in metadata_items):
        warnings.append("模型分数未校准，不代表临床概率")
    return warnings
```

`_run_suite_prediction` 合并去重后的 `_audit_warnings(suite)` 与已有 adapter warning；不因 `production_enabled=false` 返回 disabled。`evaluate_operator_case_readiness` 继续调用 `load_active_model_registry`，因此完整性错误稳定映射为 `model_unavailable`，不把活动模型误报为 ready。

`longitudinal_report_generator.py` 只消费结构化 warnings，不增加第二套模型判定逻辑；现有 `_transition_report_from_generating` 继续负责失败状态收敛。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_operator_case_readiness.py -q`

Expected: PASS，合成模型仍可生成结果，报告包含审计提示，加载/超时/取消状态无回归。

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/longitudinal_prediction.py backend/app/services/operator_case_readiness.py backend/app/services/longitudinal_report_generator.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_operator_case_readiness.py
git commit -m "feat: surface model audit state in operator reports"
```

### Task 5: 同步流程核查文档并完成全量验收

**Files:**
- Modify: `docs/AI操作者流程核查.md:173-250`
- Test: `backend/tests/`（全量回归）

**Interfaces:**
- Consumes: Task 1–4 的代码行为、专项测试输出和当前 active release set 元数据。
- Produces: 与仓库真实状态一致的第 4 项核查结论，明确工程可运行状态、审计限制和部署门禁。

- [ ] **Step 1: Write the documentation update**

将第 4 项“当前已经具备”补充为：

- 阶段/趋势模型已统一执行 required/allowed missing 特征契约；
- active release set 必须完整匹配病种任务集合；
- 模型组按 release-set ID 和 SHA-256 缓存并在指针变化后失效；
- 当前合成模型可运行，但报告固定记录合成数据、未校准和无临床有效性声明。

将“当前缺失”更新为：真实临床数据和外部验证、模型校准、生产数据库迁移、真实 PostgreSQL/浏览器 E2E 和线上冒烟仍未完成；不再保留已经修复的“报告停留 generating”描述。

- [ ] **Step 2: Run focused regression**

Run: `python -m pytest backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_release_set.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_operator_case_readiness.py backend/tests/test_operator_catalog_and_reports_api.py -q`

Expected: PASS。

- [ ] **Step 3: Run complete backend regression**

Run: `python -m pytest backend/tests -q`

Expected: 所有后端测试通过；若存在与本任务无关的外部夹具缺失，单独记录失败文件和原因，不把它归因于第 4 项。

- [ ] **Step 4: Run frontend production build**

Run: `npm --prefix frontend run build`

Expected: 构建成功；本任务不应产生前端类型或构建错误。

- [ ] **Step 5: Verify diff and commit documentation**

```bash
git diff --check
git add docs/AI操作者流程核查.md
git commit -m "docs: update operator model invocation verification"
```

Expected: 文档只反映已验证的仓库状态，并保留生产部署门禁说明。

## Plan Self-Review Checklist

- Spec coverage: 输入契约（Task 1）、release set 完整性（Task 2）、缓存/失效（Task 3）、审计和错误收敛（Task 4）、文档与全量验收（Task 5）均有对应任务。
- Placeholder scan: 计划不使用 `TODO`、`TBD` 或“稍后补充”等占位描述。
- Type consistency: 所有任务共享 `load_active_model_registry`、`load_disease_model_suite`、`build_fixed_window_inference_features` 和 `InferenceContractError.code` 的既有接口；缓存新增 `_load_cached_suite` 仅由 registry 内部调用。
- Scope: 不涉及重新训练、标准/参考病例逻辑、数据库迁移或前端视觉改造。
