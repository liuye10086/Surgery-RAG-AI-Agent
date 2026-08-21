# 预测统计按患者去重 Implementation Plan（简化版）

> **For agentic workers:** 本计划采用简化实施策略，聚焦核心生产代码，删除复杂的自动化集成测试和验收脚本。

**Goal:** 修复 `prediction_generator.py` 组装 `confirmed_cases` 时未按患者去重的统计偏差——纵向导入后同一患者的多次访视快照会被重复计数，拉偏 `present_rate_in_cases`/`abnormal_rate_in_cases`/`risk_weight`。

**Architecture:** 在 `prediction_generator.py` 内新增 `deduplicate_by_patient()` 纯函数，在查询 `CaseRecord` 后、喂给 `prediction_engine.analyze_indicators()` 前插入去重步骤。`_cases_to_dicts()` 补充 `patient_label`/`case_metadata` 字段供去重使用。`prediction_engine.py` 零改动。

**Tech Stack:** Python 3.11，纯函数、无新依赖。

**Design Spec:** [2026-08-20-prediction-patient-dedup-design.md](../specs/2026-08-20-prediction-patient-dedup-design.md)

---

## Global Constraints

- 简化流程，在当前 `main` 工作区实施；不建分支/worktree。
- 不修改 `backend/app/services/prediction_engine.py`（统计逻辑本身是对的，问题在上游数据未去重）。
- 不新增 Alembic 迁移、不改 API 契约、不改前端。
- 去重口径：同 `(source_dataset, patient_label)` 取 `(visit_date DESC, id DESC)` 二级排序最新一条；只对纵向导入数据去重，旧手工病例全部独立保留；`patient_label` 为空/None/全空格不参与去重。
- **简化验收**：Task 1 完成纯函数单测（去重逻辑本身），Task 2 直接修改生产代码，Task 3 手工验证真实库效果并记录观察结果。完成后交 Codex 事后评审代码质量和手工验证记录。
- 不提交、不推送，完成后交 Codex 事后评审。

---

## File Structure

- `backend/app/services/prediction_generator.py`：新增 `deduplicate_by_patient()`、`_sort_key()`；修改 `_cases_to_dicts()`（补充字段，保留原有归一化）与 `generate_prediction()` 调用点（插入去重、明确两处消费者使用同一变量）。
- `backend/tests/test_prediction_generator.py`：新增去重纯函数单测（11 个测试用例）。
- `docs/superpowers/validation/prediction-patient-dedup-001.md`：手工验证记录（精确统计、冒烟测试、调用链一致性验证）。

---

### Task 1: 去重纯函数（TDD）

**Files:**
- Modify: `backend/app/services/prediction_generator.py`
- Modify: `backend/tests/test_prediction_generator.py`

**Interfaces:**
- Consumes: `list[dict]`（每条含 `id`/`patient_label`/`case_metadata{source_dataset, visit_date}`/`indicators`）。
- Produces: `deduplicate_by_patient()`、`_sort_key()`。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/test_prediction_generator.py` 新增：

```python
import unittest
from unittest.mock import MagicMock
from app.services.prediction_generator import deduplicate_by_patient, _sort_key, _cases_to_dicts

class TestDeduplicateByPatient(unittest.TestCase):
    
    def test_deduplicate_keeps_latest_visit_per_patient_within_same_dataset(self):
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
            {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-03-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        p001 = next(c for c in result if c["patient_label"] == "P001")
        self.assertEqual(p001["case_metadata"]["visit_date"], "2020-06-01")
        self.assertEqual(p001["id"], 2)

    def test_deduplicate_keeps_same_label_from_different_datasets_separately(self):
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},  # 旧手工病例
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
    
    def test_deduplicate_keeps_same_label_from_two_nonblank_sources_separately(self):
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "dataset_a", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "dataset_b", "visit_date": "2020-06-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        sources = {c["case_metadata"]["source_dataset"] for c in result}
        self.assertEqual(sources, {"dataset_a", "dataset_b"})

    def test_deduplicate_uses_id_when_visit_date_missing_or_tied(self):
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 4, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)
        p001 = next(c for c in result if c["patient_label"] == "P001")
        self.assertEqual(p001["id"], 2)  # 有日期优先于无日期
        p002 = next(c for c in result if c["patient_label"] == "P002")
        self.assertEqual(p002["id"], 4)  # 并列日期时 id 更大者
    
    def test_deduplicate_all_dates_missing_uses_max_id(self):
        # 补充：所有 visit_date 均缺失时，取最大 ID
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 3, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 3)  # 最大 ID

    def test_deduplicate_keeps_unlabeled_cases_independently(self):
        cases = [
            {"id": 1, "patient_label": None, "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 2, "patient_label": "", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 3, "patient_label": "   ", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
            {"id": 4, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 4)  # 3 个无标签独立保留 + 1 个有标签

    def test_deduplicate_keeps_old_manual_cases_even_with_duplicate_labels(self):
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": None, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 2)

    def test_deduplicate_handles_input_order_reversal(self):
        forward = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
        ]
        backward = list(reversed(forward))
        self.assertEqual(
            deduplicate_by_patient(forward)[0]["id"],
            deduplicate_by_patient(backward)[0]["id"]
        )
    
    def test_deduplicate_mixed_scenario_all_types(self):
        # 补充：混合场景（纵向数据、旧手工、无标签同时存在）
        cases = [
            {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
            {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},  # 去重，保留这条
            {"id": 3, "patient_label": "P001", "case_metadata": {}, "indicators": []},  # 旧手工，独立保留
            {"id": 4, "patient_label": None, "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},  # 无标签，独立保留
            {"id": 5, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2021-01-01"}, "indicators": []},  # 另一患者
        ]
        result = deduplicate_by_patient(cases)
        self.assertEqual(len(result), 4)  # P001 纵向去重后 1 条 + P001 旧手工 1 条 + 无标签 1 条 + P002 纵向 1 条
        ids = {c["id"] for c in result}
        self.assertEqual(ids, {2, 3, 4, 5})

    def test_cases_to_dicts_includes_dedup_fields(self):
        # 补充：验证 _cases_to_dicts() 正确补充字段
        case = MagicMock(
            id=1, 
            disease_id=1, 
            indicators=[{"name": "alt", "value": 60}],
            patient_label="P001", 
            case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}
        )
        result = _cases_to_dicts([case])
        self.assertEqual(result[0]["id"], 1)
        self.assertEqual(result[0]["patient_label"], "P001")
        self.assertEqual(result[0]["case_metadata"]["source_dataset"], "longitudinal_300")
        self.assertEqual(result[0]["case_metadata"]["visit_date"], "2020-01-01")
        self.assertEqual(result[0]["indicators"], [{"name": "alt", "value": 60}])  # 保留原值
    
    def test_cases_to_dicts_preserves_empty_indicators_normalization(self):
        # 补充：验证保留了原有 "indicators or []" 归一化
        case_with_none = MagicMock(
            id=1, disease_id=1, indicators=None,
            patient_label="P001", case_metadata={}
        )
        result = _cases_to_dicts([case_with_none])
        self.assertEqual(result[0]["indicators"], [])  # None 归一化为 []
```

- [ ] **Step 2: 运行测试验证 RED**

```powershell
python -m pytest backend/tests/test_prediction_generator.py::TestDeduplicateByPatient -v
```

Expected: `ImportError` 或 `AttributeError`，`deduplicate_by_patient` 不存在。

- [ ] **Step 3: 实现**

在 `backend/app/services/prediction_generator.py` 新增：

```python
def _sort_key(case: dict) -> tuple[str, int]:
    """返回 (visit_date, id) 排序键，降序比较时字符串/int 天然支持。
    
    visit_date 缺失时返回空字符串（排序时视为最早）；
    id 缺失时返回 0（不应发生，防御性处理）。
    """
    visit_date = (case.get("case_metadata") or {}).get("visit_date") or ""
    record_id = case.get("id") or 0
    return (visit_date, record_id)


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
```

- [ ] **Step 4: 运行测试验证 GREEN**

---

### Task 2: 接入 generate_prediction 调用链（直接修改生产代码）

**Files:**
- Modify: `backend/app/services/prediction_generator.py`

- [ ] **Step 1: 修改 `_cases_to_dicts()`**

补充 `patient_label`/`case_metadata` 两个字段，**保留原有 `indicators or []` 归一化**：

```python
def _cases_to_dicts(cases: list[CaseRecord]) -> list[dict]:
    return [
        {
            "id": c.id,
            "disease_id": c.disease_id,
            "indicators": c.indicators or [],  # 保留原有归一化
            "patient_label": c.patient_label,
            "case_metadata": c.case_metadata or {}
        }
        for c in cases
    ]
```

- [ ] **Step 2: 在 `generate_prediction()` 中插入去重步骤**

找到查询 `confirmed_cases` 的位置（约 195-202 行），**保持原有查询条件，只新增去重步骤和修改两处消费者**：

```python
# 原代码（约 195-202 行）：
cases = (
    db.query(CaseRecord)
    .filter(
        CaseRecord.disease_id == disease_id,
        CaseRecord.confirmed.is_(True),
    )
    .all()
)
# 后续使用 _cases_to_dicts(cases) 作为 confirmed_cases

# 修改为：
cases = (
    db.query(CaseRecord)
    .filter(
        CaseRecord.disease_id == disease_id,
        CaseRecord.confirmed.is_(True),
    )
    .all()
)
cases_dict = _cases_to_dicts(cases)
confirmed_cases = deduplicate_by_patient(cases_dict)  # 新增：去重
total_cases = len(confirmed_cases)

# 同时修改两处消费者（原本直接调用 _cases_to_dicts(cases)）：
# 1. analyze_indicators 调用（约 203 行）改为：
analyses = analyze_indicators(
    indicators, range_by_name, confirmed_cases  # 改：使用去重后列表
)

# 2. select_representative_cases 调用（约 224 行）改为：
representative = select_representative_cases(
    confirmed_cases, abnormal_names, top_n=5  # 改：使用去重后列表
)
```

- [ ] **Step 3: 验证代码可通过编译检查和存量测试**

```powershell
cd backend
python -m py_compile app/services/prediction_generator.py
python -m pytest tests/ -v
```

若本机有 mypy，可选运行：
```powershell
mypy app/services/prediction_generator.py
```

---

### Task 3: 手工验证真实库效果（记录观察结果）

**验证日志路径**：`docs/superpowers/validation/prediction-patient-dedup-001.md`

- [ ] **Step 1: 精确验证去重正确性**

使用 Python 脚本直接查询数据库统计（不依赖 API）：

```python
from sqlalchemy import create_engine, text
from pathlib import Path
import re

# 读取数据库 URL
url = re.search(r'DATABASE_URL=(.+)', Path('backend/.env').read_text(encoding='utf-8')).group(1).strip()
engine = create_engine(url)

with engine.connect() as conn:
    for disease_name in ['脂肪肝', '阿尔茨海默病']:
        print(f"\n=== {disease_name} ===")
        
        # 原始 confirmed 行数
        raw_count = conn.execute(text("""
            SELECT COUNT(*) FROM case_records c 
            JOIN diseases d ON c.disease_id=d.id 
            WHERE d.name=:disease AND c.confirmed=true
        """), {"disease": disease_name}).scalar()
        
        # 去重键数量（与生产代码一致的标签归一化：TRIM）
        distinct_keys = conn.execute(text("""
            SELECT COUNT(DISTINCT (metadata->>'source_dataset', TRIM(patient_label)))
            FROM case_records c JOIN diseases d ON c.disease_id=d.id
            WHERE d.name=:disease AND c.confirmed=true
              AND metadata->>'source_dataset' IS NOT NULL 
              AND metadata->>'source_dataset' != ''
              AND patient_label IS NOT NULL 
              AND TRIM(patient_label) != ''
        """), {"disease": disease_name}).scalar()
        
        # 独立记录数（无 source_dataset 或无 patient_label，使用 TRIM）
        independent_count = conn.execute(text("""
            SELECT COUNT(*) FROM case_records c 
            JOIN diseases d ON c.disease_id=d.id 
            WHERE d.name=:disease AND c.confirmed=true
              AND (metadata->>'source_dataset' IS NULL 
                   OR metadata->>'source_dataset' = ''
                   OR patient_label IS NULL 
                   OR TRIM(patient_label) = '')
        """), {"disease": disease_name}).scalar()
        
        expected_deduplicated = distinct_keys + independent_count
        
        print(f"原始 confirmed 行数: {raw_count}")
        print(f"去重键数量（纵向数据）: {distinct_keys}")
        print(f"独立记录数（旧手工/无标签）: {independent_count}")
        print(f"预期去重后数量: {expected_deduplicated}")
        
        # 记录到验证日志，待 Step 2 对比实际 sample_size
```

记录到 `docs/superpowers/validation/prediction-patient-dedup-001.md`。

- [ ] **Step 2: 前端冒烟测试**

启动服务和前端，通过操作者页面手工测试：

1. 登录操作者账号
2. 选择"脂肪肝"，录入：ALT=70 U/L
3. 点击预测，等待 SSE 流完成
4. 从浏览器 Network 面板找到 `/api/v1/operator/reports` 的 SSE 响应，搜索 `event: indicators`（注意：是 event 行，不是 JSON 的 type 字段），读取紧随其后的 `data:` 行，解析 JSON 中的 `probability.sample_size` 字段
5. 记录：实际 sample_size = ___
6. 断言：`actual == expected_deduplicated`（Step 1 计算的预期值）

对 AD 重复（MMSE=20 分）。

记录代表性病例引用的 ID（从 `sources` 事件获取），注明：本次验收未检查患者标签字段（调用链一致性由代码审查确认）。

- [ ] **Step 3: 请求 Codex 事后评审**

交接信息模板：

```text
请评审任务 prediction-patient-dedup-001（已实施完成，简化版）。

实现者：Claude-Code
评审者：Codex
分支：main（简化流程）
方案：docs/superpowers/specs/2026-08-20-prediction-patient-dedup-design.md（已同步简化验收标准）
计划：docs/superpowers/plans/2026-08-20-prediction-patient-dedup-SIMPLIFIED.md
验证：纯函数单测 + 手工真实库精确验证（见 docs/superpowers/validation/prediction-patient-dedup-001.md）

简化策略说明：
经过 4 轮设计评审，核心方案（复合键去重、二级排序、末期偏差权衡）已稳定。
本轮删除复杂的自动化集成测试和验收脚本（固定分档评估、首次/末次队列对比、指标缺测影响验证），
聚焦生产代码质量：
- Task 1：纯函数单测覆盖去重逻辑的所有边界场景（11 个测试用例）
- Task 2：直接修改生产代码，通过类型检查和存量测试
- Task 3：手工验证真实库效果并记录精确统计（不依赖"约 300"判断，而是精确断言 actual == distinct_keys + independent_records）

重点检查：
1. deduplicate_by_patient() 和 _sort_key() 实现是否符合设计规格 §3.1/§3.2
2. 复合键 (source_dataset, patient_label) 是否真正隔离不同来源的同名患者
3. 二级排序 (visit_date DESC, id DESC) 是否稳定
4. _cases_to_dicts() 补充的字段是否完整且保留了原有 "indicators or []" 归一化
5. generate_prediction() 的去重插入位置是否正确（cases_dict 后、两处消费者前）
6. 手工验证记录（validation/prediction-patient-dedup-001.md）是否证明去重生效且精确符合预期

只输出评审意见，不直接修改实现提交。
```

- [ ] **Step 4: 用户审查后再提交**

不提交、不推送，等用户授权。提交正文：

```text
fix(operator): 预测统计按患者去重，修复纵向数据导入后的重复计数偏差

纵向数据导入后，同一患者多次访视快照全部计入 confirmed_cases，
随访次数多的患者在异常率统计中被重复计数。

修复：
- 新增 deduplicate_by_patient() 按 (source_dataset, patient_label) 去重
- 同患者取 (visit_date DESC, id DESC) 最新一条作为代表
- 旧手工病例（无 source_dataset）全部独立保留
- 无标签记录不参与去重

验证：纯函数单测 + 手工真实库精确统计（脂肪肝/AD 的 sample_size 精确等于去重键数+独立记录数）

AI-Agent: Claude-Code
AI-Client: VS-Code
Task-ID: prediction-patient-dedup-001
```

---

## Plan Self-Review

- 规格 §3 的方案选择、§4 验收标准均有对应任务覆盖（§4.4 已同步为队列级对比）。
- `prediction_engine.py` 零改动，去重发生在 generator 层，符合"引擎统计逻辑本身是对的"判断。
- 类型链：`CaseRecord` 查询 → `_cases_to_dicts`（补充字段）→ `deduplicate_by_patient` → `analyze_indicators`/`select_representative_cases`（入参形状不变）。
- Task 1 纯函数单测覆盖全部边界场景（两个非空 source、visit_date 并列/缺失、无标签、输入顺序反转）；Task 2 直接修改生产代码；Task 3 手工验证并记录观察结果。
- 简化策略明确：删除复杂的自动化集成测试和验收脚本，聚焦核心生产代码和手工验证，完成后交 Codex 评审代码质量。
- 提交步骤服从"不提交不推送"约束。
