# P0-03 无未来泄漏固定窗口训练数据集 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本项目明确采用单 Agent 内联执行，不使用 subagent-driven-development、双 Agent 或交叉 Agent 评审。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为脂肪肝和 AD 建立一条独立、只读、可审计的固定 365 天训练数据制作链路，只用 `as_of` 当日及以前至少 3 次的全部历史访视，并把真实训练行、全量审计和合成数据严格分离。

**Architecture:** 新增版本化 Pydantic 数据集契约和独立 dataset builder；builder 先从 `case_records` 重建患者、严格校验身份和日期，再按疾病 adapter 判断当前任务状态与下一事件，最后只把截断后的历史传给特征函数。独立 exporter 负责确定性 JSONL、manifest 和 SHA-256，CLI 默认仅在显式只读事务中输出匿名 JSON 摘要，只有指定一个尚不存在的本地目录时才导出文件。

**Tech Stack:** Python 3、Pydantic v2、SQLAlchemy 2、PostgreSQL JSONB、pytest、标准库 `hashlib/json/datetime/statistics/tempfile/unicodedata`、现有 `disease_progression` adapter 与 `longitudinal_features`。

## Global Constraints

- 全程单 Agent，不派生子 Agent，不执行双 Agent 或交叉 Agent 评审。
- 不把 `AI_COLLABORATION.md` 的双 Agent 流程作为前置条件。
- 不自行创建 worktree；实施时继续使用当前工作区，除非项目所有者另行授权。
- 严格 TDD：每个生产行为先添加目标测试并确认失败，再写最少生产代码，再运行通过测试。
- 不修改 frontend；本任务无 UI 工作，不需要读取或修改 `docs/DESIGN_SPEC.md`。
- 不修改 P0-02 已发布标准、规则、版本、projection、数据库 revision/head 或正式数据库业务数据。
- 不训练模型，不生成 joblib、模型 metadata、registry 记录或生产模型 artifact。
- 不修改线上纵向预测响应 schema、当前预测服务或报告模板。
- 不删除现有真实或合成病例；正式训练文件只能包含 `is_synthetic=false` 的明确阳性/阴性行。
- 不修改旧 `DiseaseProgressionAdapter.outcome_label()` 和 `stage_label()` 的已存在语义；P0-03 新标签在独立模块实现。
- 不让 `scripts/train_longitudinal_models.py` 或 `scripts/train_progression_model.py` 成为 P0-03 的数据来源；二者在本任务保持兼容和可运行。
- 固定窗口必须是 `(as_of, as_of+365天]`；第 365 天算阳性，`as_of` 当天事件只用于判断当前状态。
- 每名患者至少 3 次有效访视；从第 3 次开始生成候选，每条样本使用截至 `as_of` 的全部历史，不固定只取 3 次。
- 医学指标局部缺失允许继续；`source_dataset`、`patient_label`、`visit_date`、`is_synthetic` 缺失或无效时停止整个构建。
- 同一 `(source_dataset, patient_label, visit_date)` 出现重复记录时停止整个构建，不自动合并。
- 未明确的标签使用 `insufficient_observation`，必须保留审计，不得默认为阴性，也不得交给大模型补写。
- AD 目标事件只使用 `dementia_date`；不得自行增加 `mci_date` 或用未来 MMSE、MoCA、CDR、生化指标替代标签。
- 默认 CLI 只读、不导出文件、不显示患者标识；显式导出也不得写业务数据库。
- 所有日期按自然日处理，不引入时区推断；输入只接受现有 ISO date/ISO datetime 形式并归一为 `YYYY-MM-DD`。

---

## File Map

### Create

- `backend/app/schemas/longitudinal_dataset.py`：`longitudinal_fixed_window_dataset.v1` 严格 schema、四种标签状态和计数一致性校验。
- `backend/app/services/longitudinal_dataset.py`：患者重建、必需字段校验、稳定 group ID、阶段/目标/标签状态机和样本组装。
- `backend/app/services/longitudinal_dataset_export.py`：稳定 JSONL、manifest、内容哈希和原子目录导出。
- `backend/tests/test_longitudinal_dataset_schema.py`：schema 隔离和状态一致性测试。
- `backend/tests/test_longitudinal_dataset_validation.py`：身份、日期、同日重复、metadata 冲突和 group ID 测试。
- `backend/tests/test_longitudinal_dataset_labels.py`：双疾病事件与 365 天边界测试。
- `backend/tests/test_longitudinal_dataset_builder.py`：前缀、观察不足、真实/合成隔离、审计统计和泄漏防护测试。
- `backend/tests/test_longitudinal_dataset_export.py`：稳定排序、哈希、文件集合和不覆盖测试。
- `scripts/build_longitudinal_dataset.py`：默认只读匿名摘要 CLI 和显式本地导出入口。
- `scripts/tests/test_build_longitudinal_dataset.py`：只读事务、stdout、退出码、敏感信息和无训练副作用测试。

### Modify

- `backend/app/services/longitudinal_features.py`：保留旧接口，新增只针对 P0-03 的真实时间历史特征函数。
- `backend/tests/test_longitudinal_features.py`：新增真实天数斜率、最近变化、均值/极值和未来访视隔离测试。
- `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`：全部验收完成后记录 P0-03 状态和真实验证证据。

### Read Only / Must Not Modify

- `scripts/train_longitudinal_models.py`
- `scripts/train_progression_model.py`
- `scripts/tests/test_train_longitudinal_models.py`
- `scripts/tests/test_train_progression_model.py`
- `backend/app/services/disease_progression.py`
- `backend/app/services/longitudinal_readiness.py`
- `backend/app/schemas/longitudinal_readiness.py`
- `scripts/check_longitudinal_readiness.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/**`
- `backend/app/schemas/longitudinal_report.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/services/longitudinal_model_registry.py`
- `frontend/**`

---

### Task 1: Define the strict fixed-window dataset schema

**Files:**
- Create: `backend/app/schemas/longitudinal_dataset.py`
- Create: `backend/tests/test_longitudinal_dataset_schema.py`

**Interfaces:**
- Produces: `DATASET_SCHEMA_VERSION = "longitudinal_fixed_window_dataset.v1"`.
- Produces: `LabelStatus = Literal["positive", "negative", "insufficient_observation", "not_applicable"]`.
- Produces: `IndicatorHistoryFeatures`, `HistoricalFeatures`, `SampleIdentity`, `LabelAudit`, `FixedWindowSample`, `CohortCounts`, `DiseaseDatasetSummary`, `DatasetAuditSummary`.
- `FixedWindowSample.features` is the only future model-input namespace; identity and label evidence remain sibling objects.
- `LabelAudit.training_label` is `1` only for positive, `0` only for negative, and `None` for the other two states.

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/test_longitudinal_dataset_schema.py` with these core tests:

```python
import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_dataset import (
    DATASET_SCHEMA_VERSION,
    FixedWindowSample,
    LabelAudit,
)


def test_label_status_and_training_value_must_agree():
    assert LabelAudit(
        status="positive",
        training_label=1,
        reason_code="target_event_within_window",
        window_start="2024-01-02",
        window_end="2024-12-31",
        target_event="cirrhosis_or_hcc",
        event_type="cirrhosis_date",
        event_date="2024-12-31",
        last_followup_date="2025-01-01",
    ).training_label == 1
    with pytest.raises(ValidationError):
        LabelAudit(
            status="insufficient_observation",
            training_label=0,
            reason_code="followup_ends_before_window",
            window_start="2024-01-02",
            window_end="2024-12-31",
            target_event="dementia",
            last_followup_date="2024-06-01",
        )


def test_sample_requires_three_history_visits_and_isolates_features():
    payload = sample_payload(history_visit_count=3)
    sample = FixedWindowSample.model_validate(payload)
    assert sample.schema_version == DATASET_SCHEMA_VERSION
    assert "patient_label" not in sample.features.model_dump()
    payload["identity"]["history_visit_count"] = 2
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)


def test_schema_rejects_extra_feature_fields():
    payload = sample_payload(history_visit_count=3)
    payload["features"]["final_stage"] = "hcc"
    with pytest.raises(ValidationError):
        FixedWindowSample.model_validate(payload)
```

The test helper `sample_payload()` must build one complete valid sample with:

```python
{
    "schema_version": DATASET_SCHEMA_VERSION,
    "identity": {
        "disease": "fatty_liver",
        "disease_name": "脂肪肝",
        "source_dataset": "longitudinal_300",
        "patient_label": "P001",
        "group_id": "patient.v1." + "a" * 64,
        "is_synthetic": False,
        "as_of": "2024-01-01",
        "current_state": "pre_cirrhosis",
        "target_event": "cirrhosis_or_hcc",
        "history_visit_count": 3,
        "history_start": "2023-01-01",
    },
    "features": {
        "age": 60,
        "sex": "female",
        "visit_count": 3,
        "observation_span_days": 365,
        "days_since_previous_visit": 120,
        "indicators": {},
    },
    "label": {
        "status": "negative",
        "training_label": 0,
        "reason_code": "full_window_observed_without_event",
        "window_start": "2024-01-02",
        "window_end": "2024-12-31",
        "target_event": "cirrhosis_or_hcc",
        "event_type": None,
        "event_date": None,
        "last_followup_date": "2025-01-01",
    },
}
```

- [ ] **Step 2: Run the schema test and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py -q
```

Expected: collection fails because `app.schemas.longitudinal_dataset` does not exist.

- [ ] **Step 3: Implement the strict schema**

Create models with `ConfigDict(extra="forbid")`. Use these exact field shapes:

```python
class IndicatorHistoryFeatures(StrictModel):
    first: float | None
    last: float | None
    minimum: float | None
    maximum: float | None
    mean: float | None
    delta: float | None
    time_slope_per_day: float | None
    recent_delta: float | None
    rises_count: int = Field(ge=0)
    falls_count: int = Field(ge=0)
    n_observations: int = Field(ge=0)
    missing_ratio: float = Field(ge=0, le=1)


class HistoricalFeatures(StrictModel):
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Literal["male", "female"] | None = None
    visit_count: int = Field(ge=3)
    observation_span_days: int = Field(ge=0)
    days_since_previous_visit: int = Field(ge=0)
    indicators: dict[str, IndicatorHistoryFeatures]


DiseaseKey = Literal["fatty_liver", "ad"]
CurrentState = Literal[
    "pre_cirrhosis", "cirrhosis", "hcc", "pre_dementia", "dementia"
]
TargetEvent = Literal["cirrhosis_or_hcc", "hcc", "dementia", "none"]
ReasonCode = Literal[
    "target_already_reached",
    "target_event_within_window",
    "progressed_without_target_date",
    "target_event_after_window",
    "full_window_observed_without_event",
    "followup_ends_before_window",
]


class SampleIdentity(StrictModel):
    disease: DiseaseKey
    disease_name: str = Field(min_length=1)
    source_dataset: str = Field(min_length=1)
    patient_label: str = Field(min_length=1)
    group_id: str = Field(pattern=r"^patient\.v1\.[0-9a-f]{64}$")
    is_synthetic: bool
    source_document: str | None = None
    import_version: str | None = None
    as_of: date
    current_state: CurrentState
    target_event: TargetEvent
    history_visit_count: int = Field(ge=3)
    history_start: date


class LabelAudit(StrictModel):
    status: LabelStatus
    training_label: Literal[0, 1] | None
    reason_code: ReasonCode
    window_start: date
    window_end: date
    target_event: TargetEvent
    event_type: Literal["cirrhosis_date", "hcc_date", "dementia_date"] | None = None
    event_date: date | None = None
    last_followup_date: date


class FixedWindowSample(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"] = DATASET_SCHEMA_VERSION
    identity: SampleIdentity
    features: HistoricalFeatures
    label: LabelAudit


class CohortCounts(StrictModel):
    patient_count: int = Field(ge=0)
    candidate_patient_count: int = Field(ge=0)
    trainable_patient_count: int = Field(ge=0)
    visit_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    positive_count: int = Field(ge=0)
    negative_count: int = Field(ge=0)
    insufficient_observation_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    trainable_count: int = Field(ge=0)
    label_reason_counts: dict[ReasonCode, int]


class DiseaseDatasetSummary(StrictModel):
    disease: DiseaseKey
    disease_name: str
    source_datasets: list[str]
    real: CohortCounts
    synthetic: CohortCounts
    reordered_patient_count: int = Field(ge=0)


class DatasetAuditSummary(StrictModel):
    schema_version: Literal["longitudinal_fixed_window_dataset.v1"] = DATASET_SCHEMA_VERSION
    minimum_visits: Literal[3] = 3
    horizon_days: Literal[365] = 365
    diseases: dict[DiseaseKey, DiseaseDatasetSummary]
```

`LabelAudit` gets an `after` validator enforcing the four status/value combinations. `FixedWindowSample` gets an `after` validator enforcing:

- `identity.history_visit_count == features.visit_count`;
- `identity.target_event == label.target_event`;
- `label.window_start == identity.as_of + 1 day`;
- `label.window_end == identity.as_of + 365 days`.

`LabelAudit` also validates that positive, `target_event_after_window`, and `target_already_reached` rows have both `event_type` and `event_date`, while reasons without a dated event have neither. `CohortCounts` validates:

- the four status counts sum to `candidate_count`;
- positive+negative equals `trainable_count`;
- `sum(label_reason_counts.values()) == candidate_count`;
- `trainable_patient_count <= candidate_patient_count <= patient_count`.

`DiseaseDatasetSummary.source_datasets` is the sorted unique list for that disease. `DatasetAuditSummary` validates that `diseases` has exactly the keys `fatty_liver` and `ad`, and each value's `disease` matches its key.

- [ ] **Step 4: Run schema tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- backend/app/schemas/longitudinal_dataset.py backend/tests/test_longitudinal_dataset_schema.py
git commit -m "feat(dataset): define fixed-window schema"
```

---

### Task 2: Rebuild and validate patient timelines with stable group IDs

**Files:**
- Create: `backend/app/services/longitudinal_dataset.py`
- Create: `backend/tests/test_longitudinal_dataset_validation.py`

**Interfaces:**
- Produces internal frozen dataclasses `TimelineVisit`, `PatientTimeline`, `ValidationAudit` with these fields:

```python
@dataclass(frozen=True)
class TimelineVisit:
    visit_date: date
    indicators: tuple[dict[str, object], ...]
    patient_age: int | None
    sex: Literal["male", "female"] | None
    input_position: int


@dataclass(frozen=True)
class PatientTimeline:
    adapter: DiseaseProgressionAdapter
    source_dataset: str
    patient_label: str
    group_id: str
    is_synthetic: bool
    source_document: str | None
    import_version: str | None
    final_stage: object | None
    event_dates: dict[str, date]
    visits: tuple[TimelineVisit, ...]


@dataclass(frozen=True)
class ValidationAudit:
    input_row_count: int
    patient_count: int
    reordered_patient_count: int
```
- Produces `DatasetValidationError(code: str, details: dict[str, object])`; its string form contains only the stable code, never patient identifiers.
- Produces `stable_group_id(source_dataset: str, patient_label: str) -> str`.
- Produces `rebuild_patient_timelines(rows: Iterable[Mapping[str, object]]) -> tuple[list[PatientTimeline], ValidationAudit]`.
- Consumes rows shaped as `disease_name`, `patient_label`, `indicators`, and `metadata` from Task 7's database loader.

- [ ] **Step 1: Write failing identity and validation tests**

Add fixtures that produce three rows per patient and tests for:

```python
def test_group_id_is_stable_and_source_scoped():
    first = stable_group_id("longitudinal_300", "P001")
    assert first == stable_group_id("longitudinal_300", "P001")
    assert first != stable_group_id("another_dataset", "P001")
    assert first.startswith("patient.v1.")
    assert len(first.removeprefix("patient.v1.")) == 64


@pytest.mark.parametrize("field", ["source_dataset", "visit_date", "is_synthetic"])
def test_missing_required_metadata_fails_whole_build(field):
    rows = patient_rows()
    rows[0]["metadata"].pop(field)
    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)
    assert caught.value.code == f"missing_{field}"
    assert "P001" not in str(caught.value)


def test_missing_medical_indicator_does_not_reject_patient():
    rows = patient_rows()
    rows[1]["indicators"] = []
    patients, _ = rebuild_patient_timelines(rows)
    assert len(patients) == 1
    assert patients[0].visits[1].indicators == ()


def test_duplicate_same_day_visit_fails_instead_of_merging():
    rows = patient_rows()
    rows[2]["metadata"]["visit_date"] = rows[1]["metadata"]["visit_date"]
    with pytest.raises(DatasetValidationError) as caught:
        rebuild_patient_timelines(rows)
    assert caught.value.code == "duplicate_patient_visit_date"


def test_valid_out_of_order_rows_are_sorted_and_audited():
    rows = list(reversed(patient_rows()))
    patients, audit = rebuild_patient_timelines(rows)
    assert [v.visit_date.isoformat() for v in patients[0].visits] == [
        "2023-01-01", "2023-06-01", "2024-01-01"
    ]
    assert audit.reordered_patient_count == 1
```

Also test that empty/whitespace `patient_label`, invalid ISO date, non-boolean `is_synthetic`, conflicting event dates, conflicting final stage, conflicting non-null age/sex, and different diseases under one `(source_dataset, patient_label)` all fail the whole build with stable error codes. A repeated `patient_label` under a different source is deliberately a separate patient and must not fail.

- [ ] **Step 2: Run validation tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_validation.py -q
```

Expected: imports fail because the new service does not exist.

- [ ] **Step 3: Implement normalization and group identity**

Use exact group ID normalization:

```python
def _identity_text(value: object, field: str) -> str:
    text = unicodedata.normalize("NFC", str(value or "").strip())
    if not text:
        raise DatasetValidationError(f"missing_{field}")
    return text


def stable_group_id(source_dataset: str, patient_label: str) -> str:
    source = _identity_text(source_dataset, "source_dataset")
    label = _identity_text(patient_label, "patient_label")
    payload = json.dumps(
        [source, label], ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return f"patient.v1.{hashlib.sha256(payload).hexdigest()}"
```

Do not truncate the SHA-256. Do not include disease in the group payload; a conflicting disease for the same source+label is a validation error.

- [ ] **Step 4: Implement timeline reconstruction and strict checks**

Implementation rules:

1. Require row `metadata` to be an object.
2. Accept disease names only by exact adapter mapping: `脂肪肝 -> FATTY_LIVER_ADAPTER`, `阿尔茨海默病 -> AD_ADAPTER`.
3. Require `source_dataset`, `patient_label`, `visit_date`, and a true Python boolean `is_synthetic`.
4. Normalize visit dates to `date`; invalid or empty dates fail.
5. Normalize `event_dates` to a dictionary of ISO dates; allowed event keys come from that disease adapter only. Invalid date values or unexpected event keys fail.
6. Preserve each visit's indicators, age and sex; medical indicator values may be absent or non-numeric and are handled as missing by the feature layer.
7. Across rows sharing `(source_dataset, patient_label)`, require exact consistency for disease, `is_synthetic`, normalized `event_dates`, `final_stage`, `source_document`, and `import_version`, including consistent absence. Require all non-null normalized age values to agree and all non-null normalized sex values to agree; missing age/sex remains allowed.
8. Normalize a non-integer/out-of-range age or a sex outside `male`/`female` to `None` rather than failing the patient. A demographic field that is null in an earlier visit and appears in a later visit is not backfilled into the earlier prefix; features read only the visits already inside that prefix.
9. Compare original date sequence with sorted sequence to populate `reordered_patient_count`.
10. Reject duplicate natural dates after sorting.
11. Return patients sorted by `(adapter.dataset, source_dataset, patient_label)` and visits sorted by date.

- [ ] **Step 5: Run validation tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_validation.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add -- backend/app/services/longitudinal_dataset.py backend/tests/test_longitudinal_dataset_validation.py
git commit -m "feat(dataset): validate patient timelines"
```

---

### Task 3: Add P0-03 historical features using real visit dates

**Files:**
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/tests/test_longitudinal_features.py`

**Interfaces:**
- Preserves existing `sort_visits`, `build_prefixes`, `summarize_observation`, and `build_feature_vector` behavior for legacy callers.
- Produces `summarize_fixed_window_history(visits: Iterable[dict[str, Any]]) -> dict[str, Any]`.
- New result contains only `visit_count`, `observation_span_days`, `days_since_previous_visit`, and per-indicator numeric histories; it contains no visit dates, event dates, labels, final state or provenance.

- [ ] **Step 1: Write failing real-time feature tests**

Append tests:

```python
def test_fixed_window_history_uses_actual_days_and_full_prefix():
    visits = [
        _visit("2024-01-01", 10),
        _visit("2024-01-11", 20),
        _visit("2024-04-10", 30),
    ]
    result = summarize_fixed_window_history(visits)
    alt = result["indicators"]["alt"]
    assert result["visit_count"] == 3
    assert result["observation_span_days"] == 100
    assert result["days_since_previous_visit"] == 90
    assert alt["first"] == 10
    assert alt["last"] == 30
    assert alt["minimum"] == 10
    assert alt["maximum"] == 30
    assert alt["mean"] == pytest.approx(20)
    assert alt["recent_delta"] == 10
    assert alt["time_slope_per_day"] == pytest.approx(0.16483516484)


def test_fixed_window_history_records_missing_indicator_without_imputation():
    visits = [
        _visit("2024-01-01", 10),
        {"visit_date": "2024-02-01", "indicators": []},
        _visit("2024-03-01", 20),
    ]
    alt = summarize_fixed_window_history(visits)["indicators"]["alt"]
    assert alt["n_observations"] == 2
    assert alt["missing_ratio"] == pytest.approx(1 / 3)


def test_future_visit_cannot_change_an_existing_prefix_features():
    prefix = [_visit("2024-01-01", 10), _visit("2024-02-01", 20), _visit("2024-03-01", 30)]
    before = summarize_fixed_window_history(prefix)
    summarize_fixed_window_history(prefix + [_visit("2025-01-01", 999)])
    assert summarize_fixed_window_history(prefix) == before
```

- [ ] **Step 2: Run new feature tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_features.py -k fixed_window -q
```

Expected: import or name failure because `summarize_fixed_window_history` is missing.

- [ ] **Step 3: Implement the new history summary without changing legacy slope**

For each canonical lower-case indicator name, collect `(days_from_first_visit, value)` and calculate:

```python
{
    "first": values[0],
    "last": values[-1],
    "minimum": min(values),
    "maximum": max(values),
    "mean": statistics.fmean(values),
    "delta": values[-1] - values[0],
    "time_slope_per_day": _time_slope(day_value_pairs),
    "recent_delta": values[-1] - values[-2] if len(values) >= 2 else None,
    "rises_count": sum(a < b for a, b in pairwise(values)),
    "falls_count": sum(a > b for a, b in pairwise(values)),
    "n_observations": len(values),
    "missing_ratio": 1 - len(values) / len(ordered_visits),
}
```

`_time_slope` uses ordinary least squares on actual calendar-day offsets and returns `None` when fewer than two values or zero denominator. Reuse `_as_finite_float`; do not impute missing values. Continue rejecting duplicate canonical indicator names within one visit.

- [ ] **Step 4: Run the complete legacy and new feature suite**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_features.py backend/tests/test_longitudinal_trend_prediction.py -q
```

Expected: all tests pass, proving old feature consumers remain compatible.

- [ ] **Step 5: Commit Task 3**

```powershell
git add -- backend/app/services/longitudinal_features.py backend/tests/test_longitudinal_features.py
git commit -m "feat(dataset): add real-time history features"
```

---

### Task 4: Implement disease-specific current state and 365-day labels

**Files:**
- Modify: `backend/app/services/longitudinal_dataset.py`
- Create: `backend/tests/test_longitudinal_dataset_labels.py`

**Interfaces:**
- Produces frozen `TargetContext(current_state: CurrentState, target_event: TargetEvent)`.
- Produces `resolve_target(patient: PatientTimeline, as_of: date) -> TargetContext`.
- Produces `label_fixed_window(patient: PatientTimeline, as_of: date) -> LabelAudit`; this P0-03 function always uses `HORIZON_DAYS = 365` and does not accept a variable window.
- Uses future event dates and final state only in `LabelAudit`; these values are never passed to the feature function.

- [ ] **Step 1: Write failing shared boundary tests**

Test the exact interval `(as_of, as_of+365]`:

```python
@pytest.mark.parametrize(
    ("event_day", "expected_status"),
    [
        ("2024-01-01", "not_applicable"),
        ("2024-01-02", "positive"),
        ("2024-12-31", "positive"),
        ("2025-01-01", "negative"),
    ],
)
def test_ad_event_boundary(event_day, expected_status):
    patient = ad_patient(dementia_date=event_day, last_visit="2025-02-01")
    assert label_fixed_window(patient, date(2024, 1, 1)).status == expected_status
```

The dates deliberately use leap year 2024: `2024-01-01 + 365 days == 2024-12-31`; this prevents accidentally treating “same calendar date next year” as the window end.

- [ ] **Step 2: Write failing fatty-liver transition tests**

Cover:

```python
def test_fatty_liver_pre_cirrhosis_accepts_cirrhosis_or_direct_hcc():
    cirrhosis = fatty_patient(cirrhosis_date="2024-06-01", hcc_date=None)
    direct_hcc = fatty_patient(cirrhosis_date=None, hcc_date="2024-06-01")
    for patient in (cirrhosis, direct_hcc):
        decision = label_fixed_window(patient, date(2024, 1, 1))
        assert decision.status == "positive"
        assert decision.target_event == "cirrhosis_or_hcc"


def test_fatty_liver_after_cirrhosis_targets_hcc_only():
    patient = fatty_patient(cirrhosis_date="2023-12-01", hcc_date="2024-08-01")
    target = resolve_target(patient, date(2024, 1, 1))
    assert target.current_state == "cirrhosis"
    assert target.target_event == "hcc"
    assert label_fixed_window(patient, date(2024, 1, 1)).status == "positive"


def test_fatty_liver_after_hcc_is_not_applicable():
    patient = fatty_patient(cirrhosis_date="2023-01-01", hcc_date="2023-12-01")
    assert label_fixed_window(patient, date(2024, 1, 1)).status == "not_applicable"
```

- [ ] **Step 3: Write failing observation-evidence and AD tests**

Cover:

- full 365-day follow-up with no target event -> negative with `full_window_observed_without_event`;
- follow-up ending before day 365 and no later event -> `insufficient_observation`;
- explicit target event on day 366 -> negative with `target_event_after_window` even without a day-365 visit;
- fatty final stage `cirrhosis`/`hcc` without required event date -> `insufficient_observation`;
- AD final CDR numeric value `>=1` without `dementia_date` -> `insufficient_observation`;
- AD final CDR `<1`, full follow-up and no event -> negative;
- AD target context before dementia uses `current_state="pre_dementia"`, not a fabricated `normal` or `mci` date;
- future CDR/MMSE/MoCA changes do not alter the decision when `dementia_date`, final CDR and follow-up evidence are unchanged.

- [ ] **Step 4: Run label tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_labels.py -q
```

Expected: failures because target and label functions are missing.

- [ ] **Step 5: Implement target resolution and ordered decision rules**

Use these exact task states:

```text
fatty_liver: pre_cirrhosis -> cirrhosis -> hcc
ad: pre_dementia -> dementia
```

The AD task state is not a claim that AD has only two medical stages. It only names what this dataset can time reliably.

Decision order:

1. Resolve current task state using only event dates `<= as_of`.
2. If already at the task endpoint, return `not_applicable` / `target_already_reached`.
3. Find the earliest eligible target event strictly after `as_of`.
4. If it is `<= as_of + 365 days`, return positive / `target_event_within_window`.
5. If final outcome proves the relevant target eventually occurred but its required event date is missing, return `insufficient_observation` / `progressed_without_target_date`.
6. If a target event exists after day 365, return negative / `target_event_after_window`.
7. If the patient's maximum valid visit date is at least day 365, return negative / `full_window_observed_without_event`.
8. Otherwise return `insufficient_observation` / `followup_ends_before_window`.

Always set:

```python
window_start = as_of + timedelta(days=1)
window_end = as_of + timedelta(days=365)
```

For pre-cirrhosis fatty liver, eligible event types are `cirrhosis_date` and direct `hcc_date`; choose the earliest non-null future event. After cirrhosis, only `hcc_date` is eligible. For AD, only `dementia_date` is eligible. Do not inspect indicator values inside the label function.

- [ ] **Step 6: Run label and validation tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_validation.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add -- backend/app/services/longitudinal_dataset.py backend/tests/test_longitudinal_dataset_labels.py
git commit -m "feat(dataset): label fixed disease windows"
```

---

### Task 5: Assemble prefixes, block leakage, and separate train/audit cohorts

**Files:**
- Modify: `backend/app/services/longitudinal_dataset.py`
- Create: `backend/tests/test_longitudinal_dataset_builder.py`

**Interfaces:**
- Produces frozen `DatasetBuildResult(real_train, real_audit, synthetic_audit, summary)`.
- Produces `assert_feature_namespace_safe(features: Mapping[str, object]) -> None`.
- Produces `build_fixed_window_dataset(rows: Iterable[Mapping[str, object]]) -> DatasetBuildResult`; the fixed P0-03 constants are `MINIMUM_VISITS = 3` and `HORIZON_DAYS = 365` and cannot be overridden by callers.
- Consumes Task 2 timelines, Task 3 `summarize_fixed_window_history`, Task 4 label decisions, and Task 1 schemas.

- [ ] **Step 1: Write failing prefix and full-history tests**

```python
def test_six_visits_generate_four_prefixes_using_all_history_to_as_of():
    result = build_fixed_window_dataset(rows_for_patient(visit_count=6))
    audit = result.real_audit
    assert [row.identity.history_visit_count for row in audit] == [3, 4, 5, 6]
    assert [row.identity.as_of.isoformat() for row in audit] == [
        "2023-07-01", "2024-01-01", "2024-07-01", "2025-01-01"
    ]


def test_fewer_than_three_visits_produces_no_candidate_but_remains_in_summary():
    result = build_fixed_window_dataset(rows_for_patient(visit_count=2))
    assert result.real_audit == ()
    assert result.summary.diseases["fatty_liver"].real.patient_count == 1
    assert result.summary.diseases["fatty_liver"].real.visit_count == 2
```

- [ ] **Step 2: Write failing future-leakage tests**

Create two otherwise identical patient timelines. Give the second one a fifth future visit with ALT=999 and future CDR=3. Keep its patient-level metadata internally consistent across all rows, and hold label evidence constant between the two timelines. Assert the sample at the third `as_of` has byte-equivalent `features` in both builds. Separately add raw `confirmed`, `total_visits`, `visit_index`, and `cohort_group` values to input rows and assert none appears in any output `features` object.

Also directly test:

```python
@pytest.mark.parametrize(
    "forbidden",
    [
        "final_stage", "confirmed", "event_dates", "cirrhosis_date",
        "hcc_date", "dementia_date", "fatty_liver_date", "last_followup_date",
        "lost_to_followup", "total_visits", "visit_index", "cohort_group",
        "outcome_source", "assigned_final_stage", "inferred_stage",
        "source_dataset", "patient_label", "group_id", "is_synthetic",
    ],
)
def test_forbidden_feature_key_aborts_build(forbidden):
    with pytest.raises(DatasetValidationError) as caught:
        assert_feature_namespace_safe({forbidden: "leak"})
    assert caught.value.code == "forbidden_feature_field"
```

Test recursive nested keys and indicator names such as an indicator named `dementia_date`.

- [ ] **Step 3: Write failing cohort and audit-count tests**

Cover:

- one real positive, one real negative, one real insufficient and one real not-applicable candidate;
- `real_train` contains only the positive and negative rows;
- `real_audit` contains all four real candidates;
- a synthetic positive appears only in `synthetic_audit`, never in `real_train` or `real_audit`;
- summary retains all four label counts after train-row filtering;
- all prefixes of one patient share one group ID;
- equal patient labels from different sources have different group IDs and separate patient counts;
- order of input database rows does not change output sample order.

- [ ] **Step 4: Run builder tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_builder.py -q
```

Expected: failures because assembly and leakage guard are missing.

- [ ] **Step 5: Implement feature construction from prefix-only visits**

For every `build_prefixes(visits, minimum_visits=MINIMUM_VISITS)` result:

1. Convert only `prefix["visits"]` to the input of `summarize_fixed_window_history`.
2. Read age and sex from the latest non-null value inside that prefix only; never from a later visit or patient-wide fallback.
3. Build `HistoricalFeatures` from the history summary.
4. Run `assert_feature_namespace_safe(features.model_dump(mode="json"))`.
5. Call `label_fixed_window` separately with the complete patient timeline.
6. Assemble `FixedWindowSample(identity=..., features=..., label=...)`.

Use a case-insensitive normalized forbidden-key set. Dynamic indicator names are checked with the same set. The strict `HistoricalFeatures` schema is the primary allow list; the recursive forbidden scanner is the second safety layer.

- [ ] **Step 6: Implement deterministic cohort routing and summary**

Sorting key:

```python
(sample.identity.disease, sample.identity.source_dataset,
 sample.identity.patient_label, sample.identity.as_of)
```

Routing:

```python
if sample.identity.is_synthetic:
    synthetic_audit.append(sample)
else:
    real_audit.append(sample)
    if sample.label.status in {"positive", "negative"}:
        real_train.append(sample)
```

Build per-disease real/synthetic `CohortCounts` from all reconstructed patients and all candidates, not from filtered training rows. `candidate_patient_count` counts distinct patients with at least one audit sample; `trainable_patient_count` counts distinct patients with at least one positive/negative sample; `label_reason_counts` counts every audit reason before training-row filtering. Populate the disease's sorted unique `source_datasets`. Include Task 2's reordered-patient count in `DiseaseDatasetSummary`. Do not expose individual identifiers in `DatasetAuditSummary`.

- [ ] **Step 7: Run all dataset unit tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_features.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 5**

```powershell
git add -- backend/app/services/longitudinal_dataset.py backend/tests/test_longitudinal_dataset_builder.py
git commit -m "feat(dataset): assemble leak-free cohorts"
```

---

### Task 6: Export deterministic JSONL and manifest without overwriting

**Files:**
- Create: `backend/app/services/longitudinal_dataset_export.py`
- Create: `backend/tests/test_longitudinal_dataset_export.py`

**Interfaces:**
- Produces `canonical_json(value: object) -> str` using sorted keys and compact separators.
- Produces `sha256_file(path: Path) -> str`.
- Produces `export_fixed_window_dataset(result: DatasetBuildResult, output_dir: Path, *, generated_at: datetime, code_version: str) -> dict[str, object]`.
- Output root must not exist; export writes a temporary sibling directory and renames it to the requested root only after every file and hash succeeds.

- [ ] **Step 1: Write failing file-layout and filtering tests**

```python
def test_export_writes_expected_files_per_disease(tmp_path):
    target = tmp_path / "dataset"
    manifest = export_fixed_window_dataset(
        mixed_result(), target,
        generated_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        code_version="test-revision",
    )
    for disease in ("fatty_liver", "ad"):
        disease_dir = target / disease
        assert {p.name for p in disease_dir.iterdir()} == {
            "real_train.jsonl", "real_audit.jsonl", "synthetic_audit.jsonl"
        }
    assert (target / "manifest.json").is_file()
    assert all(
        json.loads(line)["identity"]["is_synthetic"] is False
        for line in (target / "fatty_liver" / "real_train.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert manifest["schema_version"] == "longitudinal_fixed_window_dataset.v1"
```

- [ ] **Step 2: Write failing determinism and no-overwrite tests**

Export the same result into two different fresh directories with different `generated_at` values. Assert:

- each corresponding JSONL file has identical bytes and SHA-256;
- `manifest["data_content_sha256"]` is identical;
- `generated_at` differs and is excluded from `data_content_sha256`;
- rows are in the Task 5 stable order;
- exporting to an existing target raises `FileExistsError` and leaves every existing byte unchanged;
- an injected write failure leaves no final target directory.

- [ ] **Step 3: Run exporter tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_export.py -q
```

Expected: import failure because exporter does not exist.

- [ ] **Step 4: Implement canonical JSONL and stable hashes**

Use:

```python
def canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
```

Each non-empty JSONL line is `canonical_json(sample.model_dump(mode="json")) + "\n"`. Empty cohorts produce an empty UTF-8 file. File hashes are calculated after closing all files.

The stable `data_content_sha256` hashes a canonical object containing only:

```python
{
    "schema_version": DATASET_SCHEMA_VERSION,
    "minimum_visits": 3,
    "horizon_days": 365,
    "summary": result.summary.model_dump(mode="json"),
    "files": {relative_path: sha256 for relative_path, sha256 in sorted(file_hashes.items())},
}
```

Manifest also records `generated_at`, `code_version`, window notation `(as_of,as_of+365d]`, explicit source separation, counts and per-file hashes, but runtime fields do not enter the stable content hash.

- [ ] **Step 5: Implement safe directory publication**

1. Resolve the requested absolute target and require its parent to exist.
2. Fail immediately if target exists.
3. Create a temporary sibling with `tempfile.mkdtemp(dir=target.parent, prefix=f".{target.name}.")`.
4. Write all files below that temporary directory.
5. Rename the completed temporary directory to target.
6. On exception, remove only the exact temporary directory created by this call; never recursively delete the requested parent or workspace root.

- [ ] **Step 6: Run exporter and dataset tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_dataset_builder.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 6**

```powershell
git add -- backend/app/services/longitudinal_dataset_export.py backend/tests/test_longitudinal_dataset_export.py
git commit -m "feat(dataset): export deterministic audit files"
```

---

### Task 7: Add the default read-only audit CLI and database loader

**Files:**
- Modify: `backend/app/services/longitudinal_dataset.py`
- Create: `scripts/build_longitudinal_dataset.py`
- Create: `scripts/tests/test_build_longitudinal_dataset.py`

**Interfaces:**
- Produces `load_case_rows(connection) -> list[dict[str, object]]`; it issues `SET TRANSACTION READ ONLY` before its single SELECT.
- CLI produces `build_error_payload(code: str) -> dict[str, object]`, `run_build(*, database_url: str, output_dir: Path | None, generated_at: datetime | None = None) -> dict[str, object]`, and `main(argv: list[str] | None = None) -> int`.
- CLI accepts only optional `--output-dir PATH`; database URL comes from existing settings and is never printed.
- Exit `0` means a valid audit/build completed; exit `2` means database, validation, output or runtime failure. Label counts do not change the exit code because the command's job is to report them, not judge model quality.

- [ ] **Step 1: Write failing read-only loader tests**

Use a fake connection capturing SQL and returning mapping rows. Assert:

```python
rows = load_case_rows(connection)
assert connection.statements[0].strip().upper() == "SET TRANSACTION READ ONLY"
assert "FROM case_records" in connection.statements[1]
assert "confirmed" not in connection.statements[1].lower()
assert set(rows[0]) == {"record_id", "disease_name", "patient_label", "indicators", "metadata"}
```

The SELECT is exactly scoped to the two exact disease names and orders by disease id then case record id. It must not load reference-standard tables or modify readiness.

- [ ] **Step 2: Write failing CLI behavior tests**

Load the script with `importlib.util` like the existing readiness CLI tests. Cover:

- default `main([])` calls `run_build(output_dir=None)` and prints exactly one JSON document;
- default mode creates no file and reports `mode="audit_only"`;
- `--output-dir <fresh>` passes that path and reports `mode="exported"`;
- database error produces `database_unavailable`, exit 2, no URL/password/traceback;
- `DatasetValidationError` produces its stable code and count-only details, never patient label;
- existing output directory produces `output_exists`, exit 2, no overwrite;
- stdout encoding is reconfigured to UTF-8 when supported;
- source contains none of `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `ALTER`, `joblib`, `.fit(`, or model artifact paths.

- [ ] **Step 3: Run loader and CLI tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_build_longitudinal_dataset.py -q
```

Expected: script import fails or required functions are missing.

- [ ] **Step 4: Implement the read-only database loader**

The service query is:

```sql
SET TRANSACTION READ ONLY
```

followed by a parameterized SELECT equivalent to:

```sql
SELECT cr.id AS record_id, d.name AS disease_name, cr.patient_label,
       cr.indicators, cr.metadata
FROM case_records cr
JOIN diseases d ON d.id = cr.disease_id
WHERE d.name IN (:fatty_liver_name, :ad_name)
ORDER BY d.id, cr.id
```

Return plain dictionaries. Do not select `cr.confirmed`.

- [ ] **Step 5: Implement transaction ownership and anonymous JSON**

`run_build` must:

1. create the SQLAlchemy engine;
2. open a connection and begin a transaction;
3. call `load_case_rows(connection)`;
4. call `build_fixed_window_dataset(rows)`;
5. if `output_dir` is provided, call exporter with the current Git revision obtained by a side-effect-free helper; if unavailable, use `"unknown"`;
6. always roll back the database transaction and dispose the engine;
7. return only `schema_version`, `generated_at`, `mode`, optional output path, stable data hash when exported, and `summary.model_dump(mode="json")`.

The default summary includes counts by disease and real/synthetic cohort but no `patient_label`, group ID, event date, source document or per-row content.

`main` catches SQLAlchemy errors, `DatasetValidationError`, `FileExistsError`, `OSError`, and a final sanitized runtime category. `_print_json` uses `ensure_ascii=False, sort_keys=True`. No exception message goes to stdout.

- [ ] **Step 6: Run CLI and service tests**

Run:

```powershell
python -m pytest scripts/tests/test_build_longitudinal_dataset.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Run old script compatibility tests**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_models.py scripts/tests/test_train_progression_model.py scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: all existing tests pass unchanged.

- [ ] **Step 8: Commit Task 7**

```powershell
git add -- backend/app/services/longitudinal_dataset.py scripts/build_longitudinal_dataset.py scripts/tests/test_build_longitudinal_dataset.py
git commit -m "feat(dataset): add read-only audit CLI"
```

---

### Task 8: Verify the real database, regressions, scope, and roadmap evidence

**Files:**
- Modify: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`

**Interfaces:**
- No new runtime interface.
- This task records actual evidence only after all code and real-data checks pass.

- [ ] **Step 1: Run the complete focused P0-03 suite**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_features.py scripts/tests/test_build_longitudinal_dataset.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run related longitudinal regressions**

Run:

```powershell
python -m pytest scripts/tests/test_train_longitudinal_models.py scripts/tests/test_train_progression_model.py scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_longitudinal_trend_prediction.py -q
```

Expected: all tests pass. If an unrelated pre-existing failure appears, stop and report it instead of changing unrelated production code.

- [ ] **Step 3: Run the existing readiness baseline unchanged**

Run:

```powershell
python scripts/check_longitudinal_readiness.py
$readinessExit = $LASTEXITCODE
Write-Output "READINESS_EXIT=$readinessExit"
```

Expected: valid `longitudinal_readiness.v1` JSON, revision/head `0012`, and the already known P0-01/P0-02 baseline. P0-03 must not alter this published response schema or its legacy prefix semantics.

- [ ] **Step 4: Run the new default real-data audit twice without exporting**

Run without creating local summary files:

```powershell
$auditOne = python scripts/build_longitudinal_dataset.py
$firstExit = $LASTEXITCODE
$auditTwo = python scripts/build_longitudinal_dataset.py
$secondExit = $LASTEXITCODE
$payloadOne = $auditOne | ConvertFrom-Json
$payloadTwo = $auditTwo | ConvertFrom-Json
Write-Output "P003_EXIT_1=$firstExit P003_EXIT_2=$secondExit"
```

Expected:

- both exit codes are 0;
- both captured outputs parse as JSON;
- `schema_version == "longitudinal_fixed_window_dataset.v1"`;
- `mode == "audit_only"`;
- both diseases exist;
- no data files, joblib files, registry rows or database writes are produced;
- ignoring `generated_at`, the two summaries are identical;
- real and synthetic counts are separately visible;
- all four label states are present as numeric counts.

- [ ] **Step 5: Compare actual statistics with the design-time estimate**

Record actual current-database values. The design-time check suggested, but did not hard-code:

```text
fatty_liver real trainable: 200 rows, 59 positive, 141 negative, 106 patients with trainable rows
ad real trainable: 165 rows, 56 positive, 109 negative, 88 patients with trainable rows
```

The completed builder's values are authoritative. If they differ, inspect label reason counts and prefix rules; do not change code merely to force these estimates. Any unexplained difference blocks completion and requires a test-backed diagnosis.

- [ ] **Step 6: Verify an explicit export in a disposable fresh directory**

Create the exact temporary parent and fresh verification path, then run:

```powershell
New-Item -ItemType Directory -Force -Path '.tmp' | Out-Null
python scripts/build_longitudinal_dataset.py --output-dir .tmp/p003-fixed-window-verification
$exportExit = $LASTEXITCODE
Write-Output "P003_EXPORT_EXIT=$exportExit"
```

Expected:

- exit 0;
- both disease directories contain exactly the three JSONL files;
- root contains `manifest.json`;
- real train files contain only real positive/negative rows;
- audit counts match the default summary;
- no model artifact exists;
- a second command to the same directory exits 2 with `output_exists` and preserves hashes.

After verification, resolve `.tmp/p003-fixed-window-verification`, verify its absolute path starts with the resolved workspace `.tmp` path plus a directory separator, then remove only that exact directory with `Remove-Item -LiteralPath ... -Recurse`. Do not remove `.tmp` or any broader directory.

- [ ] **Step 7: Check stdout and files for sensitive or forbidden content**

Search the anonymous summary for:

```powershell
python scripts/build_longitudinal_dataset.py 2>$null | Select-String -Pattern 'postgresql://|password|Traceback|patient_label|group_id|P001|A001|source_document'
```

Expected: no matches.

Inspect representative `features` objects from the disposable export before removing it and assert no forbidden key from Task 5 exists. Event dates may exist only under the sibling `label` audit object, never under `features`.

- [ ] **Step 8: Verify the change scope**

Run:

```powershell
git diff 6306291 --name-only
git diff --check
git status --short
```

Expected runtime changes are limited to:

```text
backend/app/schemas/longitudinal_dataset.py
backend/app/services/longitudinal_dataset.py
backend/app/services/longitudinal_dataset_export.py
backend/app/services/longitudinal_features.py
scripts/build_longitudinal_dataset.py
```

plus the new/modified P0-03 tests and documentation. No frontend, migration, database model, P0-02 standard, readiness schema, prediction schema, registry, report template or old training script may appear.

- [ ] **Step 9: Update the P0-03 roadmap card with actual evidence**

Immediately below `### P0-03：构建无未来泄漏的固定窗口训练数据集`, add:

```markdown
**状态**：`completed`

**Task-ID**：`longitudinal-prefix-dataset-001`

**设计文档**：`docs/superpowers/specs/2026-08-26-fixed-window-longitudinal-dataset-design.md`

**实施计划**：`docs/superpowers/plans/2026-08-26-fixed-window-longitudinal-dataset.md`

**验证记录**：`python scripts/build_longitudinal_dataset.py` 已以只读方式重复生成双疾病匿名审计摘要；记录实际真实/合成患者、候选前缀、阳性、阴性、观察不足、不适用和可训练行数量。显式临时导出验证了稳定 JSONL、manifest、SHA-256、真实/合成隔离和禁止字段防护。P0-03 新增测试、旧训练脚本回归、readiness 回归和相关纵向测试通过；未训练模型、未写数据库、未生成生产 artifact。
```

把“记录实际……”替换成此次命令的真实数字，不复制设计时估计。

- [ ] **Step 10: Commit Task 8 documentation**

```powershell
git add -- docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md
git commit -m "docs(dataset): record P0-03 verification"
```

- [ ] **Step 11: Run the final clean verification**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_dataset_schema.py backend/tests/test_longitudinal_dataset_validation.py backend/tests/test_longitudinal_dataset_labels.py backend/tests/test_longitudinal_dataset_builder.py backend/tests/test_longitudinal_dataset_export.py backend/tests/test_longitudinal_features.py scripts/tests/test_build_longitudinal_dataset.py scripts/tests/test_train_longitudinal_models.py scripts/tests/test_train_progression_model.py scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_longitudinal_end_to_end.py backend/tests/test_longitudinal_trend_prediction.py -q
python scripts/build_longitudinal_dataset.py
$datasetExit = $LASTEXITCODE
git status --short
```

Expected:

- all selected tests pass;
- new CLI exits 0 with valid anonymous JSON;
- no export occurs without `--output-dir`;
- Git working tree is clean.

---

## Completion Gate

Do not claim P0-03 complete until all conditions are true:

- The new dataset contract is `longitudinal_fixed_window_dataset.v1` and rejects extra feature fields.
- Every candidate has at least 3 visits and uses every valid historical visit through `as_of`.
- No visit, indicator or CDR after `as_of` can change that sample's features.
- The interval is exactly `(as_of, as_of+365天]` and boundary tests pass.
- Fatty liver correctly changes target from cirrhosis/direct HCC to HCC after cirrhosis.
- AD only uses `dementia_date`; future/final CDR cannot become the event label or feature.
- Positive, negative, insufficient observation and not applicable states are mutually exclusive and auditable.
- Only explicit positive/negative real rows enter `real_train.jsonl`; unknown/insufficient counts remain in audit and summary.
- Synthetic data is never present in the formal training file.
- Same patient prefixes share a source-scoped stable group ID; different source datasets never merge equal labels.
- Missing medical indicators are represented as missing, while missing identity/date/provenance or duplicate same-day visits fail safely.
- Features pass both strict allow-schema validation and recursive forbidden-field checks.
- Default CLI is read-only, anonymous, does not export, does not train and does not write the database.
- Explicit exports are deterministic, hashed, non-overwriting and contain no model artifact.
- P0-01 readiness, P0-02 standards, old training scripts, online prediction/report contracts, database schema and frontend remain unchanged.
- Focused tests, related regressions, real database audit and disposable export verification have all passed with actual evidence recorded.
