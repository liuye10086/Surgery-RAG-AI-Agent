# P0-04 纵向进展预测模型设计

> 日期：2026-08-26  
> 状态：待项目所有者审核  
> 路线图任务：P0-04 训练、评估并产出双疾病 365 天结局模型

## 1. 设计结论

P0-04 基于 P0-03 已通过的 `longitudinal_fixed_window_dataset.v1`，为脂肪肝和阿尔茨海默病（AD）建立可审计、可重复、按患者严格隔离的纵向进展预测训练与离线评估流程。

正式训练器只读取 P0-03 导出的稳定 JSONL 和 `manifest.json`，不从数据库重新构建标签，不调用旧 `outcome_label`、旧 `build_prefixes`，也不接收完整患者轨迹。正式训练、验证和测试默认只使用真实患者；合成数据仅保留在独立审计范围内。

本阶段不修改 P0-02 医学标准、P0-03 数据集语义、数据库 schema、前端、线上预测响应 schema，也不自动启用模型。旧训练脚本和旧 progression artifact 暂不清除，因为现有旧推理链路仍在引用它们；它们不属于 P0-04 正式数据入口。

通俗地说：P0-04 只拿已经验收的“历史快照训练表”训练模型，并把每一步如何分组、如何评分、如何审查都记录下来；旧系统先保持可运行，新模型单独走安全流程。

## 2. 已核查基线

### 2.1 项目状态

- 当前分支为 `main`，工作区干净。
- P0-03 最新提交为 `1608343 docs(dataset): record P0-03 verification`。
- 当前依赖为 `scikit-learn==1.9.0`、`joblib==1.5.3`、`numpy==2.3.5`。
- 当前环境没有 `xgboost`、`lightgbm`、`catboost`。

### 2.2 P0-03 实际数据规模

| 疾病/状态 | 审计前缀 | 可训练前缀 | 可训练患者 | 阳性 | 阴性 |
|---|---:|---:|---:|---:|---:|
| 脂肪肝：未肝硬化 | 256 | 147 | 86 | 50 | 97 |
| 脂肪肝：已肝硬化 | 111 | 53 | 53 | 9 | 44 |
| 脂肪肝：已肝癌 | 25 | 0 | 0 | — | — |
| AD：未痴呆 | 188 | 165 | 88 | 56 | 109 |
| AD：已痴呆 | 184 | 0 | 0 | — | — |

脂肪肝两个可训练阶段之间存在 33 名患者重叠。因此，脂肪肝两个任务必须共享同一份患者级划分，不能分别随机切分。

### 2.3 旧训练链路风险

`scripts/train_progression_model.py` 从数据库读取完整患者轨迹，并使用最后一次访视的 `confirmed` 作为标签，同时包含合成患者；这不是 P0-04 的未来 365 天任务。

`scripts/train_longitudinal_models.py` 虽使用患者级交叉验证，但仍调用旧 `build_prefixes`、旧 `outcome_label` 和旧 `stage_label`，没有强制 P0-03 schema、manifest、真实数据隔离和任务级标签校验。

旧模型文件仍被 `backend/app/services/progression_engine.py` 按旧路径加载。因此本阶段只隔离，不删除。

通俗解释：旧脚本和旧模型回答的是旧问题或服务旧功能，不能把它们改名后当成新模型；新模型必须从新数据契约重新开始。

## 3. 预测任务结构

### 3.1 脂肪肝

建立两个独立的二分类任务：

1. `fatty_liver.pre_cirrhosis_to_progression`
   - 当前状态：`pre_cirrhosis`
   - 目标事件：`cirrhosis_or_hcc`
   - 含义：未来 365 天发生肝硬化或直接发生肝癌。

2. `fatty_liver.cirrhosis_to_hcc`
   - 当前状态：`cirrhosis`
   - 目标事件：`hcc`
   - 含义：当前已肝硬化时，未来 365 天发生肝癌。

已到达 `hcc` 的样本只进入审计，不进入训练。

两个任务的标签和评估结果必须分别记录，不能合并成一个无法解释的“脂肪肝进展”标签。

### 3.2 AD

建立一个独立二分类任务：

`ad.pre_dementia_to_dementia`

- 当前状态：`pre_dementia`
- 目标事件：`dementia`
- 事件字段：`dementia_date`
- 含义：未来 365 天内是否发生明确日期的痴呆事件。

本阶段不建立正常→MCI、MCI→痴呆、CDR 1→2 或 CDR 2→3 等多阶段 CDR 模型，也不自行发明替代事件字段。未来 CDR、最终 CDR、未来 MMSE/MoCA 或生化指标不得直接成为事件标签。

通俗解释：脂肪肝分成“还没肝硬化”和“已经肝硬化”两道题；AD 当前只回答“一年内是否出现有明确日期的痴呆事件”，其他阶段问题留待以后单独设计。

## 4. 正式数据入口与数据隔离

### 4.1 数据入口

采用“显式导出、文件训练”的两步流程：

1. 通过 P0-03 CLI 显式生成一个新的、稳定的导出目录；
2. P0-04 训练器只读取该目录中的 JSONL 和 `manifest.json`。

训练器不得直接连接数据库，不得重新调用 P0-03 builder，不得读取原始生成数据，不得从完整患者轨迹重建标签。

训练前必须验证：

- `schema_version == longitudinal_fixed_window_dataset.v1`；
- manifest 中的文件 SHA-256 与实际文件一致；
- `data_content_sha256` 与 manifest 一致；
- 疾病目录和 `real_train.jsonl` 存在；
- `identity.is_synthetic == false`；
- `label.status` 只能是 `positive` 或 `negative`；
- `label.training_label` 只能是 `0` 或 `1`；
- 任务的疾病、当前状态和目标事件一致；
- 特征名称及顺序与任务契约一致；
- 没有重复样本。

如果输入包含旧 `outcome_label`、旧 `build_prefixes` 产物、完整患者轨迹或无法验证的字段，训练器必须拒绝。

### 4.2 真实与合成数据

- `real_train.jsonl` 是正式训练、开发验证和锁定测试的唯一数据来源；
- `real_audit.jsonl` 只用于审计，不用于模型指标；
- `synthetic_audit.jsonl` 只用于合成数据审计；
- 合成数据不得进入正式模型选择、阈值选择、校准或正式指标；
- 如未来开展合成数据实验，必须使用独立参数、目录、指标命名和 metadata，并明确标为非正式实验；
- 合成实验不得覆盖正式 artifact 或 registry。

通俗解释：真实病例和合成病例分开存放，正式成绩只看真实病例，合成病例最多用来检查流程。

## 5. 患者级数据划分和验证

### 5.1 划分方法

采用“锁定测试集 + 开发集患者级分层交叉验证”：

1. 先按 `group_id` 固定划分开发集和锁定测试集；
2. 开发集内部使用 `StratifiedGroupKFold`；
3. 训练折、验证折和测试集均以患者为单位互斥；
4. 测试集只在最终模型、阈值和校准方案确定后评估一次。

建议折数：

- `pre_cirrhosis_to_progression`：5 折；
- `pre_dementia_to_dementia`：5 折；
- `cirrhosis_to_hcc`：3 折，因阳性患者只有 9 名。

实际折数、每折阳性/阴性患者数和不可估计指标必须写入 metadata，不能硬编码为一定可估计。

### 5.2 脂肪肝跨阶段划分

脂肪肝两个任务先基于疾病全部可训练患者建立同一份 `group_id` 划分，再分别提取两个阶段任务。这样可保证同一患者在两个阶段中的前缀不会被分到不同集合。

相同 `patient_label` 但不同 `source_dataset` 通过 P0-03 已生成的不同 `group_id` 处理，不得错误合并。

### 5.3 预处理拟合边界

每个训练折单独拟合：

- 缺失值填补器；
- 类别编码器；
- 标准化器；
- 若未来登记了特征选择器，也必须在训练折拟合。

验证折和锁定测试集只能使用训练折已拟合的处理器。测试集不得参与特征选择、模型选择、阈值选择或概率校准。

通俗解释：每次验证只能用训练患者计算填补值和变换规则，不能偷看验证或测试患者后再调整处理方式。

## 6. 模型候选和特征流水线

### 6.1 候选模型

正式候选限定为：

1. 正则化逻辑回归，作为主模型；
2. 限制复杂度的随机森林，作为唯一备选。

不引入深度学习、XGBoost、LightGBM、CatBoost、AutoML 或大规模超参数搜索。

模型选择只使用开发集患者级交叉验证结果，综合 PR-AUC、概率校准和跨折稳定性。不能按单一最高 AUC 自动选择；若随机森林没有稳定增益，保留逻辑回归。

### 6.2 类别不平衡

采用真实样本、不重采样的方案：

- `class_weight="balanced"` 作为正式候选配置；
- 保留不加权逻辑回归作为开发集对照；
- 不使用 SMOTE；
- 不复制患者或前缀；
- 记录实际阳性/阴性患者数和前缀数。

通俗解释：可以让模型更重视少数阳性病例，但不能复制病人或凭空生成病例。

### 6.3 特征契约

每个任务独立维护稳定特征清单。允许特征包括：

- `age`、`sex`；
- `visit_count`；
- `observation_span_days`；
- `days_since_previous_visit`；
- P0-03 已批准指标的 `first`、`last`、`minimum`、`maximum`、`mean`、`delta`、`time_slope_per_day`、`recent_delta`、`rises_count`、`falls_count`、`n_observations`、`missing_ratio`。

AD 的 CDR 只有在该次访视不晚于 `as_of` 时才可作为历史特征。未来 CDR、最终 CDR 和完整轨迹汇总不得进入特征。

以下字段禁止进入模型特征：

```text
schema_version, disease, disease_name, source_dataset, patient_label,
group_id, is_synthetic, source_document, import_version, as_of,
current_state, target_event, history_visit_count, history_start,
label, event_type, event_date, last_followup_date, final_stage,
confirmed, event_dates, future visits
```

`current_state` 和 `target_event` 仅用于任务路由和审计，不直接作为模型输入。

### 6.4 预处理

推荐流水线：

```text
数值特征：SimpleImputer(strategy="median", add_indicator=True)
          → StandardScaler（逻辑回归）

sex：SimpleImputer(strategy="most_frequent")
     → OneHotEncoder(handle_unknown="ignore")
```

随机森林可以不依赖标准化，但仍通过统一的任务级预处理接口运行，并在 metadata 记录模型特定配置。不得使用标签或未来结果填补缺失。

## 7. 评价指标、阈值和校准

### 7.1 指标分层

主指标：

- PR-AUC，并同时报告阳性率基线。

辅助连续指标：

- ROC-AUC；
- Brier score；
- 校准曲线；
- 样本允许时的校准截距和斜率。

阈值分类指标：

- 灵敏度；
- 特异度；
- 阳性预测值（PPV）；
- 阴性预测值（NPV）；
- F1；
- 混淆矩阵；
- 阳性/阴性预测数量。

某折缺少阳性或阴性时，该折 ROC-AUC、PR-AUC 或相关指标标记为不可估计，不填 0、不伪造结果。

### 7.2 置信区间与波动

- 开发集报告每折指标、均值和标准差；
- 锁定测试集使用患者级 bootstrap 计算 95% 区间；
- bootstrap 重采样单位是 `group_id`，不是前缀行；
- 阳性患者过少导致区间不稳定时，必须明确记录。

通俗解释：一个患者有多条前缀记录，统计上仍然是一个人，不能把多条记录当成许多独立患者来夸大信心。

### 7.3 阈值

模型概率和分类阈值分开记录：

1. 基准阈值固定为 `0.5`，用于统一比较；
2. 开发集可使用 out-of-fold 概率探索最大化 F1 的阈值；
3. 探索阈值不得使用锁定测试集；
4. 阈值不稳定时只报告 `0.5` 结果，并标记阈值不稳定；
5. 未有明确业务或临床成本依据前，不采用灵敏度目标阈值。

锁定测试集只能使用已经确定的阈值评估一次。

### 7.4 概率校准

- 默认允许不校准，记录 `calibration_status=not_calibrated`；
- 对脂肪肝未肝硬化和 AD，可在开发集内部比较原始概率与 sigmoid/Platt 校准；
- 脂肪肝已肝硬化→肝癌默认不校准，除非预先登记的样本和稳定性门槛满足；
- isotonic 不作为 P0-04 正式方案；
- 校准器只能使用开发集 out-of-fold 预测拟合；
- 测试集不得参与校准方法选择或拟合；
- 未校准输出不得描述为临床发生概率。

## 8. 异常高分和泄漏审查

### 8.1 自动触发

出现以下任一情况时，设置 `leakage_review_required=true`：

- ROC-AUC ≥ 0.95；
- PR-AUC 接近 1.0；
- 任一折完美分离；
- Brier score 异常接近 0；
- 患者集合跨训练/验证/测试重叠；
- 重复样本或重复患者；
- 禁止字段命中；
- `patient_label`、`group_id` 或 `source_dataset` 进入特征；
- `final_stage`、`confirmed`、`event_dates`、未来 CDR 或未来访视进入特征；
- 预处理器、特征选择器、阈值或校准器使用测试患者；
- 合成患者进入正式指标；
- 特征几乎直接复制标签；
- 数据集统计与 manifest 不一致。

### 8.2 审查内容

审查记录至少包括：

1. 患者集合互斥结果；
2. 重复患者和重复样本计数；
3. 实际模型特征完整清单；
4. 禁止字段扫描结果；
5. 特征、标签和事件来源；
6. `as_of` 与未来日期边界检查；
7. 所有预处理器拟合范围；
8. 阈值和校准使用的数据范围；
9. 合成样本计数；
10. manifest、数据文件和 metadata 哈希匹配结果。

### 8.3 处理规则

- 高分警告不会自动发布模型；
- 模型保持 `candidate`；
- 发现真实泄漏时，相关评估结果作废；
- 即使审查未发现已知泄漏，也只能说明“未发现已知泄漏”，不能声称临床有效。

通俗解释：模型考满分时先检查它是不是看过答案；检查通过也只代表目前没发现作弊，不代表已经具备临床诊断能力。

## 9. artifact、metadata 和生命周期

### 9.1 artifact 命名

任务级 artifact 使用：

```text
fatty_liver_pre_cirrhosis_to_progression_365d.joblib
fatty_liver_pre_cirrhosis_to_progression_365d.meta.json

fatty_liver_cirrhosis_to_hcc_365d.joblib
fatty_liver_cirrhosis_to_hcc_365d.meta.json

ad_pre_dementia_to_dementia_365d.joblib
ad_pre_dementia_to_dementia_365d.meta.json
```

P0-04 不把旧的 `*_progression_model.joblib` 当作新的 365 天结局 artifact。现有 registry 的旧键和旧行为保持兼容；任务级加载必须增加任务、目标、窗口、特征和状态校验，不能只按疾病名加载。

### 9.2 metadata 内容

每个 artifact 的 metadata 至少记录：

- 数据集 schema 版本、manifest SHA-256、数据内容 SHA-256、训练文件 SHA-256；
- 疾病、任务、当前状态、目标事件、事件字段、`horizon_days=365`、`minimum_visits=3`；
- `feature_names`、特征数量、特征顺序哈希、禁止特征命中结果；
- 数值/类别预处理配置和拟合范围；
- 真实/合成计数；
- 划分方法、随机种子、各集合患者和类别统计、互斥检查；
- 算法、参数、`class_weight` 和随机种子；
- 每折指标、均值、标准差、测试指标和置信区间；
- 基准阈值、开发选择阈值和选择方法；
- 校准状态、方法和拟合范围；
- 泄漏审查结果、高分警告状态；
- git commit、Python/依赖版本、创建时间；
- artifact 与 metadata SHA-256；
- `status`、`production_enabled` 和临床有效性声明状态。

### 9.3 registry 状态

采用三态：

```text
candidate → reviewed → enabled
```

- `candidate`：训练和离线评估完成，尚未人工审核，不得进入生产推理；
- `reviewed`：人工确认数据、特征、指标和泄漏审查，但尚未启用；
- `enabled`：仅由独立、显式、人工授权操作启用。

训练 CLI 不得更新 registry，也不得自动进入 `enabled`。启用时必须记录人工审核信息、时间、artifact 哈希，并检查没有冲突的 enabled 模型。

通俗解释：训练完成只是“候选模型”，人工审核后才是“审核通过”，最后还要有人明确执行启用。

## 10. CLI 和安全默认行为

建议新增 P0-04 专用 CLI：

```text
scripts/train_longitudinal_outcome_models.py
```

默认运行：

```powershell
python scripts/train_longitudinal_outcome_models.py
```

只输出稳定 UTF-8 JSON 审计摘要，不训练、不生成 joblib、不写数据库、不更新 registry。摘要包括 schema、manifest/hash、任务可用性、患者/前缀/类别统计、合成计数、特征检查、泄漏检查和训练许可状态。

显式训练必须同时指定：

```powershell
python scripts/train_longitudinal_outcome_models.py \
  --dataset-dir <P0-03导出目录> \
  --train \
  --output-dir <临时输出目录>
```

训练器要求：

- 不接收数据库 URL；
- 不默认写入 `backend/app/ml_models/`；
- 输出目录不得覆盖已有内容；
- 训练结果只标记为 `candidate`；
- 正式 artifact 导出必须另有明确参数和后续授权；
- registry review/enable 必须是独立命令，不由训练 CLI 提供自动启用路径。

训练器必须拒绝错误 schema、manifest 缺失或哈希不匹配、旧字段、完整轨迹、合成样本、观察不足/不适用标签、错误任务目标、重复样本、跨集合患者和特征顺序不匹配。

## 11. 测试范围和 TDD 顺序

实现严格采用 TDD，顺序固定为：

1. 先写 P0-04 schema、JSONL/manifest 读取和输入拒绝测试；
2. 运行测试，确认因目标能力缺失而失败；
3. 编写最少但完整的正式生产实现；
4. 写并运行任务拆分、患者级划分和跨阶段互斥测试；
5. 写并运行特征、未来访视、禁止字段和预处理拟合范围测试；
6. 写并运行模型、类别权重、指标、阈值和校准测试；
7. 写并运行异常高分和泄漏阻断测试；
8. 写并运行 artifact、metadata、临时目录和 registry 状态测试；
9. 写并运行 CLI 默认只读、安全退出码和敏感信息测试；
10. 运行 P0-03、旧训练脚本、registry、预测契约和完整项目回归测试。

至少覆盖：

- 只接受 P0-03 正式数据契约；
- 拒绝旧标签、旧前缀入口和完整轨迹；
- 三个任务独立运行且目标不混淆；
- 按 `group_id` 划分，同一患者绝不跨集合；
- 脂肪肝两个阶段共享患者划分；
- 不同来源的同名患者不合并；
- 身份、标签、最终结果和未来字段不进入特征；
- 观察不足、不适用和合成样本不进入正式训练指标；
- 预处理、阈值、校准和特征选择不使用测试患者；
- 固定随机种子得到稳定划分和结果摘要；
- 数据哈希变化可被发现；
- 高分触发泄漏审查；
- metadata 完整且哈希匹配；
- 默认 CLI 不训练、不写数据库、不生成正式 artifact、不启用 registry；
- 旧链路回归保持通过。

## 12. 文件边界

### 12.1 预计新增

```text
backend/app/schemas/longitudinal_model_training.py
backend/app/services/longitudinal_model_training.py
backend/app/services/longitudinal_model_evaluation.py
backend/app/services/longitudinal_model_audit.py
scripts/train_longitudinal_outcome_models.py
backend/tests/test_longitudinal_model_training.py
backend/tests/test_longitudinal_model_evaluation.py
backend/tests/test_longitudinal_model_audit.py
scripts/tests/test_train_longitudinal_outcome_models.py
```

如果本阶段纳入独立 registry 审核/启用命令，再单独新增：

```text
scripts/manage_longitudinal_registry.py
```

### 12.2 可能小幅修改

```text
backend/app/services/longitudinal_model_registry.py
scripts/check_model_artifacts.py
```

修改仅用于任务级 artifact 和 metadata 校验、状态识别以及向后兼容，不改变旧键语义。

### 12.3 明确不修改

```text
frontend/
backend/alembic/
backend/app/db/models.py
backend/app/schemas/prediction.py
backend/app/schemas/longitudinal_report.py
backend/app/services/disease_progression.py
backend/app/services/progression_engine.py
scripts/train_progression_model.py
scripts/train_longitudinal_models.py
```

不修改 P0-02 医学标准、数据库 revision、P0-03 标签语义、固定 365 天窗口、至少 3 次访视要求或线上预测响应 schema。

## 13. 非目标和风险边界

P0-04 不负责：

- 训练大语言模型；
- 建立通用机器学习平台或 AutoML；
- 改造 AD 多阶段 CDR 标签；
- 修改前端、报告模板或 API schema；
- 写正式业务数据库；
- 自动发布或自动启用模型；
- 以离线指标高为依据声称临床有效性。

主要风险：

- 脂肪肝肝硬化后肝癌任务阳性患者只有 9 名，测试指标和校准可能不可稳定估计；
- 患者级前缀数量多于患者数，若错误按行统计会产生虚高置信度；
- 当前数据由规则和合成扩展产生，必须持续执行高分泄漏审查；
- P0-04 新任务级 artifact 与现有旧 registry 的兼容需要严格 metadata 校验；
- 训练完成不代表模型已具备临床有效性。

## 14. 完成判定

P0-04 只有在以下条件全部满足后才算完成：

- 三个任务均可从 P0-03 正式 JSONL 独立训练和评估；
- 真实/合成数据隔离和患者级集合互斥有自动化测试；
- 特征、标签、未来边界和预处理拟合范围有自动化泄漏检查；
- 开发集交叉验证与锁定测试一次性评估均有可审计输出；
- 指标、阈值、校准、置信区间和不可估计原因完整记录；
- 异常高分会触发泄漏审查且不会自动发布；
- artifact、metadata、manifest 和特征哈希能够互相校验；
- registry 保持人工审核门槛，训练 CLI 不自动启用；
- 默认 CLI 只读且不生成正式模型；
- 现有旧链路和相关项目回归测试保持通过；
- 没有把离线评估结果表述为临床诊断能力。

通俗解释：只有数据来源、患者隔离、模型成绩、泄漏检查和人工审核全部对得上，P0-04 才算完成；训练出一个文件本身不算完成。
