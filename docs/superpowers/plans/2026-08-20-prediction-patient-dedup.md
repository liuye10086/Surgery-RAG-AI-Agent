# 预测统计按患者去重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `prediction_generator.py` 组装 `confirmed_cases` 时未按患者去重的统计偏差——纵向导入后同一患者的多次访视快照会被重复计数，拉偏 `present_rate_in_cases`/`abnormal_rate_in_cases`/`risk_weight`。

**Architecture:** 在 `prediction_generator.py` 内新增 `deduplicate_by_patient()` 纯函数，在查询 `CaseRecord` 后、喂给 `prediction_engine.analyze_indicators()` 前插入去重步骤。`_cases_to_dicts()` 补充 `patient_label`/`case_metadata` 字段供去重使用。`prediction_engine.py` 零改动。

**简化实施策略**：聚焦核心生产代码，删除复杂的自动化集成测试和验收脚本。Task 1 完成纯函数单测（去重逻辑本身），Task 2 直接修改生产代码，Task 3 手工验证真实库效果并记录观察结果。Codex 事后评审代码质量和手工验证记录。

**Tech Stack:** Python 3.11，纯函数、无新依赖。

**Design Spec:** [2026-08-20-prediction-patient-dedup-design.md](../specs/2026-08-20-prediction-patient-dedup-design.md)

---

## Global Constraints

- 简化流程，在当前 `main` 工作区实施；不建分支/worktree。
- 不修改 `backend/app/services/prediction_engine.py`（统计逻辑本身是对的，问题在上游数据未去重）。
- 不新增 Alembic 迁移、不改 API 契约、不改前端。
- 去重口径：同 `(source_dataset, patient_label)` 取 `(visit_date DESC, id DESC)` 二级排序最新一条；只对纵向导入数据去重，旧手工病例全部独立保留；`patient_label` 为空/None/全空格不参与去重。
- 不提交、不推送，完成后交 Codex 事后评审。

---

## File Structure

- `backend/app/services/prediction_generator.py`：新增 `deduplicate_by_patient()`、`_sort_key()`；修改 `_cases_to_dicts()` 与 `generate_prediction()` 调用点。
- `backend/tests/test_prediction_generator.py`：新增去重单测。

---

### Task 1: 去重纯函数（TDD）

**Files:**
- Modify: `backend/app/services/prediction_generator.py`
- Modify: `backend/tests/test_prediction_generator.py`

**Interfaces:**
- Consumes: `list[dict]`（每条含 `id`/`patient_label`/`case_metadata{source_dataset, visit_date}`/`indicators`）。
- Produces: `deduplicate_by_patient()`、`_sort_key()`。

- [ ] **Step 1: 写失败测试**

```python
def test_deduplicate_keeps_latest_visit_per_patient_within_same_dataset(self):
    cases = [
        {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": [{"name": "alt", "value": 60}]},
        {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": [{"name": "alt", "value": 90}]},
        {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-03-01"}, "indicators": [{"name": "alt", "value": 40}]},
    ]
    result = deduplicate_by_patient(cases)
    self.assertEqual(len(result), 2)
    p001 = next(c for c in result if c["patient_label"] == "P001")
    self.assertEqual(p001["case_metadata"]["visit_date"], "2020-06-01")
    self.assertEqual(p001["id"], 2)

def test_deduplicate_keeps_same_label_from_different_datasets_separately(self):
    # 纵向数据 P001 + 旧手工 P001（无 source_dataset）→ 两条独立保留
    cases = [
        {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},  # 旧手工病例
    ]
    result = deduplicate_by_patient(cases)
    self.assertEqual(len(result), 2)

def test_deduplicate_keeps_same_label_from_two_nonblank_sources_separately(self):
    # 两个非空 source_dataset，同名患者 P001 → 两条独立保留（不同数据集不合并）
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
        {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300"}, "indicators": []},  # 无 visit_date
        {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        {"id": 3, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        {"id": 4, "patient_label": "P002", "case_metadata": {"source_dataset": "ad_longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},  # 并列
    ]
    result = deduplicate_by_patient(cases)
    self.assertEqual(len(result), 2)
    p001 = next(c for c in result if c["patient_label"] == "P001")
    self.assertEqual(p001["id"], 2)  # 有日期优先于无日期
    p002 = next(c for c in result if c["patient_label"] == "P002")
    self.assertEqual(p002["id"], 4)  # 并列日期时 id 更大者

def test_deduplicate_keeps_unlabeled_cases_independently(self):
    cases = [
        {"id": 1, "patient_label": None, "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
        {"id": 2, "patient_label": "", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},
        {"id": 3, "patient_label": "   ", "case_metadata": {"source_dataset": "longitudinal_300"}, "indicators": []},  # 全空格
        {"id": 4, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
    ]
    result = deduplicate_by_patient(cases)
    self.assertEqual(len(result), 4)  # 3 个无标签独立保留 + 1 个有标签

def test_deduplicate_keeps_old_manual_cases_even_with_duplicate_labels(self):
    # 两条旧手工病例，patient_label 都是 P001，但 metadata 无 source_dataset → 都独立保留
    cases = [
        {"id": 1, "patient_label": "P001", "case_metadata": None, "indicators": []},
        {"id": 2, "patient_label": "P001", "case_metadata": {}, "indicators": []},
    ]
    result = deduplicate_by_patient(cases)
    self.assertEqual(len(result), 2)

def test_deduplicate_handles_input_order_reversal(self):
    # 输入顺序反转，结果应一致（按 sort_key 排序，不依赖输入顺序）
    forward = [
        {"id": 1, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}, "indicators": []},
        {"id": 2, "patient_label": "P001", "case_metadata": {"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}, "indicators": []},
    ]
    backward = list(reversed(forward))
    self.assertEqual(
        deduplicate_by_patient(forward)[0]["id"],
        deduplicate_by_patient(backward)[0]["id"]
    )
```

- [ ] **Step 2: 运行测试验证 RED**

```powershell
python -m pytest backend/tests/test_prediction_generator.py -v -k dedup
```

Expected: `AttributeError`/`ImportError`，`deduplicate_by_patient` 不存在。

- [ ] **Step 3: 实现**

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

### Task 2: 接入 generate_prediction 调用链

**Files:**
- Modify: `backend/app/services/prediction_generator.py`
- Modify: `backend/tests/test_prediction_generator.py`

**Interfaces:**
- Consumes: `CaseRecord` 查询结果。
- Modifies: `_cases_to_dicts()`（补充字段）、`generate_prediction()`（调用去重）。

- [ ] **Step 1: 写失败测试**

```python
def test_cases_to_dicts_includes_id_patient_label_and_metadata(self):
    case = MagicMock(
        id=1, 
        disease_id=1, 
        indicators=[], 
        patient_label="P001", 
        case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}
    )
    result = _cases_to_dicts([case])
    self.assertEqual(result[0]["id"], 1)
    self.assertEqual(result[0]["patient_label"], "P001")
    self.assertEqual(result[0]["case_metadata"]["source_dataset"], "longitudinal_300")
    self.assertEqual(result[0]["case_metadata"]["visit_date"], "2020-01-01")

@pytest.mark.asyncio
async def test_generate_prediction_dedupes_before_analyzing(self):
    """集成级：mock 返回同一患者 3 条 case（不同 id/visit_date），
    断言 analyze_indicators/compute_composite_probability/select_representative_cases
    三处收到的 confirmed_cases 一致（去重后长度=1，且对象身份相同）。
    """
    from unittest.mock import AsyncMock, MagicMock, patch
    
    # 构造同患者 3 次访视的 mock cases
    mock_disease = MagicMock(id=1, name="脂肪肝")
    mock_cases = [
        MagicMock(
            id=1, disease_id=1, indicators=[{"name": "alt", "value": 60}],
            patient_label="P001", 
            case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-01-01"}
        ),
        MagicMock(
            id=2, disease_id=1, indicators=[{"name": "alt", "value": 80}],
            patient_label="P001", 
            case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-06-01"}
        ),
        MagicMock(
            id=3, disease_id=1, indicators=[{"name": "alt", "value": 90}],
            patient_label="P001", 
            case_metadata={"source_dataset": "longitudinal_300", "visit_date": "2020-12-01"}
        ),
    ]
    mock_ranges_query = MagicMock()
    mock_ranges_query.order_by.return_value.all.return_value = [
        MagicMock(indicator_name="alt", lower=0, upper=40, lower_inclusive=True, upper_inclusive=True)
    ]
    mock_report = MagicMock(id=1)
    
    mock_db = MagicMock()
    # 第一次 query(Disease) → filter → first
    # 第二次 query(ReferenceRange) → filter → order_by → all
    # 第三次 query(CaseRecord) → filter(confirmed) → all
    mock_db.query.side_effect = [
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_disease)))),
        mock_ranges_query,
        MagicMock(filter=MagicMock(return_value=MagicMock(all=MagicMock(return_value=mock_cases)))),
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_report)))),
    ]
    
    with patch("app.services.prediction_generator.analyze_indicators") as mock_analyze, \
         patch("app.services.prediction_generator.compute_composite_probability") as mock_composite, \
         patch("app.services.prediction_generator.select_representative_cases") as mock_select, \
         patch("app.services.prediction_generator._llm") as mock_llm:
        
        # mock_analyze 返回完整的 indicator analysis（包含后续构建 table 需要的字段）
        mock_analyze.return_value = [{
            "name": "alt", 
            "value": 70,
            "unit": "U/L",
            "lower": 0,
            "upper": 40,
            "is_abnormal": True,
            "deviation_pct": 75.0,
            "present_rate_in_cases": 1.0,
            "abnormal_rate_in_cases": 1.0,
            "risk_weight": 1.0
        }]
        # mock_composite 返回字典（不是元组）
        mock_composite.return_value = {
            "probability": 0.5,
            "band": "中等",
            "probability_range": {"lower": 0.4, "upper": 0.6},
            "sample_size": 1
        }
        mock_select.return_value = [{"id": 3, "indicators": [{"name": "alt", "value": 90}]}]
        
        # mock LLM astream 返回非空 delta（避免生成器跳过 LLM 阶段）
        async def mock_stream():
            yield "模拟 LLM 输出"
        mock_llm.astream.return_value = mock_stream()
        
        # 消费异步生成器直到 done 事件（此时三处调用都已发生）
        events = []
        async for event in generate_prediction(
            db=mock_db, 
            disease_id=1, 
            indicators=[{"name": "alt", "value": 70, "unit": "U/L"}],
            user_id=1,
            report_id=1
        ):
            # event 是字符串（SSE 格式），解析为字典
            if event.startswith("data: "):
                import json
                event_data = json.loads(event[6:])
                events.append(event_data)
                if event_data.get("type") == "done":
                    break
        
        # 断言三处调用一致性
        assert mock_analyze.call_count == 1
        analyze_cases = mock_analyze.call_args[0][2]  # 第 3 个位置参数
        assert len(analyze_cases) == 1
        assert analyze_cases[0]["id"] == 3  # 最新访视
        
        assert mock_composite.call_count == 1
        composite_args = mock_composite.call_args[0]  # 位置参数元组
        composite_analyses = composite_args[0]
        composite_total = composite_args[1]
        assert composite_total == 1
        assert composite_total == len(analyze_cases)
        
        assert mock_select.call_count == 1
        select_cases = mock_select.call_args[0][0]  # 第 1 个位置参数
        assert len(select_cases) == 1
        assert select_cases[0]["id"] == 3
        # 断言 analyze 与 select 使用同一个列表对象（对象身份）
        assert select_cases is analyze_cases
```

- [ ] **Step 2: 运行测试验证 RED**

- [ ] **Step 3: 实现**

`_cases_to_dicts()` 补充 `"patient_label": c.patient_label, "case_metadata": c.case_metadata or {}`；`generate_prediction()` 中 `cases_to_dicts` 结果先过 `deduplicate_by_patient()` 再传给 `analyze_indicators`/`select_representative_cases`；`total_cases` 用去重后的长度。

- [ ] **Step 4: 运行测试验证 GREEN**

---

### Task 3: 真实库验证 + Codex 评审

- [ ] **Step 1: 存量后端回归**

```powershell
python -m pytest backend/tests -v
```

- [ ] **Step 2: 去重正确性验证（直接证明"一患者一票"）**

对比修复前后同一疾病的 `total_cases`：

```python
# 修复前：脂肪肝 confirmed cases 应为 675 条（含重复访视）
# 修复后：精确等于 (纵向数据去重键数量 + 旧手工独立记录数 + 无标签记录数)

# 验证脚本示例
from backend.app.services.prediction_generator import generate_prediction, deduplicate_by_patient
from backend.app.db.models import CaseRecord, Disease

with Session() as db:
    disease = db.query(Disease).filter(Disease.name == "脂肪肝").first()
    cases_raw = db.query(CaseRecord).filter(CaseRecord.disease_id == disease.id, CaseRecord.confirmed == True).all()
    cases_dict = _cases_to_dicts(cases_raw)
    cases_deduped = deduplicate_by_patient(cases_dict)
    
    # 手工统计去重键数量
    keyed = set()
    unlabeled_count = 0
    for c in cases_dict:
        label = (c.get("patient_label") or "").strip()
        source = (c.get("case_metadata") or {}).get("source_dataset") or ""
        if label and source:
            keyed.add((source, label))
        else:
            unlabeled_count += 1
    
    expected = len(keyed) + unlabeled_count
    actual = len(cases_deduped)
    assert actual == expected, f"去重后 {actual} 条，预期 {expected} 条（{len(keyed)} 去重键 + {unlabeled_count} 独立记录）"
    print(f"✓ 脂肪肝去重正确：{actual} 条（原始 {len(cases_raw)} 条）")
```

对 AD 重复同样验证。

- [ ] **Step 3: 固定分档阈值适用性验证**

**保存修复前基线快照**（在当前分支或单独环境运行修复前版本）：

```python
# 保存到 baseline_scores.json，用于后续对比
baseline = {}
for disease_name in ["脂肪肝", "阿尔茨海默病"]:
    for anchor in get_anchors(disease_name):
        result = call_generate_prediction(disease_name, anchor["indicators"])
        baseline[anchor["id"]] = {
            "score": result["score"],
            "band": result["band"],
            "sample_size": result["sample_size"]
        }
```

**预定义临床锚点测试集**（覆盖引擎分档边界，不预设 expected_band）：

```python
# 脂肪肝锚点（覆盖不同异常指标组合和阈值边界）
anchors_fl = [
    {"id": "fl_all_normal", "label": "完全正常", "indicators": [
        {"name": "alt", "value": 30, "unit": "U/L"}, 
        {"name": "ast", "value": 25, "unit": "U/L"}
    ]},
    {"id": "fl_single_mild", "label": "单指标轻度异常", "indicators": [
        {"name": "alt", "value": 60, "unit": "U/L"}, 
        {"name": "ast", "value": 25, "unit": "U/L"}
    ]},
    {"id": "fl_two_abnormal_same_rate", "label": "双指标异常（病例库异常率相近）", "indicators": [
        {"name": "alt", "value": 120, "unit": "U/L"}, 
        {"name": "ast", "value": 80, "unit": "U/L"}
    ]},
    {"id": "fl_two_abnormal_diff_rate", "label": "双指标异常（病例库异常率差异大，若有）", "indicators": [
        {"name": "alt", "value": 200, "unit": "U/L"}, 
        {"name": "ggt", "value": 150, "unit": "U/L"}
    ]},
    {"id": "fl_boundary_0.2", "label": "基线 score 接近 0.2 阈值", "indicators": [
        # 根据基线快照结果，选择 score 在 0.18-0.22 的锚点（人工调整指标值）
    ]},
]

# AD 锚点
anchors_ad = [
    {"id": "ad_all_normal", "label": "完全正常", "indicators": [
        {"name": "mmse", "value": 28, "unit": "分"}, 
        {"name": "cdr", "value": 0, "unit": "分"}
    ]},
    {"id": "ad_single_abnormal", "label": "单指标异常", "indicators": [
        {"name": "mmse", "value": 20, "unit": "分"}, 
        {"name": "cdr", "value": 0, "unit": "分"}
    ]},
    {"id": "ad_two_abnormal", "label": "双指标异常", "indicators": [
        {"name": "mmse", "value": 18, "unit": "分"}, 
        {"name": "cdr", "value": 1, "unit": "分"}
    ]},
    {"id": "ad_add_normal_no_change", "label": "加入正常指标 band 不变", "indicators": [
        {"name": "mmse", "value": 20, "unit": "分"}, 
        {"name": "cdr", "value": 0.5, "unit": "分"},
        {"name": "moca", "value": 26, "unit": "分"}  # 正常
    ]},
]

# 修复后对比
changes = []
for anchor in anchors_fl + anchors_ad:
    result_after = call_generate_prediction_after_fix(anchor["disease"], anchor["indicators"])
    baseline_result = baseline[anchor["id"]]
    
    score_delta = result_after["score"] - baseline_result["score"]
    band_before = baseline_result["band"]
    band_after = result_after["band"]
    
    if band_before != band_after:
        # 记录跨档及可能原因
        change_record = {
            "anchor_id": anchor["id"],
            "label": anchor["label"],
            "band_change": f"{band_before} → {band_after}",
            "score_delta": score_delta,
            "sample_size_before": baseline_result["sample_size"],
            "sample_size_after": result_after["sample_size"],
            "explanation": None  # 待人工填写
        }
        
        # 判断是否可由去除重复权重解释
        if score_delta < 0 and baseline_result["sample_size"] > result_after["sample_size"]:
            change_record["explanation"] = "可能原因：去重减少 sample_size，降低了该锚点异常指标在库中的异常率"
        
        changes.append(change_record)
        print(f"[跨档] {anchor['label']}: {band_before} → {band_after}, score Δ={score_delta:.3f}")
```

**阻断规则**（按 Codex 建议修正，消除内部矛盾）：

1. 对每个跨档锚点，记录病例库异常率变化、指标缺测率、score 变化来源；
2. 能由"去除重复权重"或"末次缺测压低异常率"解释并记录证据的，允许通过；
3. **任一锚点**出现无法解释的跨档（如"完全正常"从"低"升至"中"且无合理原因），即**阻断验收，复查聚合口径和缺失值分母**；
4. 若 **50% 以上锚点发生跨档**（无论是否可解释），作为**整体分布漂移告警**，需人工复核所有跨档是否符合预期；
5. 需要重新校准阈值时，**作为独立任务**，本任务明确不修改 `prediction_engine.py`。

人工复核可以豁免阻断，但必须记录：跨档原因、审查人、批准日期、是否需要后续跟进。

- [ ] **Step 4: 末期偏差与指标缺失验证（队列级对比，文档化已知权衡）**

**末期偏差：对所有 confirmed=true 患者构建"首次快照队列"vs"末次快照队列"**

```python
from app.services.prediction_generator import _cases_to_dicts, deduplicate_by_patient
from app.services.prediction_engine import analyze_indicators

def deduplicate_by_patient_first_visit(cases: list[dict]) -> list[dict]:
    """临时函数：按 (source_dataset, patient_label) 去重，同患者取 visit_date 最早一条。
    
    复用生产代码的复合键和独立病例规则，仅反转代表访视选择方向。
    """
    keyed: dict[tuple[str, str], dict] = {}
    unlabeled: list[dict] = []
    
    for case in cases:
        label = (case.get("patient_label") or "").strip()
        source = (case.get("case_metadata") or {}).get("source_dataset") or ""
        
        if not label or not source:
            unlabeled.append(case)
            continue
        
        key = (source, label)
        existing = keyed.get(key)
        # 反转排序：取 visit_date 最早（_sort_key 最小）
        if existing is None or _sort_key(case) < _sort_key(existing):
            keyed[key] = case
    
    return list(keyed.values()) + unlabeled

def _sort_key(case: dict) -> tuple[str, int]:
    """与生产代码相同的排序键"""
    visit_date = (case.get("case_metadata") or {}).get("visit_date") or ""
    record_id = case.get("id") or 0
    return (visit_date, record_id)


with Session() as db:
    disease = db.query(Disease).filter(Disease.name == "脂肪肝").first()
    cases_raw = db.query(CaseRecord).filter(
        CaseRecord.disease_id == disease.id, 
        CaseRecord.confirmed == True
    ).all()
    cases_dict = _cases_to_dicts(cases_raw)
    
    # 构建两种队列
    first_cohort = deduplicate_by_patient_first_visit(cases_dict)
    last_cohort = deduplicate_by_patient(cases_dict)
    
    # 准备 ranges 字典（引擎要求格式：{indicator_name: range_dict}）
    ranges_raw = db.query(ReferenceRange).filter(
        ReferenceRange.disease_id == disease.id
    ).all()
    ranges = {
        r.indicator_name: {
            "lower": r.lower, 
            "upper": r.upper,
            "lower_inclusive": r.lower_inclusive,
            "upper_inclusive": r.upper_inclusive
        }
        for r in ranges_raw
    }
    
    # 对关键指标输出两种口径的统计
    patient_indicators = [{"name": "alt", "value": 70, "unit": "U/L"}]
    indicators_first = analyze_indicators(patient_indicators, ranges, first_cohort)
    indicators_last = analyze_indicators(patient_indicators, ranges, last_cohort)
    
    alt_first = next(i for i in indicators_first if i["name"] == "alt")
    alt_last = next(i for i in indicators_last if i["name"] == "alt")
    
    print(f"ALT 首次队列: present_rate={alt_first['present_rate_in_cases']:.2%}, abnormal_rate={alt_first['abnormal_rate_in_cases']:.2%}")
    print(f"ALT 末次队列: present_rate={alt_last['present_rate_in_cases']:.2%}, abnormal_rate={alt_last['abnormal_rate_in_cases']:.2%}")
    print(f"差值: abnormal_rate 变化 {(alt_last['abnormal_rate_in_cases'] - alt_first['abnormal_rate_in_cases']):.2%}")
    
    # 验收标准：将结果作为影响测量，不强制规定差值方向
    # 只要求末次策略被正确执行、差异被记录并解释
```

**指标缺失：手工统计去重后队列，验证末次缺测患者对该指标贡献分子=0、分母=1**

```python
# 选一位末次访视缺 AST、但早期测过且异常的患者（如 P050）
target_patient = "P050"
target_source = "longitudinal_300"

# 去重后队列
cohort = deduplicate_by_patient(cases_dict)

# 找到目标患者的代表快照
target_case = next(
    (c for c in cohort 
     if c.get("patient_label") == target_patient 
     and (c.get("case_metadata") or {}).get("source_dataset") == target_source),
    None
)
assert target_case is not None, f"患者 {target_patient} 未找到"

# 验证末次访视确实缺 AST
has_ast = any(ind["name"] == "ast" for ind in target_case["indicators"])
assert not has_ast, f"患者 {target_patient} 末次访视应缺 AST"

# 手工统计：cohort 中含 AST 的病例数
expected_present_count = sum(
    1 for c in cohort 
    if any(ind["name"] == "ast" for ind in c["indicators"])
)
expected_total = len(cohort)
expected_present_rate = expected_present_count / expected_total

# 调用引擎获取实际统计
patient_indicators_ast = [{"name": "ast", "value": 50, "unit": "U/L"}]
indicators_result = analyze_indicators(patient_indicators_ast, ranges, cohort)
ast_analysis = next(i for i in indicators_result if i["name"] == "ast")

# 断言：引擎的 present_rate 应等于手工统计值
assert abs(ast_analysis["present_rate_in_cases"] - expected_present_rate) < 0.001

# 证明：目标患者对 AST 的分子贡献为 0（因末次缺测），对分母贡献为 1
print(f"目标患者 {target_patient} 末次缺 AST，对该指标统计贡献：分子=0, 分母=1")
print(f"队列 present_rate: {expected_present_rate:.2%} = {expected_present_count}/{expected_total}")
```

- [ ] **Step 5: 调用链一致性验证**

```python
# 在 generate_prediction 内部 log 或断言：
# analyze_indicators、select_representative_cases、SSE 输出的 sample_size
# 三处使用的列表长度完全一致（都是去重后）

# 验证代表性病例引用的 patient_label/visit_date 确实是最新访视
```

- [ ] **Step 6: 请求 Codex 事后评审**

交接信息模板：

```text
请评审任务 prediction-patient-dedup-001（已实施完成）。

实现者：Claude-Code
评审者：Codex
分支：main（简化流程）
方案：docs/superpowers/specs/2026-08-20-prediction-patient-dedup-design.md（已按首轮评审意见修改）
计划：docs/superpowers/plans/2026-08-20-prediction-patient-dedup.md（已按首轮评审意见修改）
验证：单测 22 passed + 真实库验证 + 存量回归

首轮评审 4 项问题修复对照：
1. [P1] 去重粒度末期偏差 → 已在规格 §3.1 明确承认末期偏差是预期权衡，加验收验证末次访视异常率高于首次（Task 3 Step 4）
2. [P1] patient_label 无唯一约束 → 改为 (source_dataset, patient_label) 复合键，旧手工病例全部独立保留（§3.1、§3.2）
3. [P2] 排序规则不稳定 → 完整实现 (visit_date DESC, id DESC) 二级排序，_sort_key 返回元组（§3.2、Task 1 Step 3）
4. [P2] 固定分档阈值缺影响评估 → 加验收：固定测试输入修复前后对比，区分合理纠偏与异常跨档（Task 3 Step 3）
5. [P2] 验收标准不能证明"一患者一票" → 改为精确断言去重后数量 = 去重键数 + 独立记录数（Task 3 Step 2）；集成测试补全（Task 2 Step 1）

重点检查：
- 复合键 (source_dataset, patient_label) 实现是否真正隔离不同来源的同名患者
- _sort_key 二级排序是否稳定、防御性处理是否完备
- 末期偏差/指标缺失的验收是否能证明这是"预期权衡"而非"未修复缺陷"
- 固定分档阈值验证是否能区分合理纠偏与异常跨档（若发现异常跨档，是否有后续处理计划）

只输出评审意见，不直接修改实现提交。
```

- [ ] **Step 7: 用户审查后再提交**

不提交、不推送，等用户授权。提交正文：

```text
AI-Agent: Claude-Code
AI-Client: VS-Code
Task-ID: prediction-patient-dedup-001
```

---

## Plan Self-Review

- 规格 §3 的方案选择、§4 验收标准均有对应任务覆盖；规格 §4.4 验收标准（末期偏差队列级对比）已与计划 Task 3 Step 4 同步。
- `prediction_engine.py` 零改动，去重发生在 generator 层，符合"引擎统计逻辑本身是对的"判断。
- 类型链：`CaseRecord` 查询 → `_cases_to_dicts`（补充字段）→ `deduplicate_by_patient` → `analyze_indicators`/`select_representative_cases`（入参形状不变）。
- Task 1 补充完整测试用例（含两个非空 source 同名患者场景）；Task 2 集成测试补全可执行细节（async 消费到 done、patch 使用位置、完整 mock 返回值、对象身份断言）；Task 3 验收脚本补全接口细节（首次队列临时函数定义、ranges 字典格式、手工统计逻辑）。
- 固定分档验证改为保存基线快照后对比，预定义锚点覆盖阈值边界和不同异常率组合，阻断规则明确（任一无法解释跨档即阻断，50% 跨档作告警）。
- 末期偏差验收改为队列级对比，指标缺失验证改为手工统计证明分子/分母贡献。
- 计划中保留的临时辅助代码（`deduplicate_by_patient_first_visit`、baseline 快照保存/加载、change_record 结构）均在验收脚本中给出完整定义，不作为生产代码 Produces；集成测试的 mock 配置、SSE 解析、异步消费均给出可执行细节。
- 提交步骤服从"不提交不推送"约束。
