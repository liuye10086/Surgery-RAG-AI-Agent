# AI 操作者完整报告文档 Implementation Plan
> 执行状态（2026-09-07）：仓库任务已完成并通过本机隔离验收，实际任务状态、命令与证据见 [执行记录](../notes/2026-09-07-operator-report-execution-log.md)。下文保留批准时计划；建议的逐项提交被用户要求的最终一次提交取代。涉及目标 Linux 容量及生产发布的检查仍在部署窗口执行。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在既有输入、模型、证据基础上生成完整、中文可读、历史固定的 11 章报告，统一网页和 PDF。

**Architecture:** 推理阶段产生逐任务输入审计，纯文档构建器将快照、预测、审计和证据投影为 ReportDocument v1，确定性渲染为 Markdown。独立的指纹 v2 保护文档与原有生成结果，旧报告保留原读路径。

**Tech Stack:** 现有 Pydantic、Python、SQLAlchemy/Alembic、Vue 3/TypeScript、Markdown/bleach、Playwright、pytest/Vitest。

## Global Constraints

- 继承总计划 `2026-09-07-operator-complete-report-implementation.md` 的全部 Global Constraints；以批准设计为验收依据。
- 固定 11 章的确定性报告；不调用 LLM 创造事实或医学结论。
- 不重做第 1～5 项，不重新训练模型，不替换两份项目已批准标准，不重算或补写旧报告。
- 年龄明确为病例录入的年龄，不根据报告打开时间自动增长。
- 旧指纹无版本或 v1 继续按原算法验证；未知新版本失败关闭。
- UI 修改前完整读取 `docs/DESIGN_SPEC.md`。
- 模块 A 不独立开启新写入路径；通过模块 B 的 worker 发布。

## A1：强类型文档、固定上下文与跨模块结果契约

**Files:**
- Create: `backend/app/schemas/report_document.py`
- Create: `backend/tests/test_report_document_schema.py`
- Create: `backend/tests/report_document_fixtures.py`

**Interfaces:** 提供下列类型给 A2～A6、B1～B6。所有 schema 都 `extra=forbid`，数值拒绝 NaN/Infinity；只对已有业务严格约束的 age 等使用 strict 字段，不对合法 JSON 日期字符串启用全局 strict。

- [ ] **Step 1：先写结构与边界测试。**

```python
from datetime import date
import pytest
from pydantic import ValidationError
from app.schemas.report_document import ReportIdentity, ReportDocument

def test_identity_uses_last_visit_anchor_and_recorded_age():
    identity = ReportIdentity(
        report_id=17, batch_id="11111111-1111-4111-8111-111111111111",
        anonymous_case_code="CASE-ABCD-2345", disease_code="fatty_liver",
        disease_name="脂肪肝", age=62, sex="female",
        baseline_stage="pre_cirrhosis", baseline_stage_label="未肝硬化阶段",
        created_at="2026-09-07T00:00:00Z", anchor_date="2025-09-07",
        horizon_days=365, prediction_end_date="2026-09-07",
    )
    assert identity.anchor_date == date(2025, 9, 7)
    with pytest.raises(ValidationError):
        ReportIdentity.model_validate({**identity.model_dump(), "age": True})
    with pytest.raises(ValidationError):
        ReportIdentity.model_validate({**identity.model_dump(), "prediction_end_date": "2027-09-07"})
```

- [ ] **Step 2：运行失败。** backend：`python -m pytest tests/test_report_document_schema.py -q`。首次应因 schema 不存在失败。
- [ ] **Step 3：实现以下完整 schema。** 引用现有 runtime status；不修改 prediction v3 字段。

```python
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.schemas.longitudinal_model_registry import ModelRuntimeStatus

Sha = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

class StrictReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class PinnedStandard(StrictReportModel):
    standard_id: int
    version_id: int
    document_id: int
    document_sha256: Sha
    version_sha256: Sha

class PinnedEvidenceToken(StrictReportModel):
    standard: PinnedStandard
    dataset_release_id: str | None
    data_content_sha256: Sha | None
    eligibility_config_hash: Sha
    similarity_config_hash: Sha
    logical_dataset: str | None
    reference_status: Literal["reference_query_failed", "reference_index_stale"] | None = None

class IndicatorLabel(StrictReportModel):
    code: str
    label: str
    allowed_units: list[str]
    context_requirements: list[str]

class ReportGenerationContext(StrictReportModel):
    schema_version: Literal["report_generation_context.v1"] = "report_generation_context.v1"
    disease_code: Literal["fatty_liver", "ad"]
    release_set_id: str
    release_set_sha256: Sha
    data_release_id: str
    dataset_manifest_sha256: Sha
    split_sha256: Sha
    indicator_catalog_sha256: Sha
    indicator_labels: list[IndicatorLabel]
    minimum_visits: int = Field(ge=1, le=10)
    minimum_signal_observations: int = Field(ge=1)
    evidence_token: PinnedEvidenceToken
    template_version: Literal["operator_report.zh-CN.v1"] = "operator_report.zh-CN.v1"

class ReportIdentity(StrictReportModel):
    report_id: int = Field(gt=0)
    batch_id: UUID
    anonymous_case_code: str | None
    disease_code: Literal["fatty_liver", "ad"]
    disease_name: str
    age: int = Field(ge=0, le=120, strict=True)
    sex: Literal["male", "female"]
    baseline_stage: str
    baseline_stage_label: str
    created_at: datetime
    anchor_date: date
    horizon_days: int = Field(ge=1)
    prediction_end_date: date

    @model_validator(mode="after")
    def validate_identity(self):
        import re
        if self.anonymous_case_code is not None and not re.fullmatch(
            r"CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", self.anonymous_case_code
        ):
            raise ValueError("invalid_anonymous_case_code")
        if self.created_at.tzinfo is None:
            raise ValueError("report_time_requires_timezone")
        if self.prediction_end_date != self.anchor_date + timedelta(days=self.horizon_days):
            raise ValueError("prediction_anchor_mismatch")
        return self

class InputFieldAudit(StrictReportModel):
    name: str
    state: Literal["present", "allowed_missing", "required_missing", "invalid"]

class InputAudit(StrictReportModel):
    task: str
    fields: list[InputFieldAudit]
    frame_sha256: Sha | None = None
    numeric_imputation: str | None = None
    categorical_imputation: str | None = None
    model_invoked: bool = False
    reason_code: str | None = None

    @model_validator(mode="after")
    def validate_invocation(self):
        if len({f.name for f in self.fields}) != len(self.fields):
            raise ValueError("duplicate_audit_field")
        if self.model_invoked and (
            self.frame_sha256 is None or any(f.state in {"required_missing", "invalid"} for f in self.fields)
        ):
            raise ValueError("invalid_model_invocation_audit")
        return self

class TrainingDisclosure(StrictReportModel):
    synthetic_in_formal_metrics: bool | None
    clinical_validity_claim: bool | None
    production_enabled: bool | None
    training_file_sha256: Sha | None
    composition_note: str

class ModelRunAudit(StrictReportModel):
    task: str
    target_label: str
    horizon_kind: Literal["days", "next_visit"]
    horizon_days: int | None
    runtime: ModelRuntimeStatus
    input_audit: InputAudit
    training: TrainingDisclosure
    score_threshold: float | None = None
    risk_band_rule_version: str | None = None

class QualityIssue(StrictReportModel):
    code: str
    severity: Literal["blocking", "warning", "info"]
    source: Literal["input", "model", "standard", "reference", "observation"]
    task: str | None = None
    visit_index: int | None = Field(default=None, ge=1)
    indicator: str | None = None
    field: str | None = None
    message: str
    impact: str
    action: str

class ReportSummary(StrictReportModel):
    observation_status: Literal["available", "limited"]
    model_input_status: Literal["satisfied", "partial", "unavailable"]
    selected_model_count: int = Field(ge=0)
    invoked_model_count: int = Field(ge=0)
    available_model_count: int = Field(ge=0)
    signal_count: int = Field(ge=0)
    evidence_status: Literal["complete", "partial"]
    limitations: list[str]

class ChartPoint(StrictReportModel):
    visit_date: date
    value: float = Field(strict=True)

class ObservedChart(StrictReportModel):
    indicator: str
    label: str
    unit: str
    points: list[ChartPoint]

class ReportTable(StrictReportModel):
    title: str
    headers: list[str]
    rows: list[list[str]]

    @model_validator(mode="after")
    def same_width(self):
        if not self.headers or any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("report_table_width_mismatch")
        return self

class ReportSection(StrictReportModel):
    number: int = Field(ge=1, le=11)
    title: str
    paragraphs: list[str]
    tables: list[ReportTable]

class EvidenceReference(StrictReportModel):
    evidence_bundle_id: UUID
    evidence_snapshot_sha256: Sha

class ReportDocument(StrictReportModel):
    schema_version: Literal["report_document.v1"] = "report_document.v1"
    template_version: Literal["operator_report.zh-CN.v1"] = "operator_report.zh-CN.v1"
    identity: ReportIdentity
    generation_context: ReportGenerationContext
    summary: ReportSummary
    data_quality: list[QualityIssue]
    model_runs: list[ModelRunAudit]
    evidence: EvidenceReference
    review_items: list[QualityIssue]
    charts: list[ObservedChart]
    sections: list[ReportSection]

    @model_validator(mode="after")
    def same_generation(self):
        if [s.number for s in self.sections] != list(range(1, 12)):
            raise ValueError("report_sections_invalid")
        if self.identity.disease_code != self.generation_context.disease_code:
            raise ValueError("report_disease_mismatch")
        if self.template_version != self.generation_context.template_version:
            raise ValueError("report_template_mismatch")
        return self

class Publication(StrictReportModel):
    content: str
    prediction_result: dict
    sources: list[dict]
    evidence_snapshot: dict
    evidence_snapshot_sha256: Sha
    evidence_status: Literal["complete", "partial"]
    standard_evidence_status: str
    reference_case_status: str
    report_document: ReportDocument
    report_document_sha256: Sha
    generation_fingerprint: Sha
    generation_fingerprint_version: Literal["v2"] = "v2"
```

Publication 中既有 JSON 字段保留存储兼容形状，但 A5 工厂必须用原预测/EvidenceBundle schema 验证后才构造。ReportSection 只含固化纯文本与表格，页面不自行生成业务内容。

- [ ] **Step 4：建立完整可重复夹具。** `report_document_fixtures.py` 提供 `snapshot_payload(disease="fatty_liver")`、`context_payload()`、`document_payload()`；返回普通 JSON。访视从既有 acceptance 样本复制到独立 fixture，禁止修改共享对象。结构夹具 sections 为 1～11 合法节；内容验收由真实 builder 生成，不能用空节证明完整性。

结构夹具的具体内容如下；A3 再添加完整内容夹具 `build_demo_document`：

```python
from app.schemas.report_document import ReportDocument

SECTION_TITLES = [
    '报告摘要', '病例与预测范围', '数据质量与适用性', '已观察到的纵向变化',
    '未来 365 天进展风险', '阶段模型和下一次随访趋势的可用状态', '关键进展信号',
    '参考标准和相似病例', '不确定性与局限性', '人工复核重点', '模型和数据技术附录',
]

def snapshot_payload(disease='fatty_liver'):
    ad = disease == 'ad'
    return {
        'generation_batch_id': '11111111-1111-4111-8111-111111111111',
        'anonymous_case_code': 'CASE-ABCD-2345', 'case_id': 1, 'disease_id': 2 if ad else 1,
        'disease_code': disease, 'disease': '阿尔茨海默病' if ad else '脂肪肝',
        'age': 62, 'sex': 'female', 'baseline_stage': 'mci' if ad else 'pre_cirrhosis',
        'indicator_catalog_version': 'a' * 64,
        'visits': [
            {'visit_date': day, 'visit_index': i, 'visit_context': {}, 'notes': None,
             'indicators': [{'name': 'mmse' if ad else 'alt', 'unit': '分' if ad else 'U/L',
                             'value': float(29-i if ad else 20+i)}]}
            for i, day in enumerate(['2025-01-01', '2025-01-02', '2025-09-07'], 1)
        ],
    }

def context_payload():
    return {
        'disease_code': 'fatty_liver', 'release_set_id': 'fixture-release',
        'release_set_sha256': 'b'*64, 'data_release_id': 'fixture-data',
        'dataset_manifest_sha256': 'c'*64, 'split_sha256': 'd'*64,
        'indicator_catalog_sha256': 'a'*64, 'minimum_visits': 3,
        'minimum_signal_observations': 3,
        'indicator_labels': [{'code':'alt', 'label':'谷丙转氨酶',
                              'allowed_units':['U/L'], 'context_requirements':[]}],
        'evidence_token': {
            'standard': {'standard_id':1, 'version_id':2, 'document_id':3,
                         'document_sha256':'e'*64, 'version_sha256':'f'*64},
            'dataset_release_id':'fixture-reference', 'data_content_sha256':'1'*64,
            'eligibility_config_hash':'2'*64, 'similarity_config_hash':'3'*64,
            'logical_dataset':'fatty_liver',
        },
    }

def document_payload():
    document = ReportDocument(
        identity={
            'report_id':17, 'batch_id':'11111111-1111-4111-8111-111111111111',
            'anonymous_case_code':'CASE-ABCD-2345', 'disease_code':'fatty_liver',
            'disease_name':'脂肪肝', 'age':62, 'sex':'female',
            'baseline_stage':'pre_cirrhosis', 'baseline_stage_label':'未肝硬化阶段',
            'created_at':'2026-09-07T00:00:00Z', 'anchor_date':'2025-09-07',
            'horizon_days':365, 'prediction_end_date':'2026-09-07',
        },
        generation_context=context_payload(),
        summary={'observation_status':'available', 'model_input_status':'unavailable',
                 'selected_model_count':0, 'invoked_model_count':0, 'available_model_count':0,
                 'signal_count':0, 'evidence_status':'complete', 'limitations':[]},
        data_quality=[], model_runs=[], review_items=[], charts=[],
        evidence={'evidence_bundle_id':'22222222-2222-4222-8222-222222222222',
                  'evidence_snapshot_sha256':'4'*64},
        sections=[{'number':i, 'title':title, 'paragraphs':[], 'tables':[]}
                  for i,title in enumerate(SECTION_TITLES,1)],
    )
    return document.model_dump(mode='json')
```
- [ ] **Step 5：补验证并通过。** 覆盖未知版本、额外字段、bool age、坏匿名编号、无时区、重复模型字段、non-finite chart、错列数、缺失/倒序章节、跨病种/模板；`python -m pytest tests/test_report_document_schema.py -q`。建议提交：`feat: define immutable operator report document contract`。

## A2：在真实模型输入边界记录审计

**Files:**
- Create: `backend/app/services/report_input_audit.py`
- Modify: `backend/app/services/longitudinal_features.py`
- Modify: `backend/app/services/longitudinal_prediction.py`
- Test: `backend/tests/test_report_input_audit.py`
- Regression: `backend/tests/test_longitudinal_prediction_contract.py`

**Interfaces:** `AuditedPrediction(prediction: dict, model_runs: list[ModelRunAudit])` dataclass；`run_audited_prediction(snapshot, adapter, suite, *, visits=None) -> AuditedPrediction`。`run_longitudinal_prediction` 与特征构造器新增 keyword-only `audit_collector=None`，旧返回类型不变。生产只使用 snapshot.visits；纯函数测试可显式传 visits，两者同时给必须相同，否则 `audit_visits_mismatch`。

- [ ] **Step 1：写行为测试。** 使用已有严格 suite fixture，并给模型加 spy 检查真实 DataFrame，不能另算一份称作实际输入。

```python
from app.services.disease_progression import AD_ADAPTER
from app.services.report_input_audit import run_audited_prediction
from backend.tests.test_longitudinal_prediction_contract import _complete_ad_suite, _ad_visits

def test_audit_records_every_selected_task_and_actual_model_calls():
    result = run_audited_prediction(
        {"age": 62, "sex": "female", "baseline_stage": "mci"},
        AD_ADAPTER, _complete_ad_suite(bad_mmse=True), visits=_ad_visits(),
    )
    assert len(result.model_runs) == 7
    mmse = next(r for r in result.model_runs if r.task.endswith(".mmse"))
    assert mmse.input_audit.model_invoked is True
    assert mmse.runtime.status != "available"
    assert mmse.input_audit.frame_sha256 is not None
```

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_input_audit.py -q`。
- [ ] **Step 3：实现 collector 与输入哈希。** 在既有 row 逐字段校验处记录状态；校验失败抛出前保存具体 fields 与安全 reason；成功后按同一规范化 row 计算哈希。

```python
import hashlib
import json
from dataclasses import dataclass
from app.schemas.report_document import InputFieldAudit, ModelRunAudit

@dataclass(frozen=True)
class AuditedPrediction:
    prediction: dict
    model_runs: list[ModelRunAudit]

def fingerprint_input_row(names: list[str], values: dict) -> str:
    body = {"schema_version": "model_input_audit.v1", "columns": names,
            "values": [values[name] for name in names]}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def describe_fields(contract, values: dict) -> list[InputFieldAudit]:
    required = set(contract.required_features)
    allowed = set(contract.allowed_missing_features)
    return [InputFieldAudit(name=name, state=(
        "present" if values.get(name) is not None else
        "allowed_missing" if name in allowed and name not in required else "required_missing"
    )) for name in contract.feature_names]
```

collector 方法固定为 `prepared(task, audit)`、`invoking(task)`、`failed(task, code)`、`finalize(suite, prediction) -> list[ModelRunAudit]`。task 隔离各模型；prepared 先保存 fields，成功补 frame_sha；invoking 紧邻 predict/predict_proba 前调用，异常不将 invoked 改回 False。无效数值 fields.state=invalid，不调用哈希编码非有限值。

- [ ] **Step 4：接入所有实际任务。** 修改 `_suite_frame`、`_run_suite_outcome`、`_run_suite_stage`、`_run_suite_trend` 及旧 v2 outcome，向下传 collector；正式 v3 metadata 不走 tiny test-double fallback。outcome 的 InferenceContractError 独立于 prediction_failed 保存。finalize 合并各任务最终 ModelRuntimeStatus；未调用任务仍有 fields 与未调用原因。
- [ ] **Step 5：固化模型说明。** 从每个 metadata 的 audit/calibration/dataset_contract/production_enabled 取 TrainingDisclosure；未知构成写“未记录训练样本构成”，不从文件名猜比例。threshold 保持现有推理行为，记录 `risk_band_rule_version="longitudinal_risk_band.v1"` 与 `_risk_band` 判定顺序 `score>=0.8 / score>=threshold / score>=0.3 / other`，不改变分数或分类。模型插补只记录配置，不编造插补后的值。
- [ ] **Step 6：验证通过。** 覆盖必需缺失 spy=0、允许缺失时列序/None/插补策略、推理异常仍 invoked、非有限值原因、只记录所选结局任务、无备注进入 audit；运行 `python -m pytest tests/test_report_input_audit.py tests/test_longitudinal_prediction_contract.py -q`。建议提交：`feat: capture per-task model input audit for reports`。

## A3：文档构建、数据质量、完整访视与复核

**Depends:** A1、A2、A4、B1。A4 先交付纯渲染与证据投影，再由本任务组装完整报告。

**Files:**
- Create: `backend/app/services/report_document_builder.py`
- Create: `backend/app/services/report_review_items.py`
- Create: `backend/app/services/report_display_labels.py`
- Test: `backend/tests/test_report_document_builder.py`
- Test: `backend/tests/test_report_review_items.py`

**Interfaces:** `build_report_document(report_id: int, created_at: datetime, snapshot: dict, context: ReportGenerationContext, prediction: dict, model_runs: list[ModelRunAudit], evidence: EvidenceBuildResult) -> ReportDocument`；`build_review_items(issues: list[QualityIssue]) -> list[QualityIssue]`。builder 不得调用 DB、网络、当前目录或模型。

- [ ] **Step 1：写完整数据断言。** 在 A1 fixture 文件新增 `build_demo_document(disease="fatty_liver")`：构造有效规范化访视、运行 A2 真实纯函数配 mock suite、构造有效 EvidenceBundle 并统一 batch/disease，再调用真实 builder。证据结构可复用 `backend.tests.test_evidence_bundle_service._bundle()`；AD 使用已有 AD evidence-only 规则夹具，不能仅改 disease_code 冒充另一标准。

```python
from backend.tests.report_document_fixtures import build_demo_document

def test_every_saved_visit_and_demographic_is_in_report():
    document = build_demo_document()
    assert document.identity.age == 62
    section = document.sections[3]
    assert sum(len(t.rows) for t in section.tables if t.title.startswith("访视")) >= 3
    identity_text = str(document.sections[1].model_dump())
    for text in ("62", "女", "CASE-ABCD-2345", "未肝硬化阶段"):
        assert text in identity_text

def test_review_items_have_location_impact_and_action():
    document = build_demo_document("ad")
    for item in document.review_items:
        assert item.message and item.impact and item.action
        assert item.task or item.indicator or item.field or item.source == "reference"
```

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_document_builder.py tests/test_report_review_items.py -q`。
- [ ] **Step 3：实现比较与日期规则。** 观察值来自 snapshot/原 observation，不重算信号。以下函数放 builder 并直接测试：

```python
from datetime import date
import math

def relative_change_text(first, ratio, unit_state: str) -> str:
    if unit_state != "consistent":
        return "单位不可比较，未计算"
    if first == 0:
        return "首次值为 0，不计算百分比"
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not math.isfinite(ratio):
        return "未记录"
    return f"{ratio * 100:+.2f}%"

def calendar_positions(dates: list[str]) -> list[float]:
    values = [date.fromisoformat(value).toordinal() for value in dates]
    span = max(values) - min(values)
    if span == 0:
        return [0.0 for value in values]
    return [(value - min(values)) / span for value in values]
```

图语义保存 ChartPoint 完整日期/值。单位 consistent、值有限且点数达到固化 minimum_signal_observations 才写 charts。bool/null/string 不得隐式变成有效观察；日期函数只接受非空已校验序列。

- [ ] **Step 4：构建完整访视。** 第 4 节先全指标总览，再每次访视一张表；每表列 snapshot 指标并集，未测写“本次未记录”，不填 0/前向填充。同次原值/单位/notes 不并到其他访视。source_type/is_baseline/method/specimen/device/assay 等逐字段展示；AD 补量表/语言/教育/校正，脂肪肝补影像类型。False 和教育年限 0 不视为缺失；自由文本以纯文本交给 renderer。
- [ ] **Step 5：集中生成质量问题。** field 使用快照路径，task 使用模型任务代码；omitted 指标读原信号结果的原因。

| 条件 | code / severity | message | impact | action |
|---|---|---|---|---|
| 必需字段缺失 | required_feature_missing / warning | 模型缺少必需输入 | 对应任务未参与 | 核对并补录所列字段后生成新报告 |
| 允许字段缺失 | allowed_feature_missing / info | 部分输入未记录 | 按配置由模型管道处理 | 核对原始资料及插补策略 |
| 已调用任务失败 | prediction_failed / warning | 对应模型未生成有效结果 | 不展示该任务预测 | 核查输入并在服务恢复后生成新报告 |
| 标准条件 missing | standard_context_missing / warning | 标准适用条件未完整记录 | 不能进行该项标准数值解释 | 核对所列访视检测或量表条件 |
| 标准条件 mismatched | standard_not_applicable / info | 当前资料不符合标准适用条件 | 仅保留证据与不适用说明 | 核对检测条件与选用标准 |
| 单位问题 | observation_unit_not_comparable / warning | 观察单位不能安全比较 | 不计算变化、不绘制连线 | 核对原始检验单位 |
| 观察不足 | insufficient_observations / info | 指标有效观察次数不足 | 仅展示已记录数值 | 按实际随访补充观察 |
| 无合格参考 | no_eligible_cases / info | 当前无合格参考病例 | 不提供相似病例对照 | 结合正式标准人工复核 |
| 可比性不足 | insufficient_comparability / info | 合格病例可比信息不足 | 未提供相似病例对照 | 核对可比较的检测条件 |
| 参考查询/索引故障 | 原稳定 code / warning | 参考病例服务暂不可用 | 本次为部分证据 | 服务恢复后按需生成新报告 |

未知 reason 主文写“对应结果不可用，原因未识别”，附录保留原 code；不把异常字符串当说明。合成/校准限制进入 summary/limitations，不自动转换为治疗建议。

```python
from app.schemas.report_document import QualityIssue

def build_review_items(issues: list[QualityIssue]) -> list[QualityIssue]:
    rank = {"blocking": 0, "warning": 1, "info": 2}
    unique = {}
    for item in issues:
        key = (item.code, item.task, item.visit_index, item.indicator, item.field)
        unique.setdefault(key, item)
    return sorted(unique.values(), key=lambda x: (
        rank[x.severity], x.visit_index or 0, x.indicator or "", x.task or "", x.code,
    ))
```

- [ ] **Step 6：组装其余章节。** 第 1/2/3/5/6/7/9/10/11 节逐列满足设计 §7；保留现有 11 个中文标题。模型输入满足/已调用/成功分别统计，不从顶层 trend.status 推断全部趋势成功。第 7 节直接消费 progression_signals，不凑数；第 8 节接 A4 投影函数。无临床有效性声明始终在摘要说明。
- [ ] **Step 7：验证通过。** 增加首值 0、年龄 0、False 校正、零信号、单趋势失败、所有模型未参与、AD 缺条件、30 指标纯展示压力夹具；运行 A3 两文件与 `tests/test_longitudinal_report_acceptance.py`。建议提交：`feat: build complete longitudinal report and review checklist`。

## A4：统一中文正文与证据展示

**Depends:** A1。测试先使用 A1 结构夹具与现有证据夹具，不能依赖尚未实施的 A3 builder。

**Files:**
- Create: `backend/app/services/report_document_renderer.py`
- Create: `backend/app/services/report_evidence_presentation.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Test: `backend/tests/test_report_document_renderer.py`
- Test: `backend/tests/test_report_evidence_presentation.py`

**Interfaces:** `render_report_document(document: ReportDocument) -> str`；`build_evidence_section(bundle: EvidenceBundle) -> ReportSection`。A3 直接赋第 8 节，不在新正文上正则替换；旧 merge 为旧测试/兼容保留，worker 不调用。

- [ ] **Step 1：写一致性与注入测试。**

```python
from app.services.report_document_renderer import render_report_document, escape_text
from backend.tests.report_document_fixtures import document_payload
from app.schemas.report_document import ReportDocument

def test_report_has_eleven_sections_and_escaped_notes():
    text = render_report_document(ReportDocument.model_validate(document_payload()))
    assert sum(line.startswith("## ") for line in text.splitlines()) == 11
    assert "## 8. 参考标准和相似病例" in text
    assert "<script>" not in escape_text("<script>alert(1)</script>")
    assert "\\|" in escape_text("a|b")
    assert "\n## " not in escape_text("备注\n## 伪造章节")
```

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_document_renderer.py tests/test_report_evidence_presentation.py -q`。
- [ ] **Step 3：实现通用确定性渲染。**

```python
import html
import re
from app.schemas.report_document import ReportDocument

def escape_text(value: str) -> str:
    text = html.escape(str(value), quote=True)
    text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", text)

def render_report_document(document: ReportDocument) -> str:
    checked = ReportDocument.model_validate(document.model_dump(mode="json"))
    lines = ["# 纵向进展预测报告", ""]
    for section in checked.sections:
        lines.extend([f"## {section.number}. {escape_text(section.title)}", ""])
        for paragraph in section.paragraphs:
            lines.extend([escape_text(paragraph), ""])
        for table in section.tables:
            lines.extend([f"### {escape_text(table.title)}", ""])
            lines.append("| " + " | ".join(map(escape_text, table.headers)) + " |")
            lines.append("| " + " | ".join("---" for value in table.headers) + " |")
            for row in table.rows:
                lines.append("| " + " | ".join(map(escape_text, row)) + " |")
            lines.append("")
    return "\n".join(lines)
```

不要再次对 escape_text 结果转义，否则显示实体原文。保留网页 DOMPurify 与 PDF bleach。

- [ ] **Step 4：实现标准展示节。** 文档表包含 title/issuer/publication_date/external_identifier/source_url（安全文本）、version_label/approved_at/effective_from/parser_version；规则表包含中文 status、unit、边界及包容性、latest_value/numeric_interpretation、conditions.missing/mismatched、source 定位和 raw_text。空值“未记录”。
- [ ] **Step 5：实现参考病例全部展示。** pool_statistics 四计数与 exclusion_counts；每例匿名编号、年龄段/性别/阶段、as_of、访视数/跨度、coverage/conditional_similarity/ranking_score、所有 dimensions/comparisons、outcome_status/source/reliability。source_trace 不直接输出任意字典，只使用既有已批准白名单字段。available/positive/negative/unknown/male/female/rule status 统一中文。coverage/维度为 0～1 可格式化百分比，ranking/conditional 已为 0～100，不能再次乘 100。
- [ ] **Step 6：验证通过。** 用完整 evidence fixtures 对比必需语义行/单元格；非数值规则不产生数值诊断；参考结果附“不代表当前病例将发生相同结局”。运行 A4 两文件和旧生成器测试。建议提交：`feat: unify saved report text and evidence presentation`。

## A5：文档迁移、发布内容与指纹 v2

**Files:**
- Create: `backend/alembic/versions/0023_operator_report_document.py`
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/schemas/operator.py`
- Modify: `backend/app/services/report_integrity.py`
- Create: `backend/app/services/report_publication.py`
- Modify: `backend/app/api/operator.py`
- Modify: `database/schema.sql`
- Test: `backend/tests/test_report_document_integrity.py`
- Test: `backend/tests/test_operator_report_document_migration.py`

**Interfaces:** `verify_report_integrity` 新增 keyword-only `report_document=None, report_document_sha256=None, generation_fingerprint_version=None`；旧参数与算法不变。`build_publication(snapshot, prediction, evidence, document) -> Publication` 不提交数据库，B4 负责唯一发布事务。

- [ ] **Step 1：写版本兼容与篡改测试。**

```python
from app.services.report_publication import hash_report_document
from backend.tests.report_document_fixtures import build_demo_document

def test_document_hash_protects_demographics():
    document = build_demo_document()
    changed = document.model_copy(update={
        "identity": document.identity.model_copy(update={"age": 63})
    })
    assert hash_report_document(changed) != hash_report_document(document)
```

旧指纹增加已知 JSON/expected digest 固定值，从实施前旧实现取一次存 fixture，测试中不能动态算 expected；验证旧 content/snapshot 调整兼容。

- [ ] **Step 2：运行失败。** `python -m pytest tests/test_report_document_integrity.py tests/test_operator_report_document_migration.py -q`。
- [ ] **Step 3：实现 0023。** down_revision=0022；新增 nullable JSONB report_document、String(64) report_document_sha256、String(8) generation_fingerprint_version。用 Alembic op 与 ORM 同步下列约束，不 UPDATE 历史；同步 schema.sql；不加无查询用途的 GIN。

```sql
CHECK (report_document IS NULL OR jsonb_typeof(report_document) = 'object');
CHECK (report_document_sha256 IS NULL OR report_document_sha256 ~ '^[0-9a-f]{64}$');
CHECK (generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2'));
CHECK (generation_fingerprint_version IS DISTINCT FROM 'v2' OR
       (report_document IS NOT NULL AND report_document_sha256 IS NOT NULL
        AND generation_fingerprint IS NOT NULL AND status = 'completed'));
```

- [ ] **Step 4：实现文档哈希与新指纹。** 原 `_normalize` 与 create_generation_fingerprint 输出不改，新增：

```python
import hashlib
import json
from app.schemas.report_document import ReportDocument
from app.services.report_integrity import create_generation_fingerprint

def hash_report_document(document: ReportDocument) -> str:
    payload = document.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def fingerprint_v2(snapshot, prediction, content, evidence, document_sha256):
    body = {"version": "v2", "legacy_payload_sha256":
            create_generation_fingerprint(snapshot, prediction, content, evidence),
            "report_document_sha256": document_sha256}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

工厂顺序：原 prediction schema 验证；EvidenceBundle 验证/hash；核对 batch/disease/report_id、document.evidence hash/id、固定 context；sources=build_sources_projection(bundle)，prediction.evidence.sources 相等；content=render_report_document(document)；生成 doc hash/v2 指纹并返回 Publication。不一致抛安全 report_generation_contract_mismatch。

发布边界额外要求：11 节标题与固定清单完全相符，每节至少有解释段落或非空表格；禁止把 A1 的空节结构夹具发布成完整报告。model_runs 的 task 唯一，runtime.task/input_audit.task 与外层 task 一致；selected/invoked/available 统计必须与逐任务记录一致。为这些不一致分别写拒绝发布测试。

- [ ] **Step 5：接入详情/PDF。** ReportOut 可选字段，列表不带文档大 JSON。get_report/download 传新完整性参数；有 document/v2 但关键字段缺失为 invalid，只有全新字段为空才允许旧路径；未知版本 invalid。PDF invalid 返回 409。只在发布 completed 时写 v2，排队/运行快照使用原输入哈希。
- [ ] **Step 6：验证通过。** 覆盖 document/content/evidence/sources 改动、错批次、v2 丢字段降级、未知版本、旧空文档、case detachment；运行 `python -m pytest tests/test_report_document_integrity.py tests/test_operator_report_document_migration.py tests/test_report_integrity.py tests/test_longitudinal_report_persistence.py tests/test_schema_contracts.py -q`。建议提交：`feat: persist report documents with versioned integrity`。

## A6：网页与 PDF 展示同一保存文档

**Depends:** A5、B5；与 B6 联合验收。

**Files:**
- Create: `frontend/src/types/report-document.ts`
- Create: `frontend/src/components/report/ReportDocumentCharts.vue`
- Create: `frontend/src/utils/report-chart.ts`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/components/LongitudinalReportView.vue`
- Modify: `frontend/src/components/LongitudinalEvidenceSection.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `backend/app/services/pdf_generator.py`
- Modify: `backend/app/templates/report_pdf.html`
- Test: `frontend/src/components/__tests__/ReportDocumentView.spec.ts`
- Test: `frontend/src/utils/__tests__/report-chart.spec.ts`
- Test: `backend/tests/test_report_document_pdf.py`
- Create: `scripts/render_operator_report_visual_cases.py`

**Interfaces:** ReportDetail 增加 `report_document: ReportDocumentV1 | null` 及 hash/version；`generate_pdf` 新增 keyword-only report_document=None，保留旧位置参数。新摘要读 summary、正文读 content、图读 charts；旧报告不重建 document。

- [ ] **Step 1：写失败组件/图/PDF用例。**

```typescript
import { describe, expect, it } from 'vitest'
import { chartCoordinates } from '@/utils/report-chart'

describe('saved report chart', () => {
  it('keeps calendar spacing and rejects missing values', () => {
    const points = chartCoordinates([
      { visit_date: '2025-01-01', value: 1 },
      { visit_date: '2025-01-02', value: 2 },
      { visit_date: '2025-04-11', value: 3 },
    ])
    expect(points[1]!.x - points[0]!.x).toBeCloseTo(3.6)
    expect(() => chartCoordinates([{ visit_date: '2025-01-01', value: null } as any])).toThrow()
  })
})
```

- [ ] **Step 2：运行失败。** frontend：`npm run test:unit -- src/components/__tests__/ReportDocumentView.spec.ts src/utils/__tests__/report-chart.spec.ts`；backend：`python -m pytest tests/test_report_document_pdf.py -q`。
- [ ] **Step 3：实现 TS 对齐与纯布局。** DTO 与 A1 相同 snake_case 字段，不能用 any 跳过嵌套类型验证。坐标函数：

```typescript
export function chartCoordinates(points: Array<{visit_date: string; value: number}>) {
  const times = points.map(p => Date.parse(`${p.visit_date}T00:00:00Z`))
  if (!points.length || points.some((p, i) => typeof p.value !== 'number' ||
      !Number.isFinite(p.value) || !Number.isFinite(times[i]))) throw new Error('invalid_chart_points')
  const lowTime = Math.min(...times), spanTime = Math.max(...times) - lowTime || 1
  const lowValue = Math.min(...points.map(p => p.value))
  const spanValue = Math.max(...points.map(p => p.value)) - lowValue || 1
  return points.map((p, i) => ({
    x: 42 + (times[i]! - lowTime) / spanTime * 360,
    y: 116 - (p.value - lowValue) / spanValue * 96,
    date: p.visit_date, value: p.value,
  }))
}
```

- [ ] **Step 4：接新阅读路径。** header 显示 report_id/匿名编号/保存时间；summary 移除 `visitCount>=3`。新文档第 8 节完整正文保留；交互扩展消费该 section 保存的表格，不用当前前端字典重新替换。旧报告保留现有 evidence 组件只读兼容。invalid 遮蔽摘要/图/正文/下载，显示安全异常；unverifiable 仅提示旧资料不可验证。
- [ ] **Step 5：统一 PDF。** 新图使用 doc.charts 同一日期比例；旧图明确 consistent、有限值及可解析日期才能显示。标题/表格/上下文使用保存 content。长 evidence/review 容器允许跨页，单条内容保留合理分页；thead 重复、长单元格 overflow-wrap:anywhere，无固定高度裁剪。
- [ ] **Step 6：真实 PDF 视觉验收。** 新脚本参数 `--output-dir outputs/operator-report-visual`，读取匿名测试夹具调用 builder/render/PDF，生成脂肪肝、AD、部分模型失败、最长上下文、10×30 展示压力五组。禁止生产病例 fixture。使用 PDF 技能逐页渲染 PNG 检查中文字体/分页/溢出/日期图，记录 PDF 页数与截图；HTML 契约不等同视觉通过。
- [ ] **Step 7：通过并构建。** frontend 运行 A6 Vitest、旧 ReportView/EvidenceSection 和 `npm run build`；backend 运行 `tests/test_report_document_pdf.py tests/test_longitudinal_pdf_contract.py tests/test_longitudinal_report_persistence.py`。建议提交：`feat: render saved operator report consistently in web and pdf`。

## 模块 A 完成门槛

- A1～A6 测试通过，必需内容与旧历史兼容有语义断言，没有仅以标题验收完整性。
- A5 迁移真库验证，A6 实际 PDF 逐页检查；环境缺失记录未验收。
- 不单独宣称第 6 项完成，继续模块 B 与总计划 P1。
