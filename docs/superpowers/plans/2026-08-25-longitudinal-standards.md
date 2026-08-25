# 双疾病参考标准可用化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本任务明确禁止 subagent-driven-development、子 Agent 和交叉 Agent 评审。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于现有脂肪肝与 AD DOCX 原文，通过可审核 manifest、保守解析、严格验证和原子生命周期，为两种疾病发布 current approved 标准版本，并保留完整规则与适用性溯源。

**Architecture:** 新增严格的标准 manifest 契约和确定性 Markdown 审核清单，将医学内容审核与生产代码分离；解析候选只提供原文定位和建议，正式规则只能由已批准 manifest 导入。生命周期服务统一负责候选物化、版本发布和退役，并由 PostgreSQL 可延迟约束触发器及 resolver 读取防线共同保证 current version 一致性。

**Tech Stack:** Python 3、Pydantic v2、SQLAlchemy 2、PostgreSQL、Alembic、FastAPI、python-docx、pytest、现有标准规则层与 longitudinal readiness CLI。

## Global Constraints

- Task-ID 固定为 `longitudinal-standards-001`。
- 全程单 Agent 执行，不使用子 Agent、双 Agent或交叉 Agent 评审。
- 不把 `AI_COLLABORATION.md` 作为启动、实施或验收条件。
- 不创建 worktree；如执行期间确有需要，必须先获得项目所有者授权。
- 不修改两份源 DOCX；源文件按 SHA-256 识别，不按临时路径或文件名猜测。
- 脂肪肝 DOCX SHA-256 固定为 `f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba`。
- AD DOCX SHA-256 固定为 `96222b951522cdbb7ef211b226d95659e9dc624e684cb88240d36267d816f9df`。
- 解析候选永远不能批量接受、批量 materialize 或直接发布。
- 未经项目所有者逐条批准的 manifest 条目不得写入正式规则。
- 测试 fixture、pending manifest、解析候选和未经审核规则不得写入正式数据库。
- 正式数据库写入分为两个检查点；每个检查点执行前必须展示 dry-run 摘要并获得项目所有者明确授权。
- 本实施计划经项目所有者明确批准前，不修改生产代码、不运行迁移、不创建 draft，也不写正式数据库。
- 实现严格采用 TDD：先运行新增测试并确认 RED，再写最小实现并确认 GREEN。
- current version 只能指向同一标准集合的 approved 版本。
- 空规则、零 calculable、blocked 规则或 validation error 均阻止发布。
- Evidence-only 规则不得生成 `reference_ranges` 投影。
- 若人工审核后某疾病没有安全的 calculable 规则，停止发布并报告阻塞；不得为了通过 readiness 人为制造阈值。
- P0-02 不训练模型，不修改模型 registry、纵向预测 schema、模型 artifact 或报告模板。
- 本任务没有 UI 修改，不修改 `frontend/**`，也不读取或改动 `docs/DESIGN_SPEC.md`。
- 所有脚本默认 dry-run；正式写入必须显式传入 `--execute`。
- 工具输出不得包含数据库连接串、密码、患者编号或 traceback。

---

## File Map

### Create

- `backend/app/schemas/standard_manifest.py`：严格 manifest、审核状态、源定位、indicator 和规则契约。
- `backend/app/services/standard_manifest.py`：manifest lint、源哈希/片段校验、核心指标覆盖和 Markdown 确定性渲染。
- `backend/app/services/standard_manifest_import.py`：dry-run 规划、canonical indicator upsert、正式规则/条件导入；不自行 commit。
- `backend/app/services/standard_draft_service.py`：双疾病 draft 准备和解析的事务受控服务；不自行 commit。
- `backend/alembic/versions/0011_standard_current_version_invariant.py`：current version 可延迟数据库一致性约束。
- `backend/tests/test_standard_manifest.py`：schema、lint、渲染、覆盖和哈希测试。
- `backend/tests/test_standard_manifest_import.py`：dry-run、导入幂等、未审核拒绝和事务边界测试。
- `backend/tests/test_standard_draft_service.py`：文档哈希、draft 创建、解析和无部分写入测试。
- `scripts/check_standard_manifests.py`：只读 manifest lint、审核文档生成和 `--check`。
- `scripts/prepare_standard_drafts.py`：检查点一 dry-run/execute CLI。
- `scripts/apply_standard_manifest.py`：检查点二规则导入与发布 dry-run/execute CLI。
- `scripts/tests/test_check_standard_manifests.py`
- `scripts/tests/test_prepare_standard_drafts.py`
- `scripts/tests/test_apply_standard_manifest.py`
- `standard_manifests/fatty_liver.v1.json`
- `standard_manifests/ad.v1.json`
- `docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md`
- `docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md`

### Modify

- `backend/app/services/standard_parser.py`：保守处理近似词、单位列、性别分列和多阈值。
- `backend/app/services/standard_validation.py`：疾病语义、投影资格和发布门槛。
- `backend/app/services/standard_lifecycle.py`：原子 materialize、publish、retire 和审计。
- `backend/app/services/standard_resolver.py`：年龄/教育/平台/方法/样本/量表上下文和冲突处理。
- `backend/app/services/longitudinal_evidence.py`：保留 evidence/unmatched/warning 和 provenance。
- `backend/app/api/admin_standards.py`：路由只调用统一服务，不直接改状态或跨事务更新候选。
- `backend/app/schemas/standard.py`：补充验证输出字段和完整规则编辑契约。
- `backend/tests/test_standard_parser.py`
- `backend/tests/test_standard_validation.py`
- `backend/tests/test_standard_lifecycle.py`
- `backend/tests/test_standard_resolver.py`
- `backend/tests/test_longitudinal_evidence.py`
- `backend/tests/test_admin_standards_api.py`
- `backend/tests/test_alembic_contracts.py`
- `database/schema.sql`
- `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`：全部验收后记录 P0-02 状态和证据。

### Read Only / Must Not Modify

- `frontend/**`
- `backend/app/services/longitudinal_model_registry.py`
- `backend/app/schemas/longitudinal_report.py`
- `backend/app/services/longitudinal_prediction.py`
- `backend/app/ml_models/**`
- 两份源 DOCX 文件

---

### Task 1: Define the strict standard manifest and deterministic review contract

**Files:**
- Create: `backend/app/schemas/standard_manifest.py`
- Create: `backend/app/services/standard_manifest.py`
- Create: `backend/tests/test_standard_manifest.py`

**Interfaces:**
- Produces: `ManifestReviewState`, `EntryReviewStatus`, `ManifestEntryKind`, `ManifestActionability` literals.
- Produces: `SourceLocator`, `ManifestIndicator`, `ManifestRule`, `StandardManifestEntry`, `StandardManifest`.
- Produces: `load_standard_manifest(path: Path) -> StandardManifest`.
- Produces: `validate_standard_manifest(manifest: StandardManifest, *, source_path: Path, parsed_document: ParsedStandardDocument) -> ManifestValidationResult`.
- Produces: `render_standard_review_markdown(manifest: StandardManifest) -> str`.
- Produces: `CORE_INDICATORS: dict[str, tuple[str, ...]]`.

- [ ] **Step 1: Write failing strict-schema tests**

Create `backend/tests/test_standard_manifest.py` with:

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.standard_manifest import StandardManifest


def _entry(entry_id: str = "fatty-alt-reference") -> dict:
    return {
        "entry_id": entry_id,
        "entry_kind": "rule",
        "review_status": "pending",
        "review_note": None,
        "source": {
            "table_index": 1,
            "row_index": 1,
            "paragraph_index": None,
            "column_index": None,
            "raw_text": "ALT（谷丙转氨酶） | 男性约 9–50；女性约 7–40 | U/L",
        },
        "indicator": {
            "canonical_key": "alt",
            "name_en": "ALT",
            "name_cn": "谷丙转氨酶",
            "aliases": ["谷丙转氨酶", "丙氨酸氨基转移酶"],
            "domain": "laboratory",
            "specimen_or_modality": "serum",
            "data_type": "numeric",
            "scale_or_method": None,
            "default_unit": "U/L",
            "clinical_dimension": "liver_injury",
            "allows_numeric_comparison": True,
            "abnormal_direction": "high",
        },
        "rule": {
            "rule_type": "numeric_range",
            "comparator": None,
            "lower": 9.0,
            "upper": 50.0,
            "lower_inclusive": True,
            "upper_inclusive": True,
            "unit": "U/L",
            "sex": "male",
            "category": "reference",
            "applicability": {},
            "target_state_type": "control",
            "target_state_value": "reference",
            "clinical_dimension": "liver_injury",
            "evidence_type": "standard_table",
            "machine_actionability": "evidence-only",
            "actionability_reason": "原文使用约数",
            "interpretation": "男性约 9–50 U/L",
            "priority": 0,
            "conflict_group": None,
            "framework": None,
            "biomarker_axis": None,
            "biomarker_state": None,
            "stage": None,
            "clinical_function": None,
            "conditions": {},
        },
    }


def _manifest() -> dict:
    return {
        "schema_version": "standard_manifest.v1",
        "dataset": "fatty_liver",
        "disease_name": "脂肪肝",
        "source_document_sha256": "f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba",
        "target_version_label": "fatty-liver-2026-08-25",
        "review_state": "pending",
        "reviewed_at": None,
        "entries": [_entry()],
    }


def test_manifest_rejects_unknown_fields_and_duplicate_entry_ids():
    payload = _manifest()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        StandardManifest.model_validate(payload)

    payload = _manifest()
    payload["entries"].append(_entry())
    with pytest.raises(ValidationError, match="entry_id"):
        StandardManifest.model_validate(payload)


def test_approved_manifest_cannot_contain_pending_entries():
    payload = _manifest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    with pytest.raises(ValidationError, match="pending"):
        StandardManifest.model_validate(payload)


def test_no_safe_rule_entry_has_no_rule_payload():
    payload = _manifest()
    payload["entries"][0]["entry_kind"] = "no_safe_rule"
    payload["entries"][0]["rule"] = None
    payload["entries"][0]["review_status"] = "approved"
    manifest = StandardManifest.model_validate(payload)
    assert manifest.entries[0].rule is None


def test_reserved_applicability_keys_are_rejected():
    payload = _manifest()
    payload["entries"][0]["rule"]["applicability"] = {"_manifest_entry_id": "forged"}
    with pytest.raises(ValidationError, match="保留"):
        StandardManifest.model_validate(payload)
```

- [ ] **Step 2: Run the schema tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_manifest.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'app.schemas.standard_manifest'`.

- [ ] **Step 3: Implement the strict Pydantic contract**

Create `backend/app/schemas/standard_manifest.py` with strict models and these exact literals:

```python
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ManifestReviewState = Literal["pending", "approved"]
EntryReviewStatus = Literal["pending", "approved", "rejected"]
ManifestEntryKind = Literal["rule", "no_safe_rule"]
ManifestActionability = Literal["calculable", "evidence-only", "blocked"]
AbnormalDirection = Literal["high", "low", "ordinal_high", "ordinal_low", "contextual", "none"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceLocator(StrictModel):
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    column_index: int | None = None
    raw_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def has_location(self):
        if self.paragraph_index is None and self.table_index is None:
            raise ValueError("源定位必须包含 paragraph_index 或 table_index")
        if self.table_index is not None and self.row_index is None:
            raise ValueError("表格定位必须包含 row_index")
        return self


class ManifestIndicator(StrictModel):
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._/-]*$")
    name_en: str
    name_cn: str | None = None
    aliases: list[str] = Field(default_factory=list)
    domain: str
    specimen_or_modality: str | None = None
    data_type: Literal["numeric", "ordinal", "categorical", "qualitative"]
    scale_or_method: str | None = None
    default_unit: str | None = None
    clinical_dimension: str
    allows_numeric_comparison: bool
    abnormal_direction: AbnormalDirection


class ManifestRule(StrictModel):
    rule_type: Literal["numeric_range", "threshold", "qualitative_direction", "classification", "exclusion", "composite"]
    comparator: str | None = None
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = True
    unit: str | None = None
    sex: str | None = None
    category: str | None = None
    applicability: dict[str, Any] = Field(default_factory=dict)
    target_state_type: str
    target_state_value: str | None = None
    clinical_dimension: str
    evidence_type: str | None = None
    machine_actionability: ManifestActionability
    actionability_reason: str = Field(min_length=1)
    interpretation: str | None = None
    priority: int = 0
    conflict_group: str | None = None
    framework: str | None = None
    biomarker_axis: str | None = None
    biomarker_state: str | None = None
    stage: str | None = None
    clinical_function: str | None = None
    conditions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def applicability_does_not_use_reserved_keys(self):
        if any(str(key).startswith("_") for key in self.applicability):
            raise ValueError("applicability 不得使用下划线开头的保留键")
        return self


class StandardManifestEntry(StrictModel):
    entry_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    entry_kind: ManifestEntryKind
    review_status: EntryReviewStatus
    review_note: str | None = None
    source: SourceLocator
    indicator: ManifestIndicator
    rule: ManifestRule | None = None

    @model_validator(mode="after")
    def kind_matches_rule(self):
        if self.entry_kind == "rule" and self.rule is None:
            raise ValueError("rule 条目必须提供规则")
        if self.entry_kind == "no_safe_rule" and self.rule is not None:
            raise ValueError("no_safe_rule 条目不得提供规则")
        return self


class StandardManifest(StrictModel):
    schema_version: Literal["standard_manifest.v1"] = "standard_manifest.v1"
    dataset: Literal["fatty_liver", "ad"]
    disease_name: str
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_version_label: str = Field(min_length=1, max_length=100)
    review_state: ManifestReviewState
    reviewed_at: datetime | None = None
    entries: list[StandardManifestEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def review_and_ids_are_consistent(self):
        ids = [entry.entry_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("entry_id 必须唯一")
        if self.review_state == "approved":
            if self.reviewed_at is None:
                raise ValueError("approved manifest 必须包含 reviewed_at")
            if any(entry.review_status == "pending" for entry in self.entries):
                raise ValueError("approved manifest 不得包含 pending 条目")
        return self
```

- [ ] **Step 4: Write failing manifest lint and Markdown tests**

Extend `backend/tests/test_standard_manifest.py`:

```python
from types import SimpleNamespace

from app.services.standard_manifest import (
    CORE_INDICATORS,
    render_standard_review_markdown,
    validate_standard_manifest,
)


def _parsed(raw_text: str):
    return SimpleNamespace(segments=[SimpleNamespace(
        paragraph_index=None,
        table_index=1,
        row_index=1,
        column_index=None,
        raw_text=raw_text,
    )])


def test_manifest_rejects_hash_or_source_text_mismatch(tmp_path: Path):
    source = tmp_path / "fatty.docx"
    source.write_bytes(b"wrong")
    manifest = StandardManifest.model_validate(_manifest())
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert {item.code for item in result.errors} == {"source_hash_mismatch"}

    source.write_bytes(b"stable")
    payload = _manifest()
    import hashlib
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed("different text"),
    )
    assert {item.code for item in result.errors} == {"source_segment_mismatch"}


def test_core_indicator_coverage_requires_explicit_conclusion(tmp_path: Path):
    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    import hashlib
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "core_indicator_missing" in {item.code for item in result.errors}
    assert "afp" in result.missing_core_indicators


def test_review_markdown_is_deterministic_and_contains_decision_fields():
    manifest = StandardManifest.model_validate(_manifest())
    first = render_standard_review_markdown(manifest)
    second = render_standard_review_markdown(manifest)
    assert first == second
    assert "fatty-alt-reference" in first
    assert "evidence-only" in first
    assert "审核状态" in first


def test_approved_manifest_requires_a_safe_calculable_rule(tmp_path: Path):
    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    import hashlib
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    payload["entries"][0]["review_status"] = "approved"
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "approved_calculable_rule_missing" in {item.code for item in result.errors}


def test_approved_blocked_entry_is_rejected_by_lint(tmp_path: Path):
    source = tmp_path / "fatty.docx"
    source.write_bytes(b"stable")
    payload = _manifest()
    import hashlib
    payload["source_document_sha256"] = hashlib.sha256(b"stable").hexdigest()
    payload["review_state"] = "approved"
    payload["reviewed_at"] = "2026-08-25T12:00:00Z"
    payload["entries"][0]["review_status"] = "approved"
    payload["entries"][0]["rule"]["machine_actionability"] = "blocked"
    manifest = StandardManifest.model_validate(payload)
    result = validate_standard_manifest(
        manifest,
        source_path=source,
        parsed_document=_parsed(manifest.entries[0].source.raw_text),
    )
    assert "approved_blocked_rule" in {item.code for item in result.errors}
```

- [ ] **Step 5: Run focused tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_manifest.py -q
```

Expected: failures because `app.services.standard_manifest` does not exist.

- [ ] **Step 6: Implement lint and deterministic rendering**

Create `backend/app/services/standard_manifest.py` with:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.standard_manifest import StandardManifest

CORE_INDICATORS = {
    "fatty_liver": ("alt", "ast", "ggt", "tbil", "alb", "plt", "afp", "hba1c", "bmi", "waist"),
    "ad": ("mmse", "moca", "cdr", "nfl", "p-tau217", "aβ42/aβ40"),
}


@dataclass(frozen=True)
class ManifestFinding:
    code: str
    message: str
    entry_id: str | None = None


@dataclass(frozen=True)
class ManifestValidationResult:
    errors: list[ManifestFinding] = field(default_factory=list)
    warnings: list[ManifestFinding] = field(default_factory=list)
    missing_core_indicators: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors


def load_standard_manifest(path: Path) -> StandardManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return StandardManifest.model_validate(payload)


def _segment_key(item) -> tuple[int | None, int | None, int | None, int | None]:
    return (item.paragraph_index, item.table_index, item.row_index, item.column_index)


def validate_standard_manifest(manifest, *, source_path, parsed_document):
    errors: list[ManifestFinding] = []
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    if digest != manifest.source_document_sha256:
        errors.append(ManifestFinding("source_hash_mismatch", "源 DOCX 哈希不一致"))
    locations = {_segment_key(item): item.raw_text for item in parsed_document.segments}
    for entry in manifest.entries:
        key = _segment_key(entry.source)
        if locations.get(key) != entry.source.raw_text:
            errors.append(ManifestFinding("source_segment_mismatch", "源片段定位或原文不一致", entry.entry_id))
    covered = {entry.indicator.canonical_key for entry in manifest.entries}
    missing = sorted(set(CORE_INDICATORS[manifest.dataset]) - covered)
    for key in missing:
        errors.append(ManifestFinding("core_indicator_missing", f"核心指标缺少明确结论：{key}"))
    if manifest.review_state == "approved":
        approved_rules = [
            entry.rule
            for entry in manifest.entries
            if entry.entry_kind == "rule" and entry.review_status == "approved"
        ]
        if any(rule.machine_actionability == "blocked" for rule in approved_rules):
            errors.append(ManifestFinding("approved_blocked_rule", "approved manifest 不得包含 blocked 规则"))
        if not any(rule.machine_actionability == "calculable" for rule in approved_rules):
            errors.append(ManifestFinding("approved_calculable_rule_missing", "每种疾病至少需要一条审核通过的 calculable 规则"))
    return ManifestValidationResult(errors=errors, missing_core_indicators=missing)


def render_standard_review_markdown(manifest: StandardManifest) -> str:
    lines = [
        f"# {manifest.disease_name}标准规则审核清单",
        "",
        f"- Manifest：`{manifest.schema_version}`",
        f"- 数据集：`{manifest.dataset}`",
        f"- 源文档 SHA-256：`{manifest.source_document_sha256}`",
        f"- 目标版本：`{manifest.target_version_label}`",
        f"- 整体审核状态：`{manifest.review_state}`",
        "",
    ]
    for entry in sorted(manifest.entries, key=lambda item: item.entry_id):
        actionability = entry.rule.machine_actionability if entry.rule else "no_safe_rule"
        lines.extend([
            f"## {entry.entry_id}",
            "",
            f"- 指标：`{entry.indicator.canonical_key}` / {entry.indicator.name_cn or entry.indicator.name_en}",
            f"- 条目类型：`{entry.entry_kind}`",
            f"- 建议 actionability：`{actionability}`",
            f"- 审核状态：`{entry.review_status}`",
            f"- 审核备注：{entry.review_note or '无'}",
            f"- 原文位置：paragraph={entry.source.paragraph_index}, table={entry.source.table_index}, row={entry.source.row_index}, column={entry.source.column_index}",
            f"- 原文：{entry.source.raw_text}",
            "",
        ])
    return "\n".join(lines).rstrip() + "\n"
```

The production implementation may split private helpers, but these public names and deterministic ordering are fixed.

- [ ] **Step 7: Run Task 1 tests and commit**

Run:

```powershell
python -m pytest backend/tests/test_standard_manifest.py -q
git diff --check
```

Expected: all Task 1 tests pass and `git diff --check` has no output.

Commit:

```powershell
git add -- backend/app/schemas/standard_manifest.py backend/app/services/standard_manifest.py backend/tests/test_standard_manifest.py
git commit -m "feat(standards): add reviewed manifest contract"
```

---

### Task 2: Make DOCX candidate parsing conservative and source-faithful

**Files:**
- Modify: `backend/app/services/standard_parser.py`
- Modify: `backend/tests/test_standard_parser.py`
- Modify: `backend/app/api/admin_standards.py`
- Modify: `backend/tests/test_admin_standards_api.py`

**Interfaces:**
- Produces: `contains_approximation(text: str) -> bool`.
- Produces: `parse_sex_numeric_expressions(text: str) -> list[tuple[str, NumericExpression]]`.
- Extends `RuleCandidate` with `sex: str | None` and `parse_warnings: tuple[str, ...]`.
- Preserves: `parse_numeric_expression()` boundary semantics and `parse_standard_docx()` return type.

- [ ] **Step 1: Write failing parser safety tests**

Append to `backend/tests/test_standard_parser.py`:

```python
from app.services.standard_parser import contains_approximation, parse_sex_numeric_expressions


def test_approximate_text_is_detected_and_never_auto_calculable():
    assert contains_approximation("约 15–40")
    assert contains_approximation("常见为≥26分")
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    ast = next(item for item in parsed.rule_candidates if item.indicator_name.startswith("AST"))
    assert ast.machine_actionability == "evidence-only"
    assert "approximate_language" in ast.parse_warnings


def test_unit_comes_only_from_the_unit_cell_not_explanation_text():
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    tbil = next(item for item in parsed.rule_candidates if item.indicator_name.startswith("TBIL"))
    assert tbil.numeric.unit == "μmol/L"
    assert "不用于脂肪含量分级" not in tbil.numeric.unit


def test_sex_specific_ranges_are_preserved_as_two_candidates():
    expressions = parse_sex_numeric_expressions("男性 < 90；女性 < 85")
    assert [(sex, item.upper, item.upper_inclusive) for sex, item in expressions] == [
        ("male", 90.0, False),
        ("female", 85.0, False),
    ]
    parsed = parse_standard_docx(FIXTURES / "fatty_liver_standard.docx", parser_version="v2")
    waist = [item for item in parsed.rule_candidates if item.indicator_name.startswith("WAIST")]
    assert {(item.sex, item.numeric.upper) for item in waist} == {("male", 90.0), ("female", 85.0)}


def test_platform_or_cohort_specific_ad_threshold_is_not_generic_calculable():
    parsed = parse_standard_docx(FIXTURES / "ad_standard.docx", parser_version="v2")
    ptau = next(
        item for item in parsed.rule_candidates
        if item.indicator_name.startswith("Plasma p-tau217") and item.numeric
    )
    assert ptau.machine_actionability == "evidence-only"
    assert "missing_applicability" in ptau.parse_warnings
```

Add to `backend/tests/test_admin_standards_api.py` by extending the deterministic candidate fixture with `sex="female"` and `parse_warnings=("approximate_language",)`, then assert:

```python
stored_candidate = next(item for item in db.added if hasattr(item, "candidate_json"))
assert stored_candidate.candidate_json["sex"] == "female"
assert stored_candidate.candidate_json["parse_warnings"] == ["approximate_language"]
```

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_parser.py -q
```

Expected: import failures for the two helpers and assertion failures for unit/actionability behavior.

- [ ] **Step 3: Implement conservative row parsing**

Replace `RuleCandidate` with this complete field contract:

```python
@dataclass(frozen=True)
class RuleCandidate:
    raw_text: str
    segment: Segment
    indicator_name: str | None = None
    target_state_type: str = "evidence"
    target_state_value: str | None = None
    rule_type: str = "qualitative_direction"
    machine_actionability: str = "evidence-only"
    evidence_type: str | None = None
    applicability: dict[str, Any] = field(default_factory=dict)
    numeric: NumericExpression | None = None
    interpretation: str | None = None
    sex: str | None = None
    parse_warnings: tuple[str, ...] = ()
```

Add:

```python
_APPROXIMATION_RE = re.compile(r"(?:约|常见为|常作正常参考|大约|通常为)")
_UNIT_RE = re.compile(r"^(?:%|U/L|g/L|μmol/L|mmol/L|mg/L|ng/L|pg/mL|kg/m²|cm|10⁹/L|分|无量纲)$", re.I)


def contains_approximation(text: str) -> bool:
    return bool(_APPROXIMATION_RE.search(_clean(text)))


def _normalise_sex(value: str) -> str:
    return {"男性": "male", "女性": "female"}[value]


def parse_sex_numeric_expressions(text: str) -> list[tuple[str, NumericExpression]]:
    results = []
    for label, expression in _SEX_RE.findall(_clean(text)):
        parsed = parse_numeric_expression(expression)
        if parsed is not None:
            results.append((_normalise_sex(label), parsed))
    return results
```

Refactor `_candidate_for_row()` so it parses only the intended value cell (`cells[1]`) and reads a unit only when the final cell fully matches `_UNIT_RE`. For sex-specific expressions, emit one candidate per sex. Set `machine_actionability="evidence-only"` and add stable warnings when any of these applies:

```python
warnings = []
if contains_approximation(value_text):
    warnings.append("approximate_language")
if any(token in explanation for token in ("平台", "试剂", "队列", "示踪剂", "教育程度", "语言")):
    warnings.append("missing_applicability")
if numeric is None or not unit:
    warnings.append("not_safely_numeric")
actionability = "calculable" if numeric and unit and not warnings else "evidence-only"
```

Do not infer platform, method, cohort, age, education or scale version from surrounding prose unless an exact structured value is present in the same row.

When `admin_standards.parse_version()` serializes a deterministic candidate, include `sex` and `parse_warnings` in `candidate_json`; convert the warning tuple to a JSON list. The controlled draft service added in Task 7 must use the same serialization contract.

- [ ] **Step 4: Run parser tests and existing real-DOCX smoke tests**

Run:

```powershell
python -m pytest backend/tests/test_standard_parser.py backend/tests/test_admin_standards_api.py -q
```

Expected: all tests pass; both fixture DOCX files retain the existing table/segment counts.

- [ ] **Step 5: Commit Task 2**

```powershell
git add -- backend/app/services/standard_parser.py backend/tests/test_standard_parser.py backend/app/api/admin_standards.py backend/tests/test_admin_standards_api.py
git commit -m "fix(standards): parse medical candidates conservatively"
```

---

### Task 3: Enforce disease semantics, projection eligibility, and publish gates

**Files:**
- Modify: `backend/app/services/standard_validation.py`
- Modify: `backend/app/schemas/standard.py`
- Modify: `backend/tests/test_standard_validation.py`

**Interfaces:**
- Produces: `is_projection_eligible(rule: Any) -> bool`.
- Produces: `validate_rule(rule: Any, *, disease_key: str | None = None) -> RuleValidation`.
- Produces: `validate_version_rules(rules: list[Any], *, disease_key: str | None = None, require_calculable: bool = True) -> ValidationReport`.
- Extends `ValidationReport` with `calculable_rule_count` and `blocked_rule_count`.

- [ ] **Step 1: Write failing validation tests**

Add to `backend/tests/test_standard_validation.py`:

```python
from app.services.standard_validation import is_projection_eligible, validate_version_rules


def _rule(**updates):
    values = {
        "rule_type": "numeric_range",
        "lower": 7.0,
        "upper": 40.0,
        "unit": "U/L",
        "applicability": {},
        "machine_actionability": "calculable",
        "target_state_type": "control",
        "clinical_dimension": "liver_injury",
        "framework": None,
        "biomarker_axis": None,
        "stage": None,
        "conditions": {},
        "indicator": SimpleNamespace(
            canonical_key="alt",
            data_type="numeric",
            allows_numeric_comparison=True,
            abnormal_direction="high",
        ),
        "source_segment": SimpleNamespace(raw_text="ALT 7–40 U/L"),
    }
    values.update(updates)
    return SimpleNamespace(**values)


def test_empty_or_zero_calculable_version_cannot_publish():
    empty = validate_version_rules([], disease_key="fatty_liver")
    assert not empty.can_publish
    assert {item.code for item in empty.errors} == {"formal_rules_missing", "calculable_rules_missing"}

    evidence = validate_version_rules([
        _rule(machine_actionability="evidence-only", rule_type="qualitative_direction", lower=None, upper=None, unit=None)
    ], disease_key="fatty_liver")
    assert not evidence.can_publish
    assert "calculable_rules_missing" in {item.code for item in evidence.errors}


def test_evidence_only_and_non_numeric_calculable_rules_do_not_project():
    assert not is_projection_eligible(_rule(machine_actionability="evidence-only"))
    assert not is_projection_eligible(_rule(rule_type="classification"))
    assert is_projection_eligible(_rule())


def test_ad_directions_are_indicator_specific():
    mmse = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="mmse", data_type="ordinal", allows_numeric_comparison=True, abnormal_direction="high"),
        unit="points",
    ), disease_key="ad")
    assert "invalid_ad_direction" in {item.code for item in mmse.errors}

    cdr = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="cdr", data_type="ordinal", allows_numeric_comparison=True, abnormal_direction="ordinal_high"),
        rule_type="classification",
        lower=None,
        upper=None,
        unit=None,
        conditions={"node_type": "leaf", "payload": {"score": 0.5}},
    ), disease_key="ad")
    assert "invalid_ad_direction" not in {item.code for item in cdr.errors}


def test_approximate_or_context_incomplete_calculable_rule_is_rejected():
    approximate = validate_rule(_rule(
        source_segment=SimpleNamespace(raw_text="AST 约 15–40 U/L")
    ), disease_key="fatty_liver")
    assert "approximate_calculable_rule" in {item.code for item in approximate.errors}

    ptau = validate_rule(_rule(
        indicator=SimpleNamespace(canonical_key="p-tau217", data_type="numeric", allows_numeric_comparison=True, abnormal_direction="high"),
        unit="pg/mL",
        applicability={},
    ), disease_key="ad")
    assert "ad_biomarker_applicability_missing" in {item.code for item in ptau.errors}
```

- [ ] **Step 2: Run validation tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_validation.py -q
```

Expected: failures for missing interfaces and current empty-version behavior.

- [ ] **Step 3: Extend the validation response contract**

In `backend/app/schemas/standard.py` change `ValidationReport` to:

```python
class ValidationReport(BaseModel):
    errors: list[ValidationFinding] = Field(default_factory=list)
    warnings: list[ValidationFinding] = Field(default_factory=list)
    infos: list[ValidationFinding] = Field(default_factory=list)
    projection_count: int = 0
    calculable_rule_count: int = 0
    blocked_rule_count: int = 0

    @property
    def can_publish(self) -> bool:
        return not self.errors and self.calculable_rule_count > 0 and self.blocked_rule_count == 0
```

- [ ] **Step 4: Implement projection and disease validation**

Add exact direction maps:

```python
AD_DIRECTIONS = {
    "mmse": "ordinal_low",
    "moca": "ordinal_low",
    "cdr": "ordinal_high",
    "nfl": "high",
    "p-tau217": "high",
    "aβ42/aβ40": "low",
}
AD_CONTEXT_REQUIRED = {
    "mmse": {"education", "language", "scale_version"},
    "moca": {"education", "language", "scale_version"},
    "nfl": {"sample", "platform", "method"},
    "p-tau217": {"sample", "platform", "method"},
    "aβ42/aβ40": {"sample", "platform", "method"},
}
```

Implement:

```python
def is_projection_eligible(rule: Any) -> bool:
    indicator = getattr(rule, "indicator", None)
    return (
        getattr(rule, "machine_actionability", None) == "calculable"
        and getattr(rule, "rule_type", None) in {"numeric_range", "threshold"}
        and (getattr(rule, "lower", None) is not None or getattr(rule, "upper", None) is not None)
        and bool(getattr(rule, "unit", None))
        and bool(getattr(indicator, "allows_numeric_comparison", False))
    )
```

`validate_rule()` must add an error when a calculable rule contains approximate source language, when its indicator direction conflicts with `AD_DIRECTIONS`, or when an AD calculable rule lacks any required applicability key. `validate_version_rules()` must add `formal_rules_missing` for an empty list and `calculable_rules_missing` when no rule remains calculable after validation. Count projections with `is_projection_eligible()`, not merely `machine_actionability`.

- [ ] **Step 5: Run validation, lifecycle and schema tests**

Run:

```powershell
python -m pytest backend/tests/test_standard_validation.py backend/tests/test_standard_lifecycle.py backend/tests/test_schema_contracts.py -q
```

Expected: all tests pass after updating existing empty-version expectations to the new approved design.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- backend/app/services/standard_validation.py backend/app/schemas/standard.py backend/tests/test_standard_validation.py backend/tests/test_standard_lifecycle.py backend/tests/test_schema_contracts.py
git commit -m "feat(standards): enforce publishable rule semantics"
```

---

### Task 4: Add a deferred PostgreSQL invariant for current approved versions

**Files:**
- Create: `backend/alembic/versions/0011_standard_current_version_invariant.py`
- Modify: `backend/tests/test_alembic_contracts.py`
- Modify: `database/schema.sql`

**Interfaces:**
- Produces revision `0011`, down revision `0010`.
- Produces PostgreSQL function `enforce_reference_standard_current_version()`.
- Produces deferred constraint triggers `ck_reference_standards_current_version_deferred` and `ck_reference_standard_versions_current_target_deferred`.

- [ ] **Step 1: Write failing migration contract tests**

Add to `backend/tests/test_alembic_contracts.py`:

```python
def test_standard_current_version_invariant_follows_0010(self):
    migration = _load_revision(
        "0011_standard_current_version_invariant.py",
        "migration_0011",
    )
    self.assertEqual(migration.revision, "0011")
    self.assertEqual(migration.down_revision, "0010")


def test_standard_current_version_upgrade_rejects_existing_invalid_pointer(self):
    migration = _load_revision(
        "0011_standard_current_version_invariant.py",
        "migration_0011_guard",
    )
    bind = MagicMock()
    invalid = MagicMock()
    invalid.scalar_one.return_value = 1
    bind.execute.return_value = invalid
    migration_op = MagicMock()
    migration_op.get_bind.return_value = bind
    with patch.object(migration, "op", migration_op):
        with self.assertRaisesRegex(RuntimeError, "invalid current standard version"):
            migration.upgrade()
    executed = "\n".join(str(item.args[0]) for item in bind.execute.call_args_list)
    self.assertIn("current_version_id", executed)


def test_standard_current_version_migration_creates_deferred_constraint_triggers(self):
    source = (BACKEND_ROOT / "alembic/versions/0011_standard_current_version_invariant.py").read_text(encoding="utf-8")
    self.assertIn("DEFERRABLE INITIALLY DEFERRED", source)
    self.assertIn("ck_reference_standards_current_version_deferred", source)
    self.assertIn("ck_reference_standard_versions_current_target_deferred", source)
```

- [ ] **Step 2: Run migration tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_alembic_contracts.py -q
```

Expected: revision file missing.

- [ ] **Step 3: Implement the guarded deferred invariant migration**

Create the revision with an upgrade guard:

```sql
SELECT count(*)
FROM reference_standards rs
LEFT JOIN reference_standard_versions v ON v.id = rs.current_version_id
WHERE rs.current_version_id IS NOT NULL
  AND (v.id IS NULL OR v.standard_id <> rs.id OR v.status <> 'approved')
```

If the count is non-zero, raise:

```python
raise RuntimeError("0011 found invalid current standard version; manual review is required and no rows were changed")
```

Then create this function and triggers using `op.execute(sa.text(...))`:

```sql
CREATE FUNCTION enforce_reference_standard_current_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM reference_standards rs
    LEFT JOIN reference_standard_versions v ON v.id = rs.current_version_id
    WHERE rs.current_version_id IS NOT NULL
      AND (v.id IS NULL OR v.standard_id <> rs.id OR v.status <> 'approved')
  ) THEN
    RAISE EXCEPTION 'current_version_id must reference an approved version of the same standard'
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ck_reference_standards_current_version_deferred
AFTER INSERT OR UPDATE OF current_version_id ON reference_standards
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();

CREATE CONSTRAINT TRIGGER ck_reference_standard_versions_current_target_deferred
AFTER INSERT OR UPDATE OR DELETE ON reference_standard_versions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();
```

Downgrade drops both triggers and then the function. Mirror the terminal DDL in `database/schema.sql`.

- [ ] **Step 4: Run contract tests and isolated PostgreSQL migration verification**

Run contracts:

```powershell
python -m pytest backend/tests/test_alembic_contracts.py backend/tests/test_schema_contracts.py -q
```

For PostgreSQL, require an explicitly isolated database whose name contains `test`:

```powershell
if (-not $env:STANDARD_DOCUMENT_TEST_DATABASE_URL) { throw 'STANDARD_DOCUMENT_TEST_DATABASE_URL is required' }
$uri = [System.Uri]$env:STANDARD_DOCUMENT_TEST_DATABASE_URL
if ($uri.AbsolutePath.TrimStart('/') -notmatch 'test') { throw 'Refusing non-test database target' }
$env:DATABASE_URL = $env:STANDARD_DOCUMENT_TEST_DATABASE_URL
Push-Location backend
alembic upgrade 0010
alembic upgrade 0011
alembic current
alembic downgrade 0010
alembic upgrade 0011
Pop-Location
```

Expected: revision sequence reaches `0011`, downgrades to `0010`, and re-upgrades to `0011`. Add an isolated SQL check proving an invalid pointer fails at commit and a valid same-standard approved pointer commits.

- [ ] **Step 5: Commit Task 4**

```powershell
git add -- backend/alembic/versions/0011_standard_current_version_invariant.py backend/tests/test_alembic_contracts.py database/schema.sql
git commit -m "feat(db): enforce approved current standards"
```

---

### Task 5: Make candidate materialization, publishing, and retiring atomic

**Files:**
- Modify: `backend/app/services/standard_lifecycle.py`
- Modify: `backend/app/api/admin_standards.py`
- Modify: `backend/tests/test_standard_lifecycle.py`
- Modify: `backend/tests/test_admin_standards_api.py`

**Interfaces:**
- Produces: `materialize_candidate(db, *, candidate_id: int, admin_id: int, reason: str) -> StandardRule`.
- Produces: `publish_review_version(db, *, version_id: int, admin_id: int, commit: bool = True) -> PublishResult`.
- Produces: `retire_current_version(db, *, version_id: int, admin_id: int) -> ReferenceStandardVersion`.
- Existing `publish_approved_version()` becomes a compatibility alias calling `publish_review_version()`.
- Service functions own one commit and rollback; API routes never perform a second status commit.

- [ ] **Step 1: Write failing atomic candidate tests**

Add to `backend/tests/test_standard_lifecycle.py`:

```python
def test_materialize_candidate_locks_version_and_updates_candidate_in_one_commit():
    candidate = SimpleNamespace(
        id=5,
        version_id=2,
        segment_id=8,
        status="accepted",
        candidate_json={
            "indicator_name": "alt",
            "rule_type": "numeric_range",
            "target_state_type": "control",
            "machine_actionability": "calculable",
            "numeric": {"lower": 7, "upper": 40, "unit": "U/L"},
        },
    )
    version = SimpleNamespace(id=2, status="review")
    db = AtomicLifecycleSession(candidate=candidate, version=version)
    rule = materialize_candidate(db, candidate_id=5, admin_id=10, reason="逐条审核通过")
    assert candidate.status == "materialized"
    assert rule.version_id == 2
    assert db.commits == 1
    assert db.rollbacks == 0
    assert db.events.index("version:lock") < db.events.index("candidate:lock")


def test_materialize_candidate_rolls_back_rule_and_status_together():
    db = AtomicLifecycleSession(commit_error=RuntimeError("commit failed"))
    with pytest.raises(RuntimeError, match="commit failed"):
        materialize_candidate(db, candidate_id=5, admin_id=10, reason="审核通过")
    assert db.rollbacks == 1
```

The fake session must expose locked version/candidate rows, one `flush`, one `commit`, and rollback counting.

- [ ] **Step 2: Write failing publish/retire transaction tests**

Add focused tests:

```python
def test_publish_rejects_zero_calculable_rules_before_mutation(monkeypatch):
    report = SimpleNamespace(can_publish=False, errors=[SimpleNamespace(code="calculable_rules_missing")])
    monkeypatch.setattr("app.services.standard_lifecycle.validate_version_rules", lambda *args, **kwargs: report)
    db = PublishSession()
    with pytest.raises(ValueError, match="可计算"):
        publish_review_version(db, version_id=2, admin_id=10)
    assert db.commits == 0
    assert db.mutations == []


@pytest.mark.parametrize("failure_point", ["projection", "current_pointer", "audit", "commit"])
def test_publish_failure_rolls_back_every_state(failure_point):
    db, standard, old_version, target_version = publish_session_with_failure(failure_point)
    before = snapshot_publish_state(standard, old_version, target_version, db.projections, db.logs)
    with pytest.raises(RuntimeError):
        publish_review_version(db, version_id=target_version.id, admin_id=10)
    assert db.rollbacks == 1
    assert snapshot_publish_state(standard, old_version, target_version, db.projections, db.logs) == before


def test_retire_current_version_clears_pointer_and_disables_projection():
    db, standard, version, projections = retire_session()
    result = retire_current_version(db, version_id=version.id, admin_id=10)
    assert result.status == "retired"
    assert result.retired_at is not None
    assert standard.current_version_id is None
    assert all(not item.is_current_projection for item in projections)
    assert db.commits == 1


def test_publish_commit_false_flushes_without_committing():
    db, _, _, target_version = publish_session()
    publish_review_version(db, version_id=target_version.id, admin_id=10, commit=False)
    assert db.flushes >= 1
    assert db.commits == 0
```

- [ ] **Step 3: Run lifecycle tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_lifecycle.py backend/tests/test_admin_standards_api.py -q
```

Expected: missing interfaces and current retire behavior failures.

- [ ] **Step 4: Implement single-entry lifecycle services**

`materialize_candidate()` must:

1. Read candidate probe to determine version ID.
2. Lock owning version.
3. Require version status `draft` or `review`.
4. Lock and refresh candidate.
5. Require candidate status `accepted`.
6. Create the formal rule and change log.
7. Set candidate status `materialized`.
8. Commit once; rollback on any exception.

`publish_review_version()` must lock in this order:

```text
target version probe -> owning standard FOR UPDATE -> target version FOR UPDATE
-> previous current version FOR UPDATE -> current projections
```

It must determine `disease_key` from the owning disease, call `validate_version_rules(..., require_calculable=True)`, generate projections only when `is_projection_eligible(rule)` is true, and write a `StandardChangeLog(action="publish")`. With the default `commit=True`, commit once and rollback on failure. With `commit=False`, flush but leave commit/rollback to the caller's explicit transaction so manifest import and publication can be atomic together.

`retire_current_version()` must verify the target is the owning standard's current approved version, set `retired_at`, close projections, clear both relationship and ID, write `StandardChangeLog(action="retire")`, and commit once.

- [ ] **Step 5: Route every mutation through lifecycle services**

In `backend/app/api/admin_standards.py`:

```python
@router.post("/admin/reference-standard-versions/{version_id}/approve", response_model=StandardVersionOut)
def approve_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return publish_review_version(
            db,
            version_id=version_id,
            admin_id=getattr(admin, "id", 0),
        ).version
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/admin/reference-standard-versions/{version_id}/retire", response_model=StandardVersionOut)
def retire_version(version_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    try:
        return retire_current_version(
            db,
            version_id=version_id,
            admin_id=getattr(admin, "id", 0),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

Replace the materialize route's two-commit sequence with one call to `materialize_candidate()`.

- [ ] **Step 6: Run lifecycle/API tests and commit**

Run:

```powershell
python -m pytest backend/tests/test_standard_lifecycle.py backend/tests/test_admin_standards_api.py backend/tests/test_standard_validation.py -q
```

Expected: all pass, including failure injection and one-commit assertions.

Commit:

```powershell
git add -- backend/app/services/standard_lifecycle.py backend/app/api/admin_standards.py backend/tests/test_standard_lifecycle.py backend/tests/test_admin_standards_api.py
git commit -m "fix(standards): make lifecycle mutations atomic"
```

---

### Task 6: Harden resolver applicability and preserve conflict provenance

**Files:**
- Modify: `backend/app/services/standard_resolver.py`
- Modify: `backend/app/services/longitudinal_evidence.py`
- Modify: `backend/tests/test_standard_resolver.py`
- Modify: `backend/tests/test_longitudinal_evidence.py`

**Interfaces:**
- `_context_value()` supports `sex`, `age`, `education`, `language`, `scale_version`, `sample`, `platform`, `method`, `cohort`, `framework`, `tracer` and `device`.
- `ResolvedStandardRules` adds `conflicting_rules: list[Any]`.
- A calculable rule missing required context becomes an evidence copy with `resolution_warning`.
- Two or more equally applicable rules in one `conflict_group` are not auto-selected.

- [ ] **Step 1: Write failing resolver tests**

Add to `backend/tests/test_standard_resolver.py`:

```python
def test_ad_scale_rule_requires_education_language_and_scale_version():
    rule = SimpleNamespace(
        id=20,
        machine_actionability="calculable",
        applicability={"education": "college", "language": "zh-CN", "scale_version": "MMSE-30"},
        indicator=SimpleNamespace(canonical_key="mmse", aliases=[]),
        conflict_group=None,
    )
    version = SimpleNamespace(id=8, status="approved", rules=[rule])
    result = resolve_standard_rules(_db(SimpleNamespace(id=3, current_version=version)), 2, ["MMSE"], {"education": "college"})
    assert result.calculable_rules == []
    assert result.evidence_rules[0].resolution_warning == "缺少适用条件：language, scale_version"


def test_conflicting_matching_thresholds_are_not_auto_selected():
    first = SimpleNamespace(id=30, machine_actionability="calculable", applicability={"cohort": "DELCODE"}, conflict_group="ab-ratio-cohort", indicator=SimpleNamespace(canonical_key="aβ42/aβ40", aliases=[]))
    second = SimpleNamespace(id=31, machine_actionability="calculable", applicability={"cohort": "DELCODE"}, conflict_group="ab-ratio-cohort", indicator=SimpleNamespace(canonical_key="aβ42/aβ40", aliases=[]))
    version = SimpleNamespace(id=9, status="approved", rules=[first, second])
    result = resolve_standard_rules(_db(SimpleNamespace(id=3, current_version=version)), 2, ["Aβ42/Aβ40"], {"cohort": "DELCODE"})
    assert result.calculable_rules == []
    assert {item.id for item in result.conflicting_rules} == {30, 31}
    assert any("冲突" in warning for warning in result.warnings)


def test_resolver_rejects_current_version_from_another_standard():
    version = SimpleNamespace(id=9, standard_id=99, status="approved", rules=[])
    standard = SimpleNamespace(id=3, current_version=version)
    result = resolve_standard_rules(_db(standard), 2, ["ALT"], {})
    assert result.version_id is None
    assert "归属异常" in result.warnings[0]
```

Add to `backend/tests/test_longitudinal_evidence.py`:

```python
def test_standard_conflicts_and_unmatched_rules_are_exposed_as_sources(monkeypatch):
    resolution = SimpleNamespace(
        version_id=12,
        standard_id=3,
        calculable_rules=[],
        evidence_rules=[],
        unmatched_rules=[SimpleNamespace(id=7, applicability={"platform": "A"})],
        conflicting_rules=[SimpleNamespace(id=8, applicability={"cohort": "X"})],
        warnings=["规则冲突，未自动选择"],
    )
    monkeypatch.setattr("app.services.standard_resolver.resolve_standard_rules", lambda *args, **kwargs: resolution)
    sources = build_reference_range_sources(SimpleNamespace(), ["Aβ42/Aβ40"], disease_id=2)
    assert {item["source_type"] for item in sources} == {"standard_unmatched", "standard_conflict", "standard_warning"}
    assert all(item["standard_version_id"] == 12 for item in sources)
```

- [ ] **Step 2: Run resolver/evidence tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_resolver.py backend/tests/test_longitudinal_evidence.py -q
```

Expected: missing `conflicting_rules` and missing source types.

- [ ] **Step 3: Implement complete applicability and conflict handling**

Use stable context aliases:

```python
CONTEXT_ALIASES = {
    "platform": ("platform", "assay_platform", "modality"),
    "method": ("method", "assay", "analysis_method"),
    "sample": ("sample", "specimen", "sample_type"),
    "cohort": ("cohort", "study", "dataset"),
    "scale_version": ("scale_version", "assessment_version"),
    "education": ("education", "education_level"),
    "language": ("language", "assessment_language"),
    "tracer": ("tracer",),
    "device": ("device",),
    "age": ("age",),
    "framework": ("framework",),
}
```

After applicability matching, group matched calculable rules by non-empty `conflict_group`. If a group has more than one match, move all group members to `conflicting_rules`, remove them from `calculable_rules`, and add one deterministic warning containing sorted rule IDs.

Before reading rules, require `version.standard_id == standard.id` and `version.status == "approved"`; otherwise return no version/rules and a warning.

Update `build_reference_range_sources()` to emit `standard_unmatched`, `standard_conflict`, and `standard_warning` objects with version/rule/applicability provenance. Do not fall back to legacy unbound `ReferenceRange` rows when a versioned standard exists but yields only warnings or unmatched rules.

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
python -m pytest backend/tests/test_standard_resolver.py backend/tests/test_longitudinal_evidence.py backend/tests/test_longitudinal_end_to_end.py -q
```

Expected: all pass.

Commit:

```powershell
git add -- backend/app/services/standard_resolver.py backend/app/services/longitudinal_evidence.py backend/tests/test_standard_resolver.py backend/tests/test_longitudinal_evidence.py
git commit -m "feat(standards): preserve applicability conflicts"
```

---

### Task 7: Add read-only manifest tooling and controlled import services

**Files:**
- Create: `backend/app/services/standard_manifest_import.py`
- Create: `backend/app/services/standard_draft_service.py`
- Create: `backend/tests/test_standard_manifest_import.py`
- Create: `backend/tests/test_standard_draft_service.py`
- Create: `scripts/check_standard_manifests.py`
- Create: `scripts/prepare_standard_drafts.py`
- Create: `scripts/apply_standard_manifest.py`
- Create: `scripts/tests/test_check_standard_manifests.py`
- Create: `scripts/tests/test_prepare_standard_drafts.py`
- Create: `scripts/tests/test_apply_standard_manifest.py`

**Interfaces:**
- Produces: `ManifestImportPlan` and `plan_manifest_import(db, *, manifest, version_id) -> ManifestImportPlan`.
- Produces: `import_manifest_rules(db, *, manifest, version_id, admin_id) -> ManifestImportResult`; flushes but does not commit.
- Produces: `DraftPreparationSpec`, `plan_draft_preparation(db, specs)`, `prepare_standard_drafts(db, specs, *, admin_id)`; does not commit.
- Produces three CLIs with dry-run default and explicit `--execute`.

- [ ] **Step 1: Write failing import service tests**

Create `backend/tests/test_standard_manifest_import.py`:

```python
import pytest

from app.services.standard_manifest_import import import_manifest_rules, plan_manifest_import


def test_pending_manifest_is_rejected_before_database_mutation(approved_manifest):
    pending = approved_manifest.model_copy(update={"review_state": "pending", "reviewed_at": None})
    db = ImportSession()
    with pytest.raises(ValueError, match="approved"):
        import_manifest_rules(db, manifest=pending, version_id=4, admin_id=7)
    assert db.added == []
    assert db.flushes == 0


def test_import_plan_counts_only_approved_rule_entries(approved_manifest):
    plan = plan_manifest_import(ImportSession(), manifest=approved_manifest, version_id=4)
    assert plan.indicator_keys == ["alt", "ast"]
    assert plan.rule_entry_ids == ["fatty-alt", "fatty-ast"]
    assert plan.skipped_entry_ids == ["fatty-afp-no-safe-rule", "fatty-plt-rejected"]


def test_import_is_idempotent_by_version_and_manifest_entry_id(approved_manifest):
    db = ImportSession(existing_entry_ids={"fatty-alt"})
    result = import_manifest_rules(db, manifest=approved_manifest, version_id=4, admin_id=7)
    assert result.created_rule_entry_ids == ["fatty-ast"]
    assert result.existing_rule_entry_ids == ["fatty-alt"]
    assert db.commits == 0
```

To make idempotency auditable without a new rule column, store `manifest_entry_id` in each rule's `applicability` under reserved key `_manifest_entry_id`; reject manifests that already use keys beginning with `_`.

- [ ] **Step 2: Write failing draft service tests**

Create `backend/tests/test_standard_draft_service.py`:

```python
def test_draft_plan_matches_documents_by_hash_not_filename(tmp_path):
    source = tmp_path / "renamed.docx"
    source.write_bytes(FATTY_BYTES)
    spec = DraftPreparationSpec(
        dataset="fatty_liver",
        disease_name="脂肪肝",
        source_path=source,
        source_sha256=FATTY_SHA256,
        version_label="fatty-liver-2026-08-25",
        parser_version="v2",
    )
    plan = plan_draft_preparation(DraftSession(), [spec])
    assert plan.items[0].source_hash_matches is True


def test_prepare_two_drafts_does_not_commit_or_own_the_outer_rollback():
    db = DraftSession(fail_on_dataset="ad")
    with pytest.raises(RuntimeError):
        prepare_standard_drafts(db, BOTH_SPECS, admin_id=7)
    assert db.commits == 0
    assert db.rollbacks == 0


def test_parse_draft_replaces_only_unapproved_parse_artifacts():
    db = DraftSession(version_status="draft")
    result = prepare_standard_drafts(db, BOTH_SPECS, admin_id=7)
    assert result.items[0].segment_count > 0
    assert result.items[0].candidate_count > 0
    assert all(version.status == "draft" for version in db.created_versions)
```

- [ ] **Step 3: Run service tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/test_standard_manifest_import.py backend/tests/test_standard_draft_service.py -q
```

Expected: missing modules.

- [ ] **Step 4: Implement transaction-neutral services**

`standard_manifest_import.py` must:

- reject non-approved manifests and any pending entry;
- load and lock the target version, requiring `draft` or `review`;
- create/reuse `StandardIndicator` by exact `canonical_key` while verifying existing metadata is compatible;
- import only entries with `entry_kind="rule"` and `review_status="approved"`;
- skip rejected and `no_safe_rule` entries;
- put `_manifest_entry_id` and `_manifest_sha256` into a copied applicability dict;
- create `StandardRuleCondition` trees when conditions are non-empty;
- write a `StandardChangeLog(action="manifest_import")` per new rule;
- call `db.flush()` but never commit or rollback.

`standard_draft_service.py` must:

- match/create `StandardDocument` by exact SHA-256;
- verify source bytes before any ORM mutation;
- create a disease standard collection if absent;
- create a new draft only when the document is unlocked;
- parse with `parse_standard_docx()` and persist segments/candidates;
- never accept/materialize candidates;
- never commit or rollback.

- [ ] **Step 5: Write failing CLI contract tests**

Each script test loads the script with `importlib.util` and verifies:

```python
def test_cli_defaults_to_dry_run(script, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(script, "execute_changes", lambda *args, **kwargs: calls.append("execute"))
    monkeypatch.setattr(script, "build_plan", lambda *args, **kwargs: {"status": "dry_run"})
    assert script.main(["--manifest", "x.json"]) == 0
    assert calls == []
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"


def test_execute_path_rolls_back_on_failure(script, monkeypatch):
    transaction = FakeTransaction()
    monkeypatch.setattr(script, "open_transaction", lambda: FakeContext(transaction))
    monkeypatch.setattr(script, "execute_changes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")))
    assert script.main(["--manifest", "x.json", "--execute"]) == 2
    assert transaction.rollbacks == 1
    assert transaction.commits == 0
```

`check_standard_manifests.py` must support:

```text
--manifest PATH --source PATH --review-output PATH [--write-review | --check]
```

`prepare_standard_drafts.py` must require both `--fatty-source` and `--ad-source`, validate the fixed hashes, and prepare both diseases in one transaction only with `--execute`.

`apply_standard_manifest.py` must support one disease per invocation:

```text
--manifest PATH --source PATH --version-id ID --admin-id ID
[--import-rules] [--publish] [--execute]
```

`--publish` implies a fresh validation after import and uses `publish_review_version(..., commit=False)` in the same explicit transaction boundary. The script must not call a service that commits internally on this path.

- [ ] **Step 6: Implement the three UTF-8 JSON CLIs**

All CLIs must:

- configure stdout UTF-8;
- print one JSON document;
- return `0` for valid dry-run/success, `1` for business validation blockers, `2` for tool/database errors;
- omit exception details and credentials;
- use one explicit transaction for execute mode;
- rollback on failure and dispose the engine.

- [ ] **Step 7: Run service and CLI tests, then commit**

Run:

```powershell
python -m pytest backend/tests/test_standard_manifest_import.py backend/tests/test_standard_draft_service.py scripts/tests/test_check_standard_manifests.py scripts/tests/test_prepare_standard_drafts.py scripts/tests/test_apply_standard_manifest.py -q
```

Expected: all pass.

Commit:

```powershell
git add -- backend/app/services/standard_manifest_import.py backend/app/services/standard_draft_service.py backend/tests/test_standard_manifest_import.py backend/tests/test_standard_draft_service.py scripts/check_standard_manifests.py scripts/prepare_standard_drafts.py scripts/apply_standard_manifest.py scripts/tests/test_check_standard_manifests.py scripts/tests/test_prepare_standard_drafts.py scripts/tests/test_apply_standard_manifest.py
git commit -m "feat(standards): add controlled manifest workflow"
```

---

### Task 8: Author pending dual-disease manifests and generated review documents

**Files:**
- Create: `standard_manifests/fatty_liver.v1.json`
- Create: `standard_manifests/ad.v1.json`
- Create: `docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md`
- Create: `docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md`

**Interfaces:**
- Consumes strict manifest schema and the two fixed source hashes.
- Produces complete `pending` review packages; no database writes.

- [ ] **Step 1: Populate the fatty-liver pending manifest from exact source rows**

Create at least one explicit entry or `no_safe_rule` conclusion for each canonical key:

```text
alt, ast, ggt, tbil, alb, plt, afp, hba1c, bmi, waist
```

Required conservative starting decisions before owner review:

- ALT/AST/GGT approximate ranges: `evidence-only`.
- PLT “按实验室参考范围”: `no_safe_rule` or evidence-only, never calculable.
- AFP when no exact source rule exists: `no_safe_rule`.
- Sex-specific ALT/GGT/waist content: separate male/female entries.
- TBIL/ALB/HbA1c/BMI exact-looking rows: remain `pending`; do not mark manifest approved.

Every entry must use the actual table/row coordinates and exact `raw_text` from `fatty_liver_standard.docx`.

- [ ] **Step 2: Populate the AD pending manifest from exact source rows**

Create at least one explicit entry or `no_safe_rule` conclusion for:

```text
mmse, moca, cdr, nfl, p-tau217, aβ42/aβ40
```

Required conservative starting decisions before owner review:

- MMSE/MoCA common cutoffs: evidence-only unless education, language and scale version are explicitly supplied.
- CDR: separate ordinal classification entries; never treat as an ordinary high laboratory value.
- NfL: evidence-only if source provides direction without platform/method/sample threshold.
- p-tau217: evidence-only when the source threshold lacks a named platform/method.
- Aβ42/Aβ40: separate plasma direction evidence from CSF cohort thresholds; retain cohort conflict groups.
- DELCODE and ADNI/ActiGliA thresholds: separate entries, never a combined range.

Every entry must use exact coordinates and `raw_text` from `ad_standard.docx`.

- [ ] **Step 3: Run manifest lint in pending mode**

Run:

```powershell
python scripts/check_standard_manifests.py --manifest standard_manifests/fatty_liver.v1.json --source backend/tests/fixtures/standards/fatty_liver_standard.docx --review-output docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md --write-review
python scripts/check_standard_manifests.py --manifest standard_manifests/ad.v1.json --source backend/tests/fixtures/standards/ad_standard.docx --review-output docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md --write-review
```

Expected: JSON says schema/hash/source/coverage checks pass while overall review state remains `pending`; generated Markdown files are UTF-8 and deterministic.

- [ ] **Step 4: Verify generated review documents are current**

Run:

```powershell
python scripts/check_standard_manifests.py --manifest standard_manifests/fatty_liver.v1.json --source backend/tests/fixtures/standards/fatty_liver_standard.docx --review-output docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md --check
python scripts/check_standard_manifests.py --manifest standard_manifests/ad.v1.json --source backend/tests/fixtures/standards/ad_standard.docx --review-output docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md --check
```

Expected: both exit `0` and report no Markdown drift.

- [ ] **Step 5: Commit the pending review packages**

```powershell
git add -- standard_manifests/fatty_liver.v1.json standard_manifests/ad.v1.json docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md
git commit -m "docs(standards): add dual-disease rule reviews"
```

- [ ] **Step 6: STOP for project-owner medical review**

Provide the two Markdown paths, source hashes, entry counts and proposed calculable/evidence-only/no-safe-rule counts. Do not change `review_state` to approved and do not execute Task 10 until the project owner explicitly approves the review packages or requests changes. This medical-review stop does not itself authorize any database write; Task 9 may proceed independently only after its own dry-run and explicit checkpoint-one authorization.

---

### Task 9: Database checkpoint one — create and parse fresh draft versions

**Files:**
- No code changes expected.
- Database writes only after explicit checkpoint authorization.

**Interfaces:**
- Consumes approved implementation code and the two fixed source files; medical manifests may still be `pending` because this checkpoint creates no formal rule.
- Produces one fresh parsed draft per disease, without formal rules or approval.

- [ ] **Step 1: Capture the fresh read-only baseline**

Run:

```powershell
python scripts/check_longitudinal_readiness.py
$baselineExit = $LASTEXITCODE
Write-Output "READINESS_EXIT=$baselineExit"
```

Save only a non-sensitive summary: standard IDs, current version IDs/statuses, version/rule/candidate counts, document IDs/hashes and readiness reason codes.

- [ ] **Step 2: Run draft preparation dry-run**

Run:

```powershell
python scripts/prepare_standard_drafts.py `
  --fatty-source backend/tests/fixtures/standards/fatty_liver_standard.docx `
  --ad-source backend/tests/fixtures/standards/ad_standard.docx `
  --fatty-version-label fatty-liver-2026-08-25 `
  --ad-version-label ad-2026-08-25 `
  --parser-version v2 `
  --admin-id $adminId
```

Before running, require an explicitly supplied authorized administrator ID:

```powershell
if (-not $env:STANDARD_ADMIN_ID) { throw 'STANDARD_ADMIN_ID is required' }
$adminId = [int]$env:STANDARD_ADMIN_ID
```

Expected dry-run:

- fatty source reuses unlocked document hash `f0e1b1dd3b3da14e214711438060a0a7f42a3461a446db63963b35cc99d94fba`;
- AD source creates or reuses document hash `96222b951522cdbb7ef211b226d95659e9dc624e684cb88240d36267d816f9df`;
- one draft version per disease;
- no formal rules, no current pointer update and no projections;
- no database commit.

- [ ] **Step 3: STOP and request checkpoint-one authorization**

Present the exact dry-run JSON. Do not pass `--execute` until the project owner explicitly authorizes this database write.

- [ ] **Step 4: Execute both draft preparations in one transaction**

After authorization, rerun the same command with `--execute`.

Expected:

- both drafts and their parsed segments/candidates commit together;
- both remain `draft`;
- current pointers remain null;
- no formal rules or projections are created.

- [ ] **Step 5: Verify checkpoint-one state read-only**

Run a read-only audit and assert:

- source hashes match the pending or approved manifests;
- each document is linked to exactly one new draft;
- parsed segments exist and retain coordinates;
- all candidates remain pending/failed, never accepted/materialized;
- `standard_rules`, `standard_rule_conditions` and current projections remain unchanged.

Record the two target version IDs for Task 11.

---

### Task 10: Apply project-owner review decisions and verify approved manifests

**Files:**
- Modify: `standard_manifests/fatty_liver.v1.json`
- Modify: `standard_manifests/ad.v1.json`
- Regenerate: both Markdown review documents

**Interfaces:**
- Consumes only explicit project-owner decisions from the Task 8 medical review.
- Produces two approved manifest packages ready for database import dry-run.

- [ ] **Step 1: Apply only explicit owner decisions**

For every entry, set `review_status` to `approved` or `rejected` and record the owner's reason in `review_note`. Do not change source text, values, boundaries, units, applicability or actionability unless the owner explicitly requested that exact change.

Only after all entries are resolved, set `review_state` to `approved` and set `reviewed_at` to the actual UTC time at which the project owner approved the package. Generate that value at execution time:

```powershell
$reviewedAtUtc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
Write-Output $reviewedAtUtc
```

Copy that exact emitted value into `reviewed_at`; do not pre-populate or invent a timestamp.

- [ ] **Step 2: Run approved-manifest gates**

Run both lint/check commands from Task 8. Expected for each disease:

- no pending entries;
- source hash matches;
- all core indicators have an explicit conclusion;
- at least one approved calculable rule;
- zero approved blocked rules;
- Markdown exactly matches the approved manifest.

If either disease has zero safe calculable rules, stop and report P0-02 blocked. Do not continue to Task 11.

- [ ] **Step 3: Commit approved review decisions**

```powershell
git add -- standard_manifests/fatty_liver.v1.json standard_manifests/ad.v1.json docs/superpowers/reviews/2026-08-25-fatty-liver-standard-rules-review.md docs/superpowers/reviews/2026-08-25-ad-standard-rules-review.md
git commit -m "docs(standards): approve reviewed standard rules"
```

---

### Task 11: Database checkpoint two — import reviewed rules and atomically publish

**Files:**
- No code changes expected unless verification exposes a scoped defect; any fix must start with a failing test and a separate commit.

**Interfaces:**
- Consumes approved manifests and the two draft version IDs.
- Produces current approved versions, formal rules, conditions, audit logs and safe projections.

- [ ] **Step 1: Dry-run each approved manifest import**

Run once per disease without `--execute`:

```powershell
$adminId = [int]$env:STANDARD_ADMIN_ID
$fattyDraftVersionId = [int]$env:FATTY_DRAFT_VERSION_ID
$adDraftVersionId = [int]$env:AD_DRAFT_VERSION_ID

python scripts/apply_standard_manifest.py `
  --manifest standard_manifests/fatty_liver.v1.json `
  --source backend/tests/fixtures/standards/fatty_liver_standard.docx `
  --version-id $fattyDraftVersionId `
  --admin-id $adminId `
  --import-rules --publish

python scripts/apply_standard_manifest.py `
  --manifest standard_manifests/ad.v1.json `
  --source backend/tests/fixtures/standards/ad_standard.docx `
  --version-id $adDraftVersionId `
  --admin-id $adminId `
  --import-rules --publish
```

Expected dry-run fields:

- target disease/version identity;
- source and manifest hashes;
- new/reused canonical indicators;
- approved rules by actionability/type;
- rejected/no-safe-rule entries skipped;
- condition count;
- projection-eligible rule count;
- validation findings;
- expected current pointer transition.

- [ ] **Step 2: STOP and request checkpoint-two authorization**

Present both dry-run summaries. Do not execute either publish until the project owner explicitly authorizes the formal database write.

- [ ] **Step 3: Execute fatty-liver import and publish**

After authorization, run the fatty command with `--execute`.

Expected one transaction:

- formal indicators/rules/logs imported;
- version moves draft -> review -> approved through the controlled service;
- current pointer becomes the target version;
- only projection-eligible calculable rules create current `reference_ranges` rows;
- failure rolls back the whole disease transaction.

- [ ] **Step 4: Verify fatty-liver state before AD execution**

Run read-only checks for version status, current pointer, rule counts, projection provenance and resolver behavior. If any assertion fails, stop; do not publish AD until the defect is understood and corrected with TDD.

- [ ] **Step 5: Execute AD import and publish**

Run the AD command with `--execute`, then perform the same read-only assertions. AD rules lacking operator context must resolve as evidence-only/warnings even if their stored rule is calculable under explicit applicability.

- [ ] **Step 6: Verify transaction failure protection in an isolated database**

Before declaring completion, use the isolated test database to inject failures at projection creation and current pointer update. Verify the database contains no partially approved version, no stale current projection and no partial audit log.

---

### Task 12: Final verification, roadmap evidence, and completion record

**Files:**
- Modify: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`

**Interfaces:**
- Records exact P0-02 implementation and verification evidence only after all checks pass.

- [ ] **Step 1: Run focused standard tests**

Run:

```powershell
python -m pytest `
  backend/tests/test_standard_manifest.py `
  backend/tests/test_standard_manifest_import.py `
  backend/tests/test_standard_draft_service.py `
  backend/tests/test_standard_parser.py `
  backend/tests/test_standard_validation.py `
  backend/tests/test_standard_lifecycle.py `
  backend/tests/test_standard_resolver.py `
  backend/tests/test_longitudinal_evidence.py `
  backend/tests/test_admin_standards_api.py `
  backend/tests/test_alembic_contracts.py `
  scripts/tests/test_check_standard_manifests.py `
  scripts/tests/test_prepare_standard_drafts.py `
  scripts/tests/test_apply_standard_manifest.py -q
```

Expected: all pass with zero failures.

- [ ] **Step 2: Run related backend regressions**

Run:

```powershell
python -m pytest `
  backend/tests/test_admin_standard_documents_api.py `
  backend/tests/test_standard_models.py `
  backend/tests/test_seed_standard_drafts.py `
  backend/tests/test_longitudinal_readiness_schema.py `
  backend/tests/test_longitudinal_readiness_service.py `
  backend/tests/test_longitudinal_prediction_contract.py `
  backend/tests/test_longitudinal_end_to_end.py `
  backend/tests/test_database_baseline.py -q
```

Expected: all pass. A pre-existing unrelated failure must be reported before changing unrelated code.

- [ ] **Step 3: Verify both approved manifests and review documents**

Run the two `check_standard_manifests.py --check` commands. Expected: approved state, no pending entries, source hash match, core coverage complete, at least one approved calculable rule per disease and no Markdown drift.

- [ ] **Step 4: Run the real database baseline and readiness commands**

Run:

```powershell
python scripts/check_database_readonly.py
python scripts/check_longitudinal_readiness.py
$readinessExit = $LASTEXITCODE
Write-Output "READINESS_EXIT=$readinessExit"
```

Expected:

- database revision and code head are `0011`;
- both diseases have a current approved version;
- both versions have formal and calculable rules;
- standard-related reason codes `approved_standard_missing` and `calculable_standard_rules_missing` are absent;
- overall readiness remains `blocked` because P0-04 outcome artifacts are still missing;
- readiness exit remains `1`, proving P0-02 did not mask later blockers.

- [ ] **Step 5: Verify resolver provenance for all core indicators**

Run a read-only resolver audit for each core indicator and assert every result is one of:

- calculable rule with version/rule/applicability provenance;
- evidence-only rule with provenance and limitation;
- unmatched/conflict result with explicit warning;
- approved `no_safe_rule` conclusion recorded in the review package.

No core indicator may silently disappear.

- [ ] **Step 6: Update the P0-02 roadmap card**

Under `### P0-02：修复并发布双疾病参考标准`, add:

```markdown
**状态**：`completed`
**Task-ID**：`longitudinal-standards-001`
**设计文档**：`docs/superpowers/specs/2026-08-25-longitudinal-standards-design.md`
**实施计划**：`docs/superpowers/plans/2026-08-25-longitudinal-standards.md`
**验证记录**：脂肪肝与 AD 均已发布 current approved 标准版本；正式规则由已批准 manifest 导入，候选未批量发布；current 指针、原子发布、适用性和投影验证通过。`python scripts/check_longitudinal_readiness.py` 中标准相关阻塞已消失，P0-04 模型缺口仍保持可见。
```

Replace the summary with actual version IDs, rule/projection counts and verification results if they differ; never invent counts.

- [ ] **Step 7: Run final diff, status, and sensitive-output checks**

Run:

```powershell
git diff --check
git status --short
python scripts/check_longitudinal_readiness.py 2>$null | Select-String -Pattern 'postgresql://|password|Traceback|patient_label|P001|A001'
```

Expected: no whitespace errors, only expected task files before the documentation commit, and no sensitive matches.

- [ ] **Step 8: Commit final verification evidence**

```powershell
git add -- docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md docs/superpowers/plans/2026-08-25-longitudinal-standards.md
git commit -m "docs(standards): record P0-02 verification"
```

- [ ] **Step 9: Run final clean verification**

Repeat the focused and regression commands, database baseline, manifest checks and readiness command from a clean repository state. Do not claim P0-02 complete unless all commands were run after the final code/document commit and their outputs were read.

---

## Completion Gate

Do not mark P0-02 complete until all of the following are true:

- Two approved manifest packages exist and exactly regenerate their Markdown review documents.
- Every core indicator has an explicit owner-reviewed conclusion.
- No pending, blocked or unreviewed entry is imported.
- Both diseases have at least one safe, reviewed calculable formal rule.
- Approximate, laboratory-specific or context-incomplete text is not treated as a generic threshold.
- AD cognitive scales, CDR and biochemical markers use distinct abnormal directions.
- Current pointers are protected by service validation, a deferred PostgreSQL invariant and resolver checks.
- Candidate materialization, publishing and retiring are atomic and audited.
- Empty/zero-calculable versions cannot publish.
- Evidence-only and non-projection calculable classifications do not create invalid `reference_ranges` rows.
- Publishing failure leaves no partial version, projection, current pointer or audit state.
- Both real source hashes match the published manifests and version documents.
- `python scripts/check_longitudinal_readiness.py` no longer reports P0-02 standard blockers for either disease.
- P0-04/P0-07 and optional model gaps remain accurately visible.
- Focused tests, related regressions, migration verification, manifest checks and real read-only database checks all pass.
