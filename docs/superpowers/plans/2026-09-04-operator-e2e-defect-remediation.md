# AI Operator E2E Defect Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 AI 操作者前五项浏览器验收发现的标准性别筛选、标准原文绑定、阶段模型文案、中文校验和新建病例状态隔离问题，并保持正式参考病例数据缺失时的失败关闭状态。

**Architecture:** 标准证据链使用一个共享的“有效适用条件”构造器和一个确定性的 manifest 来源绑定服务；导入、既有数据修复、运行时预检和 postflight 复用同一来源契约。模型状态由后端和前端分别基于稳定 `status/reason_code` 映射为一致中文，FastAPI 请求校验由全局安全处理器结构化本地化，新建病例由 store 的单一重置入口驱动。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、PostgreSQL、Pytest、Vue 3、TypeScript、Pinia、Vitest、Vue Test Utils。

## Global Constraints

- 直接在 `main` 实施，不创建 worktree 或功能分支。
- 每个生产代码修改前必须先写并运行能稳定复现目标问题的失败测试。
- 不创建、伪造或激活参考病例 release；不把 E2E 病例或合成训练数据放入正式参考病例池。
- 不改变模型 artifact、模型 active 指针、标准医学内容或历史报告快照。
- 已批准/current 标准规则必须有同版本、非空且与 approved manifest 定位一致的原文片段；草稿规则仍可暂时缺少来源。
- 所有 UI 修改遵循 `docs/DESIGN_SPEC.md`，本次不调整既有布局、配色或视觉层级。
- 数据修复命令默认 dry-run，只有显式 `--apply` 才写数据库；任何缺失、歧义或冲突都完整回滚。
- 所有错误、日志和 CLI 输出不得包含数据库连接串、患者身份、病例自由文本或完整医学原文。

---

### Task 1: 统一标准规则的有效适用条件并修复性别筛选

**Files:**
- Modify: `backend/app/services/standard_evidence.py:174-201, 400-451`
- Modify: `backend/app/services/standard_resolver.py:62-82`
- Test: `backend/tests/test_standard_evidence_conditions.py`
- Test: `backend/tests/test_standard_evidence_service.py`

**Interfaces:**
- Consumes: `adapt_v1_applicability(value) -> AllNode`、`StandardRule.sex`、病例上下文 `sex`。
- Produces: `build_effective_applicability(rule: Any) -> AllNode`、`effective_applicability_hash(rule: Any) -> str`，由 EvidenceBundle 和 resolver 共用。

- [ ] **Step 1: 写入男性、女性、缺失性别和哈希变化的失败测试**

```python
def test_effective_applicability_includes_rule_sex():
    male_rule = SimpleNamespace(applicability={}, sex="male")
    node = build_effective_applicability(male_rule)
    assert evaluate_condition(node, {"sex": "male"}).status == "matched"
    assert evaluate_condition(node, {"sex": "female"}).status == "mismatched"
    assert evaluate_condition(node, {}).status == "missing"


def test_effective_applicability_hash_changes_with_sex():
    male = SimpleNamespace(applicability={"sample": "serum"}, sex="male")
    female = SimpleNamespace(applicability={"sample": "serum"}, sex="female")
    assert effective_applicability_hash(male) != effective_applicability_hash(female)
```

在 `test_standard_evidence_service.py` 增加一个包含男女两条 ALT 规则的真实证据构建测试，断言男性病例的男性规则为 `calculable`、女性规则为 `not_applicable`，且只有男性规则产生 `numeric_interpretation`。

- [ ] **Step 2: 运行失败测试并确认失败原因是 `rule.sex` 未进入条件树**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_evidence_conditions.py backend/tests/test_standard_evidence_service.py
```

Expected: 新增测试失败；女性规则当前错误返回 `calculable`，或共享函数尚不存在。

- [ ] **Step 3: 实现共享条件构造和有效适用性哈希**

在 `standard_evidence.py` 增加：

```python
def build_effective_applicability(rule: Any) -> AllNode:
    base = adapt_v1_applicability(getattr(rule, "applicability", None))
    sex = getattr(rule, "sex", None)
    if not sex:
        return base
    return AllNode(children=(*base.children, EqualsNode("sex", sex)))


def effective_applicability_hash(rule: Any) -> str:
    payload = {
        "applicability": getattr(rule, "applicability", None) or {},
        "sex": getattr(rule, "sex", None),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
```

将 `_build_standard_evidence_in_transaction` 中的 `adapt_v1_applicability(...)` 和手工 JSON 哈希替换为以上两个函数。将 `standard_resolver._applicability_matches` 改为调用 `build_effective_applicability(rule)`，并用 `effective_applicability_hash(rule)` 保存实际条件哈希。

- [ ] **Step 4: 运行专项回归并确认性别状态正确**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_evidence_conditions.py backend/tests/test_standard_evidence_service.py backend/tests/test_standard_resolver.py
```

Expected: 全部通过；男性和女性规则不会同时处于 `calculable`。

- [ ] **Step 5: 提交第 1 项修复**

```powershell
git add backend/app/services/standard_evidence.py backend/app/services/standard_resolver.py backend/tests/test_standard_evidence_conditions.py backend/tests/test_standard_evidence_service.py backend/tests/test_standard_resolver.py
git commit -m "fix: enforce standard rule sex applicability"
```

---

### Task 2: 在 manifest 导入时确定性绑定原文片段

**Files:**
- Create: `backend/app/services/standard_source_binding.py`
- Modify: `backend/app/services/standard_manifest_import.py:1-130`
- Test: `backend/tests/test_standard_manifest_import.py`
- Create: `backend/tests/test_standard_source_binding.py`

**Interfaces:**
- Consumes: `StandardManifestEntry.source`、`StandardSegment`、`ReferenceStandardVersion.id`。
- Produces: `StandardSourceBindingError.code`、`normalize_source_text(value: str) -> str`、`resolve_manifest_source_segment(db: Any, *, version_id: int, source: SourceLocator) -> StandardSegment`。

- [ ] **Step 1: 写入唯一匹配、缺失、歧义和跨版本的失败测试**

```python
def test_resolve_manifest_source_segment_requires_one_same_version_match():
    source = SourceLocator(table_index=3, row_index=3, raw_text="CDR 原文")
    matched = SimpleNamespace(
        id=12, version_id=4, paragraph_index=None, table_index=3,
        row_index=3, column_index=None, raw_text="CDR 原文",
    )
    assert resolve_manifest_source_segment(
        db_with_segments([matched]), version_id=4, source=source
    ).id == 12


@pytest.mark.parametrize(
    ("segments", "code"),
    [([], "source_segment_missing"), ([segment(1), segment(2)], "source_segment_ambiguous")],
)
def test_resolve_manifest_source_segment_fails_closed(segments, code):
    with pytest.raises(StandardSourceBindingError) as caught:
        resolve_manifest_source_segment(
            db_with_segments(segments), version_id=4,
            source=SourceLocator(table_index=3, row_index=3, raw_text="CDR 原文"),
        )
    assert caught.value.code == code
```

在 `test_standard_manifest_import.py` 更新规则导入断言，要求新规则的 `source_segment_id` 等于匹配片段 ID；增加“第二条来源失败时没有任何规则进入 `db.add`”的预解析测试。

- [ ] **Step 2: 运行测试确认导入仍写入空来源**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py
```

Expected: 新测试失败，现有导入结果的 `source_segment_id` 为 `None`。

- [ ] **Step 3: 实现来源匹配服务**

`standard_source_binding.py` 使用以下稳定契约：

```python
class StandardSourceBindingError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def normalize_source_text(value: str) -> str:
    return "\n".join(line.rstrip() for line in str(value).replace("\r\n", "\n").split("\n")).strip()


def resolve_manifest_source_segment(db, *, version_id: int, source):
    query = db.query(StandardSegment).filter(StandardSegment.version_id == version_id)
    for field in ("paragraph_index", "table_index", "row_index", "column_index"):
        value = getattr(source, field, None)
        if value is not None:
            query = query.filter(getattr(StandardSegment, field) == value)
    expected = normalize_source_text(source.raw_text or "")
    matches = [item for item in query.all() if normalize_source_text(item.raw_text) == expected]
    if not matches:
        raise StandardSourceBindingError("source_segment_missing")
    if len(matches) != 1:
        raise StandardSourceBindingError("source_segment_ambiguous")
    return matches[0]
```

函数不接受文档级 absence entry；调用者只对 approved `entry_kind="rule"` 的条目调用。

- [ ] **Step 4: 修改导入流程为先全量解析、再创建规则**

在 `import_manifest_rules` 写入 indicator 或 rule 前构造：

```python
source_segments = {
    entry.entry_id: resolve_manifest_source_segment(
        db, version_id=version_id, source=entry.source
    )
    for entry in _approved_rule_entries(manifest)
}
```

创建规则时使用：

```python
source_segment_id=source_segments[entry.entry_id].id,
```

将 `StandardSourceBindingError` 转换为 `ValueError(exc.code)`，保持现有 CLI 的事务回滚行为。

- [ ] **Step 5: 运行导入和 manifest 回归**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py backend/tests/test_standard_manifest.py scripts/tests/test_apply_standard_manifest.py
```

Expected: 全部通过；导入规则均绑定唯一来源，失败时无部分写入。

- [ ] **Step 6: 提交第 2 项修复**

```powershell
git add backend/app/services/standard_source_binding.py backend/app/services/standard_manifest_import.py backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py
git commit -m "fix: bind approved standard rules to source segments"
```

---

### Task 3: 增加既有规则来源修复工具和 postflight 检查

**Files:**
- Modify: `backend/app/services/standard_source_binding.py`
- Create: `scripts/bind_standard_rule_sources.py`
- Create: `scripts/tests/test_bind_standard_rule_sources.py`
- Modify: `scripts/check_database_readonly.py:180-295`
- Modify: `scripts/tests/test_check_operator_report_evidence_readonly.py`

**Interfaces:**
- Consumes: Task 2 的 `resolve_manifest_source_segment`、`standard_manifests/{dataset}.v1.json`、current approved `ReferenceStandardVersion.rules`。
- Produces: `SourceBindingPlan`、`plan_current_standard_bindings(db, dataset) -> SourceBindingPlan`、`apply_current_standard_bindings(db, plan) -> SourceBindingPlan`，以及 CLI `--standard {fatty_liver,ad} [--apply]`。

- [ ] **Step 1: 写入 dry-run、幂等 apply、冲突回滚和安全输出的失败测试**

```python
def test_cli_defaults_to_dry_run(monkeypatch, capsys):
    module = load_script()
    plan = SourceBindingPlan(dataset="ad", version_id=4, total_rules=8, to_bind=((30, 213),), consistent=7)
    monkeypatch.setattr(module, "build_plan", lambda *_: plan)
    assert module.main(["--standard", "ad"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "dry_run"
    assert payload["to_bind"] == 1


def test_apply_rolls_back_on_existing_source_conflict(monkeypatch, capsys):
    module = load_script()
    transaction = fake_session()
    monkeypatch.setattr(module, "SessionLocal", lambda: transaction)
    monkeypatch.setattr(
        module, "build_plan",
        lambda *_: (_ for _ in ()).throw(StandardSourceBindingError("source_binding_conflict")),
    )
    assert module.main(["--standard", "fatty_liver", "--apply"]) == 1
    assert transaction.rollbacks == 1
    assert "source_binding_conflict" in capsys.readouterr().out
```

为 checker 增加 fake connection 结果，断言 `standard_source_integrity_match=false` 会使 postflight 失败，即使标准哈希和 active releases 均正常。

- [ ] **Step 2: 运行失败测试确认工具和检查字段尚不存在**

Run:

```powershell
python -m pytest -q scripts/tests/test_bind_standard_rule_sources.py scripts/tests/test_check_operator_report_evidence_readonly.py
```

Expected: 新 CLI 或 `standard_source_integrity` 尚不存在，测试失败。

- [ ] **Step 3: 实现来源绑定计划和 CLI**

`SourceBindingPlan` 只保存 ID 和计数：

```python
@dataclass(frozen=True)
class SourceBindingPlan:
    dataset: str
    version_id: int
    total_rules: int
    to_bind: tuple[tuple[int, int], ...]
    consistent: int
```

`plan_current_standard_bindings` 验证 dataset、current approved 版本、manifest 版本标签、文档哈希和 `_manifest_entry_id`，然后为每条规则解析唯一来源。已有来源相同计入 `consistent`；已有来源不同抛出 `source_binding_conflict`。

`apply_current_standard_bindings` 逐个按 `rule_id` 和 `version_id` 锁定规则，复核原值仍为空后赋值，不调用 `commit`。CLI 负责显式 apply 时单次 `commit`，其他路径 `rollback`。

- [ ] **Step 4: 在 postflight 中加入来源完整性统计**

新增只读 SQL，按 current approved 标准统计：

```sql
SELECT d.code,
       COUNT(sr.id) AS total_rules,
       COUNT(sr.source_segment_id) AS bound_rules,
       COUNT(*) FILTER (WHERE ss.id IS NOT NULL AND ss.version_id <> sr.version_id) AS cross_version_sources,
       COUNT(*) FILTER (WHERE ss.id IS NOT NULL AND btrim(ss.raw_text) = '') AS empty_source_texts
FROM reference_standards rs
JOIN diseases d ON d.id = rs.disease_id
JOIN reference_standard_versions rsv ON rsv.id = rs.current_version_id
JOIN standard_rules sr ON sr.version_id = rsv.id
LEFT JOIN standard_segments ss ON ss.id = sr.source_segment_id
WHERE d.code IN ('ad', 'fatty_liver') AND rsv.status = 'approved'
GROUP BY d.code
ORDER BY d.code
```

只有两个病种都存在、`total_rules > 0`、`bound_rules == total_rules`、跨版本和空原文计数均为零时，`standard_source_integrity_match=true`。

- [ ] **Step 5: 运行 CLI 和 checker 单元回归**

Run:

```powershell
python -m pytest -q scripts/tests/test_bind_standard_rule_sources.py scripts/tests/test_check_operator_report_evidence_readonly.py
```

Expected: 全部通过；dry-run 没有 commit，apply 成功一次且重复执行修改数为零。

- [ ] **Step 6: 提交第 3 项修复**

```powershell
git add backend/app/services/standard_source_binding.py scripts/bind_standard_rule_sources.py scripts/tests/test_bind_standard_rule_sources.py scripts/check_database_readonly.py scripts/tests/test_check_operator_report_evidence_readonly.py
git commit -m "feat: repair and verify standard source bindings"
```

---

### Task 4: 在报告生成前失败关闭不可追溯标准

**Files:**
- Modify: `backend/app/services/standard_evidence.py:267-356`
- Modify: `backend/app/services/standard_source_binding.py`
- Test: `backend/tests/test_standard_evidence_service.py`
- Test: `backend/tests/test_evidence_bundle_service.py`
- Test: `backend/tests/test_operator_catalog_and_reports_api.py`

**Interfaces:**
- Consumes: Task 2 的 `normalize_source_text`、approved manifest、`StandardRule.source_segment`。
- Produces: `validate_rule_source_binding(rule, *, version_id: int, manifest_entry) -> None`；失败时 `StandardEvidenceError("standard_integrity_failed")`。

- [ ] **Step 1: 写入缺失来源、跨版本、空原文和 manifest 原文漂移的失败测试**

```python
@pytest.mark.parametrize("source", [None, SimpleNamespace(id=7, version_id=99, raw_text="原文")])
def test_preflight_rejects_missing_or_cross_version_rule_source(source, approved_standard):
    approved_standard.current_version.rules[0].source_segment = source
    with pytest.raises(StandardEvidenceError) as caught:
        preflight_standard(_db(approved_standard), 1, "fatty_liver")
    assert caught.value.code == "standard_integrity_failed"
```

增加 API 测试，patch 模型加载函数并断言来源完整性失败时模型加载调用次数为零。

- [ ] **Step 2: 运行失败测试确认当前预检仅验证 manifest SHA-256**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_evidence_service.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py
```

Expected: 缺失 `source_segment` 的 approved 规则仍通过当前预检，新测试失败。

- [ ] **Step 3: 实现 approved manifest 来源复核**

在 preflight 中加载 `standard_manifests/{disease_code}.v1.json`，验证 manifest 为 approved、dataset 和 target version 一致。建立 `entry_id -> entry` 映射，并对每条规则执行：

```python
entry_id = (rule.applicability or {}).get("_manifest_entry_id")
entry = entries_by_id.get(entry_id)
source = rule.source_segment
if entry is None or source is None or source.version_id != version.id:
    raise StandardEvidenceError("standard_integrity_failed")
if not source.raw_text or normalize_source_text(source.raw_text) != normalize_source_text(entry.source.raw_text or ""):
    raise StandardEvidenceError("standard_integrity_failed")
for field in ("paragraph_index", "table_index", "row_index", "column_index"):
    expected = getattr(entry.source, field)
    if expected is not None and getattr(source, field) != expected:
        raise StandardEvidenceError("standard_integrity_failed")
```

项目根目录解析复用 `operator_indicator_catalog._project_root()` 的路径策略或提取为同一公共 helper，不接受请求参数提供任意 manifest 路径。

- [ ] **Step 4: 运行预检和报告 API 回归**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_evidence_service.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py
```

Expected: 全部通过；来源问题在模型调用前以稳定错误关闭。

- [ ] **Step 5: 提交第 4 项修复**

```powershell
git add backend/app/services/standard_evidence.py backend/app/services/standard_source_binding.py backend/tests/test_standard_evidence_service.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py
git commit -m "fix: fail closed on untraceable approved standards"
```

---

### Task 5: 准确展示阶段模型状态和原因

**Files:**
- Modify: `backend/app/services/longitudinal_report_generator.py:343-397, 580-595`
- Test: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `frontend/src/components/LongitudinalPredictionSummary.vue:35-78`
- Modify: `frontend/src/api/operator.ts:345-380`
- Create: `frontend/src/components/__tests__/LongitudinalPredictionSummary.spec.ts`

**Interfaces:**
- Consumes: `ModelRuntimeStatus.status`、`reason_code`、`StageProjection.status`。
- Produces: 后端 `_stage_status_text(status: Mapping[str, Any], *, compact: bool = False) -> str`；前端 `stageStatusText` computed。

- [ ] **Step 1: 写入后端四种阶段状态的失败测试**

```python
@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("missing", "stage_model_missing", "当前未配置可用的阶段模型"),
        ("incompatible", "required_feature_missing", "本次输入缺少必需特征"),
        ("disabled", "prediction_not_applicable", "当前基线阶段不适用阶段预测"),
        ("incompatible", "prediction_failed", "阶段模型推理失败"),
    ],
)
def test_report_explains_stage_model_reason(status, reason, expected):
    prediction = _v2_prediction()
    prediction["model_status"]["stage"].update(status=status, reason_code=reason)
    assert expected in render_longitudinal_markdown(prediction)
```

- [ ] **Step 2: 写入前端摘要失败测试**

挂载 `LongitudinalPredictionSummary`，分别提供 `required_feature_missing` 和 `stage_model_missing`，断言前者显示“缺少必需特征”，后者显示“未配置可用的阶段模型”，且不再统一显示“未参与或推理失败”。

- [ ] **Step 3: 运行前后端失败测试**

Run:

```powershell
python -m pytest -q backend/tests/test_longitudinal_report_generator.py
Set-Location frontend
npm run test -- --run src/components/__tests__/LongitudinalPredictionSummary.spec.ts
Set-Location ..
```

Expected: 后端和前端新增断言均失败，因为当前代码统一输出“尚未配置”或“未参与或推理失败”。

- [ ] **Step 4: 实现单义状态映射并覆盖报告三个位置**

后端映射优先按 `reason_code`，再按 `status`：

```python
def _stage_status_text(status: Mapping[str, Any]) -> str:
    reason = status.get("reason_code")
    if status.get("status") == "available":
        return "阶段模型已参与本次推理。"
    if reason == "required_feature_missing":
        return "阶段模型存在，但本次输入缺少必需特征，因此未预测下一阶段。"
    if reason in {"prediction_not_applicable", "terminal_stage"}:
        return "当前基线阶段不适用阶段预测，因此未预测下一阶段。"
    if reason == "prediction_failed":
        return "阶段模型推理失败，未生成下一阶段预测。"
    if status.get("status") == "missing" or reason in {"stage_model_missing", "release_record_missing"}:
        return "当前未配置可用的阶段模型，因此未预测下一阶段。"
    return f"阶段模型不可用，未生成下一阶段预测；原因码：{reason or 'unknown'}。"
```

第 5 节、第 6 节和第 6.1 节调用同一函数。前端使用同样的优先级，但未知状态只显示安全中文，不把内部原因码放入视觉摘要。

- [ ] **Step 5: 运行阶段文案专项回归**

Run:

```powershell
python -m pytest -q backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_acceptance.py
Set-Location frontend
npm run test -- --run src/components/__tests__/LongitudinalPredictionSummary.spec.ts src/components/__tests__/LongitudinalReportView.spec.ts
Set-Location ..
```

Expected: 全部通过；同一报告的三个阶段说明一致。

- [ ] **Step 6: 提交第 5 项修复**

```powershell
git add backend/app/services/longitudinal_report_generator.py backend/tests/test_longitudinal_report_generator.py frontend/src/components/LongitudinalPredictionSummary.vue frontend/src/api/operator.ts frontend/src/components/__tests__/LongitudinalPredictionSummary.spec.ts
git commit -m "fix: explain stage model availability accurately"
```

---

### Task 6: 将 FastAPI 请求校验错误结构化中文化

**Files:**
- Create: `backend/app/core/validation_errors.py`
- Modify: `backend/app/main.py:1-30`
- Create: `backend/tests/test_request_validation_errors.py`
- Test: `frontend/src/api/__tests__/operator-case-workspace.spec.ts`

**Interfaces:**
- Consumes: `RequestValidationError.errors()` 中的 `type`、`loc` 和 `ctx`。
- Produces: `request_validation_exception_handler(request, exc) -> JSONResponse`，响应 `detail={code,message,issues}`。

- [ ] **Step 1: 写入年龄上限、整数、必填字段和无敏感回显的失败测试**

```python
def test_request_validation_error_is_structured_chinese(client, operator_token):
    response = client.post(
        "/api/v1/operator/cases",
        headers={"Authorization": f"Bearer {operator_token}", "Idempotency-Key": str(uuid4())},
        json=valid_case_payload(age=121),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "validation_error"
    assert detail["issues"][0]["field"] == "age"
    assert detail["issues"][0]["message"] == "必须小于或等于 120"
    assert "Input should" not in response.text
    assert "input" not in detail["issues"][0]
```

直接对本地化函数增加 `missing`、`int_parsing`、`greater_than_equal`、`string_too_long` 和未知类型的参数化测试。

- [ ] **Step 2: 运行失败测试确认当前响应仍为 Pydantic 英文数组**

Run:

```powershell
python -m pytest -q backend/tests/test_request_validation_errors.py
```

Expected: 当前 `detail` 为默认数组且消息为英文，新测试失败。

- [ ] **Step 3: 实现安全本地化处理器并注册到 FastAPI**

核心输出结构：

```python
def request_validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = [localize_validation_issue(item) for item in exc.errors()]
    return JSONResponse(
        status_code=422,
        content={
            "detail": {
                "code": "validation_error",
                "message": "输入数据无效",
                "issues": issues,
            }
        },
    )
```

`localize_validation_issue` 仅返回 `code`、`message`、可选 `field`。字段路径移除首段 `body`。消息按 `type` 和数值上下文生成，未知类型返回“输入内容格式不正确”，不返回 `input`、原请求值或异常对象。

在 `main.py` 注册：

```python
app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
```

- [ ] **Step 4: 更新前端 API 回归断言结构化中文字段错误可直接展示**

在现有 `operator-case-workspace.spec.ts` 中构造 `detail={code:'validation_error',message:'输入数据无效',issues:[{code:'less_than_equal',field:'age',message:'必须小于或等于 120'}]}`，断言 `validationIssueMap(error).age` 为中文，不新增前端翻译表。

- [ ] **Step 5: 运行前后端校验错误回归**

Run:

```powershell
python -m pytest -q backend/tests/test_request_validation_errors.py backend/tests/test_operator_case_workspace_api.py
Set-Location frontend
npm run test -- --run src/api/__tests__/operator-case-workspace.spec.ts
Set-Location ..
```

Expected: 全部通过；响应中不出现 Pydantic 英文错误或输入值。

- [ ] **Step 6: 提交第 6 项修复**

```powershell
git add backend/app/core/validation_errors.py backend/app/main.py backend/tests/test_request_validation_errors.py frontend/src/api/__tests__/operator-case-workspace.spec.ts
git commit -m "fix: localize request validation errors"
```

---

### Task 7: 统一新建病例重置入口并阻止异步旧状态回填

**Files:**
- Modify: `frontend/src/stores/operator.ts:100-210`
- Modify: `frontend/src/views/OperatorView.vue:145-180`
- Modify: `frontend/src/components/operator-case/OperatorCaseWorkspace.vue:30-55`
- Test: `frontend/src/stores/__tests__/operator-case-workspace.spec.ts`
- Test: `frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts`

**Interfaces:**
- Consumes: 当前 store 的病例、readiness、报告、预测、草稿和生成状态。
- Produces: store action `startNewLongitudinalCase() -> void`；workspace 的 `props.model` 从对象变为 `null` 时始终调用 `makeDraft(null)`。

- [ ] **Step 1: 写入 store 全状态重置失败测试**

```typescript
it('starts a new case without retaining selected case or report state', () => {
  const store = useOperatorStore()
  store.currentLongitudinalCase = existingCase()
  store.currentReport = existingReport()
  store.longitudinalPrediction = existingPrediction()
  store.readiness = readyState()
  store.draft = existingDraft()

  store.startNewLongitudinalCase()

  expect(store.currentLongitudinalCase).toBeNull()
  expect(store.currentReport).toBeNull()
  expect(store.longitudinalPrediction).toBeNull()
  expect(store.longitudinalEvidence).toBeNull()
  expect(store.readiness).toBeNull()
  expect(store.draft).toBeNull()
})
```

- [ ] **Step 2: 写入 workspace 从既有病例切换到 null 的失败测试**

```typescript
it('rebuilds a blank draft when model changes from an existing case to null', async () => {
  const wrapper = mountWorkspace({ model: existingCase() })
  await wrapper.setProps({ model: null })
  expect((wrapper.get('[aria-label="年龄"]').element as HTMLInputElement).value).toBe('0')
  expect((wrapper.get('[aria-label="指标名称"]').element as HTMLSelectElement).value).toBe('')
  expect(wrapper.text()).not.toContain('CASE-OLD')
})
```

- [ ] **Step 3: 运行失败测试确认 null 分支没有重建 draft**

Run:

```powershell
Set-Location frontend
npm run test -- --run src/stores/__tests__/operator-case-workspace.spec.ts src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts
Set-Location ..
```

Expected: store action不存在，且 workspace 仍显示旧病例值。

- [ ] **Step 4: 实现单一重置 action 和无条件 model watch**

store action：

```typescript
function startNewLongitudinalCase() {
  cancelGeneration()
  clearCurrent()
  currentLongitudinalCase.value = null
  draft.value = null
  readiness.value = null
  longitudinalPrediction.value = null
  createIdempotencyKey = null
}
```

`OperatorView.startNewLongitudinalCase` 只调用该 action，再清空 `draftDiseaseCode` 和 `validationIssues`。`OperatorCaseWorkspace` 的 watcher 改为：

```typescript
watch(
  () => props.model,
  (model) => {
    draft.value = makeDraft(model)
    baseline.value = JSON.stringify(draft.value)
    reasonOpen.value = false
  },
  { deep: true },
)
```

这样既有异步病例响应只有在它仍被赋给 `currentLongitudinalCase` 时才会进入 workspace；进入新建态时 store 和组件本地 draft 同时清空。

- [ ] **Step 5: 运行新建病例专项回归**

Run:

```powershell
Set-Location frontend
npm run test -- --run src/stores/__tests__/operator-case-workspace.spec.ts src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts
Set-Location ..
```

Expected: 全部通过；从既有病例或报告状态进入新建态都不保留旧数据。

- [ ] **Step 6: 提交第 7 项修复**

```powershell
git add frontend/src/stores/operator.ts frontend/src/views/OperatorView.vue frontend/src/components/operator-case/OperatorCaseWorkspace.vue frontend/src/stores/__tests__/operator-case-workspace.spec.ts frontend/src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts
git commit -m "fix: isolate new operator case state"
```

---

### Task 8: 修复当前标准数据并完成全链路验收

**Files:**
- Modify: `docs/AI操作者流程核查.md`
- Modify: `docs/superpowers/plans/2026-09-04-operator-e2e-defect-remediation.md`

**Interfaces:**
- Consumes: Tasks 1-7 的代码、两个 approved manifest、当前 PostgreSQL 0022 数据库。
- Produces: 当前数据库 19 条规则的同版本来源绑定、专项与完整回归证据、更新后的第 1-5 项浏览器验收记录。

- [ ] **Step 1: 运行两个病种的来源绑定 dry-run**

Run:

```powershell
python scripts/bind_standard_rule_sources.py --standard fatty_liver
python scripts/bind_standard_rule_sources.py --standard ad
```

Expected: 两个命令均返回 `status=dry_run`；合计 `total_rules=19`、`to_bind=19`、无 missing、ambiguous 或 conflict。若计数不同则停止，不执行 apply。

- [ ] **Step 2: 显式修复当前本地数据库并验证幂等**

Run:

```powershell
python scripts/bind_standard_rule_sources.py --standard fatty_liver --apply
python scripts/bind_standard_rule_sources.py --standard ad --apply
python scripts/bind_standard_rule_sources.py --standard fatty_liver
python scripts/bind_standard_rule_sources.py --standard ad
```

Expected: 首次 apply 合计绑定 19 条；重复 dry-run 的 `to_bind=0`、`consistent=19`。

- [ ] **Step 3: 运行后端相关专项回归**

Run:

```powershell
python -m pytest -q backend/tests/test_standard_evidence_conditions.py backend/tests/test_standard_evidence_service.py backend/tests/test_standard_resolver.py backend/tests/test_standard_source_binding.py backend/tests/test_standard_manifest_import.py backend/tests/test_evidence_bundle_service.py backend/tests/test_operator_catalog_and_reports_api.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_request_validation_errors.py backend/tests/test_operator_case_workspace_api.py scripts/tests/test_bind_standard_rule_sources.py scripts/tests/test_check_operator_report_evidence_readonly.py
```

Expected: 0 failures、0 errors；仅允许仓库既有且与本次无关的明确弃用 warning。

- [ ] **Step 4: 运行前端相关回归和生产构建**

Run:

```powershell
Set-Location frontend
npm run test -- --run src/api/__tests__/operator-case-workspace.spec.ts src/stores/__tests__/operator-case-workspace.spec.ts src/components/operator-case/__tests__/OperatorCaseWorkspace.spec.ts src/components/__tests__/LongitudinalPredictionSummary.spec.ts src/components/__tests__/LongitudinalReportView.spec.ts src/components/__tests__/LongitudinalEvidenceSection.spec.ts
npm run build
Set-Location ..
```

Expected: Vitest 全部通过；`vue-tsc && vite build` 退出码 0。

- [ ] **Step 5: 运行后端完整回归**

Run:

```powershell
python -m pytest -q backend/tests
```

Expected: 0 failures、0 errors；需要外部隔离 PostgreSQL 的测试只在 `TEST_DATABASE_URL` 未设置时按既有规则明确 skip。

- [ ] **Step 6: 运行数据库 postflight 并确认只剩正式参考数据阻断**

Run:

```powershell
python scripts/check_database_readonly.py --phase postflight
```

Expected:

```text
alembic_revision=0022
standards_match=true
standard_source_integrity_match=true
evidence_storage_match=true
active_releases_match=false
status=FAIL
```

不得为了把状态改成 PASS 而创建参考病例 release。

- [ ] **Step 7: 完成双病种浏览器冒烟**

脂肪肝使用男性病例和 ALT 指标，验证只展示男性范围、存在真实原文定位、历史报告和 PDF 的证据哈希一致。AD 使用 CDR 和 `scale_version=CDR`，验证显示 `evidence_only` 且不产生数值诊断。两个病种都验证 `required_feature_missing` 显示为“缺少必需特征”，年龄 121 显示中文错误，新建病例不保留旧病例字段。

Expected: 代码缺陷均不可复现；参考病例区继续明确显示正式 release 未就绪且不使用旧索引。

- [ ] **Step 8: 更新核查文档和计划勾选状态**

在 `docs/AI操作者流程核查.md` 的第 1-5 项浏览器验收记录中写入：测试病例匿名编号、报告 ID、标准来源修复数量、专项/完整测试计数、构建结果、postflight 的唯一剩余阻断。不得写入病例自由文本或数据库连接信息。

- [ ] **Step 9: 提交验收证据**

```powershell
git add docs/AI操作者流程核查.md docs/superpowers/plans/2026-09-04-operator-e2e-defect-remediation.md
git commit -m "docs: record operator defect remediation verification"
```

- [ ] **Step 10: 最终检查工作区和提交历史**

Run:

```powershell
git status --short
git log -10 --oneline
```

Expected: 工作区为空；Task 1-8 的独立提交均位于 `main`，没有未跟踪测试产物或意外数据库导出文件。
