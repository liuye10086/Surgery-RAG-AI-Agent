# 纵向进展预测 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增"纵向进展预测"能力：操作者录入新患者的多次访视指标序列，用基于 300 例纵向病例（含真实+合成）训练的机器学习模型输出进展风险。与现有单时点预测并存，互不影响。

**Architecture:** 离线训练脚本（`scripts/train_progression_model.py`）产出 joblib 模型 artifact；新增推理服务 `progression_engine.py`（纯函数特征提取 + 懒加载模型）；新增独立 API 端点 `/operator/progression-predictions`（同步响应，不接 LLM、不落库）；前端新增"进展预测" tab。MVP 范围明确排除 LLM 叙述、趋势图表、报告历史（见设计规格 §6）。

**Tech Stack:** Python 3.11、scikit-learn（新依赖）、joblib（新依赖）、SQLAlchemy（读 case_records）、Vue 3 + Element Plus（前端）。

**Design Spec:** [2026-08-20-longitudinal-progression-prediction-design.md](../specs/2026-08-20-longitudinal-progression-prediction-design.md)

---

## Global Constraints

- 简化流程，在当前 `main` 工作区实施；完成后交 Codex 事后评审；不提交、不推送直到用户授权。
- **训练数据使用全量 300 例**：P001-300 全部使用（含 150 例真实 + 150 例合成），不过滤 `is_synthetic`，换取样本量优势。
- 不修改现有 `/operator/reports`、`prediction_engine.py`、`prediction_generator.py`（单时点预测路径零改动）。
- 不新增 Alembic 迁移；预测结果不落 `AIReport`/新表。
- 新增依赖 `scikit-learn`/`joblib` 需在 `backend/requirements.txt` 固定版本号（不用开放范围）。
- 模型文件缺失时 API 必须返回明确错误，禁止静默降级或返回假结果。
- 训练脚本的 CV 结果是否达到"可接入服务"标准，由项目所有者人工判断，不设自动化硬阈值。
- MVP 范围排除项（不做）：LLM 叙述报告、趋势图表、结果持久化、模型自动重训练。

---

## File Structure

- `scripts/train_progression_model.py`：离线训练脚本（模块 + CLI）。
- `scripts/tests/test_train_progression_model.py`：训练脚本单测（特征提取、患者级分折、样本过滤）。
- `backend/app/ml_models/`：模型 artifact 目录（`.gitignore` 排除 `*.joblib`）。
- `backend/app/services/progression_engine.py`：特征提取 + 推理服务。
- `backend/tests/test_progression_engine.py`：推理单测。
- `backend/app/schemas/progression.py`：请求/响应 schema。
- `backend/app/api/operator.py`：追加新端点。
- `frontend/src/api/operator.ts`、`frontend/src/stores/operator.ts`、`frontend/src/views/OperatorView.vue`、`frontend/src/components/IndicatorRowsEditor.vue`（新增抽取组件）。

---

### Task 1: 特征提取纯函数（TDD，不依赖 DB/模型）

**Files:**
- Create: `backend/app/services/progression_engine.py`
- Create: `backend/tests/test_progression_engine.py`

**Interfaces:**
- Produces: `extract_features(visits: list[dict]) -> dict`。

- [ ] **Step 1: 写失败测试**

```python
def test_extract_features_single_visit_no_slope(self):
    visits = [{"visit_date": "2024-01-01", "indicators": [{"name": "alt", "value": 60}]}]
    features = extract_features(visits)
    self.assertEqual(features["alt"]["first"], 60)
    self.assertEqual(features["alt"]["last"], 60)
    self.assertIsNone(features["alt"]["slope"])  # 单点无法拟合斜率
    self.assertEqual(features["alt"]["n_observations"], 1)

def test_extract_features_multi_visit_computes_slope_and_rises(self):
    visits = [
        {"visit_date": "2024-01-01", "indicators": [{"name": "alt", "value": 60}]},
        {"visit_date": "2024-03-01", "indicators": [{"name": "alt", "value": 70}]},
        {"visit_date": "2024-06-01", "indicators": [{"name": "alt", "value": 90}]},
    ]
    features = extract_features(visits)
    self.assertEqual(features["alt"]["first"], 60)
    self.assertEqual(features["alt"]["last"], 90)
    self.assertEqual(features["alt"]["delta"], 30)
    self.assertAlmostEqual(features["alt"]["delta_pct"], 0.5)
    self.assertGreater(features["alt"]["slope"], 0)
    self.assertEqual(features["alt"]["rises_count"], 2)
    self.assertEqual(features["alt"]["n_observations"], 3)

def test_extract_features_handles_missing_indicator_values(self):
    visits = [
        {"visit_date": "2024-01-01", "indicators": [{"name": "alt", "value": 60}]},
        {"visit_date": "2024-03-01", "indicators": []},  # 该次未测 alt
        {"visit_date": "2024-06-01", "indicators": [{"name": "alt", "value": 90}]},
    ]
    features = extract_features(visits)
    self.assertEqual(features["alt"]["n_observations"], 2)
    self.assertEqual(features["alt"]["rises_count"], 1)

def test_extract_features_zero_first_value_delta_pct_none(self):
    visits = [
        {"visit_date": "2024-01-01", "indicators": [{"name": "x", "value": 0}]},
        {"visit_date": "2024-03-01", "indicators": [{"name": "x", "value": 5}]},
    ]
    features = extract_features(visits)
    self.assertIsNone(features["x"]["delta_pct"])
```

- [ ] **Step 2: 运行测试验证 RED**

```powershell
python -m pytest backend/tests/test_progression_engine.py -v
```

- [ ] **Step 3: 实现 `extract_features`**

用标准库实现简单线性回归斜率（`(x_i - x_mean)(y_i - y_mean)` 求和 / `(x_i - x_mean)^2` 求和，不引入 numpy）；`rises_count` 遍历相邻非空观测对比较。

- [ ] **Step 4: 运行测试验证 GREEN**

---

### Task 2: 训练脚本（读全量病例、患者级分折、产出 artifact）

**Files:**
- Create: `scripts/train_progression_model.py`
- Create: `scripts/tests/test_train_progression_model.py`
- Modify: `backend/requirements.txt`（新增 `scikit-learn==1.5.2`、`joblib==1.4.2`，版本号以实际安装可用版本为准）

**Interfaces:**
- Consumes: `case_records`（全部 300 例，不过滤 `is_synthetic`）。
- Produces: `load_all_patients(db, disease_name)`、`build_training_rows(patients_visits)`、`patient_kfold_cv(rows, labels, patient_ids, k=5)`、`train_and_save(dataset, db_url, out_dir)`。

- [ ] **Step 1: 写失败测试（样本加载 + 分折）**

```python
def test_load_all_patients_includes_all_300_cases(self):
    # SQLite 内存库注入：300 条 case（模拟 P001-300）
    # 断言返回 300 个患者的访视序列
    ...

def test_patient_kfold_cv_never_splits_same_patient_across_folds(self):
    # 构造 10 个患者、每患者 1 行训练样本，5-fold
    # 断言每折的验证集患者与训练集患者无交集
    ...

def test_build_training_rows_uses_latest_record_confirmed_as_label(self):
    # 单患者多访视，label 取该患者记录里的 confirmed 字段
    ...
```

- [ ] **Step 2: 运行测试验证 RED**

- [ ] **Step 3: 实现**

`load_all_patients()` 读取某疾病全部 `CaseRecord`（不过滤 `is_synthetic`）+ 按 `patient_label` 分组重建访视序列；`build_training_rows()` 对每患者调 `extract_features()`（Task 1）压平成特征向量 + `confirmed` 标签；`patient_kfold_cv()` 借鉴 `research/model.py` 的 `patient_folds` 原则（按患者分组而非按行分折）用 `sklearn.model_selection.GroupKFold`；`train_and_save()` 训练最终模型，`joblib.dump` + 写 `.meta.json`。

- [ ] **Step 4: 运行测试验证 GREEN**

- [ ] **Step 5: CLI 与真实库试跑（人工检查点）**

```powershell
python scripts/train_progression_model.py --dataset fatty_liver
python scripts/train_progression_model.py --dataset ad
```

Expected: 打印每折 AUC + 均值±标准差，落 `backend/app/ml_models/{dataset}_progression_model.joblib` + `.meta.json`。**此步产出的 CV 指标需要项目所有者查看后决定是否继续 Task 3-5**（对应设计规格 §5.1 的人工把关）。

---

### Task 3: 推理服务（懒加载模型 + 预测）

**Files:**
- Modify: `backend/app/services/progression_engine.py`
- Modify: `backend/tests/test_progression_engine.py`

**Interfaces:**
- Produces: `load_model(dataset)`、`predict_progression(dataset, visits)`。

- [ ] **Step 1: 写失败测试**

```python
def test_load_model_raises_clear_error_when_file_missing(self):
    with self.assertRaises(FileNotFoundError):
        load_model("nonexistent_dataset")

def test_predict_progression_returns_structured_result(self):
    # mock/临时目录放一个用假数据训练的极小模型，验证返回结构
    result = predict_progression("fatty_liver", visits=[...])
    self.assertIn("risk_band", result)
    self.assertIn("risk_score", result)
    self.assertIn("feature_summary", result)
    self.assertIn("disclaimer", result)
    self.assertIn("300", result["disclaimer"])  # 样本量注记
```

- [ ] **Step 2: 运行测试验证 RED**

- [ ] **Step 3: 实现**

`load_model()` 用 `functools.lru_cache` 懒加载并缓存 `(model, meta)`；文件不存在时抛 `FileNotFoundError` 并说明疾病名；`predict_progression()` 调 `extract_features` → 拼特征向量（按训练时的特征名顺序，从 meta 读取）→ `model.predict_proba` → 映射到风险分档（复用 `prediction_engine._BANDS` 的分档表，避免重复定义）。

- [ ] **Step 4: 运行测试验证 GREEN**

---

### Task 4: API 端点 + Schema

**Files:**
- Create: `backend/app/schemas/progression.py`
- Modify: `backend/app/api/operator.py`
- Create: `backend/tests/test_progression_api.py`

**Interfaces:**
- Produces: `VisitInput`、`LongitudinalPredictRequest`、`ProgressionPredictionOut`；`POST /operator/progression-predictions`。

- [ ] **Step 1: 写失败测试**

```python
def test_progression_prediction_endpoint_returns_risk(self):
    # TestClient POST 3 次访视 → 200，含 risk_band/feature_summary/disclaimer
    ...

def test_progression_prediction_requires_ai_operator_role(self):
    # user 角色 → 403
    ...

def test_progression_prediction_missing_model_returns_4xx_not_500(self):
    # 疾病无对应模型文件 → 明确错误码，非 500 崩溃
    ...
```

- [ ] **Step 2: 运行测试验证 RED**

- [ ] **Step 3: 实现 schema 与端点**

`VisitInput{visit_date: date, indicators: list[IndicatorInput]}`（复用现有 `IndicatorInput`）；`LongitudinalPredictRequest{disease_id: int, visits: list[VisitInput]}`（限制 visits 长度 1-10，防御性上限）；端点用 `require_ai_operator` 鉴权，查 `Disease.name` 映射到训练时的 dataset key，捕获 `FileNotFoundError` 转 422。

- [ ] **Step 4: 运行测试验证 GREEN**

---

### Task 5: 前端（IndicatorRowsEditor 抽取 + 进展预测 tab）

**Files:**
- Create: `frontend/src/components/IndicatorRowsEditor.vue`
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/components/CaseManageView.vue`（改用抽取组件，消除现有重复代码）
- Modify: `frontend/src/api/operator.ts`、`frontend/src/stores/operator.ts`

**Interfaces:**
- Produces: `IndicatorRowsEditor`（props: `modelValue: IndicatorInput[]`，emits `update:modelValue`）；`predictProgression()` API 函数。

- [ ] **Step 1: 抽取 IndicatorRowsEditor 组件**

把 `OperatorView.vue`/`CaseManageView.vue` 里逐字重复的指标行 `v-for` 模板 + `addIndicator`/`removeIndicator` 逻辑收进新组件，两处改为使用该组件（`v-model`）。

- [ ] **Step 2: 验证现有功能未回归**

```powershell
cd frontend
npx vue-tsc --noEmit
npm run build
```

Expected: 现有单时点预测和病例库表单行为不变（手动验证：录入指标、增删行、保存病例）。

- [ ] **Step 3: 新增"进展预测" tab**

`OperatorView.vue` 增加第三个 `activeView` 值 `'progression'`；访视卡片列表（每卡片：日期选择器 + `IndicatorRowsEditor`）+ "添加访视"按钮；提交后调 `predictProgression()`，展示 `risk_band` 卡片（复用 `probability-card` 样式）+ `feature_summary` 表格。

- [ ] **Step 4: 前端类型检查与构建**

```powershell
npx vue-tsc --noEmit
npm run build
```

---

### Task 6: 端到端验证 + Codex 评审

- [ ] **Step 1: 存量测试全量回归**

```powershell
python -m pytest backend/tests -v
cd frontend && npm run build
```

- [ ] **Step 2: 端到端冒烟**

在操作者端"进展预测" tab 录入一位新患者 3 次访视 → 提交 → 验证返回风险等级 + 特征摘要 + 免责声明；模型缺失场景（如临时改错疾病名）验证返回明确错误非崩溃。

- [ ] **Step 3: 请求 Codex 事后评审**

交接信息模板：

```text
请评审任务 longitudinal-progression-prediction-001。

实现者：Claude-Code
评审者：Codex
分支：main（简化流程）
方案：docs/superpowers/specs/2026-08-20-longitudinal-progression-prediction-design.md
计划：docs/superpowers/plans/2026-08-20-longitudinal-progression-prediction.md

重点检查：
1. 训练数据是否使用全量 300 例（P001-300，不过滤合成病例）
2. 患者级分折是否真正避免同患者行跨训练/验证集泄漏
3. 模型缺失时的错误处理是否清晰（无静默降级/假结果）
4. 新端点是否与现有 /operator/reports 完全隔离，互不影响
5. 免责声明措辞是否符合"模式匹配参考、非临床概率"的既有约定
6. CV AUC 数值本身是否被如实呈现（有无夸大模型可信度的表述）

只输出评审意见，不直接修改实现提交。
```

- [ ] **Step 4: 用户审查后再提交**

不提交、不推送。提交正文：

```text
AI-Agent: Claude-Code
AI-Client: VS-Code
Task-ID: longitudinal-progression-prediction-001
```

---

## Plan Self-Review

- 规格 §3-8 均有对应任务：数据加载（Task 2 全量使用）、特征工程（Task 1）、模型训练（Task 2）、推理（Task 3）、API（Task 4）、前端（Task 5）、验证评审（Task 6）。
- 训练数据范围（全量 300 例）在 Global Constraints 和 Task 2 均有强调，非单处约束。
- MVP 排除项（LLM/图表/持久化/自动重训练）在 Global Constraints 明确列出，防止实施中范围膨胀。
- 类型链：`extract_features` → `build_training_rows`/`patient_kfold_cv` → `train_and_save`（Task 1-2）；`load_model`/`predict_progression`（Task 3）→ API schema/端点（Task 4）→ 前端（Task 5）。
- 人工检查点（Task 2 Step 5 的 CV 结果确认）明确标出，不依赖自动化断言替代人工判断。
- 无 TBD；提交步骤服从"不提交不推送"约束。
