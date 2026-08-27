# 双疾病纵向关键进展信号解释器实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本项目所有者已要求全程单 Agent，因此不派发子 Agent。

**Goal:** 在不改变旧 progression 链路、数据库 schema、前端或 P0-04/P0-05 模型的前提下，建立确定性双疾病关键进展信号解释器，并将其接入 `longitudinal_prediction.v2` 与报告渲染。

**Architecture:** 新增独立 `longitudinal_signal_interpreter.py`。它接收现有 `summarize_observation` 的观察事实、P0-02 resolver 的标准解析快照、当前 outcome registry 的状态与 artifact feature metadata，输出严格结构化 `SignalInterpretationResult`。预测服务只负责调用并保存结果，报告渲染器只负责把结果翻译成中文，不在模板中重新判断业务规则。

**Tech Stack:** Python 3.11、Pydantic v2、SQLAlchemy 只读 resolver、pytest、PowerShell；不新增依赖，不调用 LLM，不执行模型预测来判断信号。

## Global Constraints

- 使用 PowerShell，并在 Python 命令前设置 `$env:PYTHONPATH='backend;.'`。
- 至少 3 次有效数值观察才生成关键进展信号；4 次或更多观察使用该指标全部有效观察，不截取最近三次。
- CDR 只能作为“阶段相关观察”，不能当作阶段模型结论或个体 outcome 模型贡献。
- 参考范围只能来自 `standard_resolver.resolve_standard_rules` 的当前 approved 规则；解释器不得复制隐藏阈值或从自由文本猜测范围。
- `used_by_outcome_model=true` 只在 outcome 状态为 `available` 且 metadata 中命中真实派生 feature names 时成立。
- 当前没有获批的个体贡献解释契约；`model_contribution` 始终为 `null`，状态必须为 `not_supported` 或 `unavailable`。
- 不训练、不重新训练、不修改、不写入 `backend/app/ml_models/` 中任何生产模型或 metadata。
- 不修改数据库 model、Alembic migration、数据库表、前端代码或旧 `/progression-predictions` 接口。
- 保留旧 `progression_signal` 字段、旧 progression engine、历史 v1 payload 和既有 API 语义；新报告只新增结构化信号来源。
- reason code、关注等级、信号排序和中文文案均由确定性代码产生，不能由 LLM 决定。
- reason、provenance、limitations 和报告内容不得包含患者身份、数据库 URL、密码、内部路径或 traceback。
- 每个任务先写失败测试并运行确认 RED，再写最小实现并运行 GREEN；每个任务结束后运行对应回归。

## 文件地图

### Create

- `backend/app/services/longitudinal_signal_interpreter.py`：canonical 映射、疾病方向、单位/标准降级、关注等级、模型 feature 映射、稳定排序。
- `backend/tests/test_longitudinal_signal_interpreter.py`：解释器纯函数、双疾病语义、单位与标准状态、模型使用和确定性测试。

### Modify

- `backend/app/schemas/longitudinal_report.py`：新增严格 `LongitudinalSignal`、`SignalInterpretationResult`，并把 `progression_signals` 加入 v2。
- `backend/app/services/longitudinal_prediction.py`：在已有观察和模型状态生成后调用解释器，保留 outcome score 计算不变。
- `backend/app/services/longitudinal_report_generator.py`：从结构化 `progression_signals` 渲染中文关键进展信号；v1 没有该字段时走兼容提示。
- `backend/tests/test_longitudinal_prediction_contract.py`：验证 v2 信号、模型使用状态与 outcome/stage/trend 不可用时的部分可用行为。
- `backend/tests/test_longitudinal_report_generator.py`：验证信号中文渲染、无足够信号提示和历史 v1 兼容。
- `backend/tests/test_longitudinal_end_to_end.py`：双疾病信号端到端、敏感信息和旧 API 回归补充。
- `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`：只有全部实现与验证通过后，最后记录 P0-06 实际状态；不得提前修改。

### Read Only / Must Not Modify

- `backend/app/db/models.py`
- `backend/alembic/versions/*`
- `backend/app/ml_models/*`
- `frontend/*`
- `backend/app/services/disease_progression.py` 中旧 progression 输出和旧接口契约
- `backend/app/services/standard_resolver.py` 的规则选择逻辑
- P0-05 registry artifact 和 release 文件

---

### Task 1: 建立严格信号 schema 与 v2 挂载点

**Files:**
- Modify: `backend/app/schemas/longitudinal_report.py`
- Create: `backend/tests/test_longitudinal_signal_interpreter.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:**
- Produces `LongitudinalSignal`、`SignalInterpretationResult`、`LongitudinalPredictionResultV2.progression_signals`。
- `progression_signals` 类型固定为 `SignalInterpretationResult`，默认值为空结果；v1 schema 不变。

- [ ] **Step 1: Write the failing schema tests**

```python
def test_signal_schema_rejects_unknown_fields_and_requires_stable_levels():
    from pydantic import ValidationError
    from app.schemas.longitudinal_report import LongitudinalSignal

    signal = LongitudinalSignal(
        indicator="alt",
        display_name="谷丙转氨酶",
        unit="U/L",
        first_value=20,
        latest_value=60,
        absolute_change=40,
        relative_change=2.0,
        observation_count=3,
        observation_span_days=365,
        observed_direction="rising",
        disease_attention_direction="rising",
        reference_status="above_range",
        reference_rule_id=1,
        reference_version_id=3,
        attention_level="priority",
        reason_codes=["directional_change", "latest_above_reference"],
        used_by_outcome_model=True,
        model_feature_names=["alt.delta", "alt.last"],
        model_contribution_status="not_supported",
        model_contribution=None,
        provenance={"standard_version_id": 3, "standard_rule_id": 1},
        limitations=[],
    )
    assert signal.attention_level == "priority"
    assert signal.model_contribution is None
    with pytest.raises(ValidationError):
        LongitudinalSignal.model_validate({**signal.model_dump(), "unexpected": True})


def test_v2_defaults_to_empty_signal_result_but_v1_contract_is_unchanged():
    from app.schemas.longitudinal_report import LongitudinalPredictionResultV1, LongitudinalPredictionResultV2

    assert LongitudinalPredictionResultV2.model_fields["progression_signals"].default_factory().signals == []
    assert "progression_signals" not in LongitudinalPredictionResultV1.model_fields
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "signal_schema or v2_defaults" -q
```

Expected: FAIL because the schema classes and v2 field do not exist.

- [ ] **Step 3: Implement the strict models**

Add `Literal` unions for `attention_level` (`none`, `attention`, `priority`), `observed_direction` (`rising`, `falling`, `stable`, `unavailable`), and the documented reference/model statuses. Use `ConfigDict(extra="forbid")`. Enforce:

```python
class LongitudinalSignal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicator: str
    display_name: str
    unit: str | None = None
    first_value: float | None = None
    latest_value: float | None = None
    absolute_change: float | None = None
    relative_change: float | None = None
    observation_count: int = Field(ge=0)
    observation_span_days: int = Field(ge=0)
    observed_direction: Literal["rising", "falling", "stable", "unavailable"]
    disease_attention_direction: Literal["rising", "falling", "none"]
    reference_status: str
    reference_rule_id: int | None = None
    reference_version_id: int | None = None
    attention_level: Literal["none", "attention", "priority"]
    reason_codes: list[str] = Field(default_factory=list)
    used_by_outcome_model: bool = False
    model_feature_names: list[str] = Field(default_factory=list)
    model_contribution_status: Literal["not_supported", "unavailable"]
    model_contribution: None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

class SignalInterpretationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["longitudinal_signal_interpretation.v1"] = "longitudinal_signal_interpretation.v1"
    signals: list[LongitudinalSignal] = Field(default_factory=list)
    omitted_indicators: list[dict[str, Any]] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
```

Add `progression_signals: SignalInterpretationResult = Field(default_factory=SignalInterpretationResult)` to v2 only. Do not relax existing v2 validators.

- [ ] **Step 4: Run GREEN and schema regression**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "signal_schema or v2_defaults" -q
python -m pytest backend/tests/test_longitudinal_prediction_contract.py -q
```

Expected: new schema tests and existing prediction contract tests pass.

- [ ] **Step 5: Commit checkpoint**

Do not commit automatically. Record the exact diff and wait for the owner’s requested integration checkpoint if one is required.

### Task 2: 实现 canonical 映射、疾病方向和三次观察规则

**Files:**
- Create: `backend/app/services/longitudinal_signal_interpreter.py`
- Modify: `backend/tests/test_longitudinal_signal_interpreter.py`

**Interfaces:**
- `canonicalize_indicator(dataset: str, raw_name: str) -> tuple[str | None, str | None]`
- `interpret_observation_signals(*, dataset: str, visits: Sequence[Mapping[str, Any]], standard_sources: Sequence[Mapping[str, Any]] | None = None, outcome_status: ModelRuntimeStatus | None = None, feature_names: Sequence[str] | None = None) -> SignalInterpretationResult`
- Internal configuration is explicit and immutable; no fuzzy matching.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_fatty_liver_alt_rising_and_alb_falling_use_disease_direction():
    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}, {"name": "ALB", "value": 45, "unit": "g/L"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 35, "unit": "U/L"}, {"name": "ALB", "value": 40, "unit": "g/L"}]},
            {"visit_date": "2024-12-31", "indicators": [{"name": "ALT", "value": 60, "unit": "U/L"}, {"name": "ALB", "value": 32, "unit": "g/L"}]},
        ],
    )
    by_name = {item.indicator: item for item in result.signals}
    assert by_name["alt"].observed_direction == "rising"
    assert by_name["alt"].disease_attention_direction == "rising"
    assert by_name["alb"].observed_direction == "falling"
    assert by_name["alb"].disease_attention_direction == "falling"


def test_three_observation_rule_uses_all_values_and_does_not_take_recent_window():
    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {"visit_date": "2020-01-01", "indicators": [{"name": "ALT", "value": 10, "unit": "U/L"}]},
            {"visit_date": "2020-06-01", "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}]},
            {"visit_date": "2021-01-01", "indicators": [{"name": "ALT", "value": 15, "unit": "U/L"}]},
            {"visit_date": "2021-06-01", "indicators": [{"name": "ALT", "value": 30, "unit": "U/L"}]},
        ],
    )
    signal = next(item for item in result.signals if item.indicator == "alt")
    assert signal.observation_count == 4
    assert signal.first_value == 10
    assert signal.latest_value == 30
    assert signal.absolute_change == 20
    assert "persistent_direction" not in signal.reason_codes


def test_ad_cdr_is_stage_related_observation_and_ptau_aliases_are_not_merged():
    assert canonicalize_indicator("ad", "plasma_nfl")[0] == "nfl"
    assert canonicalize_indicator("ad", "plasma_ptau217")[0] == "p-tau217"
    assert canonicalize_indicator("ad", "ptau181")[0] is None
    result = interpret_observation_signals(
        dataset="ad",
        visits=[
            {"visit_date": "2024-01-01", "indicators": [{"name": "CDR", "value": 0.5, "unit": "分"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "CDR", "value": 1, "unit": "分"}]},
            {"visit_date": "2024-12-31", "indicators": [{"name": "CDR", "value": 1, "unit": "分"}]},
        ],
    )
    signal = next(item for item in result.signals if item.indicator == "cdr")
    assert signal.attention_level == "attention"
    assert any("阶段相关" in text for text in signal.limitations)
```

- [ ] **Step 2: Run RED**

Run:

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "fatty_liver_alt or three_observation or ad_cdr" -q
```

Expected: FAIL because the interpreter functions do not exist.

- [ ] **Step 3: Implement explicit configuration and observation extraction**

Define immutable mappings for:

```python
FATTY_LIVER_SIGNAL_CONFIG = {
    "alt": ("谷丙转氨酶", "rising"), "ast": ("谷草转氨酶", "rising"),
    "ggt": ("γ-谷氨酰转肽酶", "rising"), "tbil": ("总胆红素", "rising"),
    "alb": ("白蛋白", "falling"), "hba1c": ("糖化血红蛋白", "rising"),
    "waist": ("腰围", "rising"), "plt": ("血小板计数", "falling"),
    "afp": ("甲胎蛋白", "rising"), "bmi": ("体质指数", "rising"),
}
AD_SIGNAL_CONFIG = {
    "mmse": ("简易精神状态检查", "falling"), "moca": ("蒙特利尔认知评估", "falling"),
    "cdr": ("临床痴呆评定", "rising"), "nfl": ("神经丝轻链", "rising"),
    "p-tau217": ("磷酸化 tau217", "rising"), "aβ42/aβ40": ("β淀粉样蛋白 42/40 比值", "falling"),
}
```

Use exact lower-case aliases only for the approved mappings (`plasma_nfl`, `plasma_ptau217`, `abeta_ratio`). Preserve `ptau181` as unsupported for signal canonicalization. Parse dates through existing `sort_visits`; ignore missing/non-finite values for effective count while appending stable limitation codes. Compute first/last, delta, relative delta (null when first is zero), span days, overall direction and persistent-direction only when every adjacent valid pair follows the same direction.

Emit `attention` only when count >= 3 and overall direction matches configured direction. Emit `none`/omitted otherwise. Do not use an invented magnitude threshold.

- [ ] **Step 4: Run GREEN**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "fatty_liver_alt or three_observation or ad_cdr" -q
```

Expected: PASS.

### Task 3: 接入正式标准、单位安全校验与 provenance

**Files:**
- Modify: `backend/app/services/longitudinal_signal_interpreter.py`
- Modify: `backend/tests/test_longitudinal_signal_interpreter.py`
- Read only: `backend/app/services/standard_resolver.py`, `backend/app/services/longitudinal_evidence.py`

**Interfaces:**
- `interpret_observation_signals(..., standard_sources=...)` consumes resolver/evidence snapshots; it does not query or mutate the database.
- Internal `_resolve_reference_state(signal, sources, context) -> ReferenceInterpretation` returns status, rule/version IDs, applicability hash and limitation codes.

- [ ] **Step 1: Write failing tests for standard and unit degradation**

```python
def test_formal_reference_hit_records_version_rule_and_priority():
    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 35, "unit": "U/L"}]},
            {"visit_date": "2024-12-31", "indicators": [{"name": "ALT", "value": 60, "unit": "U/L"}]},
        ],
        standard_sources=[{"source_type": "reference_range", "indicator": "ALT", "unit": "U/L", "lower": 7, "upper": 40, "standard_version_id": 3, "standard_rule_id": 2, "applicability_hash": "a"}],
    )
    signal = result.signals[0]
    assert signal.reference_status == "above_range"
    assert signal.reference_version_id == 3
    assert signal.reference_rule_id == 2
    assert signal.attention_level == "priority"


@pytest.mark.parametrize("units,expected", [
    ([None, None, None], "unit_missing"),
    (["U/L", "mg/L", "U/L"], "unit_conflict"),
    (["IU/L", "IU/L", "IU/L"], "unsupported_unit"),
])
def test_unit_problem_never_emits_range_abnormality(units, expected):
    result = interpret_observation_signals(
        dataset="fatty_liver",
        visits=[
            {"visit_date": f"2024-0{i+1}-01", "indicators": [{"name": "ALT", "value": value, "unit": unit}]}
            for i, (value, unit) in enumerate(zip([20, 35, 60], units))
        ],
        standard_sources=[{"source_type": "reference_range", "indicator": "ALT", "unit": "U/L", "lower": 7, "upper": 40, "standard_version_id": 3, "standard_rule_id": 2}],
    )
    signal = result.signals[0] if result.signals else result.omitted_indicators[0]
    assert expected in (signal.reason_codes if hasattr(signal, "reason_codes") else signal["reason_codes"])
    assert getattr(signal, "reference_status", None) not in {"above_range", "below_range"}


def test_ad_evidence_only_standard_allows_direction_but_not_above_below():
    result = interpret_observation_signals(
        dataset="ad",
        visits=[
            {"visit_date": "2024-01-01", "indicators": [{"name": "MMSE", "value": 28, "unit": "分"}]},
            {"visit_date": "2024-06-01", "indicators": [{"name": "MMSE", "value": 25, "unit": "分"}]},
            {"visit_date": "2024-12-31", "indicators": [{"name": "MMSE", "value": 22, "unit": "分"}]},
        ],
        standard_sources=[{"source_type": "standard_evidence", "indicator": "MMSE", "unit": "分", "standard_version_id": 4, "standard_rule_id": 28, "machine_actionability": "evidence-only"}],
    )
    signal = result.signals[0]
    assert signal.observed_direction == "falling"
    assert signal.reference_status in {"reference_not_applicable", "reference_unavailable"}
    assert signal.reference_status not in {"above_range", "below_range"}
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "formal_reference or unit_problem or evidence_only" -q
```

Expected: FAIL because standards and units are not evaluated.

- [ ] **Step 3: Implement standard snapshot matching**

Match sources by exact canonical/name-en alias after canonicalization. Accept only `source_type=reference_range` with `machine_actionability=calculable` (or legacy source without the field) for above/within/below evaluation. Select the source matching the observed unit and applicable sex/context; do not average competing rules. For evidence-only, unmatched, conflict or missing standard, return `reference_unavailable`/`reference_not_applicable` and retain standard provenance without abnormal status.

Implement explicit unit rules for current project units only: ALT/AST/GGT `U/L`, TBIL `μmol/L`, ALB `g/L`, HbA1c `%`, WAIST `cm`, BMI `kg/m²`, PLT `10⁹/L`, MMSE/MoCA/CDR `分`. No implicit conversion is allowed. Missing unit yields `unit_missing`; mixed units yield `unit_conflict`; a uniform unknown unit yields `unsupported_unit`. A unit problem blocks range classification; mixed units also omits the key signal because values cannot be safely compared.

Populate provenance only with safe fields: canonical indicator, source type, standard version/rule IDs, applicability hash, actionability and unit decision. Never include paths, raw exceptions or patient labels.

- [ ] **Step 4: Run GREEN and standard resolver regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "formal_reference or unit_problem or evidence_only" -q
python -m pytest backend/tests/test_standard_resolver.py backend/tests/test_longitudinal_evidence.py backend/tests/test_standard_validation.py -q
```

Expected: all pass.

### Task 4: 实现模型 feature 映射，但不执行模型

**Files:**
- Modify: `backend/app/services/longitudinal_signal_interpreter.py`
- Modify: `backend/tests/test_longitudinal_signal_interpreter.py`

**Interfaces:**
- `map_signal_model_features(canonical_indicator: str, *, raw_indicator: str, outcome_status: ModelRuntimeStatus | None, feature_names: Sequence[str] | None) -> tuple[bool, list[str], list[str]]`

- [ ] **Step 1: Write failing tests**

```python
def test_available_outcome_maps_raw_indicator_to_real_derived_features_without_predict():
    status = SimpleNamespace(status="available", task="fatty_liver.pre_cirrhosis_to_progression")
    used, features, reasons = map_signal_model_features(
        "alt", raw_indicator="alt", outcome_status=status,
        feature_names=["alt.first", "alt.last", "alt.delta", "sex"],
    )
    assert used is True
    assert features == ["alt.delta", "alt.first", "alt.last"]
    assert reasons == []


def test_unavailable_or_unmapped_outcome_never_claims_model_use():
    unavailable = SimpleNamespace(status="missing")
    assert map_signal_model_features("alt", raw_indicator="alt", outcome_status=unavailable, feature_names=["alt.last"])[0] is False
    available = SimpleNamespace(status="available")
    used, _, reasons = map_signal_model_features("cdr", raw_indicator="cdr", outcome_status=available, feature_names=["mmse.last"])
    assert used is False
    assert "feature_not_used" in reasons
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "available_outcome or unavailable_or_unmapped" -q
```

Expected: FAIL because feature mapping is not implemented.

- [ ] **Step 3: Implement exact feature-prefix mapping**

Use the raw input indicator prefix (`plasma_nfl` and `plasma_ptau217` must retain those prefixes) and match only names equal to `<raw_indicator>.` prefix. Sort matched feature names for deterministic output. If status is not `available`, return `used=False`, no feature names and `model_unavailable`; if available with no match, return `feature_not_used`. Every signal receives `model_contribution=None` and `model_contribution_status="not_supported"` (or `unavailable` when model state itself is unavailable). Never import or call a model object.

- [ ] **Step 4: Run GREEN and no-predict contract test**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "available_outcome or unavailable_or_unmapped" -q
python -m pytest backend/tests/test_longitudinal_prediction_contract.py -q
```

Expected: PASS; tests must fail if a future implementation calls `predict`/`predict_proba`.

### Task 5: 完成稳定排序、reason code 和解释器纯函数回归

**Files:**
- Modify: `backend/app/services/longitudinal_signal_interpreter.py`
- Modify: `backend/tests/test_longitudinal_signal_interpreter.py`

**Interfaces:**
- `interpret_observation_signals` returns deterministic `SignalInterpretationResult` with `signals` containing only `attention`/`priority` and `omitted_indicators` carrying non-signals.

- [ ] **Step 1: Write failing tests**

```python
def test_priority_precedes_attention_and_ties_use_canonical_order():
    result = interpret_observation_signals(dataset="fatty_liver", visits=_three_visit_case_with_alt_alb_plt(), standard_sources=_fatty_sources())
    assert [item.indicator for item in result.signals[:3]] == ["alt", "alb", "plt"]


def test_repeat_calculation_is_byte_identical_and_no_three_signal_padding():
    visits = [{"visit_date": "2024-01-01", "indicators": [{"name": "ALT", "value": 20, "unit": "U/L"}]}, {"visit_date": "2024-06-01", "indicators": [{"name": "ALT", "value": 21, "unit": "U/L"}]}, {"visit_date": "2024-12-31", "indicators": [{"name": "ALT", "value": 22, "unit": "U/L"}]}]
    first = interpret_observation_signals(dataset="fatty_liver", visits=visits).model_dump(mode="json")
    second = interpret_observation_signals(dataset="fatty_liver", visits=visits).model_dump(mode="json")
    assert first == second
    assert len(first["signals"]) == 1
    assert first["summary"]["signal_count"] == 1
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -k "priority_precedes or repeat_calculation" -q
```

Expected: FAIL until ranking and summary are implemented.

- [ ] **Step 3: Implement deterministic ranking and reason ordering**

Use this key, with no model score:

```python
(-level_rank[signal.attention_level], -reference_abnormal_rank(signal.reference_status), -abs(relative_change or 0), canonical_order.get(signal.indicator, 10_000), signal.indicator)
```

Use a fixed reason ordering beginning with data sufficiency/quality, then direction, then reference, then model state, then contribution state. Include `directional_change` for a matching overall direction, `persistent_direction` only when all adjacent changes match, `latest_above_reference`/`latest_below_reference` for formal range hits, and `contribution_unavailable` on every emitted signal. Add `summary.signal_count`, `summary.omitted_count`, and a safe human-readable summary code; do not pad to three signals.

- [ ] **Step 4: Run GREEN and all interpreter tests**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py -q
```

Expected: PASS.

### Task 6: 接入 longitudinal prediction v2

**Files:**
- Modify: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:**
- `run_longitudinal_prediction` calls `interpret_observation_signals` after `observation`, route and `outcome_status` are known.
- It passes the selected registry entry metadata feature names when available; no model execution is added.

- [ ] **Step 1: Write failing integration tests**

```python
def test_prediction_v2_contains_signals_when_outcome_is_unavailable():
    result = run_longitudinal_prediction(
        {"baseline_stage": None},
        _three_alt_visits(), FATTY_LIVER_ADAPTER, {},
    )
    assert result.progression_signals.schema_version == "longitudinal_signal_interpretation.v1"
    assert result.progression_signals.signals[0].used_by_outcome_model is False
    assert "model_unavailable" in result.progression_signals.signals[0].reason_codes


def test_prediction_signal_does_not_change_outcome_score(monkeypatch):
    # Reuse the existing available-entry fixture and assert score remains 0.75.
    result = _run_prediction_with_available_entry(monkeypatch)
    assert result.outcome_prediction.risk_score == 0.75
    assert result.progression_signals.signals[0].model_contribution is None
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_prediction_contract.py -k "contains_signals or does_not_change_outcome_score" -q
```

Expected: FAIL because prediction does not populate `progression_signals`.

- [ ] **Step 3: Wire the interpreter without changing model inference**

For a selected route, pass `outcome_status` and the selected entry metadata feature names; for a non-selected route pass the disabled routing status and no feature names. Build safe standard source snapshots at the existing operator boundary and attach them to the prediction input without embedding DB objects. Preserve `evidence` and warnings. Do not call `predict`, `predict_proba`, `load_model_registry`, or any LLM from the interpreter.

- [ ] **Step 4: Run GREEN and longitudinal prediction regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_trend_prediction.py -q
```

Expected: PASS; outcome score, stage status, trend status and legacy observation fields remain unchanged.

### Task 7: 接入报告渲染和历史 v1 兼容

**Files:**
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`

**Interfaces:**
- `render_longitudinal_markdown` reads `prediction.progression_signals` only for the key signal section.
- Historical v1 payloads with no `progression_signals` render a stable compatibility message and are not recalculated.

- [ ] **Step 1: Write failing renderer tests**

```python
def test_report_renders_structured_signal_reasons_in_chinese():
    prediction = _v2_prediction_with_signals([
        {"indicator": "alt", "display_name": "谷丙转氨酶", "first_value": 20, "latest_value": 60, "absolute_change": 40, "relative_change": 2.0, "observation_count": 3, "observed_direction": "rising", "disease_attention_direction": "rising", "reference_status": "above_range", "attention_level": "priority", "reason_codes": ["directional_change", "latest_above_reference"], "used_by_outcome_model": False, "model_feature_names": [], "model_contribution_status": "unavailable", "model_contribution": None, "provenance": {"standard_version_id": 3, "standard_rule_id": 2}, "limitations": []}
    ])
    content = render_longitudinal_markdown(prediction)
    assert "谷丙转氨酶" in content
    assert "持续朝关注方向变化" in content or "上升" in content
    assert "最新值高于适用参考范围" in content
    assert "暂无可靠的个体模型贡献信息" in content


def test_report_does_not_pad_missing_signals_and_v1_still_renders():
    content = render_longitudinal_markdown(_v2_prediction_with_signals([]))
    assert "当前没有足够的关键进展信号" in content
    assert "progression_signal" not in content
    assert "纵向进展预测报告" in render_longitudinal_markdown(_prediction())
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_report_generator.py -k "structured_signal or pad_missing" -q
```

Expected: FAIL because renderer still renders trend importance/technical placeholders instead of structured signals.

- [ ] **Step 3: Implement fixed Chinese reason mapping**

Add a renderer-only mapping:

```python
REASON_TEXT = {
    "directional_change": "总体变化方向符合该疾病的关注方向",
    "persistent_direction": "多次观察均朝同一方向变化",
    "latest_above_reference": "最新值高于适用参考范围",
    "latest_below_reference": "最新值低于适用参考范围",
    "reference_unavailable": "当前没有可用的正式参考范围",
    "reference_not_applicable": "现有标准仅作证据参考，未进行数值异常判断",
    "unit_missing": "缺少单位，未进行范围判断",
    "unit_conflict": "单位不一致，无法安全比较",
    "unsupported_unit": "单位不受当前标准支持",
    "insufficient_observations": "有效观察次数不足三次",
    "model_unavailable": "本次没有可用的 outcome 模型",
    "feature_not_used": "该指标未进入本次 outcome 模型特征",
    "contribution_unavailable": "暂无可靠的个体模型贡献信息",
}
```

Render facts, reference interpretation, attention level and model-use/contribution status separately. CDR limitations must include the stage-related caveat. Keep existing model status lines, evidence sources, v1 normalization and safe error behavior. Do not render internal `progression_signal`, `likely_rising` or `direction_only` as new signal conclusions.

- [ ] **Step 4: Run GREEN and report regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_longitudinal_pdf_contract.py -q
```

Expected: PASS; historical v1 remains renderable and v2 has the new section.

### Task 8: 完成 API 边界、双疾病真实数据 smoke 和安全回归

**Files:**
- Modify: `backend/app/api/operator.py` only if the existing evidence snapshot must pass an additional safe field into the generator.
- Create: `.tmp/p006-<timestamp>/fatty-liver-signal-smoke.json`
- Create: `.tmp/p006-<timestamp>/ad-signal-smoke.json`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`

**Interfaces:**
- Existing operator route remains the sole place that loads reference evidence and model registry.
- Smoke output contains no patient labels, absolute paths, database URLs or traceback.

- [ ] **Step 1: Write failing end-to-end/security tests**

```python
def test_ad_mmse_moca_signals_survive_without_outcome_model():
    result = run_longitudinal_prediction({"baseline_stage": "mci"}, _three_ad_visits(), AD_ADAPTER, {})
    names = {item.indicator for item in result.progression_signals.signals}
    assert {"mmse", "moca"}.issubset(names)
    assert all(item.used_by_outcome_model is False for item in result.progression_signals.signals)


def test_signal_provenance_and_limitations_do_not_leak_sensitive_values():
    result = run_longitudinal_prediction({"baseline_stage": None}, _three_alt_visits(), FATTY_LIVER_ADAPTER, {})
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    for secret in ("postgresql://", "password", "Traceback", r"C:\\Users\\", "P001"):
        assert secret not in serialized
```

- [ ] **Step 2: Run RED**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_end_to_end.py -k "ad_mmse_moca or provenance_and_limitations" -q
```

Expected: FAIL until end-to-end signal data is wired and sanitized.

- [ ] **Step 3: Implement route wiring only where necessary**

Pass the existing safe reference source dictionaries to prediction/generator integration. Do not add database queries to the interpreter. Keep old source persistence and old route untouched. Ensure outcome unavailable, stage missing and trend missing still produce signals.

- [ ] **Step 4: Generate deterministic smoke outputs**

Use existing `data/generated/longitudinal_300/visits.csv` and `data/generated/ad_longitudinal_300/visits.csv`; select deterministic rows with at least three valid observations for ALT/ALB/PLT and MMSE/MoCA. Use a new `.tmp/p006-YYYYMMDD-HHMMSS` directory. Serialize only signal facts, standard status/provenance, model-use status, contribution status and limitations; omit patient IDs and paths. Include one fatty-liver case with formal ALT/ALB standard hits, one PLT direction-only case, and one AD case demonstrating MMSE/MoCA direction plus NfL/p-tau217 insufficient observations.

- [ ] **Step 5: Run focused and security regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_longitudinal_signal_interpreter.py backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_evidence.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_safe_stream.py backend/tests/test_security_contracts.py -q
rg -n "postgresql://|password|Traceback|C:\\Users\\|P001|progression_signal" .tmp/p006-*
```

Expected: all focused tests pass; the smoke scan returns no sensitive data and no new report use of `progression_signal`.

### Task 9: 分层回归、范围检查并记录路线图证据

**Files:**
- Modify only after all tests pass: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`

- [ ] **Step 1: Run P0-02/P0-03/P0-04/P0-05 and legacy regressions**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest backend/tests/test_standard_resolver.py backend/tests/test_standard_validation.py backend/tests/test_standard_lifecycle.py backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_model_training.py backend/tests/test_longitudinal_model_evaluation.py backend/tests/test_longitudinal_model_audit.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_model_release.py backend/tests/test_longitudinal_task_routing.py backend/tests/test_progression_engine.py backend/tests/test_progression_api.py -q
node --test frontend/tests/progression-ui-contract.test.mjs
```

Expected: all relevant regressions pass; legacy progression output and endpoint remain unchanged.

- [ ] **Step 2: Run the required fast full-suite evidence command**

```powershell
$env:PYTHONPATH='backend;.'
python -m pytest -q --maxfail=1
```

If the first failure is the known `.superpowers/sdd` cleanup contract or a known slow research Monte Carlo test, record the exact command/output and do not claim the full suite passed. Do not delete `.superpowers/sdd` or other directories to hide failures.

- [ ] **Step 3: Verify scope and immutable production assets**

```powershell
git diff --check
git status --short
git diff --name-only
Get-ChildItem backend/app/ml_models -File | Sort-Object Name | ForEach-Object {
  [pscustomobject]@{ name = $_.Name; sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower() }
} | ConvertTo-Json
git diff -- backend/app/ml_models database backend/alembic frontend
```

Expected: no production model, DB schema/migration or frontend changes; only approved P0-06 service/schema/report/tests/docs changes appear.

- [ ] **Step 4: Record actual P0-06 verification in the roadmap**

Only after focused tests, layered regressions, smoke, scope checks and the full-suite result are recorded, update the P0-06 section with:

- design and plan paths;
- actual test commands and pass/fail totals;
- real indicator mapping and standard coverage findings;
- `.tmp/p006-*` smoke paths and contents;
- confirmation that CDR is stage-related observation only;
- confirmation that model contribution remains unavailable/null;
- confirmation that production models, DB schema/migrations, frontend and old progression API were unchanged;
- any known full-suite failure or timeout with exact evidence.

Do not mark P0-06 complete if any required focused or layered gate is incomplete.

## Completion Gate

- `progression_signals` is strict, deterministic and present in new v2 results; v1 remains renderable.
- Fatty-liver and AD canonical mappings match actual data and approved standard indicators; p-tau subtypes are not merged.
- At least three effective observations are required, and all effective observations are used.
- ALT/ALB/PLT/MMSE/MoCA/CDR and available biomarker cases have correct disease-specific direction semantics.
- Formal standard abnormality is emitted only from approved calculable resolver output with version/rule provenance.
- Missing/conflicting/unsupported units and absent/evidence-only standards degrade safely without above/below claims.
- Outcome model use is based only on available status plus exact metadata feature prefixes; no prediction call decides signal importance.
- `model_contribution` is always null with an accurate unavailable/not-supported status.
- Report renders concrete Chinese reasons, does not expose `progression_signal`, and does not pad to three signals.
- Outcome/stage/trend failures do not erase observation signals.
- Sensitive values are absent from signal payload, provenance, limitations, reports and smoke outputs.
- P0-04/P0-05 models, database schema/migrations, frontend and legacy progression engine/API are unchanged.
- Focused tests, layered regressions, smoke, `git diff --check`, scope checks and full-suite evidence are recorded accurately.
