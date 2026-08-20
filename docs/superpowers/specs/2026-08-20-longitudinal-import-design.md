# 纵向数据集导入 AI 操作者端设计

> 日期：2026-08-20  
> 协作方式：简化流程，直接在当前 `main` 工作区实施  
> 状态：已实施，Codex 首轮评审提出 4 项修复（2 P2 + 2 P3）已按 TDD 修复，待二轮评审  
> 输入：`data/generated/longitudinal_300/`（脂肪肝）与 `data/generated/ad_longitudinal_300/`（阿尔茨海默病）各五项已审核产物  
> 输出：AI 操作者端 `case_records` 数据库记录（每访视一行快照）

## 1. 背景与目标

AI 操作者端已完成预测分析模块（任务 `ai-operator-predictive-001`，四批交付）：`Disease`/`CaseRecord`/`ReferenceRange` 表、横截面预测引擎（`analyze_indicators` + `compute_composite_probability`）、operator API（病例/疾病/参考范围 CRUD）、前端 OperatorView + CaseManageView。

但当前病例库存在两个缺口：

1. **只有手工逐条录入**，无批量导入能力；
2. **`case_records` 无时间维度**——每条病例本质是单时点快照，`indicators` 为 `[{name, value, unit}]`，无 `visit_date`/进展事件日期。

项目所有者已准备好两套纵向数据集（各 300 例，已过质量门禁与独立评审）：

| 数据集 | 目录 | 访视数 | 指标数 |
|---|---|---|---|
| 脂肪肝 | `data/generated/longitudinal_300/` | 1354 | 10（alt/ast/ggt/tbil/alb/plt/hba1c/afp/waist/bmi） |
| 阿尔茨海默病 | `data/generated/ad_longitudinal_300/` | 1365 | 16（cdr/mmse/moca/abeta42/.../crp/homocysteine） |

这些 CSV **从未被任何代码导入数据库**。目标：把纵向数据导入操作者端病例库，使预测引擎的"模式匹配参考"基于真实纵向病例而非空库，并保留时间/结局/溯源语义供未来纵向分析使用。

## 2. 变更边界

### 2.1 新增文件

- `docs/superpowers/specs/2026-08-20-longitudinal-import-design.md`（本规格）
- `docs/superpowers/plans/2026-08-20-longitudinal-import.md`（实施计划）
- `scripts/import_longitudinal.py`（导入脚本，可导入模块）
- `scripts/tests/test_import_longitudinal.py`（单元测试）

### 2.2 必须保持不变

- `scripts/generate_ad_longitudinal.py`、`scripts/generate_fatty_liver_longitudinal.py`
- `scripts/extend_ad_longitudinal_to_300.py`、`scripts/extend_fatty_liver_longitudinal_to_300.py`
- `data/generated/ad_longitudinal_150/`、`data/generated/ad_longitudinal_300/`
- `data/generated/longitudinal_150/`、`data/generated/longitudinal_300/`
- `backend/app/db/models.py`（**零 schema 改动**，不新增 Alembic 迁移）
- `backend/app/services/prediction_engine.py`、`backend/app/api/operator.py`（不改预测逻辑）
- `.claude/settings.local.json`
- 前端（本次不做 UI）

### 2.3 数据集来源边界

依据 `DATA_PROVENANCE.md`：P001–P150 为逐行继承已审核基线，P151–P300 为分层重组合成患者（种子 `20260819`）。**P151–P300 不对应真实病例原文，不得作为真实世界临床证据**。导入时必须显式标记 `is_synthetic`，禁止在任何 UI 声称其为真实病例。

## 3. 方案选择

### 3.1 数据承载：每访视一行快照（已确认）

每次 visit 导入为**一条独立 `CaseRecord`**：

- `patient_label = patient_id`（如 `P001`）——同一患者多次访视通过相同 label 关联；
- `indicators = [{name, value, unit}, ...]`——该次访视非空指标，`name` 为 CSV 列名，`unit` 留空字符串；
- `case_metadata`（JSONB）承载纵向语义：
  ```python
  {
      "visit_date": "2020-03-29",
      "visit_index": 2,
      "total_visits": 5,
      "patient_age": 60, "sex": "female",
      "cohort_group": "ad_progression",
      "final_stage": "2",
      "event_dates": {                          # 仅非空事件
          "dementia_date": "2021-09-19",        # AD
          "cirrhosis_date": "...", "hcc_date": "..."  # 脂肪肝
      },
      "source_dataset": "ad_longitudinal_300",  # 溯源
      "is_synthetic": True,                     # P151–P300
      "source_document": "AD病例（1-73例）.docx",  # extracted_cases 溯源（如有）
      "import_version": "1.0.0",
  }
  ```

**为什么选它（对比其他方案）：**

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 每访视一行（本方案） | 零 schema 改动；横截面引擎立即可用；每快照都是可匹配样本 | 时序需从 metadata 读取 | **采用** |
| 扩展 schema 加 visit_date 列（0007 迁移） | 更面向未来纵向分析 | 改动面大；引擎不改造则无意义 | 留待未来 |
| 每患者一行塞 metadata | 最小改动 | 引擎读不到多时点，纵向信息对分析无意义 | 弃 |

### 3.2 导入机制：后端脚本（已确认）

沿用 `scripts/create_admin.py` 模式，新建 `scripts/import_longitudinal.py`，作为**可导入模块 + CLI**：

```
python scripts/import_longitudinal.py [--dataset fatty_liver|ad|all] [--reset]
```

- `--dataset all`（默认）：两套都导；
- `--reset`：删除该数据集已导入的 case（按 `metadata.source_dataset` 匹配）后重导；
- 幂等：同一 `(source_dataset, patient_label, visit_date)` 已存在则跳过，不产生重复行。

**为什么不做上传 UI**：本次目标是把现有数据集落库验证预测链路；上传 CSV 端点 + 前端 `el-upload` + 校验属于通用导入能力，改动面大（前端、API、校验全新建），作为后续迭代。

### 3.3 confirmed 语义：按最终结局标记（已确认）

| 数据集 | confirmed=true | confirmed=false |
|---|---|---|
| 脂肪肝 | final_stage ∈ {cirrhosis, hcc} | final_stage = fatty_liver |
| 阿尔茨海默病 | final_stage（CDR）≥ 1 | final_stage ∈ {0, 0.5} |

理由：预测引擎 `select_representative_cases` 取 `confirmed_cases` 做"确诊异常率"统计，`confirmed=true` 应聚焦进展/确诊样本；stable 样本标记 false 不参与匹配参考，避免噪音。

## 4. 数据契约（已验证）

### 4.1 `patients.csv`（脂肪肝，300 行）

```
patient_id,age,sex,cohort_group,fatty_liver_date,final_stage,cirrhosis_date,hcc_date,last_followup_date,lost_to_followup
P001,38,male,fatty_liver_progression,2019-09-20,hcc,2020-01-31,2021-09-20,2021-09-20,no
```

### 4.2 `visits.csv`（脂肪肝，1354 行）

```
patient_id,visit_date,alt,ast,ggt,tbil,alb,plt,hba1c,afp,waist,bmi
P001,2019-09-20,60.0,42.0,54.0,11.0,41.0,674.0,7.52,3.81,98.0,
```

- 每患者 3–6 行；`visit_date` 升序唯一；空值表示未测（跳过，不进 indicators）；
- `waist`/`bmi` 可能为空（如 P001 首行 bmi 空）。

### 4.3 AD 数据集同构

`patients.csv` 含 `apoe`/`gene_mutation`/`final_stage`(CDR)/`dementia_date`；`visits.csv` 16 列认知与生物标志物。`final_stage` 为 CDR 分级字符串（`"0"`~`"3"`）。

### 4.4 `extracted_cases.json`（300 项，与 patients 同序）

每项含 `patient_id`、`cohort_group`、`classification_reasons`、`source_document`（如 `"AD病例（1-73例）.docx"`）、`record_type`。P151–P300 的 `record_type` = `stratified_recombination_extension`，`source_case_id` = null。

## 5. 疾病映射

导入时确保 `diseases` 表存在：

| source_dataset | 疾病名 |
|---|---|
| `longitudinal_300` | `脂肪肝` |
| `ad_longitudinal_300` | `阿尔茨海默病` |

已存在同名疾病则复用（不重复创建）；疾病名保持现有 `DiseaseCreate` 的归一化约定（去除首尾空白）。

## 6. 安全与边界

- 本次不新增 Alembic 迁移、不改 `case_records` schema（已批准"每访视一行快照"）；
- 不改预测引擎——横截面匹配对"每次快照"天然有效；
- `is_synthetic` 标记必须写入 `case_metadata`；脚本与任何 UI 不得将 P151–P300 描述为真实病例；
- 采用简化流程在当前 `main` 实施；实现完成后由项目所有者决定提交/推送，实现过程不提交。

## 7. 验收标准

1. `python -m unittest scripts.tests.test_import_longitudinal -v` 全绿；
2. 真实 PostgreSQL 导入 300+300 患者、约 2700 条 case 记录，无报错；
3. 幂等：重跑不产生重复记录；`--reset` 后重导正常；
4. 操作者端预测跑通：选"脂肪肝/阿尔茨海默病"+ 指标 → 返回匹配度/异常分析，不再"无病例样本"；
5. 存量后端测试无回归（`python -m pytest backend/tests -v`）；
6. 原手工录入病例不受影响。
