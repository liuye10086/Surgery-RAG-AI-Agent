# 脂肪肝纵向数据集扩展至 300 例 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改已审核 `longitudinal_150/` 基线的前提下，分层重组生成 `P151–P300`，输出包含 300 例的独立五项数据产物。

**Architecture:** 新建独立扩展脚本，只读加载 150 例五项基线及现有生成器的公共常量和验证/规则检测函数。脚本复制 `P001–P150` 后，根据基线队列、结局、分类理由和指标经验分布，用独立固定种子组合 150 个生成病例；所有新增结局审计为 `generated_stage_assignment`，最终写入 `data/generated/longitudinal_300/`。原生成器与原基线目录不修改。

**Tech Stack:** Python 3、标准库 `csv/json/hashlib/tempfile/unittest`、NumPy、现有脂肪肝生成器公共函数。

## Global Constraints

- 简化流程，在当前 `main` 工作区实施；生成、验证和交叉审查完成后由用户决定提交。
- 基线提交为 `4bd104b2c0ef13e76dfe73b39a7076cb53e67235`；不得修改 `data/generated/longitudinal_150/`。
- 不修改 `scripts/generate_fatty_liver_longitudinal.py` 的版本 `1.3.1` 或既有 150 例行为。
- 不修改 CSV schema，不给 CSV 增加来源或生成标记列。
- `P001–P150` 患者行和访视行必须与基线逐字段、逐顺序一致。
- 新增患者为 `P151–P300`；新增队列 118/32，新增结局 75/50/25；总队列 236/64，总结局 150/100/50。
- 新增结局全部审计为 `generated_stage_assignment`，不得继承基线的 explicit 结局身份。
- 保留 `stable`、`r1`、`r2`、`r1_r2`、`non_rule_progression` 及确定性失访设计。
- 所有新增随访值由固定扩展种子生成；核心指标 PLT/HbA1c/AFP 每例至少三个值。
- 不处理或提交 `.claude/settings.local.json`，不修改任务范围之外文件。
- 本计划中的提交步骤延后到用户完成数据审查并明确授权后；实现过程中不得提交或推送。

---

## File Structure

- `scripts/extend_fatty_liver_longitudinal_to_300.py`：只读加载基线、构建特征池、生成新增病例、合并、验证并写五项产物。
- `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`：扩展任务的 TDD、基线不变、分布、临床轨迹、去重和可复现性测试。
- `data/generated/longitudinal_300/`：最终 300 例五项产物。
- `docs/superpowers/specs/2026-08-18-fatty-liver-longitudinal-300-extension-design.md`：已批准设计。
- `docs/superpowers/plans/2026-08-18-fatty-liver-longitudinal-300-extension.md`：本实施计划。

---

### Task 1: 锁定基线读取、哈希与复制契约

**Files:**
- Create: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Create: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `data/generated/longitudinal_150/` 下五项文件。
- Produces: `ExtensionConfig`、`load_baseline()`、`baseline_artifact_hashes()`、`clone_baseline_rows()`。

- [ ] **Step 1: 写基线读取与复制的失败测试**

```python
class FattyLiver300ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extension = load_extension()
        cls.baseline = cls.extension.load_baseline(BASELINE_DIR)

    def test_baseline_loader_reads_all_five_artifacts(self):
        self.assertEqual(len(self.baseline.patients), 150)
        self.assertEqual(len(self.baseline.extracted_cases), 150)
        self.assertEqual(self.baseline.quality["patient_count"], 150)
        self.assertIn("不得作为真实世界临床证据", self.baseline.provenance)

    def test_baseline_hashes_are_stable_and_complete(self):
        hashes = self.extension.baseline_artifact_hashes(BASELINE_DIR)
        self.assertEqual(set(hashes), {
            "patients", "visits", "quality", "provenance", "extracted_cases",
        })
        self.assertTrue(all(len(value) == 64 for value in hashes.values()))

    def test_clone_preserves_all_baseline_rows(self):
        patients, visits = self.extension.clone_baseline_rows(self.baseline)
        self.assertEqual(patients, self.baseline.patients)
        self.assertEqual(visits, self.baseline.visits)
        self.assertIsNot(patients, self.baseline.patients)
        self.assertIsNot(visits, self.baseline.visits)
```

- [ ] **Step 2: 运行测试并确认因扩展模块不存在而失败**

Run:

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_extend_fatty_liver_longitudinal_to_300
```

Expected: `ERROR`，指出 `scripts/extend_fatty_liver_longitudinal_to_300.py` 尚不存在。

- [ ] **Step 3: 实现最小基线读取模块**

在扩展脚本定义：

```python
from dataclasses import dataclass

EXTENSION_SEED = 20260819
EXTENSION_VERSION = "1.0.0"
ARTIFACT_NAMES = {
    "patients": "patients.csv",
    "visits": "visits.csv",
    "quality": "quality_report.json",
    "provenance": "DATA_PROVENANCE.md",
    "extracted_cases": "extracted_cases.json",
}

@dataclass(frozen=True)
class ExtensionConfig:
    seed: int = EXTENSION_SEED
    extension_count: int = 150
    progression_count: int = 118
    mixed_count: int = 32
    fatty_liver_count: int = 75
    cirrhosis_count: int = 50
    hcc_count: int = 25

@dataclass
class BaselineData:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    quality: dict[str, Any]
    provenance: str
    extracted_cases: list[dict[str, Any]]

def load_baseline(baseline_dir: Path) -> BaselineData:
    with (baseline_dir / ARTIFACT_NAMES["patients"]).open(encoding="utf-8", newline="") as handle:
        patients = list(csv.DictReader(handle))
    with (baseline_dir / ARTIFACT_NAMES["visits"]).open(encoding="utf-8", newline="") as handle:
        visits = list(csv.DictReader(handle))
    quality = json.loads((baseline_dir / ARTIFACT_NAMES["quality"]).read_text(encoding="utf-8"))
    provenance = (baseline_dir / ARTIFACT_NAMES["provenance"]).read_text(encoding="utf-8")
    extracted_cases = json.loads(
        (baseline_dir / ARTIFACT_NAMES["extracted_cases"]).read_text(encoding="utf-8")
    )
    return BaselineData(patients, visits, quality, provenance, extracted_cases)

def baseline_artifact_hashes(baseline_dir: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((baseline_dir / filename).read_bytes()).hexdigest()
        for name, filename in ARTIFACT_NAMES.items()
    }

def clone_baseline_rows(baseline: BaselineData) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    return [dict(row) for row in baseline.patients], [dict(row) for row in baseline.visits]
```

`load_extension()` 在测试文件中采用与现有生成器测试相同的 `importlib.util.spec_from_file_location()` 模式。

- [ ] **Step 4: 运行 Task 1 测试**

Expected: 三项测试 `OK`。

- [ ] **Step 5: 检查基线目录没有变更**

Run:

```powershell
git status --short -- data/generated/longitudinal_150
```

Expected: 无输出。

---

### Task 2: 构建分层特征池与确定性患者蓝图

**Files:**
- Modify: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `BaselineData`、`ExtensionConfig`。
- Produces: `FeaturePools`、`SyntheticProfile`、`build_feature_pools()`、`build_extension_profiles()`。

- [ ] **Step 1: 写特征池与分布失败测试**

```python
def test_feature_pools_are_built_from_audited_baseline_reasons(self):
    pools = self.extension.build_feature_pools(self.baseline)
    self.assertTrue(pools.progression_patient_ids)
    self.assertTrue(pools.mixed_patient_ids)
    self.assertIn("metabolic_comorbidity_diabetes", pools.metabolic_reason_pool)
    self.assertIn("competing_viral_hepatitis", pools.competing_reason_pool)
    self.assertIn("competing_alcohol_related_liver_disease", pools.competing_reason_pool)

def test_extension_profiles_have_exact_counts_and_generated_outcomes(self):
    profiles = self.extension.build_extension_profiles(
        self.baseline, self.extension.ExtensionConfig()
    )
    self.assertEqual([profile.patient_id for profile in profiles], [f"P{i:03d}" for i in range(151, 301)])
    self.assertEqual(Counter(profile.cohort_group for profile in profiles), {
        "fatty_liver_progression": 118, "mixed": 32,
    })
    self.assertEqual(Counter(profile.final_stage for profile in profiles), {
        "fatty_liver": 75, "cirrhosis": 50, "hcc": 25,
    })
    self.assertTrue(all(profile.outcome_source == "generated_stage_assignment" for profile in profiles))

def test_profile_assignment_is_shuffled_not_contiguous_by_stage_or_cohort(self):
    profiles = self.extension.build_extension_profiles(
        self.baseline, self.extension.ExtensionConfig()
    )
    stages = [profile.final_stage for profile in profiles]
    cohorts = [profile.cohort_group for profile in profiles]
    self.assertGreater(len(set(stages[:20])), 1)
    self.assertGreater(len(set(cohorts[:40])), 1)
    self.assertLess(max_run_length(stages), 10)
    self.assertLess(max_run_length(cohorts), 20)

def test_profile_reasons_are_cohort_consistent(self):
    profiles = self.extension.build_extension_profiles(
        self.baseline, self.extension.ExtensionConfig()
    )
    for profile in profiles:
        competing = [reason for reason in profile.classification_reasons if reason.startswith("competing_")]
        if profile.cohort_group == "fatty_liver_progression":
            self.assertEqual(competing, [])
            self.assertIn("eligible_no_competing_etiology", profile.classification_reasons)
        else:
            self.assertNotIn("eligible_no_competing_etiology", profile.classification_reasons)
```

测试辅助 `max_run_length()` 必须在测试文件中实现为对连续相同值的最大长度统计。

- [ ] **Step 2: 运行新增测试并确认失败**

Expected: `AttributeError`，缺少 `build_feature_pools` 或 `build_extension_profiles`。

- [ ] **Step 3: 定义蓝图数据结构和池构建逻辑**

```python
@dataclass(frozen=True)
class FeaturePools:
    progression_patient_ids: tuple[str, ...]
    mixed_patient_ids: tuple[str, ...]
    ages_by_cohort: dict[str, tuple[int, ...]]
    sexes_by_cohort: dict[str, tuple[str, ...]]
    metabolic_reason_pool: tuple[str, ...]
    competing_reason_pool: tuple[str, ...]
    reasons_by_cohort: dict[str, tuple[tuple[str, ...], ...]]

@dataclass(frozen=True)
class SyntheticProfile:
    patient_id: str
    cohort_group: str
    final_stage: str
    age: int
    sex: str
    classification_reasons: tuple[str, ...]
    source_components: dict[str, str]
    outcome_source: str = "generated_stage_assignment"
```

`build_feature_pools()` 从 `quality["cohort_classification_reasons"]` 和患者 CSV 建池：

- 主队列池仅使用无 `competing_` 理由的基线患者；
- mixed 池保留其竞争病因或排除理由组合；
- 人口学按 `cohort_group` 分层；
- 理由模板剥离 `source_case_id`、explicit outcome 和日期信息；
- 所有 tuple 排序后再抽样，避免 JSON/dict 插入顺序影响可复现性。

- [ ] **Step 4: 实现确定性蓝图分配**

`build_extension_profiles()` 必须：

1. 使用 `np.random.default_rng(config.seed)`；
2. 构造 118/32 队列标签和 75/50/25 结局标签；
3. 分别 shuffle 后按 `P151–P300` 绑定；
4. 主队列理由从主队列模板重组，确保包含 `documented_fatty_liver` 和 `eligible_no_competing_etiology`；
5. mixed 理由从 mixed 模板或竞争病因池重组，禁止附加 `eligible_no_competing_etiology`；
6. 年龄在分层样本基础上加入 `rng.integers(-4, 5)` 扰动并裁剪到 16–85；
7. 性别按分层经验池抽样；
8. `source_components` 分别记录 demographics、reason template 和 later baseline trajectory 的来源 patient ID，且至少 demographics 与 reason template 不得始终来自同一 ID。

- [ ] **Step 5: 运行 Task 2 测试**

Expected: Task 1–2 全部 `OK`。

---

### Task 3: 生成新增时间线、数值与规则路径

**Files:**
- Modify: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `SyntheticProfile`、基线 visits、现有生成器的 `INDICATORS`、`SAFETY_BOUNDS`、`DEFAULT_BASELINES`、`_round_value()`、`_actual_rule_memberships()`。
- Produces: `assign_extension_paths()`、`generate_extension_rows()`、新增 patient/visit/audit rows。

- [ ] **Step 1: 写时间线、轨迹和数据契约失败测试**

```python
def test_generated_extension_rows_meet_patient_and_visit_contract(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    self.assertEqual(len(result.extension_patients), 150)
    by_patient = defaultdict(list)
    for row in result.extension_visits:
        by_patient[row["patient_id"]].append(row)
    for patient in result.extension_patients:
        rows = by_patient[patient["patient_id"]]
        self.assertTrue(3 <= len(rows) <= 6)
        dates = [date.fromisoformat(row["visit_date"]) for row in rows]
        self.assertEqual(dates, sorted(set(dates)))
        self.assertTrue(730 <= (dates[-1] - dates[0]).days <= 1830)
        for indicator in ("plt", "hba1c", "afp"):
            self.assertGreaterEqual(sum(row[indicator] != "" for row in rows), 3)

def test_event_dates_match_generated_stage(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    for row in result.extension_patients:
        fatty = date.fromisoformat(row["fatty_liver_date"])
        last = date.fromisoformat(row["last_followup_date"])
        cirrhosis = date.fromisoformat(row["cirrhosis_date"]) if row["cirrhosis_date"] else None
        hcc = date.fromisoformat(row["hcc_date"]) if row["hcc_date"] else None
        self.assertLess(fatty, last)
        if row["final_stage"] == "fatty_liver":
            self.assertIsNone(cirrhosis)
            self.assertIsNone(hcc)
        elif row["final_stage"] == "cirrhosis":
            self.assertTrue(fatty < cirrhosis <= last)
            self.assertIsNone(hcc)
        else:
            self.assertTrue(fatty < hcc <= last)
            if cirrhosis:
                self.assertTrue(fatty < cirrhosis < hcc)

def test_extension_contains_all_path_types_without_assignment_mismatch(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    self.assertTrue({"stable", "r1", "r2", "r1_r2", "non_rule_progression"}.issubset(
        Counter(result.paths).keys()
    ))
    self.assertEqual(result.assigned_path_mismatches, [])

def test_generated_values_stay_inside_existing_safety_bounds(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    for row in result.extension_visits:
        for indicator, (low, high) in self.extension.BASE_GENERATOR.SAFETY_BOUNDS.items():
            if row[indicator] != "":
                self.assertTrue(low <= float(row[indicator]) <= high)
```

- [ ] **Step 2: 运行新增测试并确认失败**

Expected: 缺少 `generate_extension()`。

- [ ] **Step 3: 以只读方式加载基线生成器公共能力**

扩展脚本通过 `importlib.util.spec_from_file_location()` 加载 `scripts/generate_fatty_liver_longitudinal.py` 为 `BASE_GENERATOR`。只调用公共常量和纯计算辅助，不修改原模块。

- [ ] **Step 4: 实现路径分配**

`assign_extension_paths(profiles, rng)` 采用确定性配额：

- 75 个 `fatty_liver` 全部分配 `stable`；
- 50 个 `cirrhosis` 中至少 8 个 `r1`、5 个 `r1_r2`、其余为 `non_rule_progression`；
- 25 个 `hcc` 中至少 10 个 `r2`、5 个 `r1_r2`、其余为 `non_rule_progression`；
- 分配前按稳定 hash + seed 排序，之后再次确定性打散；
- 保证每类路径非空，并将 `{patient_id: path}` 返回。

- [ ] **Step 5: 实现基线分布采样和时间线生成**

对每个新增患者：

1. 从相同队列、优先相同结局的基线患者集合中独立选择 `baseline_source_patient_id`；
2. 从该来源的首个非空指标或全队列分位数提取指标中心；
3. 对每项指标应用患者级乘性扰动 `rng.normal(1.0, 0.08)`，并裁剪至安全范围；
4. 生成 3–6 个访视点；首访位于 2014-01-01 至 2022-08-18，末访不晚于 2026-08-18；
5. 总跨度为 24–60 个月，内部节点使用不规则月间隔并严格递增；
6. 事件日期按 `final_stage` 放在倒数第二或最后访视点；
7. 新增 `fatty_liver_date` 等于生成首访日期，审计来源为 `generated_extension_baseline`。

- [ ] **Step 6: 实现指标轨迹**

使用每项指标的基线值、进度 `t = index / (visit_count - 1)` 和路径生成：

```python
if path in {"r1", "r1_r2"}:
    hba1c = baseline_hba1c + 1.1 * t + noise
    plt = baseline_plt * (1.0 - 0.28 * t) + noise
elif path == "stable":
    hba1c = baseline_hba1c + stable_noise
    plt = baseline_plt + stable_noise

if path in {"r2", "r1_r2"}:
    afp = baseline_afp + max(0.0, 8.0 * t ** 2) + noise
```

生成后执行与原生成器一致的强制阈值修正，确保：

- 完整 R1 路径中 HbA1c 至少连续上升两段，末次 PLT 不高于基线 75%；
- 完整 R2 路径中 AFP 至少连续上升两段；
- 稳定路径不被误判为 R1/R2；
- 其它肝酶、白蛋白、胆红素、腰围和 BMI 随结局产生温和趋势并保持安全范围；
- 使用 `BASE_GENERATOR._round_value()` 统一格式。

- [ ] **Step 7: 复用现有规则检测验证分配路径**

将新增 patients/visits 传给 `BASE_GENERATOR._actual_rule_memberships()`，并实现扩展版 mismatch 检查：

- `r1` 必须在 R1 membership；
- `r2` 必须在 R2 membership；
- `r1_r2` 必须同时命中；
- `stable` 不得命中 R1 或 R2；
- `non_rule_progression` 不要求命中。

- [ ] **Step 8: 运行 Task 3 测试**

Expected: Task 1–3 全部 `OK`。

---

### Task 4: 合并、完整验证和去重门禁

**Files:**
- Modify: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `ExtensionResult`、基线 rows。
- Produces: `CombinedDataset`、`combine_dataset()`、`validate_combined_dataset()`、`duplicate_signature_report()`。

- [ ] **Step 1: 写合并与基线不变失败测试**

```python
def test_combined_dataset_has_exact_counts_and_continuous_ids(self):
    combined = self.extension.build_combined_dataset(
        self.baseline, self.extension.ExtensionConfig()
    )
    self.assertEqual(len(combined.patients), 300)
    self.assertEqual([row["patient_id"] for row in combined.patients], [f"P{i:03d}" for i in range(1, 301)])
    self.assertEqual(Counter(row["cohort_group"] for row in combined.patients), {
        "fatty_liver_progression": 236, "mixed": 64,
    })
    self.assertEqual(Counter(row["final_stage"] for row in combined.patients), {
        "fatty_liver": 150, "cirrhosis": 100, "hcc": 50,
    })

def test_first_150_patient_and_visit_rows_are_unchanged(self):
    combined = self.extension.build_combined_dataset(
        self.baseline, self.extension.ExtensionConfig()
    )
    self.assertEqual(combined.patients[:150], self.baseline.patients)
    baseline_visits = [row for row in combined.visits if int(row["patient_id"][1:]) <= 150]
    self.assertEqual(baseline_visits, self.baseline.visits)

def test_new_patients_are_not_complete_duplicates(self):
    combined = self.extension.build_combined_dataset(
        self.baseline, self.extension.ExtensionConfig()
    )
    duplicates = self.extension.duplicate_signature_report(combined.patients, combined.visits)
    self.assertEqual(duplicates["complete_duplicate_groups"], [])

def test_combined_validation_has_no_errors(self):
    combined = self.extension.build_combined_dataset(
        self.baseline, self.extension.ExtensionConfig()
    )
    validation = self.extension.validate_combined_dataset(combined.patients, combined.visits)
    self.assertEqual(validation["errors"], [])
```

- [ ] **Step 2: 运行新增测试并确认失败**

Expected: 缺少 `build_combined_dataset`、`duplicate_signature_report` 或 `validate_combined_dataset`。

- [ ] **Step 3: 实现合并数据结构**

```python
@dataclass
class CombinedDataset:
    patients: list[dict[str, Any]]
    visits: list[dict[str, Any]]
    extension: ExtensionResult
```

`build_combined_dataset()` 必须使用 `clone_baseline_rows()`，并按 `P001–P300` 顺序拼接 patients；visits 保留基线原顺序，新增 visits 按 patient ID 和日期追加。

- [ ] **Step 4: 实现 300 例验证函数**

`validate_combined_dataset()` 从现有 `validate_dataset()` 复制通用契约，但将硬编码规模改为参数：

```python
def validate_combined_dataset(patients, visits, expected_count=300):
    # 检查 P001-P300、headers、分类值、年龄、3-6 次访视、日期顺序、
    # 730-1830 天跨度、核心指标完整性、安全边界和事件日期语义。
```

不得修改原生成器以支持 300 例。

- [ ] **Step 5: 实现去重签名**

去重时忽略 `patient_id`，分别构造：

- patient signature：其余患者字段 tuple；
- visit signature：相对首访天数 + 全部指标值 tuple；
- complete signature：patient signature + visit signature。

只将 complete signature 完全一致判为完整重复。质量报告同时记录 patient-only 和 trajectory-only 重复数量用于审计，但它们不单独导致失败。

- [ ] **Step 6: 运行 Task 4 测试**

Expected: Task 1–4 全部 `OK`。

---

### Task 5: 写五项 300 例产物与审计报告

**Files:**
- Modify: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`
- Create: `data/generated/longitudinal_300/patients.csv`
- Create: `data/generated/longitudinal_300/visits.csv`
- Create: `data/generated/longitudinal_300/quality_report.json`
- Create: `data/generated/longitudinal_300/DATA_PROVENANCE.md`
- Create: `data/generated/longitudinal_300/extracted_cases.json`

**Interfaces:**
- Consumes: `CombinedDataset`、基线哈希、特征池和扩展审计。
- Produces: `build_quality_report()`、`build_extracted_cases()`、`write_outputs()`、CLI `main()`。

- [ ] **Step 1: 写产物与审计失败测试**

```python
def test_output_contains_five_artifacts_and_exact_csv_headers(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        self.assertEqual(set(paths), {
            "patients", "visits", "quality", "provenance", "extracted_cases",
        })
        with paths["patients"].open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, self.extension.BASE_GENERATOR.PATIENT_HEADERS)
            self.assertEqual(len(list(reader)), 300)
        with paths["visits"].open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, self.extension.BASE_GENERATOR.VISIT_HEADERS)

def test_quality_report_contains_extension_audit_and_expected_totals(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        report = json.loads(paths["quality"].read_text(encoding="utf-8"))
    self.assertEqual(report["patient_count"], 300)
    self.assertEqual(report["baseline_patient_count"], 150)
    self.assertEqual(report["extension_patient_count"], 150)
    self.assertEqual(report["stage_counts"], {"fatty_liver": 150, "cirrhosis": 100, "hcc": 50})
    self.assertEqual(report["extension_stage_counts"], {"fatty_liver": 75, "cirrhosis": 50, "hcc": 25})
    self.assertEqual(report["cohort_counts"], {"fatty_liver_progression": 236, "mixed": 64})
    self.assertEqual(report["extension_cohort_counts"], {"fatty_liver_progression": 118, "mixed": 32})
    self.assertEqual(report["validation"]["errors"], [])
    self.assertEqual(report["assigned_path_mismatches"], [])
    self.assertEqual(report["duplicate_check"]["complete_duplicate_groups"], [])
    for patient_id in (f"P{i:03d}" for i in range(151, 301)):
        self.assertEqual(report["outcome_assignment_audit"][patient_id]["source"], "generated_stage_assignment")

def test_extracted_cases_preserves_baseline_and_uses_extension_audit_records(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        extracted = json.loads(paths["extracted_cases"].read_text(encoding="utf-8"))
    self.assertEqual(extracted[:150], self.baseline.extracted_cases)
    self.assertEqual(len(extracted), 300)
    for row in extracted[150:]:
        self.assertEqual(row["record_type"], "stratified_recombination_extension")
        self.assertIsNone(row["source_case_id"])
        self.assertIn("source_components", row)

def test_provenance_states_extension_method_and_usage_boundary(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        provenance = paths["provenance"].read_text(encoding="utf-8")
    self.assertIn("分层重组", provenance)
    self.assertIn("P001–P150", provenance)
    self.assertIn("P151–P300", provenance)
    self.assertIn("不得作为真实世界临床证据", provenance)
    self.assertIn("R1", provenance)
    self.assertIn("R2", provenance)
```

- [ ] **Step 2: 运行新增测试并确认失败**

Expected: 缺少 `generate_and_write()`。

- [ ] **Step 3: 构建质量报告**

报告必须包含：

- `seed`、`extension_version`、`base_generator_version`；
- `baseline_artifact_hashes`；
- 总体、新增部分各自 patient/visit/cohort/stage/path 统计；
- `baseline_patient_ids=P001–P150`、`generated_extension_patient_ids=P151–P300`；
- 合并后的 `cohort_classification_reasons` 和 `outcome_assignment_audit`；
- 新增患者的 `source_components`、特征组合和 `generated_outcome_ids`；
- `generated_lost_to_followup_ids`；
- `actual_rule_signal_counts`、`cohort_rule_signal_counts`、`assigned_path_mismatches`；
- `duplicate_check`；
- 缺失率、指标分位数、随访跨度与访视次数；
- `intended_use`、`prohibited_uses`、`embedded_rule_paths`；
- `validation`。

基线 P001–P150 的原 audit 直接保留；新增 audit 使用 `source_case_id: null` 和 `source: generated_stage_assignment`。

- [ ] **Step 4: 构建 extracted cases 和 provenance**

新增 extracted record 固定字段：

```python
{
    "patient_id": profile.patient_id,
    "source_case_id": None,
    "record_type": "stratified_recombination_extension",
    "cohort_group": profile.cohort_group,
    "classification_reasons": list(profile.classification_reasons),
    "source_components": profile.source_components,
    "outcome_source": "generated_stage_assignment",
}
```

provenance 必须记录基线五项哈希、扩展种子、扩展版本、分层重组方法、总/新增统计、R1/R2 使用边界、生成结局和生成失访语义。

- [ ] **Step 5: 实现写文件和 CLI**

CLI：

```powershell
python scripts/extend_fatty_liver_longitudinal_to_300.py `
  --baseline-dir data/generated/longitudinal_150 `
  --output-dir data/generated/longitudinal_300
```

写 CSV 时使用 `encoding="utf-8"`、`newline=""`、`lineterminator="\n"`，JSON 使用 `ensure_ascii=False, indent=2, sort_keys=True` 并以换行结尾。

写文件前运行完整验证；有错误时抛出 `ValueError`，不得留下部分正式产物。先写入输出目录旁的临时目录，全部成功后再以逐文件替换方式发布。

- [ ] **Step 6: 运行 Task 5 测试**

Expected: Task 1–5 全部 `OK`。

---

### Task 6: 可复现性、正式生成与最终核验

**Files:**
- Modify: `scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py`
- Verify: `scripts/extend_fatty_liver_longitudinal_to_300.py`
- Verify: `data/generated/longitudinal_150/*`
- Verify: `data/generated/longitudinal_300/*`

**Interfaces:**
- Consumes: 完整扩展生成入口。
- Produces: 全量验证证据和正式五项产物。

- [ ] **Step 1: 写五产物双目录复现测试**

```python
def test_all_five_outputs_are_byte_reproducible(self):
    hashes = []
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        for run in ("run1", "run2"):
            paths = self.extension.generate_and_write(BASELINE_DIR, root / run)
            hashes.append({name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()})
    self.assertEqual(hashes[0], hashes[1])
```

- [ ] **Step 2: 运行完整扩展测试并确认通过**

Run:

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_extend_fatty_liver_longitudinal_to_300
```

Expected: 全部测试 `OK`。

- [ ] **Step 3: 运行原 150 例完整回归测试**

Run:

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_generate_fatty_liver_longitudinal
```

Expected: 30 项测试 `OK`。

- [ ] **Step 4: 保存任务前基线五项哈希并生成正式300例产物**

先计算 `longitudinal_150/` 五项 SHA-256，再运行：

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\extend_fatty_liver_longitudinal_to_300.py `
  --baseline-dir data\generated\longitudinal_150 `
  --output-dir data\generated\longitudinal_300
```

Expected: 输出 300 patients、新增150、总/新增队列和结局统计、0 validation errors 以及五项路径。

- [ ] **Step 5: 核对基线前后哈希完全一致**

重新计算 `longitudinal_150/` 五项 SHA-256，与 Step 4 生成前值比较。

Expected: 五项完全一致。

- [ ] **Step 6: 两个独立临时目录重新生成并比较正式产物**

使用测试以外的独立验证脚本调用 `generate_and_write()` 两次，比较：

- 临时 run1 与 run2 五项哈希一致；
- 临时产物与 `data/generated/longitudinal_300/` 五项哈希一致。

- [ ] **Step 7: 执行静态和工作区检查**

Run:

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m py_compile `
  scripts\extend_fatty_liver_longitudinal_to_300.py `
  scripts\tests\test_extend_fatty_liver_longitudinal_to_300.py

git diff --check -- `
  scripts/extend_fatty_liver_longitudinal_to_300.py `
  scripts/tests/test_extend_fatty_liver_longitudinal_to_300.py `
  docs/superpowers/specs/2026-08-18-fatty-liver-longitudinal-300-extension-design.md `
  docs/superpowers/plans/2026-08-18-fatty-liver-longitudinal-300-extension.md
```

Expected: 两条命令均成功，无输出错误。

- [ ] **Step 8: 独立交叉审查**

评审者只读检查：

- 原150例基线及合并后的前150例不变；
- 新增118/32、75/50/25与总236/64、150/100/50；
- clinical reasons 不冲突；
- 新增结局全部为 generated；
- 轨迹、事件日期、R1/R2 和失访审计；
- 去重门禁；
- 五项可复现性；
- 不修改原生成器或基线目录。

- [ ] **Step 9: 用户审查后再提交**

按用户当前要求，本步骤在用户审核数据和审查报告并明确要求提交前不得执行。提交时精确暂存本任务文件，排除 `.claude/settings.local.json` 和任何无关改动；未经单独授权不得推送。

---

## Plan Self-Review

- 规格 §1–§10 均有对应任务：基线只读（Task 1/4/6）、分层重组（Task 2）、随访和路径（Task 3）、去重与验证（Task 4）、五项审计产物（Task 5）、复现和交叉审查（Task 6）。
- 无 `TBD`、`TODO` 或未定义的“稍后实现”步骤。
- 接口命名一致：`load_baseline` → `build_feature_pools`/`build_extension_profiles` → `generate_extension` → `build_combined_dataset` → `generate_and_write`。
- 原生成器只读复用，不列为修改文件。
- 提交步骤服从用户“生成、审查后再提交”的明确要求。
