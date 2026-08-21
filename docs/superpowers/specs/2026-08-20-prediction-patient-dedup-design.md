# 预测统计按患者去重设计

> 日期：2026-08-20
> 协作方式：简化流程，直接在当前 `main` 工作区实施
> 状态：待实施
> 触发：`longitudinal-import-001` 导入纵向数据后，发现现有单时点预测统计存在患者重复计数偏差

## 1. 背景与问题

`backend/app/services/prediction_generator.py:195-199` 查询某疾病全部 `confirmed=True` 的 `CaseRecord`，`_cases_to_dicts()`（第 121-125 行）原样转换为字典列表，直接作为 `confirmed_cases` 传给 `prediction_engine.analyze_indicators()`。

`analyze_indicators()`（`prediction_engine.py:39-109`）对每个患者指标，遍历 `confirmed_cases` 统计：

```python
present_count = 该指标在多少条 case 中出现
abnormal_count = 其中多少条 case 该指标也异常
present_rate_in_cases = present_count / total_cases
abnormal_rate_in_cases = abnormal_count / total_cases if present_count else 0
risk_weight = abnormal_rate_in_cases if is_abnormal else 0.0
```

`total_cases = len(cases)`（`prediction_generator.py:199`）。

**问题**：这套统计的隐含假设是"一条 case = 一个独立患者的一次确诊快照"。`longitudinal-import-001` 导入后，同一患者有 3-6 条访视快照（`patient_label` 相同），全部计入 `confirmed_cases`：

- 随访次数多的患者在 `present_count`/`abnormal_count`/`total_cases` 里被多次计数，其指标模式主导整体异常率，稀释随访次数少的患者的统计权重；
- 这不是"引入新 bug"，而是导入前就存在于设计假设中、导入后被数据规模放大暴露的既有偏差。

**影响范围**：仅脂肪肝（confirmed 675 条 / 患者数远少于 675）、阿尔茨海默病（confirmed 1233 条）两个疾病的预测统计；旧的手工录入病例（`patient_label` 为空或每患者一条）不受影响，因为去重后行为不变。

## 2. 变更边界

### 2.1 新增/修改文件

- `backend/app/services/prediction_generator.py`：新增 `deduplicate_by_patient()`，在组装 `confirmed_cases` 前调用。
- `backend/tests/test_prediction_generator.py`：新增去重单测。
- `docs/superpowers/specs/2026-08-20-prediction-patient-dedup-design.md`（本文件）
- `docs/superpowers/plans/2026-08-20-prediction-patient-dedup.md`（实施计划）

### 2.2 不修改

- `backend/app/services/prediction_engine.py`：`analyze_indicators`/`compute_composite_probability` 的统计逻辑本身不改——它们的"每条输入=一个统计单元"设计是对的，问题在于上游喂给它们的数据未去重。
- 不新增 Alembic 迁移、不改 `CaseRecord`/`Disease` 模型、不改 API 契约、不改前端。

## 3. 方案选择

### 3.1 聚合口径：每患者取最新访视代表（已确认，明确末期偏差）

对 `confirmed_cases` 按 `(case_metadata.source_dataset, patient_label)` 复合键分组：

- **复合键设计**：只对纵向导入数据（`case_metadata` 含非空 `source_dataset`）去重；旧手工病例（`case_metadata` 为空或无 `source_dataset` 字段）全部独立保留，即使 `patient_label` 重复也不会与导入数据合并。这确保不同来源的同名患者（如旧手工 "P001" vs 导入数据 "P001"）不被误合并。
- `patient_label` 为空/None/全空格：视为独立样本，不参与去重（保持向后兼容）；
- 组内按 `(case_metadata.visit_date DESC, id DESC)` 二级排序，取**最新一条**作为该患者的代表快照：
  - `visit_date`（ISO 字符串）降序优先；
  - `visit_date` 缺失/并列时按 `id` 降序（同患者访视按时间顺序导入，id 越大越晚）；
  - 这确保排序结果稳定，不依赖数据库返回顺序。

**为什么选"取最新"而不是"OR 聚合"（同一患者任一次异常就算异常）或"每指标最近有效测量"**：

| 方案 | 语义 | 风险 |
|---|---|---|
| 取最新访视（已选） | 与"一条 case = 一次独立确诊快照"的原始设计意图一致，只是把"多次快照"折叠成"最新快照" | **末期偏差**：纵向导入数据的 `confirmed` 按患者最终结局统一标记全部访视（见 `import_longitudinal.py:232`），因此取末次访视得到的是"进展患者的末期/末随访表型"，可能系统性抬高与疾病进展相关的异常率。**指标缺失**：末次访视未测某指标时，该患者在此指标的 `present_count` 统计中被排除（引擎已有逻辑，见 `prediction_engine.py:88`），可能因检测缺失而压低异常率。这两个偏差是预期的、已知的权衡。 |
| OR 聚合 | 更"敏感"，但会系统性地拉高异常率——访视次数越多的患者，被判定异常的机会越多，引入新的、方向明确的偏差 | 弃 |
| 每指标最近有效测量 | 避免末次访视缺测丢信息，拼成"虚拟复合快照" | 实现复杂度高（需对每指标独立遍历访视），且生成的复合快照在时间上不连贯（不同指标来自不同日期），医学解释性差 | 弃 |

去重函数只在**预测查询路径**生效（`prediction_generator.py` 内部），不改 `case_records` 表数据本身，也不影响 `CaseManageView` 病例库列表展示（那里本来就是展示全部记录，去重只是"用于统计"这一步的处理）。

### 3.2 实现方式

```python
def deduplicate_by_patient(cases: list[dict]) -> list[dict]:
    """按 (source_dataset, patient_label) 复合键去重：同患者只保留最新访视。

    - 只对纵向导入数据（case_metadata 含非空 source_dataset）去重；
    - 旧手工病例（metadata 为空或无 source_dataset）全部独立保留；
    - patient_label 为空/None/全空格时不参与去重，每条独立保留。
    
    排序：visit_date DESC > id DESC（二级排序，结果稳定）。
    """
    keyed: dict[tuple[str, str], dict] = {}  # (source_dataset, patient_label) -> case
    unlabeled: list[dict] = []
    
    for case in cases:
        label = (case.get("patient_label") or "").strip()
        source = (case.get("case_metadata") or {}).get("source_dataset") or ""
        
        if not label or not source:
            # 旧手工病例或无标签记录，独立保留
            unlabeled.append(case)
            continue
        
        key = (source, label)
        existing = keyed.get(key)
        if existing is None or _sort_key(case) > _sort_key(existing):
            keyed[key] = case
    
    return list(keyed.values()) + unlabeled


def _sort_key(case: dict) -> tuple[str, int]:
    """返回 (visit_date, id) 排序键，降序比较时字符串/int 天然支持。
    
    visit_date 缺失时返回空字符串（排序时视为最早）；
    id 缺失时返回 0（不应发生，防御性处理）。
    """
    visit_date = (case.get("case_metadata") or {}).get("visit_date") or ""
    record_id = case.get("id") or 0
    return (visit_date, record_id)
```

`_cases_to_dicts()` 需要新增 `patient_label`/`case_metadata` 两个字段（目前只取 `id`/`disease_id`/`indicators`），供去重函数使用；去重后再喂给 `analyze_indicators`/`select_representative_cases`，两者的输入形状不变（仍是 `[{"indicators": [...]}, ...]`），故引擎代码零改动。

## 4. 验收标准（简化版）

**核心验收**（本次任务必须完成）：

1. **单测覆盖去重逻辑边界**：
   - 同患者、同 source_dataset 取最新；visit_date 并列时按 id 降序；
   - 同名患者、不同 source_dataset 独立保留；两个非空 source 同名患者独立保留；
   - 无标签记录独立保留；旧手工病例（无 source_dataset）独立保留；
   - 输入顺序反转结果稳定；所有 visit_date 均缺失时取最大 id；混合场景；
   - `_cases_to_dicts()` 正确补充 `patient_label`/`case_metadata` 字段。

2. **真实库精确验证**（手工记录到 validation_log.md）：
   - 脂肪肝/AD 去重后 `sample_size` 精确等于 `(去重键数量 + 独立记录数)`；
   - 手工统计：`raw_confirmed_count`、`distinct(source_dataset, patient_label) count`、`independent_manual_or_unlabeled_count`、`expected_deduplicated_count`、`actual sample_size`；
   - 断言：`actual == distinct_keys + independent_records`（不能只判断"约 300"）。

3. **存量测试无回归**：`pytest backend/tests -v` 全绿；类型检查通过（若本机有 mypy）；现有单时点预测端到端冒烟（前端操作者页面录入指标 → 返回风险分层，不报错）。

**延后验收**（不作为本任务阻断条件，后续可单独任务处理）：

- 固定分档阈值影响评估（需要基线快照和复杂锚点设计）
- 首次/末次队列比较（需要队列级统计脚本）
- 指标缺失影响验证（需要手工筛选特定患者并统计）
- 自动化集成测试（需要复杂的 async mock 配置）
