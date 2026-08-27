# 双疾病纵向关键进展信号解释器设计

> 路线图任务：P0-06 / `longitudinal-signals-001`
> 日期：2026-08-27
> 状态：设计已由项目所有者逐段确认，待文档复核

## 1. 目标

建立一个确定性、疾病感知、可审计的关键进展信号解释器，把已有的纵向观察事实、当前已发布参考标准和本次 outcome 模型的真实 feature contract 整理成结构化信号。

解释器回答四个问题：

1. 指标发生了什么变化；
2. 这个变化在当前疾病中是否属于关注方向；
3. 最新值是否有正式标准支持的范围判断；
4. 本次 outcome 模型是否使用了该指标，以及是否存在可信的个体模型贡献信息。

解释器不是诊断器、因果分析器或模型解释器。它不训练模型，不改变 risk score，不调用 LLM，也不调用 `predict`/`predict_proba` 来判断信号重要性。

## 2. 当前证据与设计边界

### 2.1 实际数据

脂肪肝 `data/generated/longitudinal_300/visits.csv` 实际包含：

`alt`、`ast`、`ggt`、`tbil`、`alb`、`plt`、`hba1c`、`afp`、`waist`、`bmi`。

AD `data/generated/ad_longitudinal_300/visits.csv` 实际包含：

`cdr`、`mmse`、`moca`、`gfap`、`crp`、`homocysteine`，以及基本只在首访出现的 `abeta42`、`abeta40`、`abeta_ratio`、`ptau181`、`ttau`、`plasma_ptau217`、`plasma_nfl`、`ykl40`、`strem2`。

因此，当前 AD 的 NfL、p-tau217 等首访型指标通常不能形成纵向信号；解释器支持这些指标，但在有效观察不足时必须返回数据不足状态。

### 2.2 当前已发布标准

- 脂肪肝 approved 版本为数据库版本 `3`。ALT、AST、GGT、TBIL、ALB、HbA1c、WAIST 有 calculable 规则；BMI 为 evidence-only；PLT 和 AFP 没有安全的数值范围规则。
- AD approved 版本为数据库版本 `4`，规则全部为 evidence-only，没有 calculable 数值范围。MMSE、MoCA、CDR、NfL、p-tau217 有方向或阶段相关证据，但适用条件不能被忽略。
- 所有参考范围、边界、单位和适用性均由现有 `standard_resolver.resolve_standard_rules` 提供。解释器不复制隐藏阈值。

### 2.3 当前 outcome artifact

P0-05 定义的正式任务只有：

- `fatty_liver.pre_cirrhosis_to_progression`
- `fatty_liver.cirrhosis_to_hcc`
- `ad.pre_dementia_to_dementia`

模型 feature 是原始指标的派生特征，例如 `alt.last`、`alt.delta`、`mmse.time_slope_per_day`，不是单一原始指标名。解释器必须根据 artifact metadata 中的实际 feature names 做精确映射。

当前 artifact 的 score semantics 是未校准的 `model_score`，没有批准的个体 SHAP、LIME 或系数贡献契约。因此每条信号的 `model_contribution` 永远不能用变化幅度、feature importance 或 risk score 代替。

## 3. 方案与组件边界

采用独立服务 `backend/app/services/longitudinal_signal_interpreter.py`。

数据流如下：

```text
访视数据
  → longitudinal_features 计算观察摘要
  → standard_resolver 解析当前正式标准
  → longitudinal_model_registry 提供 outcome 状态和 feature metadata
  → signal interpreter 生成结构化信号
  → longitudinal_prediction / report generator 写入报告
```

职责边界：

- `longitudinal_features`：计算首次值、最新值、绝对变化、相对变化、方向、有效观察数和观察跨度；
- `standard_resolver`：唯一负责标准版本、规则、适用性和范围解析；
- `longitudinal_model_registry`：唯一负责 artifact 状态和真实 feature contract；
- 新解释器：负责 canonical 映射、疾病方向、关注等级、reason code、模型使用标记和 provenance；
- `longitudinal_prediction`：把解释器结果挂到 v2 结构化预测；
- `longitudinal_report_generator`：把结构化信号渲染成中文报告；
- 旧 `progression_engine`、旧字段和 `/progression-predictions` 接口继续保留。

## 4. Canonical 指标映射

映射是显式受控表，不使用模糊字符串匹配，也不把不同 biomarker 合并。

### 4.1 脂肪肝

| 输入指标 | canonical key | 展示名 | 关注方向 |
|---|---|---|---|
| `alt` | `alt` | 谷丙转氨酶 | 升高 |
| `ast` | `ast` | 谷草转氨酶 | 升高 |
| `ggt` | `ggt` | γ-谷氨酰转肽酶 | 升高 |
| `tbil` | `tbil` | 总胆红素 | 升高 |
| `alb` | `alb` | 白蛋白 | 下降 |
| `hba1c` | `hba1c` | 糖化血红蛋白 | 升高 |
| `waist` | `waist` | 腰围 | 升高 |
| `plt` | `plt` | 血小板计数 | 下降 |
| `afp` | `afp` | 甲胎蛋白 | 升高 |
| `bmi` | `bmi` | 体质指数 | 升高方向可观察 |

PLT、AFP 没有安全数值范围；BMI 的当前规则是 evidence-only。它们可以产生方向性关注，但不能产生正式范围异常状态。

### 4.2 AD

| 输入指标 | canonical key | 展示名 | 关注方向 | 备注 |
|---|---|---|---|---|
| `mmse` | `mmse` | 简易精神状态检查 | 下降 | 认知评分 |
| `moca` | `moca` | 蒙特利尔认知评估 | 下降 | 认知评分 |
| `cdr` | `cdr` | 临床痴呆评定 | 上升 | 阶段相关观察，不是阶段模型结论 |
| `plasma_nfl` | `nfl` | 神经丝轻链 | 升高 | 需保留原始模型 feature 前缀 |
| `plasma_ptau217` | `p-tau217` | 磷酸化 tau217 | 升高 | 不与 p-tau181 合并 |
| `abeta_ratio` | `aβ42/aβ40` | β淀粉样蛋白 42/40 比值 | 下降 | 当前数据通常只有一次观察 |

`ptau181`、`ttau`、`gfap`、`ykl40`、`strem2`、`crp`、`homocysteine` 保持独立；在没有已确认疾病方向时只作为普通观察数据，不列为关键进展信号。

## 5. 结构化信号契约

在 `LongitudinalPredictionResultV2` 中新增 `progression_signals`。使用严格 Pydantic schema：

```text
LongitudinalSignal
  indicator
  display_name
  unit
  first_value
  latest_value
  absolute_change
  relative_change
  observation_count
  observation_span_days
  observed_direction
  disease_attention_direction
  reference_status
  reference_rule_id
  reference_version_id
  attention_level
  reason_codes
  used_by_outcome_model
  model_feature_names
  model_contribution_status
  model_contribution
  provenance
  limitations

SignalInterpretationResult
  schema_version
  signals
  omitted_indicators
  summary
```

字段语义：

- `first_value`、`latest_value`、`absolute_change`、`relative_change`、`observation_count`、`observation_span_days` 是观察事实；
- `observed_direction` 是数值变化方向，不等于疾病进展；
- `disease_attention_direction` 是配置的关注方向，不等于诊断；
- `reference_status` 只允许由 resolver 的正式结果和单位校验产生；
- `reference_rule_id`、`reference_version_id` 没有命中时为 `null`；
- `used_by_outcome_model=true` 只有在 outcome 状态为 `available` 且原始指标能映射到 metadata 中实际使用的 feature names 时成立；
- `model_feature_names` 记录实际命中的派生特征名称；
- `model_contribution` 固定为 `null`；
- `model_contribution_status` 使用 `not_supported` 或 `unavailable`，不能伪造个体贡献；
- `provenance` 记录观察输入来源、标准版本/规则和模型 metadata 身份，但不写数据库 URL、密码、内部路径或患者身份；
- `limitations` 记录缺少单位、标准仅 evidence-only、观察不足或模型不可用等限制。

## 6. 变化判断与关注等级

### 6.1 观察次数

- 少于 3 次有效数值观察：只展示当前观察事实，不生成关键进展信号；reason code 为 `insufficient_observations`。
- 至少 3 次有效观察：使用该指标的全部有效观察，不截取最近三次。
- 缺失、非有限或无法转换为数字的值不计入有效观察；数据不足时必须明确降级。

### 6.2 方向

同一指标的全部有效观察都会被保留。首个有效值与最后一个有效值用于绝对/相对变化和总体方向：最后值高于首值为上升，低于首值为下降，数值相同为基本稳定。中间每一步也同向时，额外加入 `persistent_direction`；中间存在反向波动时，仍保留总体方向，但不使用“持续”措辞。这样 4 次或更多观察不会被截断，也不会因为一次小波动完全丢弃总体变化。数值方向只表示上升、下降或基本稳定，不自动表示疾病已经进展。

### 6.3 关注等级

只使用两个非空等级：

- `attention`：至少 3 次有效观察，并且首值到末值的总体方向符合该疾病关注方向；
- `priority`：满足 `attention`，且最新值命中当前适用的正式 calculable 参考范围异常。

未达到上述条件的指标为 `none`，可进入 `omitted_indicators`，不在报告的关键进展信号列表中。

该规则不创造新的临床幅度阈值。变化幅度只作为事实和稳定排序依据，不单独把信号升级为 `priority`。

### 6.4 CDR 特殊边界

CDR 可以按同样的三次观察规则生成“阶段相关评分上升”信号；文字必须明确这是观察事实和阶段相关证据，不是阶段模型输出，也不是 outcome 模型个体贡献。

## 7. 单位、标准和降级

先检查有效观察的单位，再决定是否能够进行范围判断：

- 单位一致且与适用 calculable 标准一致：可以判断 within/above/below range；
- 单位缺失：可以描述变化，但 `reference_status=unit_missing`，不判断范围；
- 单位互相冲突：不能安全比较，使用 `unit_conflict`，不生成关键信号；
- 单位与标准不同：仅使用已有明确换算规则；没有安全换算时使用 `unsupported_unit`，不判断范围；
- 没有正式 calculable 标准：可以描述方向，但 `reference_status=reference_unavailable` 或 `reference_not_applicable`，不能输出 above/below/abnormal；
- evidence-only 规则：保留标准 provenance 和适用性说明，但不转换成数值异常；
- 缺失值、非有限值或不可解析值：使用 `missing_value` 或 `non_finite_value`，并重新计算有效观察数。

标准 provenance 至少包含标准版本 ID、规则 ID、适用性 hash（若有）和规则 actionability。解释器不从自由文本猜测参考范围。

## 8. Reason code

reason code 是稳定枚举，报告中文由固定映射生成，LLM 不参与选择：

- `insufficient_observations`
- `missing_value`
- `non_finite_value`
- `unit_missing`
- `unit_conflict`
- `unsupported_unit`
- `directional_change`
- `persistent_direction`
- `reference_unavailable`
- `reference_not_applicable`
- `latest_above_reference`
- `latest_below_reference`
- `feature_not_used`
- `model_unavailable`
- `contribution_unavailable`

同一输入必须按固定顺序生成 reason code，不能依赖异常文本或数据库遍历顺序。

## 9. 模型关系

解释器接收本次已选 outcome task 的 `ModelRuntimeStatus` 和 `ArtifactMetadata`，但不执行模型推理。

判定规则：

1. outcome 不可用时，所有信号 `used_by_outcome_model=false`，并加入 `model_unavailable`；
2. outcome 可用但 feature contract 没有该指标的实际派生特征时，加入 `feature_not_used`；
3. outcome 可用且命中实际 feature names 时，`used_by_outcome_model=true` 并记录 feature names；
4. 无论哪种情况，`model_contribution=null` 且状态为 `not_supported` 或 `unavailable`；
5. 不调用 `predict`、`predict_proba`、SHAP、LIME 或任何新解释模型。

## 10. 报告与兼容

- 新报告从 `progression_signals` 读取关键信号，不再直接展示内部占位词 `progression_signal`。
- 报告只渲染 `attention` 和 `priority`；如果没有满足条件的信号，明确写“当前没有足够的关键进展信号”，不凑满三条。
- 观察事实、规则解释和模型信息分开显示。
- outcome、stage 或 trend 不可用时，信号章节仍生成；stage/trend 缺失不会阻断信号。
- 历史 `longitudinal_prediction.v1` 仍由现有兼容渲染层打开；v1 没有 `progression_signals` 时显示兼容提示，不回算历史信号。
- 不修改数据库 schema、migration、P0-04/P0-05 artifact、前端和旧 `/progression-predictions` 语义。

## 11. 稳定排序

排序固定为：

1. `priority` 在前；
2. `attention` 在后；
3. 正式标准异常在方向性信号之前；
4. 绝对相对变化强度较大的在前；
5. canonical indicator 固定顺序；
6. indicator 字符串作为最终 tie-breaker。

排序只使用结构化输入，不能使用模型分数或执行时间。

## 12. 测试设计

先写失败测试，再实现。专项测试至少覆盖：

- 脂肪肝 ALT 上升、ALB 下降、PLT 下降；
- AD MMSE 下降、MoCA 下降、CDR 上升；
- AD NfL/p-tau217：当前数据只有一次时准确返回观察不足；三次样例时验证 canonical 映射，但不与其他 p-tau 亚型合并；
- 同样的数值上升在脂肪肝和 AD 中得到不同关注方向；
- 三次规则使用全部有效观察，不截取最近三次；
- 无标准时只显示方向，不输出 above/below；
- 正式标准命中并记录版本、规则 ID 和 applicability hash；
- 单位缺失、单位冲突、不支持单位；
- 缺失值、非有限值、只有一次或两次有效观察；
- outcome available 且命中真实 feature names；
- outcome available 但指标未进入 feature contract；
- outcome unavailable 时不得标记模型使用；
- model contribution 始终为 null 且状态准确；
- 不调用模型预测、不调用 LLM、不泄漏敏感信息；
- outcome/stage/trend 不可用时信号仍生成；
- 历史 v1 与当前 v2 报告兼容；
- 稳定排序和重复计算完全一致；
- 旧 progression engine/API 回归不变；
- 双疾病端到端报告和“没有达到关注条件时不凑数”。

## 13. 验收边界

P0-06 完成的标志是：

- 结构化信号可以从已有观察、正式标准和真实模型 metadata 确定性生成；
- 至少三次有效观察才判断信号，并使用该指标全部有效观察；
- CDR 仅作为阶段相关观察；
- 没有标准、单位或模型时，报告能明确降级而不猜测；
- 模型使用情况可审计，个体贡献不伪造；
- 报告不再直接展示 `progression_signal`；
- 旧报告、旧接口、旧 artifact、数据库 schema 和前端保持兼容；
- P0-07 只需消费 `progression_signals`，不再承担信号业务判断。
