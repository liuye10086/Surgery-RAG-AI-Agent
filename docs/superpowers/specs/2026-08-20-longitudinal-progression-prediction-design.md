# 纵向进展预测设计

> 日期：2026-08-20
> 协作方式：简化流程，直接在当前 `main` 工作区实施，完成后交 Codex 事后评审
> 状态：待实施
> 前置依赖：`prediction-patient-dedup-001`（不阻塞本任务开工，但训练特征工程的"病例级→患者级"处理思路与该任务共享）

## 1. 背景与目标

AI 操作者端现有预测是"单时点指标匹配"：操作者输入患者当前一组指标，与病例库做模式匹配，输出匹配度/风险分层。`longitudinal-import-001` 已把脂肪肝、AD 各 300 例（含 150 例真实 + 150 例合成）纵向数据导入 `case_records`，但 `case_metadata`（visit_date、事件日期等纵向字段）目前完全未被预测流程读取。

目标：新增**纵向进展预测**能力——操作者手工录入一位新患者的多次访视指标序列，系统基于已知结局的真实纵向病例训练的机器学习模型，输出该患者的进展风险。

**与现有单时点预测的关系**：两者并存，不互相替代。现有 `/operator/reports` 端点和 UI 不变；纵向进展预测是新增的独立入口。

## 2. 变更边界

### 2.1 新增文件

- `scripts/train_progression_model.py`：离线训练脚本（模块 + CLI）
- `scripts/tests/test_train_progression_model.py`：训练脚本单测
- `backend/app/ml_models/`：模型 artifact 存放目录（`.gitignore` 排除二进制，脚本可重新生成）
- `backend/app/services/progression_engine.py`：特征提取纯函数 + 推理服务
- `backend/tests/test_progression_engine.py`：推理服务单测
- `backend/app/schemas/progression.py`：`VisitInput`/`LongitudinalPredictRequest`/`ProgressionPredictionOut`
- 新增 API 端点 `POST /operator/progression-predictions`（在 `backend/app/api/operator.py` 追加，非新文件）
- 前端：`OperatorView.vue` 新增"进展预测"模式（本次范围见 §6）

### 2.2 修改文件

- `backend/requirements.txt`：新增 `scikit-learn`、`joblib`
- `backend/app/api/operator.py`：新增端点
- `frontend/src/api/operator.ts`、`frontend/src/stores/operator.ts`、`frontend/src/views/OperatorView.vue`

### 2.3 不修改

- 现有 `/operator/reports`、`prediction_engine.py`、`prediction_generator.py`（单时点预测路径不变）
- 不新增 Alembic 迁移（本次训练结果不落库，模型是文件 artifact；预测请求也不落 `AIReport`，见 §5.3）

## 3. 训练数据范围（已确认）

**使用全量 300 例病例训练**：脂肪肝、AD 各用全部 300 例（P001-300，含 150 例真实 + 150 例合成）。虽然 P151-300 的 `DATA_PROVENANCE` 标注为"分层重组合成、不得作为真实世界临床证据"，但为换取样本量优势（150→300 例双倍），接受训练集包含部分人工固定分布的合成数据。

**已知的样本量与合成数据取舍**：300 例仍是小样本。训练脚本必须：
- 用患者级 K-fold（不能按行分折，同患者多次访视不能同时出现在训练/验证两侧——借鉴 `research/model.py` 的 `patient_folds` 原则）；
- 输出交叉验证 AUC 及其变动范围，供人工判断模型是否达到可用门槛；
- 训练脚本运行后**不自动认为模型可用**——由项目所有者查看 CV 指标后决定是否让 `progression_engine.py` 加载该模型（下详）。

## 4. 特征工程（纯 Python，不依赖 pandas）

对每位患者的访视序列（按 `visit_date` 升序），针对每个纵向指标计算：

```python
{
    "first": 首次访视值,
    "last": 末次访视值,
    "delta": last - first,
    "delta_pct": delta / first（first=0 时记为 None）,
    "slope": 简单线性回归斜率（对 (访视序号, 指标值) 拟合）,
    "rises_count": 连续两次访视间上升的次数,
    "n_observations": 该指标非空访视数,
}
```

标签（训练时）：直接用现有 `case_records.confirmed` 语义（脂肪肝 cirrhosis/hcc→1，AD CDR≥1→1；已在 `import_longitudinal.py` 落库时算好，训练脚本直接读该患者最新一条记录的 `confirmed` 字段，不重新计算）。

**为什么不做生存分析/删失处理（呼应 research/ 的方法论）**：research 子项目的 `label_for` 专门处理"删失"（随访未到终点时点，结局未知）。本次训练集是**已有明确 `final_stage` 结局**的 300 例回顾性病例（脂肪肝/AD 生成器保证每患者都有 `final_stage`），不存在删失问题，可以用简单二分类，不需要生存分析框架。这是刻意的范围缩小，把方法论复杂度留给 research 子项目的后续工作。

## 5. 模型与推理

### 5.1 训练脚本 `scripts/train_progression_model.py`

```
python scripts/train_progression_model.py --dataset fatty_liver|ad|all [--db-url URL] [--out-dir backend/app/ml_models]
```

流程：读 `case_records`（全部 300 例，不过滤 `is_synthetic`）→ 按患者重建访视序列 → 特征工程（§4）→ 患者级 5-fold 交叉验证 `GradientBoostingClassifier`（`sklearn.ensemble`）→ 打印每折 AUC + 均值±标准差 → 用全部 300 例重新训练最终模型 → `joblib.dump` 到 `backend/app/ml_models/{dataset}_progression_model.joblib` + 同名 `.meta.json`（记录特征名顺序、训练样本量、CV AUC、训练时间、`sklearn` 版本）。

**300 例样本量下 CV AUC 的预期与人工把关**：不预设"必须 ≥ 0.7 才算通过"这类硬阈值——样本量仍属小样本，AUC 方差较大。脚本只负责如实输出，验收标准是"项目所有者看到 CV 结果后决定是否继续接入服务"（对应 Task 3 的人工检查点）。

### 5.2 推理服务 `backend/app/services/progression_engine.py`

```python
def extract_features(visits: list[dict]) -> dict[str, float | None]:
    """纯函数：从访视序列提取特征。可脱离 DB/模型单测。"""

def load_model(dataset: str) -> tuple[Any, dict]:
    """懒加载 joblib 模型 + meta；模型文件不存在时抛出明确错误
    （不静默降级、不返回假结果）。"""

def predict_progression(dataset: str, visits: list[dict]) -> dict:
    """返回 {risk_band, risk_score, feature_summary, model_meta, disclaimer}。"""
```

风险分档延续现有措辞约定（`prediction_engine.py` 的"模式匹配参考，非临床确诊概率"），本次输出增加 `disclaimer` 字段固定文案：**"基于 300 例纵向病例训练的统计模型参考，样本量有限，不作为临床诊断依据"**。

### 5.3 API：新增独立端点，不复用 `/operator/reports`

**为什么新增端点而不复用现有 `/operator/reports`**：现有端点的请求/响应契约（`PredictRequest`/SSE 报告流）是为"单时点指标 + LLM 生成叙述报告"设计的。纵向进展预测的输入形状不同（多访视序列）、输出不需要 LLM 叙述（结构化风险即可，见 §6 MVP 范围），复用会让现有契约承担双重语义，增加两个功能相互踩脚的风险。

```
POST /operator/progression-predictions
{
  "disease_id": int,
  "visits": [
    {"visit_date": "2024-01-01", "indicators": [{"name": "alt", "value": 60, "unit": "U/L"}, ...]},
    ...
  ]
}
→ 200 {
  "risk_band": "高" | "中" | "低" | "极低" | "极高",
  "risk_score": float,
  "feature_summary": [{"indicator": "alt", "first": ..., "last": ..., "slope": ..., "rises_count": ...}, ...],
  "model_meta": {"trained_on": 300, "cv_auc_mean": 0.xx, "cv_auc_std": 0.xx},
  "disclaimer": "..."
}
```

同步响应（非 SSE），不落 `AIReport`/`ai_reports` 表——这是本次 MVP 的范围缩小（详见 §6），后续要接入报告历史/PDF 下载再评估是否需要落库。

鉴权：复用现有 `require_ai_operator`。

## 6. MVP 范围（本次不做，后续增强）

- **不接 LLM 生成叙述性报告**：只返回结构化风险 JSON。理由：先验证"纵向特征 + 模型"这条新链路本身能跑通、结果可信，再决定是否需要 LLM 包装成可读报告——避免一次性把机器学习管线和 LLM 生成两个新增复杂度捆在一起验证。
- **不做趋势图表**：前端只展示 `feature_summary` 的数值摘要表格，不引入图表库（ECharts 等）。
- **不落库、无报告历史**：预测结果不持久化，操作者需要保留结果需自行记录（后续若要接入历史，需评估是否新建表或扩展 `ai_reports`）。
- **不做模型自动重训练/热更新**：模型是离线训练产物，`progression_engine.py` 服务启动时懒加载，更新模型需要重跑训练脚本并重启服务。

## 7. 前端改动（范围内）

`OperatorView.vue` 新增"进展预测"标签（与现有"预测分析"/"病例库" tab 并列）：

- 多访视录入：外层"添加访视"卡片（每卡片一个日期选择器），内层复用现有指标行 `v-for` 模板（抽出 `IndicatorRowsEditor.vue` 供两处复用，顺带解决现有 `OperatorView`/`CaseManageView` 指标表单代码重复问题）；
- 结果展示：风险等级卡片（复用现有 `probability-card` 样式模式）+ `feature_summary` 的 `el-table`（列：指标/首次值/末次值/斜率/上升次数）。

## 8. 验收标准

1. 训练脚本能跑通、输出 CV AUC，且项目所有者已过目 CV 结果、明确同意接入服务（人工检查点，非自动化断言）；
2. `extract_features()` 纯函数单测覆盖：单次访视（无法算斜率）、多次访视、含缺失值指标；
3. API 端到端：提交 3 次访视 → 返回结构化风险，含 `disclaimer`；
4. 模型文件缺失时 API 返回明确错误（如"该疾病尚无可用进展预测模型"），不崩溃、不返回假结果；
5. 存量测试无回归；新端点不影响 `/operator/reports` 现有行为。
