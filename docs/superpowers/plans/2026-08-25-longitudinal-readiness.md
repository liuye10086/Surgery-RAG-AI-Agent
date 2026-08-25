# 双疾病纵向报告就绪检查 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本项目明确采用单 Agent 内联执行，不使用 subagent-driven-development 或任何双 Agent 流程。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立一条只读命令，分别输出脂肪肝和阿尔茨海默病的数据、标准、模型与完整报告能力状态，并以稳定 JSON 契约和退出码说明当前阻塞项。

**Architecture:** 新增独立 readiness Pydantic schema 和领域服务，将数据库快照、标签统计、参考标准检查、artifact 检查与能力聚合拆成可单测函数；CLI 仅负责运行环境、显式只读事务、JSON 输出和退出码。线上 `LongitudinalPredictionResult.v1`、生产 registry、数据库 schema、前端和模型文件保持不变。

**Tech Stack:** Python 3、Pydantic v2、SQLAlchemy 2、PostgreSQL、joblib、pytest、现有疾病 adapter 与纵向前缀逻辑。

## Global Constraints

- 全程单 Agent 开发，不派生子 Agent，不执行双 Agent 交叉评审。
- 不修改 `backend/app/schemas/longitudinal_report.py` 的 `LongitudinalPredictionResult.v1`。
- 不修改 `backend/app/services/longitudinal_model_registry.py` 或生产推理加载行为。
- 不修改数据库 schema，不新增 Alembic revision，不写入数据库业务数据。
- 不训练、不重命名、不启用模型 artifact。
- 不修改前端或 UI；本任务不涉及 `docs/DESIGN_SPEC.md`。
- 所有生产代码必须遵循测试先行：先观察目标测试因缺少行为而失败，再写最小实现。
- CLI stdout 只能包含单一 JSON 文档；业务阻塞、工具失败分别返回退出码 `1`、`2`。
- 数据库业务查询必须运行在显式只读事务中，并最终回滚。
- 输出不得包含数据库 URL、密码、患者编号、Python traceback 或未脱敏异常正文。

---

## File Map

### Create

- `backend/app/schemas/longitudinal_readiness.py`：readiness v1 Pydantic 契约、状态枚举与顶层聚合校验。
- `backend/app/services/longitudinal_readiness.py`：数据库快照、前缀标签、标准、artifact、报告能力和状态汇总。
- `scripts/check_longitudinal_readiness.py`：只读 CLI、JSON 输出、退出码和工具级错误过滤。
- `backend/tests/test_longitudinal_readiness_schema.py`：schema 与状态语义测试。
- `backend/tests/test_longitudinal_readiness_service.py`：纯函数、数据库快照和 artifact 检查测试。
- `scripts/tests/test_check_longitudinal_readiness.py`：CLI 事务、JSON、退出码和敏感信息测试。

### Modify

- `scripts/check_model_artifacts.py`：只新增单文件 SHA-256 公共函数，保持现有 manifest 和 CLI 行为不变。
- `scripts/tests/test_check_model_artifacts.py`：覆盖新增哈希函数和原行为回归。
- `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`：验收完成后记录 P0-01 状态、文档、提交和验证证据。

### Read Only / Must Not Modify

- `backend/app/schemas/longitudinal_report.py`
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/api/operator.py`
- `backend/app/db/models.py`
- `backend/alembic/versions/*`
- `frontend/**`

---

### Task 1: Define the readiness v1 schema and strict status aggregation

**Files:**
- Create: `backend/app/schemas/longitudinal_readiness.py`
- Create: `backend/tests/test_longitudinal_readiness_schema.py`

**Interfaces:**
- Produces: `ReadinessStatus`, `CheckStatus`, `ArtifactStatus`, `ReasonSeverity` literals.
- Produces: `ReadinessReason`, `DataReadiness`, `StandardReadiness`, `ArtifactReadiness`, `ModelReadiness`, `CapabilityReadiness`, `ReportContractReadiness`, `DiseaseReadiness`, `EnvironmentReadiness`, `LongitudinalReadinessReport`.
- Produces: `status_from_reasons(reasons: list[ReadinessReason]) -> ReadinessStatus`.
- Later tasks construct these models directly; all models reject unknown fields with `ConfigDict(extra="forbid")`.

- [ ] **Step 1: Write failing schema tests**

Create `backend/tests/test_longitudinal_readiness_schema.py` with focused tests:

```python
import pytest
from pydantic import ValidationError

from app.schemas.longitudinal_readiness import (
    DiseaseReadiness,
    LongitudinalReadinessReport,
    ReadinessReason,
    status_from_reasons,
)


def _reason(code: str, severity: str, next_task: str) -> ReadinessReason:
    return ReadinessReason(
        code=code,
        message=f"message:{code}",
        severity=severity,
        next_task=next_task,
    )


def _disease(dataset: str, reasons: list[ReadinessReason]) -> DiseaseReadiness:
    return DiseaseReadiness(
        dataset=dataset,
        disease_name="脂肪肝" if dataset == "fatty_liver" else "阿尔茨海默病",
        status=status_from_reasons(reasons),
        data={
            "status": "available",
            "patient_count": 1,
            "visit_count": 2,
            "all_prefix_count": 1,
            "estimable_prefix_count": 1,
            "positive_count": 1,
            "negative_count": 0,
            "unknown_count": 0,
            "source_datasets": [dataset],
            "real_patient_count": 1,
            "synthetic_patient_count": 0,
            "unknown_provenance_patient_count": 0,
        },
        standard={"status": "available"},
        models={
            "outcome": {"status": "available", "artifact_type": "outcome"},
            "stage": {"status": "not_configured", "artifact_type": "stage"},
            "trends": [],
        },
        report_contract={"status": "available", "capabilities": []},
        available_capabilities=["reference_data"],
        reasons=reasons,
        next_tasks=list(dict.fromkeys(reason.next_task for reason in reasons)),
    )


def test_status_from_reasons_uses_strict_severity_order():
    assert status_from_reasons([]) == "ready"
    assert status_from_reasons([_reason("stage_model_missing", "degraded", "P2-01")]) == "degraded"
    assert status_from_reasons([_reason("outcome_model_missing", "blocked", "P0-04")]) == "blocked"


def test_report_requires_both_diseases_and_aggregates_worst_status():
    fatty = _disease("fatty_liver", [_reason("stage_model_missing", "degraded", "P2-01")])
    ad = _disease("ad", [_reason("approved_standard_missing", "blocked", "P0-02")])
    report = LongitudinalReadinessReport(
        generated_at="2026-08-25T00:00:00Z",
        overall_status="blocked",
        environment={"database_check": "available"},
        diseases={"fatty_liver": fatty, "ad": ad},
    )
    assert report.schema_version == "longitudinal_readiness.v1"
    assert report.overall_status == "blocked"


def test_report_rejects_missing_disease_or_inconsistent_overall_status():
    fatty = _disease("fatty_liver", [])
    with pytest.raises(ValidationError):
        LongitudinalReadinessReport(
            generated_at="2026-08-25T00:00:00Z",
            overall_status="ready",
            environment={"database_check": "available"},
            diseases={"fatty_liver": fatty},
        )


def test_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ReadinessReason(
            code="x",
            message="x",
            severity="blocked",
            next_task="P0-01",
            unexpected=True,
        )
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.schemas.longitudinal_readiness'`.

- [ ] **Step 3: Implement the minimal readiness schema**

Create `backend/app/schemas/longitudinal_readiness.py` with these exact public shapes:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ReadinessStatus = Literal["ready", "degraded", "blocked"]
CheckStatus = Literal["available", "degraded", "blocked", "not_applicable"]
ArtifactStatus = Literal["available", "missing", "incompatible", "disabled", "not_configured"]
ReasonSeverity = Literal["degraded", "blocked"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReadinessReason(StrictModel):
    code: str
    message: str
    severity: ReasonSeverity
    next_task: str
    details: dict[str, object] = Field(default_factory=dict)


class DataReadiness(StrictModel):
    status: CheckStatus
    patient_count: int = 0
    visit_count: int = 0
    all_prefix_count: int = 0
    estimable_prefix_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    unknown_count: int = 0
    source_datasets: list[str] = Field(default_factory=list)
    real_patient_count: int = 0
    synthetic_patient_count: int = 0
    unknown_provenance_patient_count: int = 0

    @model_validator(mode="after")
    def counts_are_consistent(self):
        if self.positive_count + self.negative_count + self.unknown_count != self.all_prefix_count:
            raise ValueError("前缀标签统计不一致")
        if self.estimable_prefix_count != self.positive_count + self.negative_count:
            raise ValueError("可估计前缀统计不一致")
        return self


class StandardReadiness(StrictModel):
    status: CheckStatus
    standard_id: int | None = None
    current_version_id: int | None = None
    version_label: str | None = None
    version_status: str | None = None
    content_hash: str | None = None
    rule_count: int = 0
    calculable_rule_count: int = 0


class ArtifactReadiness(StrictModel):
    status: ArtifactStatus
    artifact_type: Literal["outcome", "stage", "trend"]
    indicator: str | None = None
    model_file: str | None = None
    metadata_file: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)


class ModelReadiness(StrictModel):
    outcome: ArtifactReadiness
    stage: ArtifactReadiness
    trends: list[ArtifactReadiness] = Field(default_factory=list)


class CapabilityReadiness(StrictModel):
    key: str
    required: bool
    status: CheckStatus
    message: str
    next_task: str | None = None


class ReportContractReadiness(StrictModel):
    status: CheckStatus
    capabilities: list[CapabilityReadiness] = Field(default_factory=list)


class DiseaseReadiness(StrictModel):
    dataset: Literal["fatty_liver", "ad"]
    disease_name: str
    status: ReadinessStatus
    data: DataReadiness
    standard: StandardReadiness
    models: ModelReadiness
    report_contract: ReportContractReadiness
    available_capabilities: list[str] = Field(default_factory=list)
    reasons: list[ReadinessReason] = Field(default_factory=list)
    next_tasks: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def status_matches_reasons(self):
        expected = status_from_reasons(self.reasons)
        if self.status != expected:
            raise ValueError("疾病状态与原因严重级别不一致")
        expected_tasks = list(dict.fromkeys(reason.next_task for reason in self.reasons))
        if self.next_tasks != expected_tasks:
            raise ValueError("next_tasks 必须由 reasons 按顺序去重生成")
        return self


class EnvironmentReadiness(StrictModel):
    database_check: Literal["available"]
    alembic_revision: str | None = None
    code_heads: list[str] = Field(default_factory=list)
    revision_matches: bool | None = None


class LongitudinalReadinessReport(StrictModel):
    schema_version: Literal["longitudinal_readiness.v1"] = "longitudinal_readiness.v1"
    generated_at: datetime
    overall_status: ReadinessStatus
    environment: EnvironmentReadiness
    diseases: dict[Literal["fatty_liver", "ad"], DiseaseReadiness]

    @model_validator(mode="after")
    def diseases_and_status_are_consistent(self):
        if set(self.diseases) != {"fatty_liver", "ad"}:
            raise ValueError("readiness 报告必须分别包含 fatty_liver 和 ad")
        expected = max(
            (item.status for item in self.diseases.values()),
            key={"ready": 0, "degraded": 1, "blocked": 2}.__getitem__,
        )
        if self.overall_status != expected:
            raise ValueError("overall_status 必须等于疾病状态中的最高严重度")
        return self


def status_from_reasons(reasons: list[ReadinessReason]) -> ReadinessStatus:
    if any(reason.severity == "blocked" for reason in reasons):
        return "blocked"
    if reasons:
        return "degraded"
    return "ready"
```

Do not add tool-level `error` to this success report schema; the CLI error envelope is a separate minimal dict because it represents failure to construct a report.

- [ ] **Step 4: Run schema tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Commit Task 1**

```powershell
git add -- backend/app/schemas/longitudinal_readiness.py backend/tests/test_longitudinal_readiness_schema.py
git commit -m "feat(readiness): add strict readiness schema"
```

---

### Task 2: Aggregate reference patients, visits, 365-day labels, and standard state

**Files:**
- Create: `backend/app/services/longitudinal_readiness.py`
- Create: `backend/tests/test_longitudinal_readiness_service.py`

**Interfaces:**
- Consumes: `DiseaseProgressionAdapter`, `FATTY_LIVER_ADAPTER`, `AD_ADAPTER`, `build_prefixes`, `ReadinessReason`, `DataReadiness`, `StandardReadiness`.
- Produces: `REFERENCE_DATASET_ALIASES: dict[str, tuple[str, ...]]`.
- Produces: `CORE_DISEASES: tuple[DiseaseProgressionAdapter, ...]`.
- Produces: `aggregate_reference_data(rows: list[dict[str, object]], adapter: DiseaseProgressionAdapter) -> tuple[DataReadiness, list[ReadinessReason]]`.
- Produces: `assess_standard(row: dict[str, object] | None) -> tuple[StandardReadiness, list[ReadinessReason]]`.
- Produces: `load_database_snapshot(connection) -> dict[str, object]` using only SELECT statements.

- [ ] **Step 1: Write failing data and standard tests**

Add to `backend/tests/test_longitudinal_readiness_service.py`:

```python
import json

import joblib

from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER
from app.services.longitudinal_readiness import aggregate_reference_data, assess_standard


def _row(patient, visit_date, *, final_stage, event_dates, synthetic=None, source="longitudinal_300"):
    metadata = {
        "source_dataset": source,
        "visit_date": visit_date,
        "final_stage": final_stage,
        "event_dates": event_dates,
    }
    if synthetic is not None:
        metadata["is_synthetic"] = synthetic
    return {
        "patient_label": patient,
        "indicators": [{"name": "ALT", "value": 10}],
        "metadata": metadata,
    }


def test_reference_data_groups_patients_and_preserves_unknown_labels():
    rows = [
        _row("P1", "2024-01-01", final_stage="fatty_liver", event_dates={}, synthetic=False),
        _row("P1", "2024-06-01", final_stage="fatty_liver", event_dates={}, synthetic=False),
        _row("P2", "2024-01-01", final_stage="cirrhosis", event_dates={}, synthetic=True),
        _row("P2", "2024-06-01", final_stage="cirrhosis", event_dates={}, synthetic=True),
    ]
    data, reasons = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.patient_count == 2
    assert data.visit_count == 4
    assert data.all_prefix_count == 2
    assert data.negative_count == 1
    assert data.positive_count == 0
    assert data.unknown_count == 1
    assert data.real_patient_count == 1
    assert data.synthetic_patient_count == 1
    assert {reason.code for reason in reasons} == {"label_class_missing"}


def test_reference_data_does_not_guess_provenance_from_patient_number():
    rows = [
        _row("P999", "2024-01-01", final_stage="fatty_liver", event_dates={}, synthetic=None),
        _row("P999", "2024-06-01", final_stage="fatty_liver", event_dates={}, synthetic=None),
    ]
    data, _ = aggregate_reference_data(rows, FATTY_LIVER_ADAPTER)
    assert data.synthetic_patient_count == 0
    assert data.unknown_provenance_patient_count == 1


def test_ad_uses_ad_event_semantics_for_positive_prefix():
    rows = [
        _row("A1", "2024-01-01", final_stage="dementia", event_dates={"dementia_date": "2024-12-01"}, source="ad_longitudinal_300"),
        _row("A1", "2024-02-01", final_stage="dementia", event_dates={"dementia_date": "2024-12-01"}, source="ad_longitudinal_300"),
    ]
    data, _ = aggregate_reference_data(rows, AD_ADAPTER)
    assert data.positive_count == 1


def test_standard_requires_current_approved_version_and_calculable_rule():
    missing, missing_reasons = assess_standard(None)
    assert missing.status == "blocked"
    assert [reason.code for reason in missing_reasons] == ["approved_standard_missing"]

    retired, retired_reasons = assess_standard({
        "standard_id": 1,
        "current_version_id": 2,
        "version_status": "retired",
        "version_label": "v0.1",
        "content_hash": "abc",
        "rule_count": 0,
        "calculable_rule_count": 0,
    })
    assert retired.status == "blocked"
    assert [reason.code for reason in retired_reasons] == ["approved_standard_missing"]

    evidence_only, reasons = assess_standard({
        "standard_id": 1,
        "current_version_id": 3,
        "version_status": "approved",
        "version_label": "v1",
        "content_hash": "def",
        "rule_count": 4,
        "calculable_rule_count": 0,
    })
    assert evidence_only.status == "blocked"
    assert [reason.code for reason in reasons] == ["calculable_standard_rules_missing"]
```

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: import fails because `app.services.longitudinal_readiness` does not exist.

- [ ] **Step 3: Implement row aggregation and standard assessment**

Create `backend/app/services/longitudinal_readiness.py` and implement:

```python
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text

from app.schemas.longitudinal_readiness import DataReadiness, ReadinessReason, StandardReadiness
from app.services.disease_progression import AD_ADAPTER, FATTY_LIVER_ADAPTER, DiseaseProgressionAdapter
from app.services.longitudinal_features import build_prefixes

CORE_DISEASES = (FATTY_LIVER_ADAPTER, AD_ADAPTER)
REFERENCE_DATASET_ALIASES = {
    "fatty_liver": ("longitudinal_300",),
    "ad": ("ad_longitudinal_300",),
}


def _reason(code: str, message: str, severity: str, next_task: str, **details: object) -> ReadinessReason:
    return ReadinessReason(
        code=code,
        message=message,
        severity=severity,
        next_task=next_task,
        details=details,
    )


def aggregate_reference_data(
    rows: list[dict[str, object]],
    adapter: DiseaseProgressionAdapter,
) -> tuple[DataReadiness, list[ReadinessReason]]:
    patients: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        source = str(metadata.get("source_dataset") or "unknown")
        label = str(row.get("patient_label") or "")
        patient = patients.setdefault(
            (source, label),
            {"visits": [], "case_metadata": metadata, "provenance": metadata.get("is_synthetic")},
        )
        patient["visits"].append({
            "visit_date": metadata.get("visit_date"),
            "indicators": row.get("indicators") or [],
        })

    positive = negative = unknown = all_prefixes = visit_count = 0
    real = synthetic = provenance_unknown = 0
    for patient in patients.values():
        visits = [visit for visit in patient["visits"] if visit.get("visit_date")]
        visit_count += len(visits)
        provenance = patient.get("provenance")
        if provenance is True:
            synthetic += 1
        elif provenance is False:
            real += 1
        else:
            provenance_unknown += 1
        for prefix in build_prefixes(visits, adapter.minimum_visits):
            all_prefixes += 1
            label = adapter.outcome_label(
                patient,
                date.fromisoformat(prefix["as_of"]),
                timedelta(days=365),
            )
            if label == 1:
                positive += 1
            elif label == 0:
                negative += 1
            else:
                unknown += 1

    reasons: list[ReadinessReason] = []
    if not patients or visit_count == 0:
        reasons.append(_reason("reference_data_missing", "缺少参考患者或纵向访视", "blocked", "P0-01"))
    elif positive + negative == 0:
        reasons.append(_reason("estimable_labels_missing", "没有可估计的未来365天结局标签", "blocked", "P0-03"))
    elif positive == 0 or negative == 0:
        reasons.append(_reason("label_class_missing", "可估计标签没有同时包含阳性和阴性", "blocked", "P0-03"))

    data = DataReadiness(
        status="blocked" if reasons else "available",
        patient_count=len(patients),
        visit_count=visit_count,
        all_prefix_count=all_prefixes,
        estimable_prefix_count=positive + negative,
        positive_count=positive,
        negative_count=negative,
        unknown_count=unknown,
        source_datasets=sorted({source for source, _ in patients}),
        real_patient_count=real,
        synthetic_patient_count=synthetic,
        unknown_provenance_patient_count=provenance_unknown,
    )
    return data, reasons


def assess_standard(row: dict[str, object] | None) -> tuple[StandardReadiness, list[ReadinessReason]]:
    values = row or {}
    approved = values.get("version_status") == "approved"
    calculable = int(values.get("calculable_rule_count") or 0)
    reasons: list[ReadinessReason] = []
    if not approved:
        reasons.append(_reason("approved_standard_missing", "没有当前已批准的参考标准", "blocked", "P0-02"))
    elif calculable == 0:
        reasons.append(_reason("calculable_standard_rules_missing", "当前标准没有可计算的正式规则", "blocked", "P0-02"))
    return StandardReadiness(
        status="blocked" if reasons else "available",
        standard_id=values.get("standard_id"),
        current_version_id=values.get("current_version_id"),
        version_label=values.get("version_label"),
        version_status=values.get("version_status"),
        content_hash=values.get("content_hash"),
        rule_count=int(values.get("rule_count") or 0),
        calculable_rule_count=calculable,
    ), reasons
```

Ensure patient-level metadata comes from the same grouped patient and is passed under `case_metadata`, which is already supported by the adapter.

- [ ] **Step 4: Add the read-only database snapshot query tests**

Extend the same test file with a fake connection that records SQL and returns mapped rows. Test:

```python
class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement, parameters=None):
        sql = str(statement).strip()
        self.statements.append(sql)
        if sql == "SET TRANSACTION READ ONLY":
            return FakeResult([])
        if sql == "SHOW server_version":
            return FakeResult(["18.1"])
        if "FROM alembic_version" in sql:
            return FakeResult(["0010"])
        if "FROM diseases" in sql and "case_records" not in sql and "reference_standards" not in sql:
            return FakeResult([{"id": 2, "name": "脂肪肝"}, {"id": 4, "name": "阿尔茨海默病"}])
        if "FROM case_records" in sql:
            return FakeResult([])
        if "reference_standards" in sql:
            return FakeResult([])
        if "information_schema.columns" in sql:
            return FakeResult([
                {"table_name": "ai_reports", "column_name": "input_snapshot"},
                {"table_name": "ai_reports", "column_name": "prediction_result"},
                {"table_name": "ai_reports", "column_name": "content"},
                {"table_name": "ai_reports", "column_name": "status"},
                {"table_name": "ai_reports", "column_name": "operator_case_id"},
                {"table_name": "operator_cases", "column_name": "patient_label"},
                {"table_name": "operator_cases", "column_name": "disease_id"},
                {"table_name": "operator_case_visits", "column_name": "case_id"},
                {"table_name": "operator_case_visits", "column_name": "visit_date"},
                {"table_name": "operator_case_visits", "column_name": "indicators"},
            ])
        raise AssertionError(f"unexpected SQL: {sql}")


def test_load_database_snapshot_starts_with_read_only_and_uses_only_selects():
    connection = FakeConnection()
    snapshot = load_database_snapshot(connection)
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"
    assert snapshot["alembic_revision"] == "0010"
    for sql in connection.statements[1:]:
        assert sql.lstrip().upper().startswith(("SELECT", "SHOW"))
```

The fake results must cover:

- `SHOW server_version`
- `SELECT version_num FROM alembic_version`
- diseases
- case records joined to diseases
- standards/current versions/rule counts
- AIReport storage columns from `information_schema.columns`

- [ ] **Step 5: Run the new snapshot test and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: the new test fails because `load_database_snapshot` is missing.

- [ ] **Step 6: Implement `load_database_snapshot` with read-only SQL**

Implement `load_database_snapshot(connection)` with this ordering:

```python
connection.execute(text("SET TRANSACTION READ ONLY"))
server_version = connection.execute(text("SHOW server_version")).scalar_one_or_none()
alembic_revision = connection.execute(
    text("SELECT version_num FROM alembic_version LIMIT 1")
).scalar_one_or_none()
```

Then execute three SELECT queries:

1. Diseases: `id`, `name`.
2. Case records joined to diseases: disease id/name, `patient_label`, `indicators`, `metadata`.
3. Standards joined to current version and rules: IDs, label, status, content hash, total and calculable counts.

Also query `information_schema.columns` only for `ai_reports`, `operator_cases`, and `operator_case_visits` so later capability checks can prove storage support without reading report content or patient identifiers.

Return a plain dict with:

```python
{
    "server_version": server_version,
    "alembic_revision": alembic_revision,
    "diseases": disease_rows,
    "case_rows": case_rows,
    "standard_rows": standard_rows,
    "table_columns": table_columns,
}
```

Do not select `AIReport.content`, `query`, `input_snapshot`, or patient labels from operator-owned cases.

- [ ] **Step 7: Run service tests and existing longitudinal training tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_train_longitudinal_models.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 2**

```powershell
git add -- backend/app/services/longitudinal_readiness.py backend/tests/test_longitudinal_readiness_service.py
git commit -m "feat(readiness): audit longitudinal data and standards"
```

---

### Task 3: Add strict, independent artifact diagnostics

**Files:**
- Modify: `scripts/check_model_artifacts.py`
- Modify: `scripts/tests/test_check_model_artifacts.py`
- Modify: `backend/app/services/longitudinal_readiness.py`
- Modify: `backend/tests/test_longitudinal_readiness_service.py`

**Interfaces:**
- Produces from artifact script: `sha256_file(path: Path) -> str`.
- Produces from readiness service: `OUTCOME_METADATA_FIELDS: frozenset[str]`.
- Produces: `check_outcome_artifact(dataset: str, model_dir: Path) -> tuple[ArtifactReadiness, list[ReadinessReason]]`.
- Produces: `check_optional_artifacts(adapter: DiseaseProgressionAdapter, model_dir: Path) -> tuple[ArtifactReadiness, list[ArtifactReadiness], list[ReadinessReason]]` returning stage, trends, reasons.
- Does not call the production registry and does not execute `predict` or `predict_proba`.

- [ ] **Step 1: Write a failing single-file hash test**

Extend `scripts/tests/test_check_model_artifacts.py`:

```python
from check_model_artifacts import sha256_file, sha256_manifest


def test_sha256_file_matches_manifest_value(tmp_path: Path):
    artifact = tmp_path / "model.joblib"
    artifact.write_bytes(b"stable")
    assert sha256_file(artifact) == sha256_manifest(tmp_path)["model.joblib"]
```

- [ ] **Step 2: Run and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_check_model_artifacts.py -q
```

Expected: import fails for missing `sha256_file`.

- [ ] **Step 3: Extract `sha256_file` without changing existing behavior**

Modify `scripts/check_model_artifacts.py`:

```python
def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
```

Change `sha256_manifest` to call `sha256_file(path)`. Do not change patterns, JSON output, sorting, arguments, or exit behavior.

- [ ] **Step 4: Run artifact script tests and verify GREEN**

Run:

```powershell
python -m pytest scripts/tests/test_check_model_artifacts.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Write failing outcome artifact tests**

Extend `backend/tests/test_longitudinal_readiness_service.py`. Define a top-level, joblib-picklable fake:

```python
from scripts.check_model_artifacts import sha256_file


class PredictProbaModel:
    def predict_proba(self, rows):
        raise AssertionError("readiness 检查不得执行患者预测")


def _write_outcome_artifact(tmp_path, *, metadata_updates=None):
    model_path = tmp_path / "fatty_liver_longitudinal_outcome_365d.joblib"
    meta_path = tmp_path / "fatty_liver_longitudinal_outcome_365d.meta.json"
    joblib.dump(PredictProbaModel(), model_path)
    metadata = {
        "dataset": "fatty_liver",
        "disease": "脂肪肝",
        "target": "outcome_365d",
        "horizon_days": 365,
        "feature_names": ["alt.last"],
        "feature_version": "longitudinal_features.v1",
        "model_name": "GradientBoostingClassifier",
        "model_version": "test-v1",
        "training_dataset_version": "test-dataset-v1",
        "sklearn_version": "1.9.0",
        "trained_at": "2026-08-25T00:00:00Z",
        "artifact_sha256": sha256_file(model_path),
        "calibration_status": "not_calibrated",
    }
    metadata.update(metadata_updates or {})
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return model_path, meta_path
```

Add tests for:

```python
def test_missing_outcome_artifact_maps_to_p0_04(tmp_path):
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "missing"
    assert [reason.code for reason in reasons] == ["outcome_model_missing"]
    assert reasons[0].next_task == "P0-04"


def test_outcome_artifact_rejects_missing_metadata_field(tmp_path):
    _, meta_path = _write_outcome_artifact(tmp_path)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata.pop("feature_version")
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "incompatible"
    assert [reason.code for reason in reasons] == ["outcome_model_incompatible"]
    assert "missing_metadata:feature_version" in artifact.issues


def test_outcome_artifact_rejects_wrong_hash_without_loading(tmp_path, monkeypatch):
    _write_outcome_artifact(tmp_path, metadata_updates={"artifact_sha256": "0" * 64})
    monkeypatch.setattr(
        "app.services.longitudinal_readiness.joblib.load",
        lambda path: (_ for _ in ()).throw(AssertionError("must not load")),
    )
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "incompatible"
    assert artifact.issues == ["artifact_sha256_mismatch"]
    assert reasons[0].code == "outcome_model_incompatible"


def test_compatible_outcome_artifact_is_loaded_but_not_invoked(tmp_path):
    _write_outcome_artifact(tmp_path)
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "available"
    assert reasons == []
    assert artifact.metadata["model_version"] == "test-v1"


def test_legacy_progression_model_is_not_accepted_as_365_day_outcome(tmp_path):
    joblib.dump(PredictProbaModel(), tmp_path / "fatty_liver_progression_model.joblib")
    (tmp_path / "fatty_liver_progression_model.meta.json").write_text("{}", encoding="utf-8")
    artifact, reasons = check_outcome_artifact("fatty_liver", tmp_path)
    assert artifact.status == "missing"
    assert reasons[0].code == "outcome_model_missing"
```

The `_write_outcome_artifact` fixture above must retain these required semantic values:

```python
{
    "dataset": "fatty_liver",
    "disease": "脂肪肝",
    "target": "outcome_365d",
    "horizon_days": 365,
    "feature_names": ["alt.last"],
    "feature_version": "longitudinal_features.v1",
    "model_name": "GradientBoostingClassifier",
    "model_version": "test-v1",
    "training_dataset_version": "test-dataset-v1",
    "sklearn_version": "1.9.0",
    "trained_at": "2026-08-25T00:00:00Z",
    "artifact_sha256": "<actual hash>",
    "calibration_status": "not_calibrated"
}
```

- [ ] **Step 6: Run focused outcome tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -k "outcome_artifact or legacy_progression" -q
```

Expected: failures because artifact check functions are missing.

- [ ] **Step 7: Implement strict outcome artifact inspection**

In `backend/app/services/longitudinal_readiness.py`:

```python
OUTCOME_METADATA_FIELDS = frozenset({
    "dataset", "disease", "target", "horizon_days", "feature_names",
    "feature_version", "model_name", "model_version",
    "training_dataset_version", "sklearn_version", "trained_at",
    "artifact_sha256", "calibration_status",
})
```

`check_outcome_artifact` must:

1. Resolve only `{dataset}_longitudinal_outcome_365d.joblib` and matching `.meta.json`.
2. Return `missing` when both are absent and `incompatible` when only one exists.
3. Parse metadata as UTF-8 JSON object.
4. Report all missing metadata keys in stable sorted order.
5. Validate dataset, disease name from adapter, `target == "outcome_365d"`, horizon 365, non-empty string feature names, and non-empty feature version.
6. Calculate actual SHA-256 using `sha256_file` and compare before `joblib.load`.
7. Load only after static checks pass.
8. Check `callable(getattr(model, "predict_proba", None))` without invoking it.
9. Return metadata fields safe for display; do not return the loaded model object.
10. Use filenames relative to `model_dir`, not absolute filesystem paths.

All incompatibilities map to one `outcome_model_incompatible` reason with `details={"issues": sorted(issues)}`. Missing maps to `outcome_model_missing`.

- [ ] **Step 8: Write failing optional artifact tests**

Add tests:

```python
def test_stage_not_configured_and_missing_trends_are_degraded(tmp_path):
    stage, trends, reasons = check_optional_artifacts(FATTY_LIVER_ADAPTER, tmp_path)
    assert stage.status == "not_configured"
    assert {item.indicator for item in trends} == set(FATTY_LIVER_ADAPTER.key_indicators)
    assert all(item.status == "missing" for item in trends)
    assert {reason.code for reason in reasons} == {"stage_model_missing", "trend_models_missing"}
    assert all(reason.severity == "degraded" for reason in reasons)
```

- [ ] **Step 9: Run optional artifact test and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -k optional_artifacts -q
```

Expected: failure because `check_optional_artifacts` is missing.

- [ ] **Step 10: Implement optional artifact diagnostics**

Rules:

- Stage has no current production filename contract, so return `not_configured`, not a guessed path.
- Trends use the existing production pattern `{dataset}_trend_{indicator}.joblib` plus `.meta.json` for every adapter key indicator.
- Missing all trend artifacts creates one `trend_models_missing` degraded reason containing missing indicators.
- Partially present trend pairs must be checked for pair completeness and loadability; do not invent a richer metadata contract than the current production code defines.
- A malformed present trend artifact is `incompatible`, but remains a degraded optional capability in P0-01.
- Do not invoke any trend model.

- [ ] **Step 11: Run artifact and service tests**

Run:

```powershell
python -m pytest scripts/tests/test_check_model_artifacts.py backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: all tests pass.

- [ ] **Step 12: Commit Task 3**

```powershell
git add -- scripts/check_model_artifacts.py scripts/tests/test_check_model_artifacts.py backend/app/services/longitudinal_readiness.py backend/tests/test_longitudinal_readiness_service.py
git commit -m "feat(readiness): validate longitudinal artifacts"
```

---

### Task 4: Evaluate report capabilities and build the complete two-disease report

**Files:**
- Modify: `backend/app/services/longitudinal_readiness.py`
- Modify: `backend/tests/test_longitudinal_readiness_service.py`

**Interfaces:**
- Produces: `REQUIRED_CAPABILITIES` and `OPTIONAL_CAPABILITIES` ordered tuples.
- Produces: `assess_report_contract(*, table_columns: dict[str, set[str]], data: DataReadiness, standard: StandardReadiness, outcome: ArtifactReadiness, stage: ArtifactReadiness, trends: list[ArtifactReadiness], implemented_required: set[str] | None = None) -> tuple[ReportContractReadiness, list[ReadinessReason], list[str]]`.
- Produces: `build_readiness_report(snapshot: dict[str, object], *, model_dir: Path, code_heads: set[str], generated_at: datetime | None = None) -> LongitudinalReadinessReport`.
- Produces: `collect_longitudinal_readiness(connection, *, model_dir: Path, code_heads: set[str], generated_at: datetime | None = None) -> LongitudinalReadinessReport`.

- [ ] **Step 1: Write failing capability tests**

Add tests that pass explicit dependencies rather than reading production files:

```python
from app.schemas.longitudinal_readiness import ArtifactReadiness, DataReadiness, StandardReadiness


def _complete_data():
    return DataReadiness(
        status="available", patient_count=2, visit_count=4,
        all_prefix_count=2, estimable_prefix_count=2,
        positive_count=1, negative_count=1, unknown_count=0,
        source_datasets=["longitudinal_300"], real_patient_count=2,
        synthetic_patient_count=0, unknown_provenance_patient_count=0,
    )


def _available_standard():
    return StandardReadiness(
        status="available", standard_id=1, current_version_id=2,
        version_label="v1", version_status="approved", content_hash="abc",
        rule_count=2, calculable_rule_count=1,
    )


def _artifact(artifact_type, status, *, indicator=None, metadata=None):
    return ArtifactReadiness(
        status=status, artifact_type=artifact_type, indicator=indicator,
        metadata=metadata or {},
    )


def _table_columns():
    return {
        "ai_reports": {"input_snapshot", "prediction_result", "content", "status", "operator_case_id", "sources"},
        "operator_cases": {"patient_label", "disease_id", "sex", "baseline_stage"},
        "operator_case_visits": {"case_id", "visit_date", "indicators"},
    }


def test_required_capability_failure_blocks_report_contract():
    contract, reasons, available = assess_report_contract(
        table_columns=_table_columns(),
        data=_complete_data(),
        standard=_available_standard(),
        outcome=_artifact("outcome", "available", metadata={"calibration_status": "not_calibrated"}),
        stage=_artifact("stage", "not_configured"),
        trends=[_artifact("trend", "missing", indicator="alt")],
        implemented_required={
            "case_identity", "input_scope", "observed_longitudinal_changes",
            "outcome_365d", "reference_standard_interpretation",
            "evidence_sources", "limitations", "manual_review_items",
            "persistence_and_history", "pdf_delivery",
        },
    )
    required = {item.key: item for item in contract.capabilities if item.required}
    assert required["case_identity"].status == "available"
    assert required["outcome_365d"].status == "available"
    assert contract.status == "blocked"  # key_progression_signals not implemented yet
    assert [reason.code for reason in reasons] == ["report_contract_invalid"]
    assert "case_identity" in available


def test_optional_stage_and_trend_capabilities_do_not_block_required_contract():
    contract, reasons, _ = assess_report_contract(
        table_columns=_table_columns(),
        data=_complete_data(),
        standard=_available_standard(),
        outcome=_artifact("outcome", "available", metadata={"calibration_status": "not_calibrated"}),
        stage=_artifact("stage", "not_configured"),
        trends=[_artifact("trend", "missing", indicator="alt")],
        implemented_required=set(REQUIRED_CAPABILITIES),
    )
    assert contract.status == "degraded"
    assert reasons == []
    optional = {item.key: item for item in contract.capabilities if not item.required}
    assert optional["stage_projection"].status == "degraded"
    assert optional["next_followup_trend_model"].status == "degraded"
```

The capability evaluation must distinguish missing runtime dependencies from optional enhancements. It must not look for Markdown headings.

- [ ] **Step 2: Run capability tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -k capability -q
```

Expected: failure because `assess_report_contract` does not exist.

- [ ] **Step 3: Implement explicit capability dependency rules**

Define ordered required keys exactly as the design:

```python
REQUIRED_CAPABILITIES = (
    "case_identity",
    "input_scope",
    "data_quality_explanation",
    "observed_longitudinal_changes",
    "outcome_365d",
    "reference_standard_interpretation",
    "key_progression_signals",
    "evidence_sources",
    "limitations",
    "manual_review_items",
    "persistence_and_history",
    "pdf_delivery",
)
OPTIONAL_CAPABILITIES = (
    "stage_projection",
    "next_followup_trend_model",
    "calibrated_probability",
)
```

Use explicit dependency checks:

- Case identity and input scope require operator case/visit fields and `ai_reports.input_snapshot`.
- Observed changes require reference data with longitudinal prefixes and the existing observation contract.
- Outcome requires compatible outcome artifact.
- Reference interpretation requires available standard.
- Persistence/history requires `ai_reports.input_snapshot`, `prediction_result`, `content`, `status`, and `operator_case_id`.
- PDF delivery requires persistence fields and the existing completed-report download capability; represent this as a code capability constant, not a live PDF render.
- Data-quality explanation and key progression signals must reflect current explicit structural support. Do not declare them available merely because Markdown contains a generic warning or `progression_signal` string.
- Evidence, limitations, and manual review require their existing structured/rendering support; document the evidence used in code constants.
- Stage/trend are degraded when optional artifacts are unavailable.
- Calibrated probability is degraded unless outcome metadata explicitly states a supported calibrated status.

If any required capability is blocked, return a single `report_contract_invalid` blocked reason with a sorted list of missing capability keys. Optional gaps remain represented by their model reasons and capability rows.

- [ ] **Step 4: Write failing full report aggregation tests**

Add tests with a pure snapshot fixture containing two diseases:

```python
def _snapshot_fixture():
    return {
        "server_version": "18.1",
        "alembic_revision": "0010",
        "diseases": [
            {"id": 2, "name": "脂肪肝"},
            {"id": 4, "name": "阿尔茨海默病"},
        ],
        "case_rows": [],
        "standard_rows": [],
        "table_columns": _table_columns(),
    }


def test_build_report_keeps_diseases_separate_and_aggregates_worst_status(tmp_path):
    report = build_readiness_report(_snapshot_fixture(), model_dir=tmp_path, code_heads={"0010"})
    assert set(report.diseases) == {"fatty_liver", "ad"}
    assert report.diseases["fatty_liver"].disease_name == "脂肪肝"
    assert report.diseases["ad"].disease_name == "阿尔茨海默病"
    assert report.overall_status == "blocked"
    assert "P0-02" in report.diseases["fatty_liver"].next_tasks
    assert "P0-04" in report.diseases["ad"].next_tasks


def test_collect_readiness_calls_snapshot_loader_once(monkeypatch, tmp_path):
    sentinel_connection = object()
    sentinel_snapshot = _snapshot_fixture()
    calls = []

    def fake_load(connection):
        calls.append(connection)
        return sentinel_snapshot

    monkeypatch.setattr("app.services.longitudinal_readiness.load_database_snapshot", fake_load)
    report = collect_longitudinal_readiness(
        sentinel_connection,
        model_dir=tmp_path,
        code_heads={"0010"},
        generated_at="2026-08-25T00:00:00Z",
    )
    assert calls == [sentinel_connection]
    assert report.schema_version == "longitudinal_readiness.v1"
```

- [ ] **Step 5: Run aggregation tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_service.py -k "build_report or collect_readiness" -q
```

Expected: failure because report aggregation functions are missing.

- [ ] **Step 6: Implement disease matching and complete report aggregation**

Implementation rules:

1. Match database diseases by exact configured Chinese name: `脂肪肝` and `阿尔茨海默病`.
2. A missing disease produces zeroed data, blocked standard/model-dependent capabilities, and `disease_not_found`.
3. Filter reference case rows by disease id from the database, not by display-name substring.
4. Call data, standard, outcome, optional artifact and report-contract checkers independently for each adapter.
5. Concatenate reasons in deterministic route order: `P0-01`, `P0-02`, `P0-03`, `P0-04`, `P0-05`, `P0-06`, `P0-07`, `P1-*`, `P2-*`; remove duplicate `(code, next_task)` pairs.
6. Set disease status with `status_from_reasons`.
7. Derive `next_tasks` from the final reason list only.
8. Set `overall_status` from the two disease statuses.
9. Include environment revision, code heads, and exact `revision_matches`.
10. Use an injected `generated_at` in tests; default to current UTC in production.

- [ ] **Step 7: Run all readiness tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 4**

```powershell
git add -- backend/app/services/longitudinal_readiness.py backend/tests/test_longitudinal_readiness_service.py
git commit -m "feat(readiness): aggregate report capabilities"
```

---

### Task 5: Add the read-only JSON CLI and exact exit behavior

**Files:**
- Create: `scripts/check_longitudinal_readiness.py`
- Create: `scripts/tests/test_check_longitudinal_readiness.py`

**Interfaces:**
- Produces: `build_error_payload(code: str) -> dict[str, object]`.
- Produces: `exit_code_for_report(report: LongitudinalReadinessReport) -> int`.
- Produces: `run_check(*, database_url: str, model_dir: Path, code_heads: set[str]) -> LongitudinalReadinessReport`.
- Produces: `main() -> int`.
- Consumes: `settings.DATABASE_URL`, `MODEL_DIR`, Alembic `ScriptDirectory`, and `collect_longitudinal_readiness`.

- [ ] **Step 1: Write failing exit-code and error-envelope tests**

Create `scripts/tests/test_check_longitudinal_readiness.py`, loading the script with `importlib.util` like `backend/tests/test_database_baseline.py`.

```python
import json
from types import SimpleNamespace


def test_exit_code_is_zero_without_blocked_disease(checker):
    assert checker.exit_code_for_report(SimpleNamespace(overall_status="degraded")) == 0


def test_exit_code_is_one_when_any_disease_is_blocked(checker):
    assert checker.exit_code_for_report(SimpleNamespace(overall_status="blocked")) == 1


def test_error_payload_contains_no_exception_details(checker):
    payload = checker.build_error_payload("database_unavailable")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["overall_status"] == "error"
    assert "postgresql://" not in serialized
    assert "Traceback" not in serialized
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: script file is missing.

- [ ] **Step 3: Implement basic CLI helpers**

Create `scripts/check_longitudinal_readiness.py` with project path setup matching existing scripts. Implement:

```python
def build_error_payload(code: str) -> dict[str, object]:
    return {
        "schema_version": "longitudinal_readiness.v1",
        "overall_status": "error",
        "error": {
            "code": code,
            "message": "无法完成纵向报告就绪检查",
        },
    }


def exit_code_for_report(report: LongitudinalReadinessReport) -> int:
    return 1 if report.overall_status == "blocked" else 0
```

Use `json.dumps(payload, ensure_ascii=False, sort_keys=True)` for the single stdout document.

- [ ] **Step 4: Write failing transaction lifecycle tests**

Add fake engine/connection/transaction objects and test:

```python
class FakeTransaction:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class FakeConnection:
    def __init__(self, transaction):
        self.transaction = transaction
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return self.transaction

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposals = 0

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposals += 1


def test_run_check_rolls_back_and_disposes_engine_on_success(checker, monkeypatch, tmp_path):
    transaction = FakeTransaction()
    connection = FakeConnection(transaction)
    engine = FakeEngine(connection)
    expected = SimpleNamespace(overall_status="blocked")
    monkeypatch.setattr(checker, "create_engine", lambda *args, **kwargs: engine)
    monkeypatch.setattr(checker, "collect_longitudinal_readiness", lambda *args, **kwargs: expected)
    result = checker.run_check(database_url="postgresql://hidden", model_dir=tmp_path, code_heads={"0010"})
    assert result is expected
    assert connection.begin_calls == 1
    assert transaction.rollbacks == 1
    assert engine.disposals == 1


def test_main_returns_two_and_prints_sanitized_json_on_database_error(checker, monkeypatch, capsys):
    monkeypatch.setattr(
        checker,
        "run_check",
        lambda **kwargs: (_ for _ in ()).throw(
            checker.SQLAlchemyError("postgresql://user:password@localhost/private")
        ),
    )
    assert checker.main() == 2
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["error"]["code"] == "database_unavailable"
    assert "postgresql://" not in output
    assert "password" not in output
    assert "Traceback" not in output
```

- [ ] **Step 5: Run transaction tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_check_longitudinal_readiness.py -q
```

Expected: failures because `run_check` and/or `main` are incomplete.

- [ ] **Step 6: Implement CLI transaction, Alembic heads, and exception classification**

Implementation outline:

```python
def get_code_heads() -> set[str]:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


def run_check(*, database_url: str, model_dir: Path, code_heads: set[str]):
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                return collect_longitudinal_readiness(
                    connection,
                    model_dir=model_dir,
                    code_heads=code_heads,
                )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
```

`main()` must:

1. Call `run_check`.
2. Print `report.model_dump(mode="json")` as one JSON document.
3. Return `exit_code_for_report(report)`.
4. Catch SQLAlchemy/database connection errors as `database_unavailable`.
5. Catch other exceptions as `runtime_error`.
6. Print only `build_error_payload(code)` and return `2`.
7. Never log exception details to stdout.

The service itself issues `SET TRANSACTION READ ONLY`; the CLI owns rollback and dispose.

- [ ] **Step 7: Add source-level mutation and stdout contract tests**

Test that CLI source contains no mutating SQL tokens:

```python
for forbidden in ("DROP ", "TRUNCATE ", "INSERT ", "UPDATE ", "DELETE ", "ALTER "):
    assert forbidden not in source.upper()
```

Also run `main()` with a stub report and assert `json.loads(capsys.readouterr().out)` succeeds with no prefix/suffix text.

- [ ] **Step 8: Run CLI and readiness test suite**

Run:

```powershell
python -m pytest scripts/tests/test_check_longitudinal_readiness.py backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit Task 5**

```powershell
git add -- scripts/check_longitudinal_readiness.py scripts/tests/test_check_longitudinal_readiness.py
git commit -m "feat(readiness): add read-only readiness CLI"
```

---

### Task 6: Verify the real environment, protect regressions, and record roadmap evidence

**Files:**
- Modify: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`

**Interfaces:**
- No new runtime interface.
- Records exact implementation evidence only after all checks pass.

- [ ] **Step 1: Run focused readiness tests**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py scripts/tests/test_check_model_artifacts.py -q
```

Expected: all tests pass with no warnings or errors.

- [ ] **Step 2: Run related longitudinal regressions**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_longitudinal_end_to_end.py scripts/tests/test_train_longitudinal_models.py backend/tests/test_database_baseline.py -q
```

Expected: all tests pass. If a pre-existing failure appears, stop and report it before changing unrelated code.

- [ ] **Step 3: Verify forbidden production files are unchanged**

Run:

```powershell
git diff a46face --name-only
```

Expected changed runtime files are limited to:

```text
backend/app/schemas/longitudinal_readiness.py
backend/app/services/longitudinal_readiness.py
scripts/check_longitudinal_readiness.py
scripts/check_model_artifacts.py
```

plus the three new test files, the modified artifact test, the implementation plan, and the roadmap. No registry, prediction schema, DB model, migration, API, or frontend path may appear.

- [ ] **Step 4: Run the existing database baseline check**

Run:

```powershell
python scripts/check_database_readonly.py
```

Expected: JSON contains `"status": "PASS"`, revision `0010`, code head `0010`, and exit code `0`.

- [ ] **Step 5: Run the new real readiness command and capture evidence**

Run:

```powershell
python scripts/check_longitudinal_readiness.py
$readinessExit = $LASTEXITCODE
Write-Output "EXIT_CODE=$readinessExit"
```

Expected current-environment assertions:

- JSON parses successfully.
- `overall_status == "blocked"`.
- Both `fatty_liver` and `ad` are present and `blocked`.
- Fatty liver reports 300 patients and 1354 visits.
- AD reports 300 patients and 1365 visits.
- Fatty liver standard reports current retired version with zero calculable rules.
- AD reports no approved standard.
- Both outcome artifacts are `missing`; legacy `*_progression_model.joblib` files are not accepted.
- `next_tasks` includes `P0-02` and `P0-04` for both diseases.
- Exit code is `1`, proving business blockers are distinct from tool failure.

Do not hard-code patient/visit counts in unit tests; these are real-environment evidence only.

- [ ] **Step 6: Inspect JSON for sensitive data**

Save stdout only to an ignored temporary location if needed, then search for:

```powershell
python scripts/check_longitudinal_readiness.py 2>$null | Select-String -Pattern 'postgresql://|password|Traceback|patient_label|P001|A001'
```

Expected: no matches. The command still exits `1`; that is expected for current business blockers.

- [ ] **Step 7: Update the P0-01 roadmap card with actual evidence**

Under `### P0-01：建立双疾病基线审计与完整报告契约`, add a compact record immediately below the heading:

```markdown
**状态**：`completed`  
**Task-ID**：`longitudinal-readiness-001`  
**设计文档**：`docs/superpowers/specs/2026-08-25-longitudinal-readiness-design.md`  
**实施计划**：`docs/superpowers/plans/2026-08-25-longitudinal-readiness.md`  
**验证记录**：`python scripts/check_longitudinal_readiness.py` 成功输出双疾病只读 JSON；当前业务状态为 `blocked`、退出码为 `1`，缺口明确映射到 P0-02/P0-04 等后续任务。新增及相关回归测试通过。
```

If actual counts or statuses differ from the design-time baseline, record the actual result rather than editing code to force old numbers.

- [ ] **Step 8: Run documentation and diff checks**

Run:

```powershell
rg -n "longitudinal-readiness-001|状态.*completed|实施计划|验证记录" docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md
git diff --check
git status --short
```

Expected: roadmap record is present, `git diff --check` has no output, and status contains only expected task files.

- [ ] **Step 9: Commit Task 6**

```powershell
git add -- docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md docs/superpowers/plans/2026-08-25-longitudinal-readiness.md
git commit -m "docs(readiness): record P0-01 verification"
```

- [ ] **Step 10: Run final clean verification**

Run:

```powershell
python -m pytest backend/tests/test_longitudinal_readiness_schema.py backend/tests/test_longitudinal_readiness_service.py scripts/tests/test_check_longitudinal_readiness.py scripts/tests/test_check_model_artifacts.py backend/tests/test_longitudinal_model_registry.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_longitudinal_end_to_end.py scripts/tests/test_train_longitudinal_models.py backend/tests/test_database_baseline.py -q
python scripts/check_database_readonly.py
python scripts/check_longitudinal_readiness.py
$readinessExit = $LASTEXITCODE
git status --short
```

Expected:

- All selected tests pass.
- Existing database baseline exits `0` with `PASS`.
- New readiness command exits `1` with a valid blocked business report.
- `git status --short` is clean.

---

## Completion Gate

Do not claim P0-01 complete until all of the following are true:

- The independent `longitudinal_readiness.v1` schema exists and rejects inconsistent status.
- The command reports fatty liver and AD separately.
- Unknown labels remain visible in counts.
- Standards require current approved versions with calculable formal rules.
- Legacy progression artifacts are never accepted as 365-day outcome artifacts.
- Artifact checks validate metadata, SHA-256, loadability, and interface without executing prediction.
- Stage/trend gaps are degraded; missing required standard/outcome capabilities are blocked.
- The CLI uses explicit read-only transaction semantics and exits `0/1/2` as designed.
- Tool failures are sanitized.
- Production registry, prediction schema, database schema, API and frontend remain unchanged.
- Focused tests, related regressions, existing DB baseline, and real readiness command have been run with recorded output.
- The roadmap contains accurate completion and verification evidence.
