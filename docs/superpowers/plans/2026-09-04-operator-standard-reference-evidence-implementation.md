# AI 操作者第 5 项：疾病标准与参考病例证据层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为脂肪肝和 AD 的 AI 操作者纵向报告建立可追溯、可复现、隐私安全的正式标准与参考病例证据层，并让网页、历史报告和 PDF 使用同一不可变证据快照。

**Architecture:** 报告创建后先固定并校验当前批准标准和活动参考数据版本，标准不可用时在模型调用前失败；模型完成原始推理后，独立证据服务解析标准、筛选参考窗口、执行确定性复排并生成 `EvidenceBundle v1`。信号解释、兼容 `sources`、正文、前端和 PDF 全部从该快照派生，旧报告继续走只读兼容路径。

**Tech Stack:** Python 3.11、FastAPI、Pydantic v2、SQLAlchemy、Alembic、PostgreSQL JSONB/GIN、pytest、Vue 3、TypeScript、Element Plus、Vitest、Playwright、Jinja2。

## Global Constraints

- 设计基线：`docs/superpowers/specs/2026-09-04-operator-standard-reference-evidence-design.md`，实现不得静默偏离。
- 仅覆盖 AI 操作者电脑端、脂肪肝 `fatty_liver` 和阿尔茨海默病 `ad`。
- 正式标准来源固定为 `backend/tests/fixtures/standards/fatty_liver_standard.docx`、`backend/tests/fixtures/standards/ad_standard.docx` 及对应已批准 `standard_manifests/*.v1.json`。
- 标准缺失、文档/版本/归属/哈希完整性失败、标准查询失败必须在模型调用前阻止报告。
- AD 当前八条规则始终为 `evidence-only`，不得输出通用数值异常、确诊或必然进展判断。
- 正式参考病例只允许非合成、来源可追溯、匿名编号合法、活动 release 内且结局来源为批准白名单的窗口；P151–P300、生成结局和推断结局全部排除。
- 相似度算法固定为 `reference_similarity.v1`：八维权重 `20/10/5/15/20/20/5/5`，`coverage >= 0.60`、`ranking_score >= 50`、至少一个核心指标、最多五例、最多五百个 Python 候选。
- 参考病例后续结局不得进入准入后的评分、模型输入或当前病例信号判断，只能在排序完成后展示。
- 标准失败为硬失败；无合格病例和可比性不足是正常完成状态；参考查询失败或索引过期生成 `partial` 报告并明确警告。
- `EvidenceBundle v1` 使用 `extra="forbid"`、ISO 8601、分数六位小数和稳定 SHA-256；哈希时将自身声明置为 `null`。
- 新报告的输入、预测、证据、正文和完整性指纹必须在同一次终态事务中保存；旧报告不回填、不重算。
- API、日志、SSE、页面和 PDF 不得暴露 `patient_label`、原始自由文本病历、SQL、文件绝对路径或底层异常正文。
- 所有 UI 修改前复核 `docs/DESIGN_SPEC.md`，使用其暖杏蓝变量、`880px` 内容宽度、状态文字/图标/颜色三重表达、键盘焦点和 reduced-motion 规范。
- 数据库变更仅使用向后兼容新增结构；生产部署前只执行只读预检，迁移和正式窗口构建必须处于单独部署窗口。

## 执行状态（2026-09-04）

- Task 1～13：仓库实现及相应单元/组件测试已完成；最终加固提交为 `e919e76`。
- Task 14：真实 PostgreSQL 场景已落为可执行集成测试，10,000 次评分性能验收已通过；因当前未设置 `TEST_DATABASE_URL`，PostgreSQL 执行和电脑端浏览器 E2E/PDF 视觉验收留在部署窗口。
- Task 15：只读 preflight/postflight 门禁、仓库分层回归和第 5 项审计记录已完成；当前配置数据库处于 revision `0019`，preflight 对代码 head `0022` 正确返回 `FAIL`。
- Task 16：未执行。必须在有备份、目标数据库凭据和维护窗口时依次完成迁移、标准激活、参考窗口构建、postflight、双病种冒烟与回滚验证。
- 仓库完成不等于生产上线；Task 16 全部通过前不得把生产状态标记为完成。

---

## 文件结构

- Create: `backend/app/schemas/longitudinal_evidence.py` — `EvidenceBundle v1`、标准证据、参考窗口与评分的唯一严格契约。
- Create: `backend/app/services/standard_evidence.py` — v1 条件适配、指标级上下文、标准完整性预检和来源证据。
- Create: `backend/app/services/reference_case_eligibility.py` — 匿名编号、来源、合成状态、结局白名单和稳定排除码。
- Create: `backend/app/services/reference_case_windows.py` — 防未来信息泄漏的 365 天窗口构建、幂等持久化和活动索引读取。
- Create: `backend/app/services/reference_case_similarity.py` — `reference_similarity.v1` 八维确定性评分与稳定排序。
- Create: `backend/app/services/evidence_bundle.py` — 版本固定、一次重试、参考降级、快照规范化和兼容投影。
- Modify: `backend/app/services/longitudinal_signal_interpreter.py` — 从标准证据规则解释观察信号，不再依赖松散来源字典。
- Modify: `backend/app/services/longitudinal_prediction.py` — 只产生原始模型结果，不接收标准或参考病例结果。
- Modify: `backend/app/services/longitudinal_report_generator.py` — 模型后构建证据、解释信号、渲染正文并原子保存。
- Modify: `backend/app/services/report_integrity.py` — 将证据快照加入生成指纹和读取校验。
- Modify: `backend/app/core/config.py` — 标准与参考病例数据库查询的独立毫秒超时。
- Modify: `backend/app/api/operator.py` — 标准预检、稳定硬失败、证据 SSE、报告详情和 PDF 快照传递。
- Modify: `backend/app/schemas/operator.py` — 新证据字段的历史兼容响应。
- Modify: `backend/app/schemas/operator_visit_context.py` — 新增独立 `assay_platform`。
- Modify: `backend/app/db/models.py` — `ReferenceCaseWindow`、标准引用字段和报告证据字段。
- Create: `backend/alembic/versions/0022_operator_report_evidence.py` — 证据层新增结构和无损降级保护。
- Modify: `database/schema.sql` — 干净安装结构与 `0022` 对齐。
- Create: `scripts/build_reference_case_windows.py` — 默认 dry-run、显式 `--apply` 的幂等构建工具。
- Modify: `scripts/check_database_readonly.py` — 迁移前后结构、完整性和索引只读门禁。
- Modify: `frontend/src/api/operator.ts` — `EvidenceBundle v1` 严格 TypeScript 类型、SSE 和上下文字段。
- Modify: `frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue` — 检测平台录入。
- Create: `frontend/src/components/LongitudinalEvidenceSection.vue` — 正式标准和参考病例结构化证据区。
- Modify: `frontend/src/components/LongitudinalReportView.vue` — 新旧报告路由和证据组件集成。
- Modify: `backend/app/services/pdf_generator.py`、`backend/app/templates/report_pdf.html` — 从快照生成打印证据卡片和技术追溯。
- Create/Modify tests under `backend/tests/`, `backend/tests/integration/`, `backend/tests/e2e/`, `scripts/tests/`, `frontend/src/**/__tests__/` and `frontend/tests/` as named in each task.
- Modify: `docs/AI操作者流程核查.md` — 仅在实现和验证完成后记录第 5 项仓库完成状态及生产门禁。

### Task 1: 固定 `EvidenceBundle v1` 与自验证哈希契约

**Files:**
- Create: `backend/app/schemas/longitudinal_evidence.py`
- Create: `backend/app/services/evidence_bundle.py`
- Create: `backend/tests/test_longitudinal_evidence_schema.py`

**Interfaces:**
- Consumes: 严格、已脱敏的标准证据和参考病例结果。
- Produces: `EvidenceBundle`、`StandardEvidence`、`ReferenceCaseEvidence`、`ReferenceCaseWindowWrite`、`ReferenceCaseFeatureProfile`、`ReferenceCaseProfile`、`ReferenceCaseSelection`；`finalize_evidence_bundle(bundle) -> EvidenceBundle`；`verify_evidence_bundle(bundle) -> bool`。

- [ ] **Step 1: Write the failing schema and hash tests**

在 `backend/tests/test_longitudinal_evidence_schema.py` 建立最小合法 bundle fixture，并加入以下核心断言：

```python
from pydantic import ValidationError

from app.schemas.longitudinal_evidence import EvidenceBundle
from app.services.evidence_bundle import finalize_evidence_bundle, verify_evidence_bundle


def test_bundle_forbids_unknown_fields_and_hashes_without_self_reference(bundle_payload):
    payload = dict(bundle_payload)
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(payload)

    bundle = finalize_evidence_bundle(EvidenceBundle.model_validate(bundle_payload))
    assert bundle.integrity.evidence_snapshot_sha256 is not None
    assert verify_evidence_bundle(bundle) is True
    changed = bundle.model_copy(update={"warnings": ["changed"]})
    assert verify_evidence_bundle(changed) is False


def test_reference_case_schema_has_no_identity_label(bundle_payload):
    case = bundle_payload["reference_cases"]["cases"][0]
    case["patient_label"] = "forbidden"
    with pytest.raises(ValidationError):
        EvidenceBundle.model_validate(bundle_payload)
```

- [ ] **Step 2: Run the tests and confirm the contract is absent**

Run from `backend`: `python -m pytest tests/test_longitudinal_evidence_schema.py -q`

Expected: FAIL with import errors for `app.schemas.longitudinal_evidence` and `finalize_evidence_bundle`.

- [ ] **Step 3: Implement the strict models**

Define a shared strict base and exact top-level states in `backend/app/schemas/longitudinal_evidence.py`:

```python
class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceIntegrity(StrictEvidenceModel):
    canonicalization_version: Literal["v1"] = "v1"
    hash_algorithm: Literal["sha256"] = "sha256"
    evidence_snapshot_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )


class EvidenceBundle(StrictEvidenceModel):
    schema_version: Literal["longitudinal_evidence_bundle.v1"] = (
        "longitudinal_evidence_bundle.v1"
    )
    evidence_bundle_id: UUID
    generation_batch_id: UUID
    disease_code: Literal["fatty_liver", "ad"]
    created_at: datetime
    standard: StandardEvidence
    reference_cases: ReferenceCaseEvidence
    warnings: list[str] = Field(default_factory=list)
    integrity: EvidenceIntegrity = Field(default_factory=EvidenceIntegrity)
```

同文件完整定义以下子模型及枚举：`EvidenceDocument`、`EvidenceVersion`、`EvidenceSourceLocator`、`EvidenceConditionDecision`、`StandardRuleEvidence`、`StandardEvidence`、`ReferenceDataRelease`、`ReferenceFeatureComparison`、`ReferenceCaseScoreBreakdown`、`ReferenceCaseWindowWrite`、`ReferenceCaseFeatureProfile`、`ReferenceCaseProfile`、`ReferencePoolStatistics`、`ReferenceCaseEvidence`。`ReferenceCaseWindowWrite` 与 Task 3 持久化列一一对应；`ReferenceCaseFeatureProfile` 只包含人口学、阶段、窗口特征和检测上下文，不含任何结局；`ReferenceCaseProfile` 组合匿名编号、`features`、比较项、评分、后续结局和脱敏来源，不定义 `patient_label`。

- [ ] **Step 4: Implement canonicalization and self-excluding SHA-256**

在 `backend/app/services/evidence_bundle.py` 加入：

```python
def canonicalize_evidence_bundle(bundle: EvidenceBundle) -> bytes:
    payload = bundle.model_dump(mode="json")
    payload["integrity"]["evidence_snapshot_sha256"] = None
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def finalize_evidence_bundle(bundle: EvidenceBundle) -> EvidenceBundle:
    digest = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    integrity = bundle.integrity.model_copy(
        update={"evidence_snapshot_sha256": digest}
    )
    return bundle.model_copy(update={"integrity": integrity})


def verify_evidence_bundle(bundle: EvidenceBundle) -> bool:
    declared = bundle.integrity.evidence_snapshot_sha256
    if declared is None:
        return False
    actual = hashlib.sha256(canonicalize_evidence_bundle(bundle)).hexdigest()
    return hmac.compare_digest(declared, actual)
```

所有分数字段使用字段验证器量化为六位小数，拒绝 NaN 和 Infinity；所有 UTC 时间序列化为带时区 ISO 8601。

- [ ] **Step 5: Run focused tests and commit**

Run from `backend`: `python -m pytest tests/test_longitudinal_evidence_schema.py -q`

Expected: PASS.

```bash
git add backend/app/schemas/longitudinal_evidence.py backend/app/services/evidence_bundle.py backend/tests/test_longitudinal_evidence_schema.py
git commit -m "feat: define longitudinal evidence bundle contract"
```

### Task 2: 实现指标级上下文和类型化标准条件

**Files:**
- Modify: `backend/app/schemas/operator_visit_context.py:8-36`
- Create: `backend/app/services/standard_evidence.py`
- Modify: `backend/tests/test_operator_visit_context.py`
- Create: `backend/tests/test_standard_evidence_conditions.py`

**Interfaces:**
- Consumes: `case: Mapping[str, Any]`、已按日期规范化的 `visits`、规则 `applicability: dict[str, Any]`。
- Produces: `build_indicator_contexts(case, visits) -> dict[str, IndicatorContext]`；`adapt_v1_applicability(value) -> ConditionNode`；`evaluate_condition(node, context) -> ConditionDecision`。

- [ ] **Step 1: Write failing context and predicate tests**

```python
def test_required_means_present_and_not_literal_required():
    node = adapt_v1_applicability({"platform": "required"})
    decision = evaluate_condition(node, {"assay_platform": "Roche cobas"})
    assert decision.status == "matched"


def test_latest_indicator_uses_its_own_visit_context():
    contexts = build_indicator_contexts(
        {"age": 67, "sex": "female", "baseline_stage": "mci", "disease_code": "ad"},
        [
            {"visit_date": "2025-01-01", "visit_context": {"assay_platform": "A"},
             "indicators": [{"name": "nfl", "value": 20, "unit": "pg/mL"}]},
            {"visit_date": "2025-06-01", "visit_context": {"assay_platform": "B"},
             "indicators": [{"name": "mmse", "value": 24, "unit": "分"}]},
        ],
    )
    assert contexts["nfl"].assay_platform == "A"
    assert contexts["mmse"].assay_platform == "B"
```

同时测试 `equals`、`in`、开闭 `range`、`all`、`any`、`not`，并验证结果严格区分 `matched`、`missing`、`mismatched`。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_operator_visit_context.py tests/test_standard_evidence_conditions.py -q`

Expected: FAIL because `assay_platform` and the typed evaluator do not exist.

- [ ] **Step 3: Extend the visit context without conflating device and platform**

在 `VisitContext` 增加字段，并把它加入现有文本规范化 validator：

```python
assay_platform: str | None = Field(None, max_length=200)
```

不要从 `device_name` 自动回填 `assay_platform`。自由文本 `notes`、`treatment_change`、`diagnosis_change` 不进入条件上下文。

- [ ] **Step 4: Implement typed nodes, v1 adaptation, and latest-observation context**

在 `standard_evidence.py` 定义判别联合：

```python
ConditionNode = PresentNode | EqualsNode | InNode | RangeNode | AllNode | AnyNode | NotNode


def adapt_v1_applicability(value: dict[str, Any]) -> AllNode:
    children: list[ConditionNode] = []
    for field, expected in sorted(value.items()):
        if field in NON_CLINICAL_APPLICABILITY_KEYS:
            continue
        if expected == "required":
            children.append(PresentNode(field=field))
        elif isinstance(expected, list):
            children.append(InNode(field=field, values=expected))
        else:
            children.append(EqualsNode(field=field, value=expected))
    return AllNode(children=children)
```

`build_indicator_contexts` 使用 `sort_visits`，逐指标覆盖为最近一次有效观察的上下文；输出病例级字段、canonical code/unit、观察日期、`assay_platform`、方法、样本、量表版本、语言、教育信息和 `measurement_context_changed`。字段别名只用于读取规则键，不能把设备、方法、平台和样本互相推断。

- [ ] **Step 5: Run focused tests and commit**

Run from `backend`: `python -m pytest tests/test_operator_visit_context.py tests/test_standard_evidence_conditions.py -q`

Expected: PASS.

```bash
git add backend/app/schemas/operator_visit_context.py backend/app/services/standard_evidence.py backend/tests/test_operator_visit_context.py backend/tests/test_standard_evidence_conditions.py
git commit -m "feat: add typed standard applicability context"
```

### Task 3: 增加证据窗口、标准引用和报告快照存储

**Files:**
- Create: `backend/alembic/versions/0022_operator_report_evidence.py`
- Modify: `backend/app/db/models.py:77-101,587-610,706-760`
- Modify: `database/schema.sql`
- Create: `backend/tests/test_operator_evidence_migration.py`
- Modify: `backend/tests/test_alembic_contracts.py`

**Interfaces:**
- Consumes: Alembic head `0021`。
- Produces: `ReferenceCaseWindow` ORM；`AIReport.evidence_snapshot/evidence_snapshot_sha256/evidence_status/standard_evidence_status/reference_case_status`；标准引用元数据和片段页码。

- [ ] **Step 1: Write failing ORM, migration-chain, and clean-schema tests**

```python
def test_evidence_revision_follows_0021():
    migration = _load_revision()
    assert migration.revision == "0022"
    assert migration.down_revision == "0021"


def test_reference_window_has_privacy_and_version_columns():
    columns = {column.name for column in ReferenceCaseWindow.__table__.columns}
    assert "patient_label" not in columns
    assert {"anonymous_case_code", "dataset_release_id", "data_content_sha256",
            "feature_summary", "outcome_source", "eligibility_config_hash"}.issubset(columns)


def test_report_evidence_columns_are_nullable_for_legacy_rows():
    columns = {column.name: column for column in AIReport.__table__.columns}
    for name in ("evidence_snapshot", "evidence_snapshot_sha256", "evidence_status",
                 "standard_evidence_status", "reference_case_status"):
        assert columns[name].nullable is True
```

检查 `database/schema.sql` 包含同名表、唯一约束、CHECK 和三个索引。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_operator_evidence_migration.py tests/test_alembic_contracts.py -q`

Expected: FAIL because revision `0022` and the new columns do not exist.

- [ ] **Step 3: Implement the additive ORM and migration**

`ReferenceCaseWindow` 使用以下唯一键和字段类型：

```python
__table_args__ = (
    UniqueConstraint("dataset_release_id", "anonymous_case_code", "as_of",
                     "horizon_days", "profile_schema_version",
                     name="uq_reference_case_windows_identity"),
    CheckConstraint("horizon_days = 365", name="ck_reference_case_windows_horizon"),
    CheckConstraint("age IS NULL OR age BETWEEN 0 AND 120", name="ck_reference_case_windows_age"),
    CheckConstraint("visit_count >= 3", name="ck_reference_case_windows_visits"),
    CheckConstraint("observation_span_days >= 0", name="ck_reference_case_windows_span"),
    CheckConstraint("anonymous_case_code ~ '^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$'",
                    name="ck_reference_case_windows_anonymous_code"),
    Index("ix_reference_case_windows_pool", "disease_id", "dataset_release_id",
          "eligibility_status", "baseline_stage"),
    Index("ix_reference_case_windows_case", "dataset_release_id", "anonymous_case_code"),
    Index("ix_reference_case_windows_features", "feature_summary", postgresql_using="gin"),
)
```

JSONB 字段全部为非空 `{}`/`[]` 默认；哈希列为 `String(64)` 且有十六进制 CHECK；`is_synthetic` 非空。`standard_documents` 增加 `issuer`、`publication_date: Date`、`external_identifier`、`source_url`，`standard_segments` 增加正数可空 `page_number`。

`AIReport` 新字段保持可空，并对非空值增加枚举与哈希格式 CHECK。降级前锁定相关表；若 `reference_case_windows` 非空、任一报告已有证据快照，或标准新增引用字段已有值，则抛出 `RuntimeError("refusing_to_drop_nonempty_longitudinal_evidence")`。

- [ ] **Step 4: Mirror the final structure in `database/schema.sql`**

干净安装 SQL 必须包含：

```sql
CREATE TABLE IF NOT EXISTS reference_case_windows (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(id) ON DELETE RESTRICT,
    anonymous_case_code VARCHAR(14) NOT NULL,
    logical_dataset VARCHAR(64) NOT NULL,
    dataset_release_id VARCHAR(100) NOT NULL,
    data_content_sha256 CHAR(64) NOT NULL,
    as_of DATE NOT NULL,
    horizon_days INTEGER NOT NULL DEFAULT 365,
    baseline_stage VARCHAR(100) NOT NULL,
    age INTEGER,
    sex VARCHAR(10),
    visit_count INTEGER NOT NULL,
    observation_span_days INTEGER NOT NULL,
    feature_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    measurement_context_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome_status VARCHAR(30) NOT NULL,
    outcome_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome_source VARCHAR(100) NOT NULL,
    outcome_reliability VARCHAR(20) NOT NULL,
    source_trace JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_synthetic BOOLEAN NOT NULL,
    eligibility_status VARCHAR(30) NOT NULL,
    exclusion_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeline_sha256 CHAR(64) NOT NULL,
    profile_schema_version VARCHAR(100) NOT NULL,
    eligibility_config_hash CHAR(64) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_reference_case_windows_identity UNIQUE
        (dataset_release_id, anonymous_case_code, as_of, horizon_days, profile_schema_version),
    CONSTRAINT ck_reference_case_windows_horizon CHECK (horizon_days = 365),
    CONSTRAINT ck_reference_case_windows_age CHECK (age IS NULL OR age BETWEEN 0 AND 120),
    CONSTRAINT ck_reference_case_windows_visits CHECK (visit_count >= 3),
    CONSTRAINT ck_reference_case_windows_span CHECK (observation_span_days >= 0),
    CONSTRAINT ck_reference_case_windows_anonymous_code CHECK
        (anonymous_case_code ~ '^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$')
);
CREATE INDEX IF NOT EXISTS ix_reference_case_windows_pool
ON reference_case_windows(disease_id, dataset_release_id, eligibility_status, baseline_stage);
CREATE INDEX IF NOT EXISTS ix_reference_case_windows_case
ON reference_case_windows(dataset_release_id, anonymous_case_code);
CREATE INDEX IF NOT EXISTS ix_reference_case_windows_features
ON reference_case_windows USING gin(feature_summary);
```

列类型、默认值、FK 删除语义、CHECK 名和索引名与 ORM/Alembic 完全一致。

- [ ] **Step 5: Run migration contract tests and commit**

Run from `backend`: `python -m pytest tests/test_operator_evidence_migration.py tests/test_alembic_contracts.py -q`

Expected: PASS.

```bash
git add backend/alembic/versions/0022_operator_report_evidence.py backend/app/db/models.py database/schema.sql backend/tests/test_operator_evidence_migration.py backend/tests/test_alembic_contracts.py
git commit -m "feat: add operator evidence storage"
```

### Task 4: 建立标准完整性预检和来源证据服务

**Files:**
- Modify: `backend/app/services/standard_evidence.py`
- Modify: `backend/app/services/standard_resolver.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/test_standard_evidence_service.py`
- Modify: `backend/tests/test_standard_resolver.py`

**Interfaces:**
- Consumes: `disease_id`、`disease_code`、输入快照、当前 `ReferenceStandard.current_version`。
- Produces: `StandardVersionToken`；`preflight_standard(db, disease_id, disease_code) -> StandardVersionToken`；`build_standard_evidence(db, token, snapshot) -> StandardEvidence`；稳定 `StandardEvidenceError.code`。

- [ ] **Step 1: Write failing integrity, provenance, and AD safety tests**

```python
def test_preflight_rejects_document_hash_mismatch(approved_standard, tmp_path):
    approved_standard.current_version.standard_document.file_path = str(tmp_path / "standard.docx")
    Path(approved_standard.current_version.standard_document.file_path).write_bytes(b"changed")
    with pytest.raises(StandardEvidenceError) as error:
        preflight_standard(db_for(approved_standard), 1, "fatty_liver")
    assert error.value.code == "standard_integrity_failed"


def test_ad_rules_remain_evidence_only(approved_ad_standard, ad_snapshot):
    token = preflight_standard(db_for(approved_ad_standard), 2, "ad")
    evidence = build_standard_evidence(db_for(approved_ad_standard), token, ad_snapshot)
    assert evidence.rules
    assert all(rule.status != "calculable" for rule in evidence.rules)
    assert all(rule.numeric_interpretation is None for rule in evidence.rules)
```

另测标准缺失、非 approved、版本归属错误、文件不存在、文档/版本哈希不一致、规则 manifest 哈希不一致、缺条件、不适用、冲突和完整 source locator。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_standard_evidence_service.py tests/test_standard_resolver.py -q`

Expected: FAIL because the current resolver converts failures into warnings and does not validate the source file.

- [ ] **Step 3: Implement stable preflight failures and immutable token**

```python
@dataclass(frozen=True)
class StandardVersionToken:
    standard_id: int
    version_id: int
    document_id: int
    document_sha256: str
    version_sha256: str


class StandardEvidenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
```

`preflight_standard` 以 eager load 一次读取 standard/version/document/rules/segments，验证疾病归属、approved/current 指针、真实文件 SHA-256、文档/版本哈希和每条 `_manifest_sha256`。任何数据库异常转换为 `standard_query_failed`，但不能把本服务主动抛出的 `standard_missing` 或 `standard_integrity_failed` 覆盖掉。

`Settings` 增加 `STANDARD_EVIDENCE_QUERY_TIMEOUT_MS: int = 500`；标准查询在自己的短事务执行 `SET LOCAL statement_timeout = 500`，退出时提交只读成功事务或回滚失败事务，不把该设置泄漏到模型调用。

- [ ] **Step 4: Build source-complete rule evidence**

`build_standard_evidence` 按每个指标最近观察上下文调用 Task 2 evaluator，输出唯一状态：`calculable`、`evidence_only`、`missing_context`、`not_applicable`、`conflict`。来源固定包含文档、版本、规则、条件决策、章节/段落/表格/行列/页码和经过长度限制的原文片段。

数值解释只允许：

```python
if disease_code == "fatty_liver" and rule.machine_actionability == "calculable":
    numeric_interpretation = compare_numeric_value(latest_value, rule)
else:
    numeric_interpretation = None
```

保留 `resolve_standard_rules` 作为旧调用兼容包装，但让它复用 typed evaluator；移除把 `"required"` 当字面值比较的旧逻辑。

- [ ] **Step 5: Run standard suites and commit**

Run from `backend`: `python -m pytest tests/test_standard_evidence_service.py tests/test_standard_evidence_conditions.py tests/test_standard_resolver.py tests/test_standard_manifest.py tests/test_standard_manifest_import.py -q`

Expected: PASS.

```bash
git add backend/app/services/standard_evidence.py backend/app/services/standard_resolver.py backend/app/core/config.py backend/tests/test_standard_evidence_service.py backend/tests/test_standard_resolver.py
git commit -m "feat: build traceable standard evidence"
```

### Task 5: 实现参考病例生产准入和防泄漏窗口画像

**Files:**
- Create: `backend/app/services/reference_case_eligibility.py`
- Create: `backend/app/services/reference_case_windows.py`
- Create: `backend/tests/test_reference_case_eligibility.py`
- Create: `backend/tests/test_reference_case_windows.py`

**Interfaces:**
- Consumes: 当前活动 release 的 `CaseRecord` 行和既有 `rebuild_patient_timelines`、`summarize_fixed_window_history`。
- Produces: `evaluate_reference_candidate(candidate: ReferenceEligibilityCandidate) -> EligibilityDecision`；`build_window_profiles(rows: Sequence[Mapping[str, Any]], disease_code: str, release: ReferenceDataRelease) -> WindowBuildResult`，其中 `WindowBuildResult.profiles: tuple[ReferenceCaseWindowWrite, ...]`。

- [ ] **Step 1: Write failing strict-admission tests**

使用参数化测试逐一验证稳定排除码：

```python
@pytest.mark.parametrize(("change", "reason"), [
    ({"is_synthetic": True}, "synthetic_source"),
    ({"anonymous_case_code": None}, "anonymous_code_missing"),
    ({"anonymous_case_code": "P151"}, "anonymous_code_invalid"),
    ({"outcome_source": "generated_stage_assignment"}, "outcome_source_not_allowed"),
    ({"source_trace": {}}, "source_trace_missing"),
])
def test_reference_candidate_is_excluded_by_one_stable_reason(valid_candidate, change, reason):
    candidate = valid_candidate.model_copy(update=change)
    decision = evaluate_reference_candidate(candidate)
    assert decision.eligible is False
    assert reason in decision.reasons
```

增加一个窗口泄漏测试：改变 `as_of` 之后的结局值只能改变展示结局，不能改变 `feature_summary`、`timeline_sha256`、年龄、阶段或检测上下文摘要。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_reference_case_eligibility.py tests/test_reference_case_windows.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement explicit allowlists and deterministic reasons**

```python
ANONYMOUS_CODE = re.compile(r"^CASE-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")
OUTCOME_ALLOWLIST = {
    "fatty_liver": frozenset({"explicit_cirrhosis", "explicit_hcc"}),
    "ad": frozenset({"explicit_cdr", "documented_ad_unspecified"}),
}
REASON_ORDER = (
    "disease_mismatch", "release_mismatch", "synthetic_source",
    "anonymous_code_missing", "anonymous_code_invalid", "insufficient_visits",
    "source_trace_missing", "outcome_source_not_allowed",
    "outcome_reliability_insufficient", "task_incompatible", "timeline_invalid",
)
ELIGIBILITY_CONFIG_VERSION = "reference_eligibility.v1"
ELIGIBILITY_CONFIG_HASH = hashlib.sha256(json.dumps(
    {
        "version": ELIGIBILITY_CONFIG_VERSION,
        "anonymous_pattern": ANONYMOUS_CODE.pattern,
        "outcome_allowlist": {key: sorted(value) for key, value in OUTCOME_ALLOWLIST.items()},
        "minimum_visits": 3,
        "outcome_reliability": "high",
    },
    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
).encode("utf-8")).hexdigest()
REFERENCE_PROFILE_SCHEMA_VERSION = (
    f"reference_case_profile.v1+{ELIGIBILITY_CONFIG_HASH[:12]}"
)


class ReferenceEligibilityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    disease_code: Literal["fatty_liver", "ad"]
    expected_disease_code: Literal["fatty_liver", "ad"]
    dataset_release_id: str
    expected_release_id: str
    is_synthetic: bool
    anonymous_case_code: str | None
    visit_count: int = Field(ge=0)
    source_trace: dict[str, Any]
    outcome_source: str
    outcome_reliability: Literal["low", "medium", "high"]
    task_compatible: bool
    timeline_valid: bool


@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class WindowBuildResult:
    profiles: tuple[ReferenceCaseWindowWrite, ...]
    total_windows: int
    eligible_windows: int
    exclusion_counts: dict[str, int]
```

只信任结构化 `is_synthetic is False`、release ID/hash、逐例 `source_trace` 和 `outcome_source`；不再根据 `patient_label` 或数据集名称猜测真伪。等价人工审核结局必须在版本化配置中显式增加，不能运行时模糊匹配。

- [ ] **Step 4: Build 365-day profiles using information available at `as_of`**

每个患者从第三次有效访视开始产生窗口；`history = visits[:index + 1]`，画像只调用：

```python
feature_summary = summarize_fixed_window_history(history)
timeline_sha256 = sha256_json({
    "anonymous_case_code": anonymous_code,
    "as_of": as_of.isoformat(),
    "visits": history,
})
```

结局单独计算 `(as_of, as_of + 365 days]` 并写入 outcome 字段。输出 profile 不含 label、姓名、住院号、联系方式或自由文本；检测上下文摘要只保留枚举/规范化短字段与布尔变化标记。

- [ ] **Step 5: Run focused tests and commit**

Run from `backend`: `python -m pytest tests/test_reference_case_eligibility.py tests/test_reference_case_windows.py tests/test_anonymous_case_privacy.py -q`

Expected: PASS.

```bash
git add backend/app/services/reference_case_eligibility.py backend/app/services/reference_case_windows.py backend/tests/test_reference_case_eligibility.py backend/tests/test_reference_case_windows.py
git commit -m "feat: admit audited reference case windows"
```

### Task 6: 增加默认 dry-run 的幂等参考窗口构建器

**Files:**
- Modify: `backend/app/services/reference_case_windows.py`
- Create: `scripts/build_reference_case_windows.py`
- Create: `scripts/tests/test_build_reference_case_windows.py`
- Create: `backend/tests/integration/test_reference_case_window_persistence.py`

**Interfaces:**
- Consumes: `logical_dataset`、活动 release 和 Task 5 profiles。
- Produces: `synchronize_reference_case_windows(db, logical_dataset, apply=False) -> WindowBuildStatistics`；CLI `--dataset {fatty_liver,ad} [--apply]`。

- [ ] **Step 1: Write failing dry-run and idempotency tests**

```python
def test_dry_run_never_adds_or_commits(db, active_rows):
    result = synchronize_reference_case_windows(db, "fatty_liver", apply=False)
    assert result.total_windows >= result.eligible_windows
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_apply_is_idempotent(real_postgres_session):
    first = synchronize_reference_case_windows(real_postgres_session, "fatty_liver", apply=True)
    second = synchronize_reference_case_windows(real_postgres_session, "fatty_liver", apply=True)
    assert second.inserted == 0
    assert second.unchanged == first.eligible_windows
```

CLI 测试验证无 `--apply` 时 `apply=False`，输出只含总数、合格数、排除原因计数、release/config hash，不含临床值。

- [ ] **Step 2: Run tests and verify failure**

Run from repository root: `python -m pytest scripts/tests/test_build_reference_case_windows.py backend/tests/integration/test_reference_case_window_persistence.py -q`

Expected: FAIL because the synchronizer and CLI do not exist.

- [ ] **Step 3: Implement active-release identity and idempotent upsert**

活动 release 必须恰好一个 ID 和一个 `data_content_sha256`；多活动版本、缺哈希或行间哈希冲突抛出 `ReferenceIndexError`。同一 release 的源内容或准入配置发生变化时必须发布新的 `profile_schema_version`，正式写入使用 PostgreSQL不可变 upsert；同一唯一键已存在时不覆盖。dry-run 不调用 `flush`/`commit`。

```python
class ReferenceIndexError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class WindowBuildStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_dataset: str
    dataset_release_id: str
    data_content_sha256: str
    eligibility_config_hash: str
    total_windows: int = Field(ge=0)
    eligible_windows: int = Field(ge=0)
    inserted: int = Field(ge=0)
    unchanged: int = Field(ge=0)
    exclusion_counts: dict[str, int] = Field(default_factory=dict)


def synchronize_reference_case_windows(db, logical_dataset: str, *, apply: bool = False):
    release, rows = load_active_reference_rows(db, logical_dataset)
    result = build_window_profiles(rows, release.disease_code, release)
    statistics = WindowBuildStatistics(
        logical_dataset=logical_dataset,
        dataset_release_id=release.dataset_release_id,
        data_content_sha256=release.data_content_sha256,
        eligibility_config_hash=ELIGIBILITY_CONFIG_HASH,
        total_windows=result.total_windows,
        eligible_windows=result.eligible_windows,
        inserted=0,
        unchanged=0,
        exclusion_counts=result.exclusion_counts,
    )
    if not apply:
        return statistics
    statement = postgresql.insert(ReferenceCaseWindow).values(
        [profile.model_dump(mode="json") for profile in result.profiles]
    ).on_conflict_do_nothing(
        constraint="uq_reference_case_windows_identity"
    )
    inserted = max(int(db.execute(statement).rowcount or 0), 0)
    db.commit()
    return statistics.model_copy(update={
        "inserted": inserted,
        "unchanged": result.eligible_windows - inserted,
    })
```

- [ ] **Step 4: Implement a safe CLI**

`scripts/build_reference_case_windows.py` 使用互斥的默认 dry-run/显式 apply 行为：

```python
parser.add_argument("--dataset", required=True, choices=("fatty_liver", "ad"))
parser.add_argument("--apply", action="store_true")
result = synchronize_reference_case_windows(db, args.dataset, apply=args.apply)
print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))
```

异常输出只包含 `status=BLOCKED` 和稳定 `error_code`，进程返回 1。

- [ ] **Step 5: Run unit and PostgreSQL integration tests, then commit**

Run from repository root: `python -m pytest scripts/tests/test_build_reference_case_windows.py backend/tests/integration/test_reference_case_window_persistence.py -q`

Expected: PASS when the test PostgreSQL is available; unavailable infrastructure must be an explicit skip, not a false pass.

```bash
git add backend/app/services/reference_case_windows.py scripts/build_reference_case_windows.py scripts/tests/test_build_reference_case_windows.py backend/tests/integration/test_reference_case_window_persistence.py
git commit -m "feat: build versioned reference case windows"
```

### Task 7: 实现 `reference_similarity.v1` 确定性评分

**Files:**
- Create: `backend/app/services/reference_case_similarity.py`
- Create: `backend/tests/test_reference_case_similarity.py`

**Interfaces:**
- Consumes: 当前病例 `ReferenceCaseFeatureProfile` 与最多 500 个合格 `ReferenceCaseProfile`；评分时只向纯函数传入候选的 `.features`。
- Produces: `score_reference_case(current: ReferenceCaseFeatureProfile, candidate: ReferenceCaseFeatureProfile) -> ReferenceCaseScoreBreakdown`；`rank_reference_cases(current: ReferenceCaseFeatureProfile, candidates: Sequence[ReferenceCaseProfile], limit: int = 5) -> ReferenceCaseSelection`。

- [ ] **Step 1: Write failing exact-formula tests**

```python
def test_ranking_score_penalizes_missing_dimensions(current_profile, candidate_profile):
    scored = score_reference_case(current_profile, candidate_profile.features)
    assert scored.available_weight == 80
    assert scored.coverage == 0.8
    assert scored.ranking_score == round(scored.conditional_similarity * 0.8, 6)


def test_outcome_change_does_not_change_similarity(current_profile, candidate_profile):
    first = score_reference_case(current_profile, candidate_profile.features)
    changed = candidate_profile.model_copy(update={"outcome_value": "different"})
    second = score_reference_case(current_profile, changed.features)
    assert first == second


def test_ties_use_stable_privacy_safe_order(current_profile, candidates):
    selected = rank_reference_cases(current_profile, list(reversed(candidates)))
    assert [item.anonymous_case_code for item in selected.cases] == sorted(
        item.anonymous_case_code for item in selected.cases
    )
```

逐项测试八个权重、AD 阶段相邻、脂肪肝跨任务排除、单侧阈值尺度、量表范围、趋势方向/斜率、跨度/频率、检测条件不兼容、核心指标门槛、`coverage=0.60` 和 `score=50` 边界。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_reference_case_similarity.py -q`

Expected: FAIL with missing module.

- [ ] **Step 3: Implement immutable configuration and eight dimensions**

```python
WEIGHTS = MappingProxyType({
    "stage_task": 20, "age": 10, "sex": 5, "indicator_coverage": 15,
    "latest_values": 20, "trend": 20, "span_frequency": 5, "context": 5,
})
AD_STAGE_ORDER = ("normal", "mci", "pre_dementia")
MIN_COVERAGE = Decimal("0.60")
MIN_RANKING_SCORE = Decimal("50")
MAX_RESULTS = 5
MAX_CANDIDATES = 500
EPSILON = Decimal("1e-9")
```

每个不可比较维度从 `available_weight` 排除；`conditional_similarity = 100 * weighted_sum / available_weight`，`coverage = available_weight / 100`，`ranking_score = conditional_similarity * coverage`。单侧阈值尺度固定为 `max(abs(boundary), 0.1 * max(abs(a), abs(b)), epsilon)`；输出统一六位小数。

- [ ] **Step 4: Implement gates and stable ordering**

先排除任务不兼容；评分后要求核心指标、coverage 和 ranking score。排序 key 固定为：

```python
key=lambda item: (
    -item.score.ranking_score,
    -item.score.coverage,
    -OUTCOME_RELIABILITY_RANK[item.outcome_reliability],
    item.anonymous_case_code,
    -item.as_of.toordinal(),
)
```

`rank_reference_cases` 调用 `score_reference_case(current, candidate.features)`；评分完成后才把结局字段从原候选复制到返回模型，因此评分纯函数的参数类型不暴露 outcome 字段。

- [ ] **Step 5: Run tests and commit**

Run from `backend`: `python -m pytest tests/test_reference_case_similarity.py -q`

Expected: PASS and repeated shuffled inputs produce byte-identical JSON.

```bash
git add backend/app/services/reference_case_similarity.py backend/tests/test_reference_case_similarity.py
git commit -m "feat: rank audited reference cases deterministically"
```

### Task 8: 编排版本固定、一次重试和参考病例降级

**Files:**
- Modify: `backend/app/services/evidence_bundle.py`
- Modify: `backend/app/services/longitudinal_data_release.py`
- Modify: `backend/app/core/config.py`
- Create: `backend/tests/test_evidence_bundle_service.py`

**Interfaces:**
- Consumes: Task 4 `StandardVersionToken`、活动 reference release、输入快照。
- Produces: `EvidenceVersionToken`；`preflight_evidence_versions(db, disease_id: int, disease_code: str) -> EvidenceVersionToken`；`build_evidence_bundle_with_retry(db, snapshot: dict[str, Any], initial_token: EvidenceVersionToken) -> EvidenceBuildResult`。

- [ ] **Step 1: Write failing version-switch and degradation tests**

```python
def test_standard_change_retries_once_then_fails(snapshot):
    with patch("app.services.evidence_bundle.read_version_token", side_effect=[A, B, C]):
        with pytest.raises(EvidenceBuildError) as error:
            build_evidence_bundle_with_retry(db, snapshot, A)
    assert error.value.code == "evidence_version_changed"


def test_reference_query_failure_keeps_standard_and_marks_partial(snapshot, token):
    with patch("app.services.evidence_bundle.query_reference_windows", side_effect=TimeoutError):
        result = build_evidence_bundle_with_retry(db, snapshot, token)
    assert result.bundle.reference_cases.status == "reference_query_failed"
    assert result.evidence_status == "partial"
    assert result.bundle.standard.status == "available"
```

另测 `no_eligible_cases`、`insufficient_comparability`、`reference_index_stale`、中途只切换一次时成功重试，以及兼容投影不包含 `patient_label`。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_evidence_bundle_service.py -q`

Expected: FAIL because orchestration is not implemented.

- [ ] **Step 3: Implement evidence version tokens and bounded retry**

```python
@dataclass(frozen=True)
class EvidenceVersionToken:
    standard: StandardVersionToken
    dataset_release_id: str
    data_content_sha256: str
    eligibility_config_hash: str
    similarity_config_hash: str


@dataclass(frozen=True)
class EvidenceBuildResult:
    bundle: EvidenceBundle
    evidence_status: Literal["complete", "partial"]
    sources_projection: tuple[dict[str, Any], ...]


def build_evidence_bundle_with_retry(db, snapshot, initial_token):
    token = initial_token
    for attempt in range(2):
        result = build_evidence_bundle_once(db, snapshot, token)
        current = read_version_token(db, snapshot["disease_code"])
        if current == token:
            return result
        if attempt == 0:
            token = current
            continue
        raise EvidenceBuildError("evidence_version_changed")
    raise AssertionError("bounded retry exhausted")
```

不持有跨模型调用的事务或行锁。标准构建异常继续硬失败；参考查询异常只生成显式状态，不回退到旧筛选、不读取上一 release。

- [ ] **Step 4: Add independent timeouts and the bounded candidate query**

在 `Settings` 增加参考查询配置；标准配置已由 Task 4 提供：

```python
REFERENCE_CASE_QUERY_TIMEOUT_MS: int = 750
```

标准和参考查询分别在自己的短事务设置 `SET LOCAL statement_timeout`。参考窗口查询必须在数据库端执行病种、release、`eligibility_status='eligible'`、任务兼容和核心指标硬筛选：

```python
query = (
    db.query(ReferenceCaseWindow)
    .filter(
        ReferenceCaseWindow.disease_id == disease_id,
        ReferenceCaseWindow.dataset_release_id == token.dataset_release_id,
        ReferenceCaseWindow.data_content_sha256 == token.data_content_sha256,
        ReferenceCaseWindow.eligibility_config_hash == token.eligibility_config_hash,
        ReferenceCaseWindow.eligibility_status == "eligible",
        ReferenceCaseWindow.feature_summary["indicators"].op("?|")(
            postgresql.array(sorted(core_indicators))
        ),
    )
    .order_by(ReferenceCaseWindow.id.asc())
    .limit(MAX_CANDIDATES)
)
```

没有当前 release 的窗口返回 `reference_index_stale`；查询成功但零 eligible 窗口返回 `no_eligible_cases`；有窗口但评分门槛全部未通过返回 `insufficient_comparability`。

- [ ] **Step 5: Produce the only legacy `sources` projection**

```python
def build_sources_projection(bundle: EvidenceBundle) -> list[dict[str, Any]]:
    standard = [project_standard_rule(rule) for rule in bundle.standard.rules]
    references = [project_reference_case(case) for case in bundle.reference_cases.cases]
    result = [*standard, *references]
    assert all("patient_label" not in item for item in result)
    return result
```

投影只包含旧客户端所需的标准边界/版本/规则 ID、匿名编号、评分、共同指标和稳定状态；不得加入自由文本来源路径。

- [ ] **Step 6: Run tests and commit**

Run from `backend`: `python -m pytest tests/test_evidence_bundle_service.py tests/test_longitudinal_data_release.py -q`

Expected: PASS.

```bash
git add backend/app/services/evidence_bundle.py backend/app/services/longitudinal_data_release.py backend/app/core/config.py backend/tests/test_evidence_bundle_service.py
git commit -m "feat: orchestrate versioned report evidence"
```

### Task 9: 把模型原始输出与标准信号解释彻底分离

**Files:**
- Modify: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/app/services/longitudinal_signal_interpreter.py`
- Modify: `backend/app/schemas/longitudinal_report.py`
- Modify: `backend/tests/test_longitudinal_prediction_contract.py`
- Modify: `backend/tests/test_longitudinal_signal_interpreter.py`

**Interfaces:**
- Consumes: 原始 `LongitudinalPredictionResultV3`、访视和 `StandardEvidence`。
- Produces: `run_longitudinal_prediction(case: dict[str, Any], visits: list[dict[str, Any]], adapter, model_registry: dict[str, Any] | None = None) -> LongitudinalPredictionResult` 不再接收标准；`attach_signal_interpretation(prediction: LongitudinalPredictionResultV3, visits: Sequence[Mapping[str, Any]], standard: StandardEvidence) -> LongitudinalPredictionResultV3`。

- [ ] **Step 1: Write failing separation and AD tests**

```python
def test_prediction_does_not_accept_standard_or_reference_outcomes():
    signature = inspect.signature(run_longitudinal_prediction)
    assert "standard_sources" not in signature.parameters
    assert "reference_cases" not in signature.parameters


def test_attach_ad_evidence_never_creates_numeric_abnormality(raw_ad_prediction, ad_standard):
    result = attach_signal_interpretation(raw_ad_prediction, AD_VISITS, ad_standard)
    statuses = {signal.reference_status for signal in result.progression_signals.signals}
    assert not statuses.intersection({"above_range", "below_range"})
```

增加脂肪肝 calculable、missing context、跨访视检测条件变化和原始模型分数不变测试。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_longitudinal_prediction_contract.py tests/test_longitudinal_signal_interpreter.py -q`

Expected: FAIL because prediction currently accepts `standard_sources` and performs解释 inside the prediction path.

- [ ] **Step 3: Remove evidence from model invocation and add explicit attachment**

`run_longitudinal_prediction` 仅接收 `case`、`visits`、`adapter`、`model_registry`，返回空的 `progression_signals`。新增：

```python
def attach_signal_interpretation(prediction, visits, standard):
    interpreted = interpret_observation_signals(
        dataset=prediction.disease["dataset"],
        visits=visits,
        standard_rules=standard.rules,
        outcome_status=prediction.model_status.outcome,
        feature_names=prediction.evidence.get("outcome_feature_names", []),
    )
    return prediction.model_copy(update={"progression_signals": interpreted})
```

`interpret_observation_signals` 只接受严格 `StandardRuleEvidence`；历史单元测试可通过一个明确的 `legacy_standard_sources_to_evidence` 测试 helper 迁移，生产路径不得继续传任意字典。

- [ ] **Step 4: Run prediction and interpreter suites, then commit**

Run from `backend`: `python -m pytest tests/test_longitudinal_prediction_contract.py tests/test_longitudinal_signal_interpreter.py tests/test_longitudinal_report_generator.py -q`

Expected: PASS; 修改标准或参考结局不改变原始风险分数、阶段候选和趋势模型输出。

```bash
git add backend/app/services/longitudinal_prediction.py backend/app/services/longitudinal_signal_interpreter.py backend/app/schemas/longitudinal_report.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_longitudinal_signal_interpreter.py
git commit -m "refactor: separate prediction from evidence interpretation"
```

### Task 10: 接入报告 API、SSE、原子持久化与完整性校验

**Files:**
- Modify: `backend/app/api/operator.py:339-530`
- Modify: `backend/app/services/longitudinal_report_generator.py:406-620`
- Modify: `backend/app/services/report_integrity.py`
- Modify: `backend/app/schemas/operator.py`
- Modify: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `backend/tests/test_longitudinal_report_persistence.py`
- Modify: `backend/tests/test_report_integrity.py`
- Modify: `backend/tests/test_operator_catalog_and_reports_api.py`

**Interfaces:**
- Consumes: `EvidenceVersionToken`、原始模型结果和 `EvidenceBuildResult`。
- Produces: SSE `evidence` 事件；完整 `ReportOut.evidence_snapshot`；标准硬失败和参考部分失败的稳定终态。

- [ ] **Step 1: Write failing API and atomic persistence tests**

```python
def test_standard_failure_happens_before_model(client, operator_case, monkeypatch):
    predicted = Mock()
    monkeypatch.setattr("app.api.operator.preflight_evidence_versions",
                        Mock(side_effect=StandardEvidenceError("standard_integrity_failed")))
    monkeypatch.setattr("app.services.longitudinal_report_generator.run_longitudinal_prediction", predicted)
    response = client.post(f"/api/v1/operator/longitudinal-cases/{operator_case.id}/reports")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "standard_integrity_failed"
    predicted.assert_not_called()


def test_completed_report_persists_one_evidence_snapshot(db, generated_report):
    assert generated_report.evidence_status in {"complete", "partial"}
    assert generated_report.evidence_snapshot_sha256 == (
        generated_report.evidence_snapshot["integrity"]["evidence_snapshot_sha256"]
    )
    assert generated_report.generation_fingerprint
```

增加标准查询失败、参考超时 partial、无病例 complete、版本连续变化失败、终态事务回滚、旧报告 `evidence_snapshot=None` 可读和 SSE 不泄露异常测试。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_longitudinal_report_generator.py tests/test_longitudinal_report_persistence.py tests/test_report_integrity.py tests/test_operator_catalog_and_reports_api.py -q`

Expected: FAIL because evidence fields and event are not connected.

- [ ] **Step 3: Preflight before model and preserve failed-report audit**

在输入快照和 `AIReport` 生成批次保存后调用：

```python
try:
    evidence_token = preflight_evidence_versions(
        db, disease_id=case.disease_id, disease_code=disease.code
    )
except StandardEvidenceError as exc:
    transition_report_failed(db, report.id, error_stage="standard_evidence", code=exc.code)
    raise _operator_http_error(503, exc.code, STANDARD_PUBLIC_MESSAGES[exc.code])
```

删除原先把标准和相似病例包在同一个 `except Exception: sources=[]` 的路径。generator 接收固定 token，先运行纯模型，再构建 bundle、attach signals、render。

- [ ] **Step 4: Save and stream one canonical evidence result**

成功终态一次写入：

```python
_transition_report_from_generating(
    db,
    report_id,
    prediction_result=payload,
    evidence_snapshot=bundle.model_dump(mode="json"),
    evidence_snapshot_sha256=bundle.integrity.evidence_snapshot_sha256,
    evidence_status=evidence_result.evidence_status,
    standard_evidence_status=bundle.standard.status,
    reference_case_status=bundle.reference_cases.status,
    sources=evidence_result.sources_projection,
    content=content,
    generation_fingerprint=generation_fingerprint,
    status="completed",
)
```

在 `prediction` 后、正文 `delta` 前发送 `_sse("evidence", bundle.model_dump(mode="json"))`。标准证据构建失败设置 `error_stage=standard_evidence`；持久化失败保持 `error_stage=persistence`。

- [ ] **Step 5: Extend integrity to include evidence**

把指纹实现统一为：

```python
def create_generation_fingerprint(snapshot, prediction_result, evidence_snapshot, content):
    payload = {
        "input_snapshot": _normalize(snapshot, drop_hash_declaration=True),
        "prediction_result": _normalize(prediction_result),
        "evidence_snapshot": _normalize(evidence_snapshot),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
        allow_nan=False, sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

`verify_report_integrity` 增加 `evidence_snapshot` 和 `evidence_sha256` 参数，先以 `EvidenceBundle.model_validate` 与 `verify_evidence_bundle` 验证证据，再验证 generation fingerprint。旧报告缺少证据字段时仍为 `unverifiable/legacy_missing_integrity_fields`；新报告证据哈希不一致时为 `invalid/evidence_integrity_mismatch`。

- [ ] **Step 6: Run report suites and commit**

Run from `backend`: `python -m pytest tests/test_longitudinal_report_generator.py tests/test_longitudinal_report_persistence.py tests/test_report_integrity.py tests/test_operator_catalog_and_reports_api.py -q`

Expected: PASS.

```bash
git add backend/app/api/operator.py backend/app/services/longitudinal_report_generator.py backend/app/services/report_integrity.py backend/app/schemas/operator.py backend/tests/test_longitudinal_report_generator.py backend/tests/test_longitudinal_report_persistence.py backend/tests/test_report_integrity.py backend/tests/test_operator_catalog_and_reports_api.py
git commit -m "feat: persist and stream report evidence snapshots"
```

### Task 11: 增加前端严格类型、检测平台输入和 SSE 状态

**Files:**
- Modify: `frontend/src/api/operator.ts:1-110,341-460`
- Modify: `frontend/src/stores/operator.ts:1-280`
- Modify: `frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue:39-97`
- Modify: `frontend/src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts`
- Modify: `frontend/src/stores/__tests__/operator-case-workspace.spec.ts`
- Modify: `frontend/tests/longitudinal-report-ui-contract.test.mjs`

**Interfaces:**
- Consumes: 后端 `EvidenceBundle v1` 和 SSE `evidence`。
- Produces: `ReportDetail.evidence_snapshot: EvidenceBundle | null`、`PredictionStreamCallbacks.onEvidence`、store `longitudinalEvidence`。

- [ ] **Step 1: Write failing frontend contract tests**

```typescript
it('emits assay platform without replacing device name', async () => {
  await wrapper.find('[aria-label="检测平台"]').setValue('Roche cobas')
  const context = latestUpdate(wrapper)[0].visit_context
  expect(context?.assay_platform).toBe('Roche cobas')
  expect(context?.device_name).toBeUndefined()
})


it('stores the streamed evidence independently from prediction', () => {
  callbacks.onEvidence(evidenceFixture)
  expect(store.longitudinalEvidence?.schema_version)
    .toBe('longitudinal_evidence_bundle.v1')
})
```

静态契约测试要求 `ReportDetail.sources` 不再是 `any[]`，证据状态均为字符串联合类型。

- [ ] **Step 2: Run tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts src/stores/__tests__/operator-case-workspace.spec.ts`

Run: `node --test frontend/tests/longitudinal-report-ui-contract.test.mjs`

Expected: FAIL because `assay_platform`、`EvidenceBundle` and `onEvidence` are absent.

- [ ] **Step 3: Add exact TypeScript contracts and parse the evidence event**

在 `operator.ts` 定义与 Pydantic 一一对应的 `EvidenceBundleV1` 子类型，并加入：

```typescript
export type EvidenceStatus = 'complete' | 'partial'
export type StandardEvidenceStatus = 'available' | 'context_incomplete' | 'not_applicable' | 'conflict'
export type ReferenceCaseStatus = 'available' | 'no_eligible_cases' |
  'insufficient_comparability' | 'reference_query_failed' | 'reference_index_stale'

export interface ReportDetail extends ReportListItem {
  content: string
  sources: LegacyEvidenceSource[]
  evidence_snapshot: EvidenceBundleV1 | null
  evidence_snapshot_sha256: string | null
  prediction_result: LongitudinalPrediction | null
  input_snapshot: Record<string, unknown> | null
}
```

SSE parser 的 `case 'evidence'` 调用 `callbacks.onEvidence(payload)`；生成开始和打开历史报告前清空 live evidence，历史详情加载后只使用保存快照。

- [ ] **Step 4: Add the independent assay platform field**

在 `VisitContext` 增加 `assay_platform?: string | null`，编辑器“设备名称”后增加：

```vue
<label>检测平台
  <input aria-label="检测平台" :value="visit.visit_context?.assay_platform ?? ''"
    maxlength="200" :disabled="readonly"
    @input="updateContext(index, 'assay_platform', nullableText(($event.target as HTMLInputElement).value))" />
</label>
```

沿用既有 field-level error、readonly 和克隆逻辑。

- [ ] **Step 5: Run frontend tests and commit**

Run: `npm --prefix frontend run test:unit -- --run src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts src/stores/__tests__/operator-case-workspace.spec.ts`

Run: `node --test frontend/tests/longitudinal-report-ui-contract.test.mjs`

Expected: PASS.

```bash
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/components/operator-case/OperatorVisitTimelineEditor.vue frontend/src/components/operator-case/__tests__/OperatorVisitTimelineEditor.spec.ts frontend/src/stores/__tests__/operator-case-workspace.spec.ts frontend/tests/longitudinal-report-ui-contract.test.mjs
git commit -m "feat: consume typed longitudinal evidence"
```

### Task 12: 构建网页正式标准与参考病例证据区

**Files:**
- Create: `frontend/src/components/LongitudinalEvidenceSection.vue`
- Create: `frontend/src/components/__tests__/LongitudinalEvidenceSection.spec.ts`
- Modify: `frontend/src/components/LongitudinalReportView.vue`
- Modify: `frontend/tests/longitudinal-report-ui-contract.test.mjs`

**Interfaces:**
- Consumes: `evidence: EvidenceBundleV1 | null`。
- Produces: 标准卡片、参考病例卡片、四类参考状态、可访问折叠器和固定安全提示。

- [ ] **Step 1: Re-read the required UI design spec**

完整读取 `docs/DESIGN_SPEC.md`，把本任务使用的 CSS 变量、圆角、阴影、间距、焦点和 reduced-motion 规则记录在本任务实施笔记中；若文件内容与批准设计冲突，停止并让用户评审，不自行选边。

- [ ] **Step 2: Write failing component tests for every state**

```typescript
it.each([
  ['no_eligible_cases', '当前没有通过生产准入的参考病例。'],
  ['insufficient_comparability', '存在合格病例，但与当前病例可比信息不足。'],
  ['reference_query_failed', '参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。'],
])('renders %s distinctly', (status, copy) => {
  const wrapper = mount(LongitudinalEvidenceSection, {
    props: { evidence: evidenceFixture({ referenceStatus: status }) },
  })
  expect(wrapper.text()).toContain(copy)
})


it('never renders a patient label and always renders the non-causal notice', () => {
  const wrapper = mount(LongitudinalEvidenceSection, { props: { evidence: fullFixture } })
  expect(wrapper.text()).not.toContain('patient_label')
  expect(wrapper.text()).toContain('参考病例结果不代表当前病例将发生相同结局。')
})
```

增加键盘展开、ARIA、规则缺条件、AD evidence-only、评分分项和 provenance 定位测试。

- [ ] **Step 3: Run tests and verify failure**

Run: `npm --prefix frontend run test:unit -- --run src/components/__tests__/LongitudinalEvidenceSection.spec.ts`

Expected: FAIL because the component does not exist.

- [ ] **Step 4: Implement the evidence component**

模板固定两个 `aria-labelledby` 区域。标准规则显示状态、最新观察、条件决策、版本和 source locator；参考病例只显示匿名编号、分数/覆盖率、年龄段、性别、阶段、访视/跨度、比较项、结局来源和可靠性。

状态映射必须是穷尽式：

```typescript
const referenceStateCopy: Record<ReferenceCaseStatus, string> = {
  available: '',
  no_eligible_cases: '当前没有通过生产准入的参考病例。',
  insufficient_comparability: '存在合格病例，但与当前病例可比信息不足。',
  reference_query_failed: '参考病例查询暂时不可用，本报告仅使用正式标准和模型结果。',
  reference_index_stale: '参考病例索引版本已过期，本报告未使用旧版本病例。',
}
```

使用 `var(--bg-surface)`、`var(--border-light)`、`var(--radius-item)`、`var(--shadow-sm)`；交互目标至少 `44px`，focus-visible 清晰，动画受 `prefers-reduced-motion` 控制。

- [ ] **Step 5: Route new and legacy reports explicitly**

`LongitudinalReportView.vue` 把带 ID 的保存 HTML 按 `section-8` 到 `section-9` 边界拆成前后两段；结构化组件自身使用 `id="section-8"`，从而保持 11 节目录和正文顺序：

```vue
<template v-if="evidence?.schema_version === 'longitudinal_evidence_bundle.v1'">
  <div class="markdown-body" v-html="splitContent.beforeEvidence" />
  <LongitudinalEvidenceSection id="section-8" :evidence="evidence" />
  <div class="markdown-body" v-html="splitContent.afterEvidence" />
</template>
<div v-else class="markdown-body" v-html="renderedContent" />
```

`splitEvidenceSectionHtml` 使用 `DOMParser`，删除原第 8 节 heading 及其到第 9 节之前的兄弟节点；找不到任一边界时返回安全 fallback：`beforeEvidence=renderedContent`、`afterEvidence=''` 并把结构化证据追加在正文后。新报告不能再把 Markdown 第 8 节作为第二份冲突证据展示；旧报告保留既有 Markdown/`sources` 路径。

- [ ] **Step 6: Run frontend tests, build, and commit**

Run: `npm --prefix frontend run test:unit -- --run src/components/__tests__/LongitudinalEvidenceSection.spec.ts`

Run: `node --test frontend/tests/longitudinal-report-ui-contract.test.mjs`

Run: `npm --prefix frontend run build`

Expected: all PASS; Vue type checking and Vite build complete without errors.

```bash
git add frontend/src/components/LongitudinalEvidenceSection.vue frontend/src/components/__tests__/LongitudinalEvidenceSection.spec.ts frontend/src/components/LongitudinalReportView.vue frontend/tests/longitudinal-report-ui-contract.test.mjs
git commit -m "feat: render structured longitudinal evidence"
```

### Task 13: 让 Markdown 与 PDF 使用同一证据快照

**Files:**
- Modify: `backend/app/services/longitudinal_report_generator.py`
- Modify: `backend/app/services/pdf_generator.py`
- Modify: `backend/app/templates/report_pdf.html`
- Modify: `backend/app/api/operator.py:548-610`
- Modify: `backend/tests/test_longitudinal_report_template_contract.py`
- Modify: `backend/tests/test_longitudinal_pdf_contract.py`
- Modify: `backend/tests/test_pdf_generation.py`

**Interfaces:**
- Consumes: 保存的 `EvidenceBundle v1`，不得查询当前标准或病例库。
- Produces: `render_evidence_markdown(bundle) -> str`；`generate_pdf(content, title, prediction_result, evidence_snapshot) -> bytes`。

- [ ] **Step 1: Write failing snapshot-consistency and print tests**

```python
def test_pdf_uses_saved_evidence_without_querying_current_sources(saved_report):
    with patch("app.services.standard_evidence.build_standard_evidence") as current:
        html = pdf_generator._markdown_to_safe_html(
            saved_report.content,
            saved_report.prediction_result,
        )
    current.assert_not_called()
    assert saved_report.evidence_snapshot_sha256 in html


def test_pdf_contains_reference_limit_and_anonymous_code(saved_report):
    html = pdf_generator._markdown_to_safe_html(
        saved_report.content,
        saved_report.prediction_result,
    )
    assert "参考病例结果不代表当前病例将发生相同结局" in html
    assert "CASE-" in html
    assert "patient_label" not in html
```

增加标准版本、数据 release、算法版本、配置哈希、partial 警告和 AD 无异常措辞测试。

- [ ] **Step 2: Run tests and verify failure**

Run from `backend`: `python -m pytest tests/test_longitudinal_report_template_contract.py tests/test_longitudinal_pdf_contract.py tests/test_pdf_generation.py -q`

Expected: FAIL because PDF does not accept the evidence snapshot.

- [ ] **Step 3: Render one evidence mapping into Markdown and PDF**

新增纯函数 `render_evidence_markdown(bundle)`；标准状态、来源、参考空状态和限制文案与前端映射逐字一致。PDF 入口签名改为：

```python
def generate_pdf(markdown_content: str, title: str = "分析报告",
                 prediction_result: dict[str, Any] | None = None,
                 evidence_snapshot: dict[str, Any] | None = None) -> bytes:
```

`generate_pdf` 先用 Pydantic 校验保存快照及其哈希，再渲染已经由同一快照生成并被 generation fingerprint 覆盖的保存正文；非法新快照拒绝下载并返回安全 500，不查询 current 数据补救。旧报告 `None` 继续原路径。

- [ ] **Step 4: Add print evidence cards and technical appendix**

把 `_CriticalSectionBlocksTreeprocessor._SECTION_CLASSES` 增加 `"参考标准和相似病例": "evidence-block"`，让保存正文中的第 8 节成为唯一打印证据区；Jinja 模板为 `.evidence-block` 提供浅边框、12px 圆角和 `break-inside: avoid`。保存正文第 11 节显示 evidence hash、标准版本、数据版本、算法版本和配置哈希，不显示绝对文件路径。

- [ ] **Step 5: Run PDF tests and commit**

Run from `backend`: `python -m pytest tests/test_longitudinal_report_template_contract.py tests/test_longitudinal_pdf_contract.py tests/test_pdf_generation.py -q`

Expected: PASS; Playwright 可用时 PDF bytes 以 `%PDF` 开头。

```bash
git add backend/app/services/longitudinal_report_generator.py backend/app/services/pdf_generator.py backend/app/templates/report_pdf.html backend/app/api/operator.py backend/tests/test_longitudinal_report_template_contract.py backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_pdf_generation.py
git commit -m "feat: render saved evidence in reports and pdf"
```

### Task 14: 完成 PostgreSQL、性能、故障和浏览器验收

**Files:**
- Create: `backend/tests/integration/test_operator_report_evidence.py`
- Create: `backend/tests/test_reference_case_similarity_performance.py`
- Modify: `backend/tests/e2e/test_operator_case_workspace.py`
- Modify: `scripts/run_operator_case_e2e.ps1`

**Interfaces:**
- Consumes: 已完成的迁移、窗口、API、前端和 PDF 链路。
- Produces: 双病种成功、硬失败、正常空状态、partial 降级、历史稳定性和性能门禁证据。

- [ ] **Step 1: Add real PostgreSQL integration scenarios**

```python
@pytest.mark.parametrize("disease_code", ["fatty_liver", "ad"])
def test_report_snapshot_round_trip_is_immutable(pg_client, seeded_evidence, disease_code):
    case_id = seeded_evidence.case_ids[disease_code]
    response = pg_client.post(f"/api/v1/operator/longitudinal-cases/{case_id}/reports")
    assert response.status_code == 200
    done = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ") and '"report_id"' in line
    ][-1]
    before = pg_client.get(f"/api/v1/operator/reports/{done['report_id']}").json()
    seeded_evidence.switch_current_versions(disease_code)
    after = pg_client.get(f"/api/v1/operator/reports/{done['report_id']}").json()
    assert after["evidence_snapshot"] == before["evidence_snapshot"]
    assert after["content"] == before["content"]
```

在同一测试模块定义 `seeded_evidence` fixture，返回具有 `case_ids: dict[str, int]` 和 `switch_current_versions(disease_code: str) -> None` 的控制对象；切换方法只更新测试事务内已创建的批准标准 current 指针与活动 release 标记。

同文件覆盖标准缺失/哈希错误/查询超时、无合格病例、可比性不足、参考超时、索引过期、版本连续切换和终态事务失败。

- [ ] **Step 2: Add the 10,000-window benchmark and SQL query budget**

性能测试预生成 10,000 个窗口，硬筛选只返回 500 个；使用 `time.perf_counter()` 重复预热后测量并断言：

```python
EXPECTED_EVIDENCE_QUERY_BUDGET = 8
ordered = sorted(samples)
p95 = ordered[math.ceil(len(ordered) * 0.95) - 1]
assert candidate_count <= 500
assert p95 <= 1.0
assert sql_counter.count <= EXPECTED_EVIDENCE_QUERY_BUDGET
```

查询预算固定为 8，不允许 N+1。CI 性能节点不满足稳定 PostgreSQL 资源时标记专用 `performance`，但发布门禁必须运行。

- [ ] **Step 3: Extend browser E2E for the five required states**

浏览器场景固定为：脂肪肝 calculable、AD evidence-only、无合格病例、参考服务失败 partial、标准硬失败。每个场景断言页面文案、匿名编号、PDF 下载状态和没有 `patient_label`；标准硬失败断言未出现模型生成阶段。

- [ ] **Step 4: Run integration, performance, and E2E tests**

Run from `backend`: `python -m pytest tests/integration/test_reference_case_window_persistence.py tests/integration/test_operator_report_evidence.py -q`

Run from `backend`: `python -m pytest tests/test_reference_case_similarity_performance.py -m performance -q`

Run from repository root: `powershell -ExecutionPolicy Bypass -File scripts/run_operator_case_e2e.ps1`

Expected: all required scenarios PASS; infrastructure absence is reported as BLOCKED for deployment, never recorded as production pass.

- [ ] **Step 5: Commit the acceptance suite**

```bash
git add backend/tests/integration/test_operator_report_evidence.py backend/tests/test_reference_case_similarity_performance.py backend/tests/e2e/test_operator_case_workspace.py scripts/run_operator_case_e2e.ps1
git commit -m "test: cover longitudinal evidence acceptance"
```

### Task 15: 扩展只读部署门禁并完成项目流程核查

**Files:**
- Modify: `scripts/check_database_readonly.py`
- Modify: `backend/tests/test_operator_case_workspace_migration.py`
- Create: `scripts/tests/test_check_operator_report_evidence_readonly.py`
- Modify: `docs/AI操作者流程核查.md`

**Interfaces:**
- Consumes: 数据库结构、活动标准、活动参考 release 和已构建窗口统计。
- Produces: `--phase preflight|postflight` 的不修改数据库 JSON `PASS/FAIL/BLOCKED` 报告；第 5 项仓库完成与生产待办记录。

- [ ] **Step 1: Write failing read-only checker tests**

```python
def test_checker_requires_evidence_columns_constraints_and_indexes(fake_connection):
    report = collect_checks(fake_connection, {"0022"}, phase="postflight")
    assert report["evidence_storage"]["missing_columns"] == []
    assert report["evidence_storage"]["missing_constraints"] == []
    assert report["evidence_storage"]["missing_indexes"] == []


def test_checker_never_executes_mutating_sql(fake_connection):
    collect_checks(fake_connection, {"0022"}, phase="postflight")
    sql = "\n".join(str(call.args[0]) for call in fake_connection.execute.call_args_list)
    assert "SET TRANSACTION READ ONLY" in sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|CREATE|DROP)\b", sql, re.I)
```

检查器还要报告两个标准当前版本/文件哈希状态、活动 release 唯一性、合格窗口数、索引 release/config hash 是否一致，但不输出病例指标值。

- [ ] **Step 2: Run tests and verify failure**

Run from repository root: `python -m pytest scripts/tests/test_check_operator_report_evidence_readonly.py backend/tests/test_operator_case_workspace_migration.py -q`

Expected: FAIL because the checker does not know revision `0022` or evidence structures.

- [ ] **Step 3: Implement additive read-only checks**

扩展现有常量而不删除旧门禁：

```python
REQUIRED_COLUMNS["reference_case_windows"] = {
    "disease_id", "anonymous_case_code", "dataset_release_id", "as_of",
    "feature_summary", "outcome_source", "eligibility_status",
    "timeline_sha256", "eligibility_config_hash",
}
REQUIRED_COLUMNS["ai_reports"].update({
    "evidence_snapshot", "evidence_snapshot_sha256", "evidence_status",
    "standard_evidence_status", "reference_case_status",
})
```

参数解析器增加必填 `--phase {preflight,postflight}`。`preflight` 允许数据库仍在 `0021`，只检查数据是否可迁移并返回 `migration_required=true`；`postflight` 必须唯一 head 为 `0022` 且所有新结构通过。所有查询在 `SET TRANSACTION READ ONLY` 后执行并在 finally 回滚。连接错误输出 `BLOCKED` 和异常类型，不输出连接串。

- [ ] **Step 4: Run full layered verification before editing the audit document**

Run from `backend`: `python -m pytest tests/test_longitudinal_evidence_schema.py tests/test_standard_evidence_conditions.py tests/test_standard_evidence_service.py tests/test_reference_case_eligibility.py tests/test_reference_case_windows.py tests/test_reference_case_similarity.py tests/test_evidence_bundle_service.py tests/test_longitudinal_signal_interpreter.py tests/test_longitudinal_report_generator.py tests/test_longitudinal_report_persistence.py tests/test_report_integrity.py -q`

Run from repository root: `python -m pytest scripts/tests/test_build_reference_case_windows.py scripts/tests/test_check_operator_report_evidence_readonly.py -q`

Run: `npm --prefix frontend run test:unit`

Run: `node --test frontend/tests/*.test.mjs`

Run: `npm --prefix frontend run build`

Expected: all repository-side suites PASS. 再运行项目既有全量后端套件；任何失败必须先定位为本变更回归或已存在问题，不得只记录为通过。

- [ ] **Step 5: Update the workflow audit with evidence, not predictions**

仅在 Step 4 通过后修改 `docs/AI操作者流程核查.md` 第 5 项，记录：已实现文件、测试命令及实际结果、两份标准哈希核对结果、正式参考池统计、当前仓库完成状态。生产数据库迁移、正式 `--apply` 构建、线上浏览器冒烟和监控未执行时必须保留为未完成门禁，不能写“已上线”。

- [ ] **Step 6: Commit repository completion evidence**

```bash
git add scripts/check_database_readonly.py backend/tests/test_operator_case_workspace_migration.py scripts/tests/test_check_operator_report_evidence_readonly.py docs/AI操作者流程核查.md
git commit -m "docs: record operator evidence verification"
```

### Task 16: 执行部署窗口、回滚验证与最终验收

**Files:**
- Modify: `docs/AI操作者流程核查.md` — 仅在生产门禁全部通过后补充真实部署证据。

**Interfaces:**
- Consumes: 已备份的目标 PostgreSQL、构建产物、revision `0022` 和批准的部署窗口。
- Produces: 生产只读预检、迁移、窗口统计、影子验证、启用、冒烟和回滚证据。

- [ ] **Step 1: Capture recoverable deployment inputs**

记录数据库备份标识、应用版本/commit、当前 Alembic revision、两个标准版本与哈希、两个活动数据 release 与内容哈希。缺少任一值则停止部署并标记 BLOCKED。

- [ ] **Step 2: Run preflight and migration**

Run from repository root: `python scripts/check_database_readonly.py --phase preflight`

Expected: `status=PASS`、revision 为 `0021`、`migration_required=true`，并且所有数据安全检查通过。

Run from `backend`: `python -m alembic upgrade 0022`

Run from repository root: `python scripts/check_database_readonly.py --phase postflight`

Expected: postflight `status=PASS`、唯一 head `0022`、所有证据列/约束/索引存在。

- [ ] **Step 3: Dry-run, review, and explicitly apply both reference indexes**

Run: `python scripts/build_reference_case_windows.py --dataset fatty_liver`

Run: `python scripts/build_reference_case_windows.py --dataset ad`

人工复核合格数和各排除原因；确认生成/推断/合成窗口为零准入后执行：

Run: `python scripts/build_reference_case_windows.py --dataset fatty_liver --apply`

Run: `python scripts/build_reference_case_windows.py --dataset ad --apply`

重复两个 `--apply` 命令，Expected: `inserted=0` 且 `unchanged=eligible_windows`，证明幂等。

- [ ] **Step 4: Enable through shadow and user-visible gates**

先启用 `EvidenceBundle v1` 影子校验，比较标准状态、参考状态和兼容 sources，不向用户显示影子结果；无隐私泄漏、无标准误算和无版本错配后再依次启用后端证据链路、前端结构化证据区和 PDF。

- [ ] **Step 5: Run production smoke and monitor**

对脂肪肝 calculable、AD evidence-only、无合格病例、参考查询失败、标准硬失败和历史旧报告执行浏览器/PDF 冒烟。监控标准硬失败率、reference partial 率、候选数量、P95 构建耗时和证据完整性失败；日志抽查不得包含 label、临床值或路径。

- [ ] **Step 6: Verify rollback without deleting evidence**

关闭新 UI/后端读取开关，确认旧客户端可从脱敏 `sources` 投影读取新报告；不得执行 `alembic downgrade` 删除非空证据表/列，不得删除证据快照或窗口。恢复开关后再次核对历史报告 hash 和正文未变化。

- [ ] **Step 7: Mark production completion only after all gates pass**

把部署时间、revision、release/config hash、窗口数量、冒烟结果和监控观察窗口补入变更记录。此时才可把 `docs/AI操作者流程核查.md` 的生产部署门禁标记完成；若需要修改文档，单独提交 `docs: record operator evidence deployment`。
