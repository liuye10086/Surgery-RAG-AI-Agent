# Longitudinal Prediction Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AI 操作者端升级为“操作者纵向病例 → 多次访视 → 进展/阶段与指标趋势预测 → 可保存预测报告”的完整闭环，同时保留现有参考病例库和单次指标快速评估。

**Architecture:** 保留 `case_records` 作为训练/检索参考病例；新增 `operator_cases` 与 `operator_case_visits` 保存操作者输入。以疾病适配器统一脂肪肝和阿尔茨海默病的标签、阶段、关键指标和时间窗口规则；结构化预测服务先生成经过 schema 校验的结果，再由受约束的报告生成器组织 Markdown、来源和 PDF，并保存到现有 `ai_reports`。

**Tech Stack:** Python 3.11、FastAPI、SQLAlchemy、Alembic、Pydantic v2、PostgreSQL JSONB、scikit-learn、joblib、LangChain/DeepSeek streaming、Vue 3、TypeScript、Pinia、Element Plus、marked、Playwright PDF。

## Global Constraints

- `case_records` 继续表示参考病例；不得把操作者输入患者混入参考病例库或复用 `confirmed` 作为操作者病例状态。
- 首期仅支持 `脂肪肝` 和 `阿尔茨海默病`；通用管线必须通过疾病适配器扩展。
- 结构化预测结果由代码/模型产生；LLM 不得创建或修改风险分数、阶段、时间窗口、未来数值或引用。
- 未校准的 `risk_score` 只能称为模型分数/风险等级，不得显示为临床发病概率。
- 当前模型包含分层重组合成数据；报告和相似病例来源必须显式显示合成数据警告。
- 固定窗口不可估计时使用 `window_status=not_estimable`，阶段模型不可用时使用 `stage_projection.status=not_estimated`，趋势数值模型不可用时使用 `forecast.status=direction_only`。
- 新增数据库变更必须使用新的 Alembic revision；不得修改既有 revision 文件。
- 报告生成必须保存 `input_snapshot`、`prediction_result`、`sources`、模型版本和报告状态；LLM 失败不能丢失结构化结果。
- 现有单次预测 `analysis_type="predictive"` 保持可用；纵向报告使用 `analysis_type="longitudinal_predictive"`。
- UI 修改前必须完整遵守 `docs/DESIGN_SPEC.md`；使用现有暖杏蓝变量和 Element Plus 组件。
- 每个任务先写失败测试，再写最小实现；任务完成后运行该任务的专门测试和相关存量测试。

---

## File Map

本计划涉及的文件职责如下：

| 文件 | 责任 |
|---|---|
| `backend/app/db/models.py` | 新增操作者病例、访视和报告关联字段的 ORM 定义 |
| `backend/alembic/versions/0008_longitudinal_operator_cases.py` | 创建新表、索引、外键和报告字段 |
| `backend/app/schemas/longitudinal_case.py` | 病例/访视 CRUD 的 Pydantic 契约 |
| `backend/app/schemas/longitudinal_report.py` | 结构化预测结果、SSE 事件和报告响应契约 |
| `backend/app/api/operator.py` | 操作者病例、访视和纵向报告路由 |
| `backend/app/services/longitudinal_case_service.py` | 病例/访视持久化、所有者校验和输入快照 |
| `backend/app/services/disease_progression.py` | 脂肪肝/阿尔茨海默病适配器和阶段定义 |
| `backend/app/services/longitudinal_features.py` | 日期排序、缺失率、观察趋势和模型输入特征 |
| `backend/app/services/longitudinal_prediction.py` | 结局、阶段和指标趋势模型推理与结构化结果校验 |
| `backend/app/services/longitudinal_evidence.py` | 参考病例、参考范围、文档来源排序与合成标记 |
| `backend/app/services/longitudinal_report_generator.py` | SSE、受约束 LLM、章节生成、持久化 |
| `scripts/train_progression_model.py` | 时间前缀训练样本和结局模型训练 |
| `scripts/train_longitudinal_trend_models.py` | 下一次访视趋势方向模型训练 |
| `backend/app/ml_models/` | 模型和 `.meta.json` artifact |
| `frontend/src/api/operator.ts` | 病例、访视、纵向报告 API 类型和 SSE 客户端 |
| `frontend/src/stores/operator.ts` | 病例、报告、生成阶段和取消状态 |
| `frontend/src/views/OperatorView.vue` | 默认纵向报告工作台 |
| `frontend/src/components/OperatorSidebar.vue` | 纵向病例/报告导航 |
| `frontend/src/components/LongitudinalCaseEditor.vue` | 病例信息和访视时间线编辑器 |
| `frontend/src/components/LongitudinalPredictionSummary.vue` | 结构化预测摘要、趋势表和警告 |
| `backend/app/templates/report_pdf.html` | 纵向 PDF 样式兼容性检查 |

---

### Task 1: 建立数据库表和 ORM 边界

**Files:**
- Create: `backend/alembic/versions/0008_longitudinal_operator_cases.py`
- Create: `backend/tests/test_longitudinal_schema_contracts.py`
- Modify: `backend/app/db/models.py`
- Modify: `database/schema.sql`

**Interfaces:**
- Produces ORM classes `OperatorCase` and `OperatorCaseVisit`.
- Adds `AIReport.operator_case_id` and `AIReport.input_snapshot`.
- Keeps `CaseRecord` unchanged as the reference-case model.

- [ ] **Step 1: Write failing schema tests**

```python
def test_operator_case_tables_have_owner_and_visit_constraints():
    from app.db.models import AIReport, OperatorCase, OperatorCaseVisit

    assert OperatorCase.__tablename__ == "operator_cases"
    assert OperatorCaseVisit.__tablename__ == "operator_case_visits"
    assert {"user_id", "disease_id", "patient_label", "baseline_stage", "status"}.issubset(
        {column.name for column in OperatorCase.__table__.columns}
    )
    assert {"case_id", "visit_date", "visit_index", "indicators"}.issubset(
        {column.name for column in OperatorCaseVisit.__table__.columns}
    )
    report_columns = {column.name for column in AIReport.__table__.columns}
    assert {"operator_case_id", "input_snapshot"}.issubset(report_columns)
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python -m pytest backend/tests/test_longitudinal_schema_contracts.py -v`

Expected: FAIL because the new ORM classes and report columns do not exist.

- [ ] **Step 3: Add ORM models and relationships**

Implement `OperatorCase` with `user_id`, `disease_id`, `patient_label`, `sex`, `baseline_stage`, `notes`, `status`, timestamps and relationships to `User`, `Disease`, visits and reports. Implement `OperatorCaseVisit` with `case_id`, `visit_date`, `visit_index`, `indicators`, `notes`, timestamp and a unique constraint on `(case_id, visit_date)`. Add indexes for `user_id`, `disease_id`, `case_id`, and visit date. Add nullable `operator_case_id` and JSONB `input_snapshot` to `AIReport` so old rows remain valid.

- [ ] **Step 4: Add Alembic migration**

Create revision `0008` from `0007`. Create the two new tables, foreign keys with owner/cascade semantics, indexes, the unique visit-date constraint, and the two nullable `ai_reports` columns. The downgrade must remove constraints before tables/columns.

- [ ] **Step 5: Update the SQL initialization snapshot**

Add the same tables, columns, indexes and defaults to `database/schema.sql`. Keep its definitions aligned with the ORM and migration, but do not use the snapshot as a replacement for Alembic.

- [ ] **Step 6: Run schema and migration contract tests**

Run: `python -m pytest backend/tests/test_longitudinal_schema_contracts.py backend/tests/test_alembic_contracts.py -v`

Expected: PASS; existing `case_records` columns remain unchanged.

- [ ] **Step 7: Commit the database boundary**

```powershell
git add backend/app/db/models.py backend/alembic/versions/0008_longitudinal_operator_cases.py backend/tests/test_longitudinal_schema_contracts.py database/schema.sql
git commit -m "feat: add operator longitudinal case storage"
```

### Task 2: Implement operator case and visit CRUD

**Files:**
- Create: `backend/app/schemas/longitudinal_case.py`
- Create: `backend/app/services/longitudinal_case_service.py`
- Create: `backend/tests/test_longitudinal_case_service.py`
- Modify: `backend/app/api/operator.py`

**Interfaces:**
- `create_operator_case(db, user_id, payload) -> OperatorCase`
- `list_operator_cases(db, user_id, disease_id=None) -> list[OperatorCase]`
- `add_visit(db, user_id, case_id, payload) -> OperatorCaseVisit`
- `build_input_snapshot(case, visits) -> dict`
- API paths: `/operator/longitudinal-cases` and `/operator/longitudinal-cases/{case_id}/visits`.

- [ ] **Step 1: Add validation tests**

```python
def test_visit_rejects_duplicate_date_and_empty_indicators():
    from pydantic import ValidationError
    from app.schemas.longitudinal_case import VisitCreate

    with pytest.raises(ValidationError):
        VisitCreate(visit_date="2024-01-01", indicators=[])

def test_snapshot_contains_sorted_visits_without_user_identity():
    snapshot = build_input_snapshot(case, visits_out_of_order)
    assert [v["visit_date"] for v in snapshot["visits"]] == ["2024-01-01", "2024-06-01"]
    assert "real_name" not in snapshot
```

- [ ] **Step 2: Run tests to verify the new schemas/service fail**

Run: `python -m pytest backend/tests/test_longitudinal_case_service.py -v`

Expected: FAIL because the schemas and service functions are not implemented.

- [ ] **Step 3: Implement Pydantic contracts**

Define `IndicatorValue`, `OperatorCaseCreate`, `OperatorCaseUpdate`, `OperatorCaseOut`, `VisitCreate`, `VisitUpdate`, `VisitOut`, and list response models. Validate finite numeric values, nonempty names/units, `male|female` sex, ISO dates, one or more indicators, and max 10 visits per case.

- [ ] **Step 4: Implement service ownership and ordering**

Load a case only with `OperatorCase.user_id == current_user.id`. On every visit write, reject duplicate `(case_id, visit_date)`, sort all visits by date, rewrite `visit_index` from 1, and return the ordered list. `build_input_snapshot()` must include disease, case metadata, ordered visits, requested model options and no personally identifying user fields.

- [ ] **Step 5: Add CRUD routes**

Add authenticated routes for create/list/get/update/delete cases and create/update/delete visits. Use `require_ai_operator`; return 404 for another user’s case rather than revealing existence. Keep existing `/operator/cases` reference-case routes unchanged during the migration.

- [ ] **Step 6: Run focused API/service tests**

Run: `python -m pytest backend/tests/test_longitudinal_case_service.py backend/tests/test_operator_permissions.py -v`

Expected: PASS, including cross-user access denial and duplicate-date rejection.

- [ ] **Step 7: Commit the case workflow**

```powershell
git add backend/app/schemas/longitudinal_case.py backend/app/services/longitudinal_case_service.py backend/app/api/operator.py backend/tests/test_longitudinal_case_service.py
git commit -m "feat: add operator longitudinal case workflow"
```

### Task 3: Refactor feature extraction for historical prefixes

**Files:**
- Create: `backend/app/services/longitudinal_features.py`
- Create: `backend/tests/test_longitudinal_features.py`
- Modify: `backend/app/services/progression_engine.py`

**Interfaces:**
- `sort_visits(visits) -> list[dict]`
- `build_prefixes(visits, minimum_visits=2) -> list[dict]`
- `summarize_observation(visits) -> dict`
- `build_feature_vector(visits, feature_names) -> list[float]`
- Existing `extract_features(visits)` remains backward-compatible for current tests.

- [ ] **Step 1: Write prefix and missingness tests**

```python
def test_prefixes_never_include_future_visits():
    visits = [visit("2024-01-01"), visit("2024-06-01"), visit("2025-01-01")]
    prefixes = build_prefixes(visits, minimum_visits=2)
    assert len(prefixes) == 2
    assert prefixes[0]["as_of"] == "2024-06-01"
    assert len(prefixes[0]["visits"]) == 2

def test_observation_summary_reports_span_and_missingness():
    result = summarize_observation(visits)
    assert result["visit_count"] == 3
    assert result["observation_span_days"] == 366
    assert result["missingness_summary"]["ALT"] == pytest.approx(1 / 3)
```

- [ ] **Step 2: Run the focused feature tests and verify failure**

Run: `python -m pytest backend/tests/test_longitudinal_features.py -v`

Expected: FAIL because the prefix and observation functions do not exist.

- [ ] **Step 3: Implement deterministic feature helpers**

Sort by parsed `date`, reject duplicate dates, build each historical prefix without later rows, compute observation span, per-indicator missingness, first/last/delta/delta percentage/slope/rises/observation count, and latest reference-range status. Preserve the existing feature names used by model metadata.

- [ ] **Step 4: Run existing progression tests**

Run: `python -m pytest backend/tests/test_prediction_engine.py backend/tests/test_progression_engine.py backend/tests/test_longitudinal_features.py -v`

Expected: PASS; the old `extract_features()` and existing structured endpoint behavior remain compatible.

- [ ] **Step 5: Commit feature extraction**

```powershell
git add backend/app/services/longitudinal_features.py backend/app/services/progression_engine.py backend/tests/test_longitudinal_features.py
git commit -m "feat: add longitudinal prefix feature extraction"
```

### Task 4: Train time-aware outcome and stage models

**Files:**
- Create: `scripts/tests/test_train_longitudinal_models.py`
- Modify: `scripts/train_progression_model.py`
- Create: `scripts/train_longitudinal_models.py`
- Create: `backend/app/services/disease_progression.py`
- Modify: `backend/app/ml_models/*.meta.json` only when regenerated by the approved training command

**Interfaces:**
- `build_prefix_training_rows(patient_visits, adapter) -> TrainingRows`
- `patient_grouped_cv(rows, labels, groups, estimator_factory) -> CVReport`
- `train_outcome_model(dataset, db_url, out_dir, horizons) -> ModelMetadata`
- `DiseaseProgressionAdapter.outcome_label(patient, as_of, horizon) -> int | None`
- `DiseaseProgressionAdapter.stage_label(patient, as_of) -> str | None`

- [ ] **Step 1: Add tests for temporal labels and patient grouping**

```python
def test_prefix_label_uses_event_date_after_as_of():
    label = fatty_liver_adapter.outcome_label(
        {"event_dates": {"cirrhosis_date": "2025-01-01"}},
        as_of=date(2024, 1, 1),
        horizon=timedelta(days=365),
    )
    assert label == 0

def test_grouped_folds_keep_patient_prefixes_together():
    folds = patient_grouped_cv(rows, labels, groups, estimator_factory)
    for fold in folds:
        assert set(fold.train_groups).isdisjoint(fold.validation_groups)
```

- [ ] **Step 2: Run training tests to verify failure**

Run: `python -m pytest scripts/tests/test_train_longitudinal_models.py -v`

Expected: FAIL because adapters and prefix-label training functions are not present.

- [ ] **Step 3: Implement disease adapters**

Define explicit fatty-liver and AD adapters with disease name, dataset, target labels, stage order, key indicators, event-date fields, minimum visits, and synthetic-data warning. Return `None` for an unestimable horizon rather than treating missing event dates as negative labels.

- [ ] **Step 4: Build prefix training rows**

Load imported reference records grouped by `(source_dataset, patient_label)`, sort visits, produce historical prefixes, extract features using only visits up to each prefix, and label each prefix from event dates/final stage. Exclude prefixes with unknown labels from the corresponding horizon while preserving patient group IDs.

- [ ] **Step 5: Train and persist outcome/stage artifacts**

Use patient-grouped folds, an imputer plus the existing GradientBoosting family for outcome models, and an explicit stage model only where labels support it. Persist `.joblib` and `.meta.json` containing dataset, target, horizon, feature order, patient count, synthetic ratio, fold metrics, calibration status and training timestamp. Do not claim calibrated probabilities until a calibration evaluation is implemented.

- [ ] **Step 6: Run offline training and inspect metrics**

Run:

```powershell
python scripts/train_longitudinal_models.py --dataset fatty_liver --horizon 12_months
python scripts/train_longitudinal_models.py --dataset ad --horizon 12_months
```

Expected: patient-level fold reports, explicit counts of estimable/unknown labels, and artifacts under `backend/app/ml_models/`. The owner must review metrics before enabling a model in the API.

- [ ] **Step 7: Run model tests**

Run: `python -m pytest scripts/tests/test_train_longitudinal_models.py backend/tests/test_progression_engine.py -v`

Expected: PASS, including no future-visit leakage and clear missing-artifact errors.

- [ ] **Step 8: Commit the model contract**

```powershell
git add scripts/train_progression_model.py scripts/train_longitudinal_models.py scripts/tests/test_train_longitudinal_models.py backend/app/services/disease_progression.py backend/tests/test_progression_engine.py
git commit -m "feat: add time-aware longitudinal outcome models"
```

### Task 5: Add indicator trend direction models

**Files:**
- Create: `scripts/train_longitudinal_trend_models.py`
- Create: `scripts/tests/test_train_longitudinal_trend_models.py`
- Create: `backend/tests/test_longitudinal_trend_prediction.py`
- Modify: `backend/app/services/disease_progression.py`

**Interfaces:**
- `derive_next_visit_direction(current, next_value, tolerance) -> str`
- `build_trend_training_rows(patient_visits, adapter) -> TrendRows`
- `predict_indicator_trends(visits, adapter, model_registry) -> list[dict]`

- [ ] **Step 1: Write direction-label tests**

```python
def test_direction_label_uses_tolerance_for_stable_values():
    assert derive_next_visit_direction(100, 102, tolerance=0.05) == "stable"
    assert derive_next_visit_direction(100, 120, tolerance=0.05) == "rising"
    assert derive_next_visit_direction(100, 80, tolerance=0.05) == "falling"
```

- [ ] **Step 2: Run trend tests and verify failure**

Run: `python -m pytest scripts/tests/test_train_longitudinal_trend_models.py backend/tests/test_longitudinal_trend_prediction.py -v`

Expected: FAIL because direction labels and trend inference are not implemented.

- [ ] **Step 3: Implement direction-only training rows**

For each patient prefix with a later observed value for a key indicator, label the next observed direction using an adapter-specific tolerance. Keep patient IDs as groups. Do not produce rows for indicators with no later observation.

- [ ] **Step 4: Train and persist trend artifacts**

Train one direction model per disease/indicator only when class counts meet a documented minimum. Persist direction metrics, class counts, feature order, horizon semantics and `forecast_mode="direction_only"`. Missing or insufficient models must be represented as unavailable, not as a neutral prediction.

- [ ] **Step 5: Implement inference output**

Return `observed`, `reference`, `forecast`, and `importance` objects exactly as the design contract requires. Use `projected_value=null` and `prediction_interval=null` for direction-only models.

- [ ] **Step 6: Run focused tests and commit**

Run: `python -m pytest scripts/tests/test_train_longitudinal_trend_models.py backend/tests/test_longitudinal_trend_prediction.py -v`

Expected: PASS.

```powershell
git add scripts/train_longitudinal_trend_models.py scripts/tests/test_train_longitudinal_trend_models.py backend/app/services/disease_progression.py backend/tests/test_longitudinal_trend_prediction.py
git commit -m "feat: add longitudinal indicator trend prediction"
```

### Task 6: Implement the structured longitudinal prediction service

**Files:**
- Create: `backend/app/schemas/longitudinal_report.py`
- Create: `backend/tests/test_longitudinal_prediction_contract.py`
- Create: `backend/app/services/longitudinal_prediction.py`
- Modify: `backend/app/services/progression_engine.py`

**Interfaces:**
- `run_longitudinal_prediction(case, visits, adapter, model_registry) -> LongitudinalPredictionResult`
- `validate_prediction_result(result) -> LongitudinalPredictionResult`
- `prediction_result_to_dict(result) -> dict`

- [ ] **Step 1: Write the result-contract tests**

```python
def test_result_contains_outcome_stage_and_trend_sections():
    result = run_longitudinal_prediction(case, visits, fatty_liver_adapter, registry)
    assert result.schema_version == "longitudinal_prediction.v1"
    assert result.outcome_prediction.risk_score is not None
    assert result.outcome_prediction.stage_projection.status in {"available", "not_estimated"}
    assert result.trend_predictions[0].forecast.status in {"direction_only", "not_estimable"}

def test_unavailable_stage_never_emits_a_stage_guess():
    result = run_longitudinal_prediction(case, visits, adapter_without_stage_model, registry)
    assert result.outcome_prediction.stage_projection.status == "not_estimated"
    assert result.outcome_prediction.stage_projection.likely_next_stage is None
```

- [ ] **Step 2: Run the contract tests and verify failure**

Run: `python -m pytest backend/tests/test_longitudinal_prediction_contract.py -v`

Expected: FAIL because the schemas and service do not exist.

- [ ] **Step 3: Implement Pydantic result schemas**

Define models for disease, observation, prediction windows, confidence, stage projection, observed trend, reference status, forecast, trend importance, evidence and warnings. Use explicit nullable fields and enum-like literals for `available`, `not_estimable`, `not_estimated`, `direction_only`, and `model_score` semantics.

- [ ] **Step 4: Implement the service pipeline**

Validate minimum visits, dates and indicators; resolve the disease adapter; calculate observation summaries; load only models matching dataset/feature metadata; calculate follow-up and available fixed-window outcome scores; call stage and trend predictors; add synthetic-data, calibration, missingness and sample-size warnings; validate the final object before returning it.

- [ ] **Step 5: Keep the existing structured endpoint compatible**

Adapt `/operator/progression-predictions` to call the new service and map the complete result to the old `ProgressionPredictionOut` only when the client requests the legacy endpoint. The new report endpoint must use the complete `LongitudinalPredictionResult`, not the reduced legacy response.

- [ ] **Step 6: Run prediction tests and commit**

Run: `python -m pytest backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_progression_api.py backend/tests/test_progression_engine.py -v`

Expected: PASS with explicit unavailable-model behavior.

```powershell
git add backend/app/schemas/longitudinal_report.py backend/app/services/longitudinal_prediction.py backend/app/services/progression_engine.py backend/tests/test_longitudinal_prediction_contract.py backend/tests/test_progression_api.py
git commit -m "feat: add structured longitudinal prediction result"
```

### Task 7: Implement longitudinal evidence selection

**Files:**
- Create: `backend/app/services/longitudinal_evidence.py`
- Create: `backend/tests/test_longitudinal_evidence.py`
- Modify: `backend/app/services/prediction_generator.py` only if shared source helpers are extracted without changing single-time behavior

**Interfaces:**
- `select_similar_longitudinal_cases(db, disease_id, visits, adapter, limit=5) -> list[dict]`
- `build_reference_range_sources(db, indicator_names, patient_sex) -> list[dict]`
- `build_document_sources(db, disease_id, indicator_names) -> list[dict]`
- `mark_synthetic_source(source) -> dict`

- [ ] **Step 1: Write source provenance tests**

```python
def test_synthetic_reference_case_is_explicitly_marked():
    source = mark_synthetic_source({"patient_label": "P151", "is_synthetic": True})
    assert source["provenance"] == "synthetic"
    assert "合成" in source["display_warning"]

def test_similarity_uses_trajectory_features_not_patient_identity():
    selected = select_similar_longitudinal_cases(db, disease_id, visits, adapter, limit=5)
    assert all("patient_label" in item for item in selected)
    assert all("overlap_features" in item for item in selected)
```

- [ ] **Step 2: Run evidence tests and verify failure**

Run: `python -m pytest backend/tests/test_longitudinal_evidence.py -v`

Expected: FAIL because the evidence service does not exist.

- [ ] **Step 3: Implement trajectory similarity and provenance**

Group reference `CaseRecord` rows by source dataset and patient label, derive the same observation features used by the model, rank by comparable trajectory features and target outcome, cap results at five, and include `source_dataset`, `is_synthetic`, final outcome, and overlap features. Never expose raw internal identity beyond the reference label already used by the project.

- [ ] **Step 4: Implement range/document sources**

Reuse reference-range selection semantics, including sex-specific ranges and inclusive boundaries. Query only documents available to `ai_operator` through existing scope rules. Normalize all source objects to citation index, title, content, document ID, page, source type, and provenance.

- [ ] **Step 5: Run evidence and source-access tests**

Run: `python -m pytest backend/tests/test_longitudinal_evidence.py backend/tests/test_source_access.py backend/tests/test_reference_standard.py -v`

Expected: PASS with operator-only source filtering.

- [ ] **Step 6: Commit evidence selection**

```powershell
git add backend/app/services/longitudinal_evidence.py backend/tests/test_longitudinal_evidence.py backend/app/services/prediction_generator.py
git commit -m "feat: add longitudinal prediction evidence selection"
```

### Task 8: Build the persisted longitudinal report generator

**Files:**
- Create: `backend/app/services/longitudinal_report_generator.py`
- Create: `backend/tests/test_longitudinal_report_generator.py`
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/schemas/longitudinal_report.py`

**Interfaces:**
- `generate_longitudinal_report(db, user_id, case_id) -> AsyncGenerator[str, None]`
- `build_longitudinal_prompt(snapshot, prediction_result, evidence) -> ChatPromptValue`
- `validate_report_markdown(content, prediction_result) -> list[str]`
- `persist_longitudinal_report(db, report_id, content, prediction_result, sources, snapshot) -> None`

- [ ] **Step 1: Write persistence and prompt-safety tests**

```python
def test_report_is_saved_with_snapshot_and_structured_result(db):
    report_id = create_generating_report(db, case, snapshot)
    persist_longitudinal_report(db, report_id, "## 报告摘要\n...", result, sources, snapshot)
    report = db.query(AIReport).get(report_id)
    assert report.analysis_type == "longitudinal_predictive"
    assert report.input_snapshot["visits"] == snapshot["visits"]
    assert report.prediction_result["schema_version"] == "longitudinal_prediction.v1"

def test_validator_rejects_unavailable_stage_claim():
    errors = validate_report_markdown("预测将进入肝硬化", result_with_not_estimated_stage)
    assert errors
```

- [ ] **Step 2: Run generator tests and verify failure**

Run: `python -m pytest backend/tests/test_longitudinal_report_generator.py -v`

Expected: FAIL because the generator and validation functions do not exist.

- [ ] **Step 3: Implement fixed-section prompt and source grounding**

Build the nine required sections plus technical appendix. Pass the structured result, input snapshot and evidence as separate immutable blocks. Instruct the LLM to preserve all numbers, render unavailable fields with their explicit status, avoid diagnostic certainty, identify synthetic sources, and end with the fixed disclaimer.

- [ ] **Step 4: Implement streaming and guarded persistence**

Create `AIReport(status="generating", analysis_type="longitudinal_predictive")` before model generation. Emit `stage`, `prediction`, `delta`, `sources`, `done`, and `error` events. Persist the structured result before starting LLM streaming; persist content periodically; on completion set title/content/sources/status; on LLM failure set `failed` while retaining structured result and snapshot; on client cancellation set `cancelled` only from `generating`.

- [ ] **Step 5: Implement markdown consistency validation**

Check required headings, final disclaimer, forbidden certainty terms, and selected numeric facts from the structured result. Validation failure must mark the report failed or trigger one constrained regeneration; never silently save an ungrounded report.

- [ ] **Step 6: Add the report route**

Add `POST /operator/longitudinal-cases/{case_id}/prediction-reports` using `require_ai_operator`, owner validation and `StreamingResponse(media_type="text/event-stream")`. Reuse existing report ownership/download functions after adding `operator_case_id` filtering where needed.

- [ ] **Step 7: Run generator/API/PDF tests and commit**

Run: `python -m pytest backend/tests/test_longitudinal_report_generator.py backend/tests/test_pdf_generation.py backend/tests/test_operator_predictive_api.py -v`

Expected: PASS; LLM failure and cancellation leave auditable terminal state.

```powershell
git add backend/app/services/longitudinal_report_generator.py backend/app/api/operator.py backend/app/schemas/longitudinal_report.py backend/tests/test_longitudinal_report_generator.py
git commit -m "feat: generate and persist longitudinal prediction reports"
```

### Task 9: Add report API contracts and preserve single-time behavior

**Files:**
- Create: `backend/tests/test_longitudinal_report_api.py`
- Modify: `backend/app/schemas/operator.py`
- Modify: `backend/app/api/operator.py`
- Modify: `backend/tests/test_operator_predictive_api.py`

**Interfaces:**
- `ReportOut` and `ReportListItem` expose `operator_case_id`, `input_snapshot` only when present, and the full `prediction_result`.
- `GET /operator/reports?analysis_type=longitudinal_predictive` filters longitudinal reports.

- [ ] **Step 1: Add response-schema tests**

```python
def test_longitudinal_report_response_exposes_case_and_snapshot():
    fields = ReportOut.model_fields
    assert {"operator_case_id", "input_snapshot"}.issubset(fields)

def test_single_time_predictive_report_contract_is_unchanged():
    assert ReportOut.model_fields["analysis_type"].default == "retrospective"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest backend/tests/test_longitudinal_report_api.py backend/tests/test_operator_predictive_api.py -v`

Expected: FAIL only for the new longitudinal fields/filter behavior.

- [ ] **Step 3: Extend schemas and list filtering**

Add nullable fields with safe defaults for old rows. Keep existing owner verification. Ensure list and detail endpoints return the new fields without requiring non-null values on old single-time reports.

- [ ] **Step 4: Add integration tests**

Cover: create longitudinal report, list by analysis type, fetch detail, download completed PDF, reject another user, reject non-completed download, and confirm old `/operator/reports` single-time tests pass unchanged.

- [ ] **Step 5: Run backend API regression tests and commit**

Run: `python -m pytest backend/tests/test_longitudinal_report_api.py backend/tests/test_operator_predictive_api.py backend/tests/test_operator_permissions.py -v`

Expected: PASS.

```powershell
git add backend/app/schemas/operator.py backend/app/api/operator.py backend/tests/test_longitudinal_report_api.py backend/tests/test_operator_predictive_api.py
git commit -m "feat: expose longitudinal reports through operator APIs"
```

### Task 10: Build the frontend longitudinal case editor and summary

**Files:**
- Create: `frontend/src/components/LongitudinalCaseEditor.vue`
- Create: `frontend/src/components/LongitudinalPredictionSummary.vue`
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/components/OperatorSidebar.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Test: `frontend/tests/longitudinal-report-ui-contract.test.mjs`

**Interfaces:**
- API functions: `listLongitudinalCases`, `createLongitudinalCase`, `updateLongitudinalCase`, `deleteLongitudinalCase`, `addLongitudinalVisit`, `updateLongitudinalVisit`, `deleteLongitudinalVisit`, `generateLongitudinalReportStream`.
- Store state: `longitudinalCases`, `currentLongitudinalCase`, `longitudinalPrediction`, `longitudinalReportGenerating`, `longitudinalReportContent`, `longitudinalReportStage`.

- [ ] **Step 1: Read the UI design spec and write UI contract tests**

Before editing Vue files, read `docs/DESIGN_SPEC.md` completely. Add tests asserting the default view contains a longitudinal case workflow, a visit timeline, a report-generation action, required report sections, and a clear loading/error state.

- [ ] **Step 2: Run the frontend contract tests and verify failure**

Run: `npm --prefix frontend test -- --runInBand` if the configured test command supports it; otherwise run `node frontend/tests/longitudinal-report-ui-contract.test.mjs`.

Expected: FAIL because the new component and labels are not present.

- [ ] **Step 3: Add typed API clients and SSE parsing**

Define TypeScript interfaces matching `longitudinal_case.py` and `longitudinal_report.py`. Parse `stage`, `prediction`, `delta`, `sources`, `done`, and `error`. Return an abort function and ensure `AbortError` does not display as a network failure.

- [ ] **Step 4: Add Pinia state and actions**

Implement fetch/create/update/delete case actions, visit actions, start/cancel report generation, report selection, and reset behavior. On `prediction`, populate the structured summary immediately; on `done`, refresh the report list and detail; on error, retain structured prediction if available and show failed state.

- [ ] **Step 5: Build the case editor**

Create a disease selector, internal label, baseline stage, sex, notes, date-sorted visit cards, reusable `IndicatorRowsEditor`, duplicate-date prevention, minimum-visit validation, and save/update controls. Use stable dimensions and existing CSS variables.

- [ ] **Step 6: Build the structured summary**

Render outcome risk as “模型风险等级/模型分数”, not clinical probability; render stage status, time-window status, observed trends, direction-only forecasts, missingness, model caveats, and synthetic-data warnings. Do not render absent projected values as zero or blank certainty.

- [ ] **Step 7: Rework the operator view**

Make longitudinal prediction the default workbench view. Keep the single-time quick assessment and reference-case management as separate navigation items. Add streaming Markdown report content, report history, source cards, re-run action and PDF download. Respect the existing scroll-follow behavior.

- [ ] **Step 8: Run frontend checks and commit**

Run: `npm --prefix frontend run build` and `node frontend/tests/longitudinal-report-ui-contract.test.mjs`.

Expected: TypeScript/Vite build succeeds and the UI contract passes.

```powershell
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/src/components/OperatorSidebar.vue frontend/src/components/LongitudinalCaseEditor.vue frontend/src/components/LongitudinalPredictionSummary.vue frontend/src/views/OperatorView.vue frontend/tests/longitudinal-report-ui-contract.test.mjs
git commit -m "feat: add longitudinal prediction report workbench"
```

### Task 11: Align PDF output with longitudinal reports

**Files:**
- Modify: `backend/app/services/pdf_generator.py` only if metadata/footer handling is needed
- Modify: `backend/app/templates/report_pdf.html`
- Create: `backend/tests/test_longitudinal_pdf_contract.py`

**Interfaces:**
- `generate_pdf(markdown_content, title)` continues to accept Markdown and returns PDF bytes.
- Longitudinal Markdown headings/tables/disclaimers must render without losing provenance warnings.

- [ ] **Step 1: Write PDF content tests**

```python
def test_longitudinal_markdown_keeps_required_sections_and_warning():
    html = markdown_to_safe_html(longitudinal_markdown)
    assert "疾病阶段与进展结局预测" in html
    assert "合成数据" in html
    assert "不构成诊断" in html
```

- [ ] **Step 2: Run PDF tests and identify missing styling/allowlist behavior**

Run: `python -m pytest backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_pdf_generation.py -v`

Expected: Existing pipeline passes basic rendering; any missing table/blockquote/sup styling is visible in the focused contract.

- [ ] **Step 3: Update only the required template styles**

Keep the existing PDF sanitization allowlist. Add styles for warning blocks, model-status labels, trend tables, source provenance and technical appendix without embedding untrusted HTML.

- [ ] **Step 4: Render a real sample PDF**

Run the project PDF test with Playwright installed and inspect the generated page image/PDF for page breaks, Chinese text, tables, warnings and footer numbering.

- [ ] **Step 5: Commit PDF alignment**

```powershell
git add backend/app/services/pdf_generator.py backend/app/templates/report_pdf.html backend/tests/test_longitudinal_pdf_contract.py
git commit -m "feat: format longitudinal prediction PDFs"
```

### Task 12: End-to-end verification, data leakage audit and handoff

**Files:**
- Create: `backend/tests/test_longitudinal_end_to_end.py`
- Create: `docs/superpowers/validation/longitudinal-prediction-report-001.md`
- Modify: `docs/DEVELOPMENT.md` only to document the verified local commands and model artifact prerequisites

- [ ] **Step 1: Add end-to-end test fixture**

Create a deterministic fixture with one fatty-liver case, three visits, a fake compatible outcome model, a fake trend model, a reference case, and a mocked LLM stream. Assert the completed report contains the structured prediction, all required headings, sources, input snapshot and `analysis_type="longitudinal_predictive"`.

- [ ] **Step 2: Add failure-path tests**

Cover duplicate dates, insufficient visits, missing model artifact, incompatible model metadata, unavailable 12-month window, unavailable stage model, LLM exception, client cancellation, owner mismatch, and failed-report PDF download.

- [ ] **Step 3: Run backend verification**

Run:

```powershell
python -m pytest backend/tests -v
python -m pytest scripts/tests -v
```

Expected: all existing and new tests pass. Any model metric that is not estimable must be reported as such rather than converted to zero.

- [ ] **Step 4: Run frontend verification**

Run:

```powershell
npm --prefix frontend run build
node frontend/tests/longitudinal-report-ui-contract.test.mjs
```

Expected: build and UI contract pass.

- [ ] **Step 5: Perform the leakage and provenance audit**

Verify that every training sample has an `as_of` date, no feature reads a later visit, patient IDs are disjoint across folds, unknown event dates are not negative labels, synthetic reference cases are marked, and report numbers match the stored `prediction_result`.

- [ ] **Step 6: Verify database migration and PDF path**

Run Alembic upgrade/downgrade checks against a disposable PostgreSQL database, then upgrade again and generate a completed longitudinal PDF. Confirm old `AIReport` rows and single-time reports remain readable.

- [ ] **Step 7: Write validation evidence and handoff**

Record commands, model artifact versions, CV metrics, known non-estimable windows, screenshots/PDF checks, and residual risks in `docs/superpowers/validation/longitudinal-prediction-report-001.md`. Do not claim clinical validity; state that the artifacts are for internal workflow/model validation unless separately approved.

```powershell
git add backend/tests/test_longitudinal_end_to_end.py docs/superpowers/validation/longitudinal-prediction-report-001.md docs/DEVELOPMENT.md
git commit -m "test: verify longitudinal prediction report workflow"
```

### Task 13: Remove confirmed legacy operator report code

**Files:**
- Modify: `frontend/src/api/operator.ts`
- Modify: `frontend/src/stores/operator.ts`
- Create: `frontend/tests/operator-legacy-cleanup.test.mjs`
- Modify: `docs/DEVELOPMENT.md` only if it documents the removed generic report API

**Scope boundary:**

The reference-case CRUD functions (`listCases`, `createCase`, `updateCase`, `deleteCase`) remain because `CaseManageView.vue` uses them. The prediction stream (`generatePredictionStream`) remains because single-time quick assessment remains supported. Shared `ReportStreamCallbacks`, `parseOperatorSSE`, `currentSources`, report list/detail/delete/download functions, and cancellation behavior remain where used by the current or longitudinal report flows.

The confirmed dead code is the old generic report path:

- `generateReportStream(query, departmentIds, analysisBackend, callbacks)` in `frontend/src/api/operator.ts`;
- `generateReport(query, departmentIds, analysisBackend)` in `frontend/src/stores/operator.ts`;
- the `generateReportStream` import and returned `generateReport` store action;
- the unused `analysis_backend` request construction and `analysisBackend` parameter associated only with that path.

- [ ] **Step 1: Freeze the reference scan in a test**

```javascript
import fs from 'node:fs'

const api = fs.readFileSync('frontend/src/api/operator.ts', 'utf8')
const store = fs.readFileSync('frontend/src/stores/operator.ts', 'utf8')

if (api.includes('function generateReportStream')) throw new Error('legacy API still present')
if (store.includes('function generateReport(')) throw new Error('legacy store action still present')
if (store.includes('generateReportStream')) throw new Error('legacy store import still present')
if (api.includes('analysis_backend')) throw new Error('legacy backend selector still present')
```

- [ ] **Step 2: Run the cleanup test before deletion**

Run: `node frontend/tests/operator-legacy-cleanup.test.mjs`

Expected: FAIL because the old generic report functions are still present.

- [ ] **Step 3: Re-run the repository reference search**

Run: `rg -n -S "generateReportStream|generateReport\(|analysisBackend|analysis_backend" frontend/src backend/app backend/tests`

Record all remaining references. Only references belonging to this task’s dead generic path may be removed; any reference from a live single-time or longitudinal flow must remain and be renamed only when necessary for clarity.

- [ ] **Step 4: Remove only unreferenced generic report code**

Delete the old API function and store action/import. Keep `generatePredictionStream` and all report history/download functions. Do not remove backend `AIReport` fields used by old persisted rows, and do not delete historical design documents.

- [ ] **Step 5: Run cleanup and regression checks**

Run:

```powershell
node frontend/tests/operator-legacy-cleanup.test.mjs
rg -n -S "generateReportStream|generateReport\(|analysisBackend|analysis_backend" frontend/src backend/app backend/tests
npm --prefix frontend run build
```

Expected: the cleanup test passes, the reference search returns no live-code matches for the deleted generic path, and the frontend build succeeds.

- [ ] **Step 6: Commit the cleanup separately**

```powershell
git add frontend/src/api/operator.ts frontend/src/stores/operator.ts frontend/tests/operator-legacy-cleanup.test.mjs docs/DEVELOPMENT.md
git commit -m "refactor: remove unused operator report stream"
```

## Dependency and Review Gates

1. Task 1 must complete before Tasks 2, 8 and 9.
2. Task 3 must complete before Tasks 4, 5 and 6.
3. Task 4 must pass an owner metric review before enabling outcome/12-month models in production API code.
4. Task 5 may ship direction-only forecasts; exact future values remain disabled until independent evaluation passes.
5. Tasks 6 and 7 must complete before Task 8 can generate a report.
6. Task 8 must pass a second-agent review because it changes the RAG/LLM report path and persistence state machine.
7. Task 10 must be reviewed against `docs/DESIGN_SPEC.md` before merging UI work.
8. Task 13 runs after the frontend API/store flow has been migrated, so cleanup cannot remove a still-used path.
9. Task 12 is the completion gate; no “complete” claim is made before backend, frontend, migration, leakage, legacy-cleanup and PDF checks pass.

## Out of Scope for This Plan

- Automatic import from a real EHR/EMR.
- Patient-identifying fields such as name or ID number.
- Treatment or prescription generation.
- Exact future numeric intervals before independent validation.
- Online model retraining or hot reload.
- Merging the `research/` experimental pipeline into production operator APIs.
