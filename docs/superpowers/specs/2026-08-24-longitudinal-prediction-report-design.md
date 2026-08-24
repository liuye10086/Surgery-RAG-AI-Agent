# 纵向进展预测报告设计规格

> 日期：2026-08-24  
> 状态：待项目所有者审核  
> 目标：将 AI 操作者端的主流程从“多次访视后返回结构化风险 JSON”升级为“纵向病例 → 两类预测 → 可解释预测报告 → 历史/PDF”。

## 1. 背景与问题

当前项目已经具备三项基础能力：

1. `case_records` 以“每访视一行”的方式保存脂肪肝和阿尔茨海默病参考纵向病例；
2. `progression_engine.py` 可以从多次访视提取变化特征，并输出一个最终进展风险分数；
3. `AIReport`、SSE 报告流和 PDF 生成链路已经存在，但只接入了单次指标预测。

当前纵向流程的主要缺口是：

- 只输出风险等级和特征摘要，不生成叙述性报告；
- 当前模型预测的是“最终是否进入进展结局”，不是严格的未来时间窗口风险；
- 没有预测具体疾病阶段转移；
- 没有预测未来指标趋势；
- 操作者输入的患者没有独立的持久化对象，与参考病例库的语义边界不清楚；
- 纵向预测没有进入报告历史和 PDF 下载流程。

本规格将纵向进展预测报告定义为 AI 操作者端的主产品能力。单次指标预测保留为辅助入口，不再作为纵向流程的替代品。

## 2. 产品目标

操作者应能够：

1. 创建一个待分析的纵向病例；
2. 输入同一患者的多次访视日期和指标；
3. 查看已观察到的指标变化；
4. 获得疾病进展结局/阶段预测；
5. 获得关键指标的未来趋势预测；
6. 查看模型依据、相似参考病例和参考标准；
7. 生成一份固定结构的 Markdown 报告；
8. 保存报告、再次查看和下载 PDF；
9. 在新增访视后重新生成预测，并保留每次预测报告的输入快照。

首期疾病范围固定为：

- 脂肪肝；
- 阿尔茨海默病。

接口、数据结构和报告章节必须按疾病适配器设计，后续可以接入其他疾病，而不修改通用报告管线。

## 3. 设计原则

### 3.1 参考病例与操作者病例分离

现有 `case_records` 继续作为训练/检索参考病例库。操作者输入的新患者使用独立的纵向病例表，不能与参考病例共享 `confirmed` 语义或删除权限。

### 3.2 结构化预测先于 LLM

所有风险、阶段、方向、数值、时间窗口和置信度必须先由确定性代码或模型计算。LLM 只负责把结构化结果组织成自然语言，禁止自行创造数字、未来阶段、时间窗口或引用。

### 3.3 区分观察趋势与未来预测

- `observed`：由输入访视直接计算出的历史事实；
- `forecast`：模型对未来窗口或下一次随访的预测；
- 两者必须使用不同字段和不同报告措辞。

### 3.4 不把模型分数伪装成临床概率

在完成独立校准前，统一使用“模型分数”“风险等级”“模式匹配参考”等措辞。`risk_score` 不得在 UI、报告或 PDF 中单独标记为“发病概率”。

### 3.5 合成数据必须显式标识

当前训练集包含分层重组合成病例。报告中的相似病例、模型说明和局限性必须保留该信息，不得将合成病例描述为真实临床证据。

### 3.6 先保证可审计，再扩展预测精度

每次报告保存完整输入快照、模型版本、结构化结果、来源和免责声明，使报告可以被复现和审查。

## 4. 现有结构审计结论

### 4.1 保留的现有结构

- `diseases`：继续作为疾病字典；
- `case_records`：继续保存导入的参考纵向病例，每次访视一行；
- `reference_ranges`：继续保存指标参考范围；
- `documents/chunks`：继续提供操作者范围内的文档和 RAG 来源；
- `ai_reports`：继续作为报告生命周期、历史和 PDF 的基础表；
- `progression_engine.py`：保留特征提取和模型加载接口，重构推理输出；
- `report_pdf.html` 和 `pdf_generator.py`：继续复用 Markdown 到 PDF 的管线。

### 4.2 必须修正的冲突

1. 现有 `/operator/cases` 同时承担参考病例 CRUD，不能再直接表示操作者正在分析的新患者；
2. 现有 `/operator/progression-predictions` 不落库、不生成报告，只适合作为底层推理接口；
3. 当前模型使用完整随访轨迹和最终 `confirmed` 标签，不能直接宣称为未来 12 个月预测；
4. 当前报告 `AIReport` 没有保存纵向病例和访视输入快照；
5. 当前前端纵向页面只显示结构化结果，没有病例时间线、报告流和报告历史；
6. `frontend/src/api/operator.ts` 中遗留的通用报告流接口与当前 `/operator/reports` 预测契约不一致，需要在实现时清理或隔离。

## 5. 数据库设计

### 5.1 新增 `operator_cases`

该表表示操作者拥有的一个纵向分析病例，不表示训练参考病例。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 主键 |
| `user_id` | integer FK | 创建者；删除时级联 |
| `disease_id` | integer FK | 疾病 |
| `patient_label` | varchar | 内部病例标签，不要求真实姓名 |
| `sex` | varchar | `male` / `female` / null |
| `baseline_stage` | varchar | 当前已知阶段；脂肪肝建议由操作者确认 |
| `notes` | text | 病例备注 |
| `status` | varchar | `active` / `archived` |
| `created_at` | timestamptz | 创建时间 |
| `updated_at` | timestamptz | 更新时间 |

约束：

- `user_id` 必须参与所有查询权限过滤；
- `disease_id` 只能指向已存在疾病；
- `patient_label` 只作内部标识，报告不输出真实身份字段；
- `baseline_stage` 可为空，但脂肪肝报告在缺少当前阶段时必须降低阶段预测能力并显示警告。

### 5.2 新增 `operator_case_visits`

该表表示操作者病例的一次访视。

建议字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 主键 |
| `case_id` | integer FK | 所属 `operator_cases` |
| `visit_date` | date | 访视日期 |
| `visit_index` | integer | 按日期排序的序号 |
| `indicators` | JSONB | `[{name, value, unit}]` |
| `notes` | text | 访视备注 |
| `created_at` | timestamptz | 创建时间 |

约束：

- `(case_id, visit_date)` 唯一；
- `visit_index` 在同一病例内唯一且由后端按日期重排；
- 每次访视至少有一个有效指标；
- 数值必须是有限数字，单位不能为空；
- 删除或修改访视后，旧报告不变，新报告使用新的输入快照。

指标继续使用现有 JSON 结构，不立即拆成单独指标表，以降低迁移复杂度并复用现有 `IndicatorRowsEditor`。

### 5.3 扩展 `ai_reports`

保留现有报告表，新增：

| 字段 | 类型 | 说明 |
|---|---|---|
| `operator_case_id` | integer FK | 纵向病例；单次旧报告为空 |
| `input_snapshot` | JSONB | 生成时完整病例、访视和输入参数快照 |

纵向报告使用：

```text
analysis_type = "longitudinal_predictive"
```

现有字段的纵向语义：

- `query`：生成请求摘要或病例标签；
- `content`：完整 Markdown 报告；
- `sources`：参考范围、相似病例、模型信息和文档来源；
- `prediction_result`：第 7 节结构化结果；
- `input_snapshot`：本次生成使用的不可变输入快照；
- `status`：复用 `generating/completed/failed/cancelled`；
- `download_count`：复用 PDF 下载计数。

不新增独立 `prediction_runs` 或 `prediction_reports` 表。一次 `AIReport` 即一次预测运行和一份报告，避免重复实现状态机、权限和 PDF 逻辑。

### 5.4 迁移和兼容

- 新增 Alembic revision，不修改旧 revision；
- 存量 `AIReport` 继续视为旧类型或单次预测类型；
- 存量 `case_records` 不迁移、不改变 `confirmed` 语义；
- `database/schema.sql` 在迁移实现后同步更新，但不是迁移权威来源。

## 6. 疾病适配器

通用管线不直接写死疾病字段，使用疾病适配器提供：

```python
class DiseaseProgressionAdapter:
    dataset: str
    disease_name: str
    endpoint_definition: dict
    stage_definition: dict
    indicator_roles: dict
    horizon_policy: dict
```

### 6.1 脂肪肝

- 目标结局：进展至肝硬化或肝癌；
- 阶段：脂肪肝 → 肝硬化 → 肝癌；
- 当前阶段：优先使用 `operator_cases.baseline_stage`；缺失时不得声称已知当前阶段；
- 重点趋势指标：ALT、AST、GGT、TBIL、ALB、PLT、AFP，以及 BMI/腰围/HbA1c 等代谢指标；
- 事件日期：训练数据中的 `cirrhosis_date`、`hcc_date` 可用于构造时间窗口标签。

### 6.2 阿尔茨海默病

- 目标结局：进展至 CDR ≥ 1；
- 阶段：CDR 0 → CDR 0.5 → CDR 1 → CDR 2 → CDR 3；
- 当前阶段：优先使用末次 CDR，必要时允许操作者校正；
- 重点趋势指标：CDR、MMSE、MoCA、Aβ、p-tau、NfL、GFAP、CRP、同型半胱氨酸等；
- 事件日期：训练数据中的 `dementia_date` 可用于构造时间窗口标签。

## 7. 预测模型设计

最终报告必须包含两类独立预测。

### 7.1 进展结局/阶段预测

#### 7.1.1 训练样本重构

不能继续只用“完整患者轨迹 → 最终 `confirmed`”训练唯一模型。新训练数据以历史访视前缀为样本：

```text
患者截至第 1 次访视的特征 → 后续结局
患者截至第 2 次访视的特征 → 后续结局
患者截至第 3 次访视的特征 → 后续结局
```

同一患者的所有前缀必须进入同一个交叉验证分组，不能跨训练集和验证集。

#### 7.1.2 固定窗口

第一阶段优先建立“未来 12 个月”窗口。只有在事件日期、末次随访日期和失访语义足够完整时，才输出该窗口结果。

如果 12 个月标签不可估计，则输出：

- 下一次随访趋势；
- 后续观察期内的结局风险；
- `window_status = "not_estimable"` 和明确原因。

不得把“后续随访期内”的结果改写成“未来 12 个月概率”。

#### 7.1.3 阶段模型

为每种疾病建立阶段转移或有序阶段模型，至少返回：

- 当前阶段；
- 最可能下一阶段；
- 候选阶段及其模型分数；
- 阶段预测是否可估计；
- 训练标签和模型版本。

阶段模型未完成时，`stage_projection.status` 必须是 `not_estimated`，报告只能描述当前阶段和结局风险，不能由 LLM 补全未来阶段。

### 7.2 指标趋势预测

对每个疾病适配器定义的关键指标建立下一次随访或固定窗口趋势预测。

至少返回：

- 已观察方向：上升、下降、稳定、数据不足；
- 预测方向：可能上升、可能下降、可能稳定、不可估计；
- 预测窗口；
- 当前值和参考范围状态；
- 斜率、变化幅度和观测次数；
- 预测依据和置信等级。

未来精确数值和区间只有在独立评估合格后才能返回。否则：

```json
{
  "status": "direction_only",
  "projected_value": null,
  "prediction_interval": null
}
```

### 7.3 训练和评估要求

- 患者级 GroupKFold 或等价分组交叉验证；
- 训练/验证按时间前缀构造，防止使用未来访视信息；
- 报告 AUC、PR-AUC、Brier 或校准误差；
- 阶段模型报告混淆矩阵、宏平均 F1 或有序误差；
- 趋势模型报告方向准确率、宏平均 F1 和数值误差（如启用数值预测）；
- 记录合成数据比例；
- 模型元数据必须包含数据集、特征顺序、训练时间、版本和评估指标。

## 8. 结构化预测结果契约

`AIReport.prediction_result` 使用以下顶层结构：

```json
{
  "schema_version": "longitudinal_prediction.v1",
  "disease": {
    "id": 1,
    "name": "脂肪肝",
    "dataset": "fatty_liver"
  },
  "observation": {
    "visit_count": 4,
    "first_visit_date": "2023-01-01",
    "last_visit_date": "2024-06-01",
    "observation_span_days": 517,
    "latest_stage": "脂肪肝",
    "missingness_summary": {}
  },
  "outcome_prediction": {
    "target": "progression_to_cirrhosis_or_hcc",
    "target_label": "进展至肝硬化或肝癌",
    "risk_score": 0.78,
    "risk_band": "高",
    "score_semantics": "model_score",
    "calibrated_probability": null,
    "prediction_windows": [
      {
        "window": "12_months",
        "label": "未来12个月",
        "status": "available",
        "risk_score": 0.64,
        "risk_band": "中等"
      },
      {
        "window": "followup_horizon",
        "label": "后续随访期内",
        "status": "available",
        "risk_score": 0.78,
        "risk_band": "高"
      }
    ],
    "current_stage": "脂肪肝",
    "stage_projection": {
      "status": "available",
      "likely_next_stage": "肝硬化",
      "stage_candidates": [
        {"stage": "肝硬化", "score": 0.62},
        {"stage": "肝癌", "score": 0.16},
        {"stage": "维持当前阶段", "score": 0.22}
      ]
    },
    "confidence": {
      "level": "moderate",
      "basis": "patient_level_cross_validation",
      "trained_on": 300,
      "cv_auc_mean": 0.9962,
      "cv_auc_std": 0.0042,
      "calibration_status": "not_calibrated"
    }
  },
  "trend_predictions": [
    {
      "indicator": "ALT",
      "unit": "U/L",
      "observed": {
        "first": 60,
        "last": 90,
        "delta": 30,
        "delta_pct": 0.5,
        "slope": 15,
        "rises_count": 3,
        "n_observations": 4,
        "direction": "rising"
      },
      "reference": {
        "lower": null,
        "upper": 40,
        "status_at_latest": "above_range"
      },
      "forecast": {
        "direction": "likely_rising",
        "status": "direction_only",
        "window": "next_followup",
        "projected_value": null,
        "prediction_interval": null,
        "basis": "observed_slope_and_longitudinal_model"
      },
      "importance": {
        "rank": 1,
        "role": "major_progression_signal"
      }
    }
  ],
  "evidence": {
    "similar_longitudinal_cases": [],
    "reference_ranges": [],
    "documents": []
  },
  "warnings": []
}
```

约束：

- `risk_score` 未校准时不得渲染为百分比概率；
- `stage_projection.status = "not_estimated"` 时不得出现确定性阶段结论；
- `forecast.status = "direction_only"` 时不得出现伪造的未来数值；
- `warnings` 必须包含合成数据、样本量、校准状态和数据缺失相关警告（适用时）；
- 所有数值在进入 LLM 前必须经过 schema 校验。

## 9. 报告章节设计

报告标题格式：

```text
{疾病名称} 纵向进展预测报告 · {病例标签}
```

正文固定为以下章节。

### 9.1 报告摘要

回答：当前处于什么阶段、未来进展风险如何、最需要关注哪些指标。

风险等级必须带限定词：

> 该结果为基于当前纵向模型和已纳入病例的统计参考，不等同于临床诊断或经过校准的个体发病概率。

### 9.2 病例与数据概况

包括：

- 疾病和病例标签；
- 访视次数；
- 首次/末次访视日期；
- 观察跨度；
- 当前阶段；
- 指标缺失率；
- 是否满足模型最低输入要求。

### 9.3 已观察到的纵向变化

使用确定性表格展示：

| 指标 | 首次值 | 末次值 | 变化量 | 变化比例 | 斜率 | 方向 | 参考范围 |
|---|---:|---:|---:|---:|---:|---|---|

本章只描述历史事实，不写未来判断。

### 9.4 未来指标趋势预测

每个重点指标展示：

- 当前观察方向；
- 未来预测方向；
- 预测窗口；
- 是否只能给方向；
- 影响程度；
- 置信等级和依据。

LLM 不得自行添加输入中没有的未来数值。

### 9.5 疾病阶段与进展结局预测

包括：

- 当前阶段；
- 目标进展结局；
- 未来 12 个月结果（可估计时）；
- 后续随访期结果；
- 最可能下一阶段；
- 候选阶段排序；
- 模型分数语义和模型版本。

### 9.6 关键进展信号

列出模型和趋势共同支持的主要信号：

- 持续异常；
- 变化斜率；
- 多指标协同变化；
- 与参考病例的轨迹重叠；
- 当前阶段和结局之间的关系。

该章节可以由 LLM 组织语言，但信号列表必须由后端确定性生成。

### 9.7 相似病例与参考依据

分组展示：

- 相似纵向参考病例；
- 正常范围来源；
- 操作者可访问的文档来源；
- 模型版本和训练统计。

每个合成参考病例必须显示“合成数据，仅用于统计和流程验证”。

### 9.8 不确定性与局限性

固定包含：

- 不是临床诊断；
- 模型分数不是校准概率；
- 训练样本量有限；
- 数据包含合成病例；
- 访视数量、跨度或缺失值对结果的影响；
- 无法据此推断因果关系；
- 不直接给出治疗处方。

### 9.9 随访与人工复核建议

只提供监测和复核建议：

- 建议重点复查的指标；
- 建议补充的缺失信息；
- 建议何时重新运行预测；
- 何时需要医生人工复核。

结尾固定包含：

> 本报告由 AI 基于纵向病例数据、模型和知识库自动生成，仅供研究和临床辅助参考，不构成诊断、处方或独立临床决策依据。

### 9.10 技术附录

包括：

- 原始访视快照摘要；
- 特征定义；
- 结构化预测结果摘要；
- 模型版本和评估指标；
- 报告生成时间；
- 完整来源列表。

## 10. 后端服务与 API

### 10.1 领域服务边界

建议拆分为：

```text
longitudinal_case_service
  - 病例和访视 CRUD
  - 所有者校验
  - 输入快照

longitudinal_feature_service
  - 日期排序
  - 缺失值处理
  - 观察趋势计算

longitudinal_prediction_service
  - 疾病适配器
  - 结局/阶段模型
  - 指标趋势模型
  - 结构化结果校验

longitudinal_evidence_service
  - 相似参考病例
  - 参考范围
  - 操作者文档来源

longitudinal_report_generator
  - 固定章节模板
  - LLM 叙述
  - SSE 增量输出
  - AIReport 持久化
```

### 10.2 主要接口

```text
POST   /operator/longitudinal-cases
GET    /operator/longitudinal-cases
GET    /operator/longitudinal-cases/{case_id}
PUT    /operator/longitudinal-cases/{case_id}
DELETE /operator/longitudinal-cases/{case_id}

POST   /operator/longitudinal-cases/{case_id}/visits
PUT    /operator/longitudinal-cases/{case_id}/visits/{visit_id}
DELETE /operator/longitudinal-cases/{case_id}/visits/{visit_id}

POST   /operator/longitudinal-cases/{case_id}/prediction-reports
GET    /operator/reports?analysis_type=longitudinal_predictive
GET    /operator/reports/{report_id}
GET    /operator/reports/{report_id}/download
```

`/operator/progression-predictions` 可以在迁移期保留为内部结构化推理接口，但前端主流程不再直接调用它。

纵向报告生成接口使用 SSE：

```text
stage      校验、特征计算、模型推理、检索、生成报告
prediction 结构化预测结果
delta      Markdown 增量
sources    来源列表
done       report_id
error      可展示错误
```

## 11. 前端工作台设计

### 11.1 默认入口

AI 操作者工作台默认进入“纵向预测报告”，而不是单次指标预测。

### 11.2 页面区域

1. 左侧：纵向病例列表和报告历史；
2. 中央上部：病例基本信息和疾病选择；
3. 中央中部：按日期排列的访视时间线；
4. 中央下部：生成报告、取消生成、重新预测；
5. 右侧或报告区：结构化预测摘要、指标趋势和 Markdown 报告；
6. 来源区：相似病例、参考范围和模型说明。

### 11.3 交互规则

- 新增访视后自动按日期排序；
- 修改访视后提示“已有报告基于旧输入”；
- 生成新报告不会覆盖旧报告；
- 报告列表显示疾病、病例标签、生成时间和报告状态；
- 当数据不足时允许保存病例，但禁用生成按钮并说明缺少的条件；
- 合成参考病例使用明显但克制的来源标识；
- 页面和 PDF 的风险等级、数值、警告必须来自同一个 `prediction_result`。

### 11.4 单次预测入口

单次指标预测保留为“快速评估”入口，使用独立的 `analysis_type = "predictive"`。它不与纵向病例的访视列表混用，也不写入 `operator_cases`。

## 12. 报告生成安全约束

- LLM prompt 必须把结构化结果标记为不可改写事实；
- 禁止 LLM 生成结构化 JSON 作为唯一事实来源；
- LLM 输出后进行章节、数字和免责声明校验；
- 数字必须来自 `prediction_result`、`input_snapshot` 或明确来源；
- 预测不到的字段必须渲染为“无法估计/尚未建立模型”，不得渲染为空白或猜测；
- 报告不得出现“确诊”“必然”“一定会”等确定性诊断措辞；
- 参考病例来源必须携带 `is_synthetic` 和 `source_dataset`；
- 非 `ai_operator` 用户不能访问操作者病例或报告；
- 报告所有权校验沿用当前 `_verify_report_owner` 逻辑并扩展到病例和访视。

## 13. 错误与降级策略

### 输入错误

- 日期重复：拒绝保存；
- 访视少于模型最低要求：允许保存，禁止生成或降级为观察性摘要；
- 指标值不是有限数字：拒绝保存；
- 疾病没有适配器：返回“该疾病暂不支持纵向预测”；
- 缺少脂肪肝当前阶段：允许结局预测时显示阶段未知，但不得生成确定性阶段转移。

### 模型错误

- 模型文件缺失：报告失败，不返回假结果；
- 模型版本不兼容：报告失败并记录错误；
- 固定时间窗口不可估计：保留后续随访期或下一次随访结果，并明确窗口状态；
- 阶段模型未配置：`stage_projection.status = "not_estimated"`；
- 趋势数值模型未配置：只返回方向，不返回未来数值。

### LLM 错误

- 结构化预测结果先落库；
- LLM 生成失败时报告状态为 `failed`，保留结构化结果和错误信息；
- 不得把 LLM 失败伪装成完整报告；
- 可选提供“仅结构化结果”查看，但必须标记为非完整叙述报告。

## 14. 实施阶段与验收

### 阶段 A：数据库和病例工作流

- Alembic 新增 `operator_cases`、`operator_case_visits`；
- 完成所有者权限和 CRUD；
- 扩展 `ai_reports` 的 `operator_case_id`、`input_snapshot`；
- 完成输入快照和历史报告关联测试。

验收：同一操作者可以创建病例、录入/修改多次访视，其他操作者无法访问；旧参考病例和旧报告测试不回归。

### 阶段 B：时间前缀训练和结局模型

- 重构训练样本为历史访视前缀；
- 构造未来 12 个月和后续随访期标签；
- 患者级交叉验证；
- 输出 AUC、PR-AUC、Brier/校准信息；
- 记录合成数据比例和失访处理。

验收：验证集不存在同一患者跨折泄漏，所有窗口标签可追溯到事件日期和随访日期。

### 阶段 C：阶段模型和趋势模型

- 为脂肪肝和阿尔茨海默病实现疾病适配器；
- 完成阶段转移/有序阶段预测；
- 完成下一次随访方向预测；
- 对数值区间预测设置独立评估门槛，未达标时保持 `direction_only`。

验收：结构化结果能够同时表达结局预测和趋势预测，并能明确标记不可估计字段。

### 阶段 D：结构化预测和证据服务

- 重构 `progression_engine.py` 输出第 8 节契约；
- 实现参考病例按轨迹相似度排序；
- 补充参考范围和文档来源；
- 统一合成数据和模型警告。

验收：同一输入重复运行得到一致的结构化结果（忽略生成时间和报告 ID）。

### 阶段 E：报告生成和持久化

- 新增纵向报告 SSE 接口；
- 固定章节模板 + 受约束 LLM 叙述；
- 保存输入快照、结构化结果、内容、来源和状态；
- 复用报告详情、历史和 PDF 下载。

验收：报告正文章节完整，正文数字与结构化结果一致，LLM 失败不会丢失结构化结果。

### 阶段 F：前端工作台

- 纵向病例列表；
- 访视时间线编辑；
- 结构化预测摘要；
- 流式报告展示；
- 报告历史、重新预测和 PDF 下载；
- 单次指标预测降级为辅助入口。

验收：操作者可以从创建病例到下载报告完成一条完整闭环，页面与 PDF 的核心结果一致。

### 阶段 G：最终验证

- 后端全量测试；
- 前端类型检查和 UI 契约测试；
- 数据泄漏检查；
- 报告数字一致性检查；
- 合成病例标识检查；
- 模型缺失、窗口不可估计、LLM 失败、取消生成测试；
- PDF 渲染检查。

## 15. 非目标

本规格首期不包含：

- 自动从真实电子病历系统导入患者；
- 真实姓名、身份证号等身份信息管理；
- 自动治疗方案或处方；
- 未经验证的精确未来数值；
- 模型自动重训练和在线热更新；
- 将合成数据包装成真实临床证据；
- 将研究型 `research/` 子项目直接并入生产预测 API。

## 16. 关键验收标准

功能必须同时满足：

1. 输入同一病例至少两次、建议三次以上访视；
2. 输出已观察到的指标变化；
3. 输出疾病进展结局风险；
4. 输出关键指标未来趋势方向；
5. 阶段预测不可用时明确显示不可估计，而不是猜测；
6. 固定窗口不可用时明确降级为后续随访/下一次随访语义；
7. 生成固定章节的纵向预测报告；
8. 报告包含模型依据、参考病例、合成数据警告和免责声明；
9. 报告保存输入快照和结构化结果；
10. 支持历史查看和 PDF 下载；
11. 不破坏现有单次指标预测和旧报告；
12. 同一患者不能跨训练/验证折泄漏；
13. 任何报告结论都能追溯到输入、模型或来源。

