# AD Longitudinal 300-Patient Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改已审核 AD 150 例基线的前提下，分层重组生成 P151–P300，并输出包含 300 例的独立五项纵向数据产物。

**Architecture:** 新建独立扩展脚本，只读加载 `ad_longitudinal_150` 五项基线和原 AD 生成器的字段、边界、格式化及规则检测函数。脚本逐行复制 P001–P150，再以独立固定种子组合人口学、静态标志、分类理由、单次标志物和纵向轨迹来源，生成 P151–P300；所有新增结局审计为 `generated_stage_assignment`，最终写入独立 `ad_longitudinal_300` 目录。

**Tech Stack:** Python 3 标准库：`csv`、`json`、`hashlib`、`importlib.util`、`random`、`tempfile`、`shutil`、`statistics`、`unittest`。

## Global Constraints

- 采用简化流程，在当前 `main` 工作区实施；不创建分支或 worktree。
- 不提交、不推送、不清理工作区，除非项目所有者另行明确授权。
- 不修改 `scripts/generate_ad_longitudinal.py`、`scripts/tests/test_generate_ad_longitudinal.py` 或 `data/generated/ad_longitudinal_150/`。
- 不修改任何脂肪肝生成器、扩展器及 `data/generated/longitudinal_150/`、`data/generated/longitudinal_300/`。
- 不修改、暂存或删除 `.claude/settings.local.json`。
- P001–P150 患者行和访视行必须与基线逐字段、逐顺序一致。
- P151–P300 为分层重组合成患者，不对应新的 Word 病例原文。
- 新增 CDR 固定为 `0:5 / 0.5:10 / 1:55 / 2:45 / 3:35`；最终为 `10 / 20 / 110 / 90 / 70`。
- 新增队列固定为 `ad_progression:124 / mixed:26`；最终为 `248 / 52`。
- 新增路径固定为 `r1:25 / r2:25 / r1_r2:25 / non_rule_progression:45 / stable:30`；最终为 `50 / 50 / 50 / 90 / 60`。
- 新增 stable 固定包含 CDR 0 的 5 例、CDR 0.5 的 10 例、以及基线至末次均为 CDR 1 的 15 例。
- CSV schema、字段顺序、UTF-8 无 BOM、空字符串缺失约定保持不变，不增加来源或 synthetic 列。
- 扩展固定种子使用 `20260819`，扩展器版本使用 `1.0.0`。
- 五项输出在两个独立临时目录字节级一致，正式产物必须与临时生成一致。
- `validation.errors=[]`、`assigned_path_mismatches=[]`、完整重复组为空才允许写正式产物。

---

## File Structure

- `scripts/extend_ad_longitudinal_to_300.py`：只读加载基线、建立特征池、生成新增患者、合并验证、构建审计并原子写五项产物。
- `scripts/tests/test_extend_ad_longitudinal_to_300.py`：基线保护、精确分布、轨迹路径、去重、审计和可复现性测试。
- `data/generated/ad_longitudinal_300/`：最终五项 300 例产物。
- `docs/superpowers/specs/2026-08-19-ad-longitudinal-300-extension-design.md`：已批准设计规格。
- `docs/superpowers/plans/2026-08-19-ad-longitudinal-300-extension.md`：本计划。

---

### Task 1: 锁定基线读取、哈希和复制契约

**Files:**
- Create: `scripts/extend_ad_longitudinal_to_300.py`
- Create: `scripts/tests/test_extend_ad_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `Path` 指向 `data/generated/ad_longitudinal_150/`。
- Produces: `ExtensionConfig`、`BaselineData`、`load_baseline()`、`baseline_artifact_hashes()`、`clone_baseline_rows()`。

- [x] **Step 1: 写扩展模块加载器和失败测试**

```python
ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "extend_ad_longitudinal_to_300.py"
BASELINE_DIR = ROOT / "data" / "generated" / "ad_longitudinal_150"

def load_extension():
    spec = importlib.util.spec_from_file_location("ad_longitudinal_300_extension", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

class ADLongitudinal300ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extension = load_extension()
        cls.baseline = cls.extension.load_baseline(BASELINE_DIR)

    def test_baseline_loader_reads_all_five_artifacts(self):
        self.assertEqual(len(self.baseline.patients), 150)
        self.assertEqual(len(self.baseline.visits), 672)
        self.assertEqual(len(self.baseline.extracted_cases), 150)
        self.assertEqual(self.baseline.quality["patient_count"], 150)
        self.assertIn("不得作为真实世界临床证据", self.baseline.provenance)
```

- [x] **Step 2: 运行测试并验证 RED**

Run:

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_extend_ad_longitudinal_to_300 -v
```

Expected: `ERROR`，指出 `scripts/extend_ad_longitudinal_to_300.py` 不存在。

- [x] **Step 3: 实现基线数据结构和读取器**

```python
EXTENSION_SEED = 20260819
EXTENSION_VERSION = "1.0.0"
BASE_GENERATOR_PATH = Path(__file__).with_name("generate_ad_longitudinal.py")

@dataclass(frozen=True)
class ExtensionConfig:
    seed: int = EXTENSION_SEED
    extension_count: int = 150
    cohort_counts: tuple[tuple[str, int], ...] = (("ad_progression", 124), ("mixed", 26))
    stage_counts: tuple[tuple[str, int], ...] = (("0", 5), ("0.5", 10), ("1", 55), ("2", 45), ("3", 35))
    path_counts: tuple[tuple[str, int], ...] = (("r1", 25), ("r2", 25), ("r1_r2", 25), ("non_rule_progression", 45), ("stable", 30))

@dataclass
class BaselineData:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    quality: dict[str, Any]
    extracted_cases: list[dict[str, Any]]
    provenance: str
```

`load_baseline()` 使用 `csv.DictReader` 和 UTF-8 JSON/Markdown 读取全部五项文件；`baseline_artifact_hashes()` 对 `BASE_GENERATOR.ARTIFACT_NAMES` 每项计算 SHA-256；`clone_baseline_rows()` 返回逐行 `dict()` 副本。

- [x] **Step 4: 增加哈希和深复制测试**

```python
def test_baseline_hashes_are_complete(self):
    hashes = self.extension.baseline_artifact_hashes(BASELINE_DIR)
    self.assertEqual(set(hashes), set(self.extension.BASE_GENERATOR.ARTIFACT_NAMES))
    self.assertTrue(all(len(value) == 64 for value in hashes.values()))

def test_clone_preserves_all_baseline_rows(self):
    patients, visits = self.extension.clone_baseline_rows(self.baseline)
    self.assertEqual(patients, self.baseline.patients)
    self.assertEqual(visits, self.baseline.visits)
    self.assertIsNot(patients, self.baseline.patients)
    self.assertIsNot(visits, self.baseline.visits)
    self.assertIsNot(patients[0], self.baseline.patients[0])
```

- [x] **Step 5: 运行 Task 1 测试并验证 GREEN**

Expected: Task 1 测试全部 `ok`。

---

### Task 2: 构建特征池和精确患者蓝图

**Files:**
- Modify: `scripts/extend_ad_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_ad_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `BaselineData`、`ExtensionConfig`。
- Produces: `FeaturePools`、`SyntheticProfile`、`build_feature_pools()`、`build_extension_profiles()`、`assign_extension_paths()`。

- [x] **Step 1: 写精确分布和来源组件失败测试**

```python
def test_extension_profiles_have_exact_counts_and_generated_outcomes(self):
    profiles = self.extension.build_extension_profiles(
        self.baseline, self.extension.ExtensionConfig()
    )
    self.assertEqual(
        [profile.patient_id for profile in profiles],
        [f"P{i:03d}" for i in range(151, 301)],
    )
    self.assertEqual(Counter(profile.cohort_group for profile in profiles), {"ad_progression": 124, "mixed": 26})
    self.assertEqual(Counter(profile.final_stage for profile in profiles), {"0": 5, "0.5": 10, "1": 55, "2": 45, "3": 35})
    self.assertTrue(all(profile.outcome_source == "generated_stage_assignment" for profile in profiles))
    for profile in profiles:
        self.assertEqual(
            set(profile.source_components),
            {
                "demographics_patient_id",
                "static_marker_patient_id",
                "classification_reason_patient_id",
                "baseline_biomarker_patient_id",
                "trajectory_patient_id",
            },
        )
```

- [x] **Step 2: 写路径精确计数和 stable 兼容性失败测试**

```python
def test_extension_paths_match_approved_counts_and_stable_stage_contract(self):
    profiles = self.extension.build_extension_profiles(self.baseline, self.extension.ExtensionConfig())
    paths = self.extension.assign_extension_paths(profiles, self.extension.ExtensionConfig())
    self.assertEqual(Counter(paths.values()), {"r1": 25, "r2": 25, "r1_r2": 25, "non_rule_progression": 45, "stable": 30})
    stages = {profile.patient_id: profile.final_stage for profile in profiles}
    stable_stages = Counter(stages[patient_id] for patient_id, path in paths.items() if path == "stable")
    self.assertEqual(stable_stages, {"0": 5, "0.5": 10, "1": 15})
    self.assertTrue(all(stages[patient_id] in {"1", "2", "3"} for patient_id, path in paths.items() if path != "stable"))
```

- [x] **Step 3: 运行 Task 2 测试并验证 RED**

Expected: `AttributeError`，缺少特征池、患者蓝图或路径函数。

- [x] **Step 4: 实现特征池和蓝图数据结构**

```python
@dataclass(frozen=True)
class FeaturePools:
    patient_ids_by_cohort: dict[str, tuple[str, ...]]
    patient_ids_by_stage: dict[str, tuple[str, ...]]
    classification_reasons_by_cohort: dict[str, tuple[tuple[str, ...], ...]]

@dataclass(frozen=True)
class SyntheticProfile:
    patient_id: str
    cohort_group: str
    final_stage: str
    age: int
    sex: str
    apoe: str
    gene_mutation: str
    classification_reasons: tuple[str, ...]
    source_components: dict[str, str]
    outcome_source: str = "generated_stage_assignment"
```

`build_feature_pools()` 从患者 CSV、质量报告和 extracted audit 建立队列/阶段/理由池。`build_extension_profiles()` 使用局部 `random.Random(config.seed)` 分别打散队列和阶段标签，从相同队列抽取来源患者，并要求人口学、静态标志、分类理由、基线标志物和轨迹来源尽可能不同。

- [x] **Step 5: 实现精确路径分配**

`assign_extension_paths()` 必须：

1. 将全部 CDR 0 和 0.5，以及 15 名 CDR 1 患者分为 stable；
2. 从余下 CDR 1/2/3 患者中固定种子打散；
3. 依次分配 25 `r1_r2`、25 `r1`、25 `r2`、45 `non_rule_progression`；
4. 验证所有计数和阶段兼容性，否则抛出 `ValueError`。

- [x] **Step 6: 增加标签打散与队列一致性测试**

```python
def test_profile_labels_are_shuffled_and_reasons_are_cohort_consistent(self):
    profiles = self.extension.build_extension_profiles(self.baseline, self.extension.ExtensionConfig())
    self.assertLess(max_run_length([profile.final_stage for profile in profiles]), 10)
    self.assertLess(max_run_length([profile.cohort_group for profile in profiles]), 20)
    for profile in profiles:
        if profile.cohort_group == "mixed":
            self.assertIn("explicit_competing_diagnosis", profile.classification_reasons)
        else:
            self.assertNotIn("explicit_competing_diagnosis", profile.classification_reasons)
```

- [x] **Step 7: 运行 Task 2 测试并验证 GREEN**

Expected: 精确计数、stable 组成、来源组件和打散测试全部通过。

---

### Task 3: 生成新增时间线、指标和五类路径

**Files:**
- Modify: `scripts/extend_ad_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_ad_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `BaselineData`、`list[SyntheticProfile]`、路径映射、`ExtensionConfig`。
- Produces: `ExtensionResult`、`generate_extension()`。

- [x] **Step 1: 写新增患者与访视契约失败测试**

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
        for field in self.extension.BASE_GENERATOR.LONGITUDINAL_FIELDS:
            self.assertGreaterEqual(sum(row[field] != "" for row in rows), 3)
        for field in self.extension.BASE_GENERATOR.SINGLE_MEASUREMENT_FIELDS:
            self.assertNotEqual(rows[0][field], "")
            self.assertTrue(all(row[field] == "" for row in rows[1:]))
```

- [x] **Step 2: 写路径数值和事件一致性失败测试**

```python
def test_extension_path_signals_and_events_match_assignments(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    self.assertEqual(result.assigned_path_mismatches, [])
    by_patient = defaultdict(list)
    for row in result.extension_visits:
        by_patient[row["patient_id"]].append(row)
    patients = {row["patient_id"]: row for row in result.extension_patients}
    for patient_id, path in result.paths.items():
        rows = by_patient[patient_id]
        self.assertEqual(self.extension.BASE_GENERATOR.detect_rule_path(rows), path)
        self.assertEqual(rows[-1]["cdr"], patients[patient_id]["final_stage"])
        reached = [row["visit_date"] for row in rows if float(row["cdr"]) >= 1]
        self.assertEqual(patients[patient_id]["dementia_date"], reached[0] if reached else "")
```

- [x] **Step 3: 运行 Task 3 测试并验证 RED**

Expected: 缺少 `generate_extension()` 或轨迹实现。

- [x] **Step 4: 实现时间线与经验基线抽取**

`_timeline()` 生成 3–6 次日期、730–1830 天跨度，末次不晚于 `BASE_GENERATOR.DATA_CUTOFF`。`_source_baseline()` 从 `baseline_biomarker_patient_id` 的首访读取单次标志物，从 `trajectory_patient_id` 读取纵向首值；缺少值时使用原生成器安全范围内的确定性默认值。

- [x] **Step 5: 实现 CDR 与认知轨迹**

- stable + final 0/0.5：所有 CDR 固定为最终值；
- stable + final 1：所有 CDR 固定为 1，`dementia_date` 等于首访；
- 其余路径：调用或等价复用原生成器 `_cdr_sequence(final_stage, count)`；
- MMSE/MoCA 从轨迹来源首值加有限扰动，进展路径总体下降，stable 仅小幅波动；
- 所有值通过原生成器 `_clip()` 和 `_format_number()`。

- [x] **Step 6: 实现单次标志物和炎症轨迹**

- 从基线来源读取并扰动单次标志物；
- `abeta_ratio` 使用扰动后的 `abeta42 / abeta40` 重新计算并裁剪；
- R1/R1+R2 强制 Aβ42/p-tau 阈值和 GFAP 末三次严格上升；
- R2/R1+R2 强制 CRP 末三次严格上升和同型半胱氨酸末值高于基线；
- non_rule_progression/stable 明确破坏完整 R1 与 R2；
- R1 的第一次 GFAP 上升日期必须早于首次 CDR ≥ 1；
- 所有字段位于 `SAFETY_BOUNDS`。

- [x] **Step 7: 实现 ExtensionResult 和失访**

```python
@dataclass
class ExtensionResult:
    profiles: list[SyntheticProfile]
    extension_patients: list[dict[str, str]]
    extension_visits: list[dict[str, str]]
    paths: dict[str, str]
    assigned_path_mismatches: list[dict[str, str]]
    generated_lost_to_followup_ids: list[str]
```

使用 `random.Random(config.seed + 300)` 生成轨迹；确定性选择少量失访 ID，并把 detected path 与 assigned path 不同的病例加入 mismatches。

- [x] **Step 8: 增加安全范围和 R1 提前测试**

```python
def test_extension_values_stay_in_bounds_and_r1_precedes_dementia(self):
    result = self.extension.generate_extension(self.baseline, self.extension.ExtensionConfig())
    by_patient = defaultdict(list)
    for row in result.extension_visits:
        by_patient[row["patient_id"]].append(row)
        for field, (low, high) in self.extension.BASE_GENERATOR.SAFETY_BOUNDS.items():
            if row[field] != "":
                self.assertTrue(low <= float(row[field]) <= high)
    patients = {row["patient_id"]: row for row in result.extension_patients}
    for patient_id, path in result.paths.items():
        if path not in {"r1", "r1_r2"}:
            continue
        rows = by_patient[patient_id]
        gfap = [float(row["gfap"]) for row in rows]
        first_rise = next(index for index in range(1, len(gfap)) if gfap[index] > gfap[index - 1])
        self.assertLess(rows[first_rise]["visit_date"], patients[patient_id]["dementia_date"])
```

- [x] **Step 9: 运行 Task 3 测试并验证 GREEN**

Expected: 访视、路径、事件、边界和时序测试全部通过。

---

### Task 4: 合并、验证和完整重复门禁

**Files:**
- Modify: `scripts/extend_ad_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_ad_longitudinal_to_300.py`

**Interfaces:**
- Consumes: `BaselineData`、`ExtensionResult`。
- Produces: `CombinedDataset`、`build_combined_dataset()`、`validate_combined_dataset()`、`duplicate_signature_report()`。

- [x] **Step 1: 写合并分布和基线保护失败测试**

```python
def test_combined_dataset_has_exact_counts_and_preserves_baseline(self):
    combined = self.extension.build_combined_dataset(self.baseline, self.extension.ExtensionConfig())
    self.assertEqual(len(combined.patients), 300)
    self.assertEqual([row["patient_id"] for row in combined.patients], [f"P{i:03d}" for i in range(1, 301)])
    self.assertEqual(combined.patients[:150], self.baseline.patients)
    self.assertEqual([row for row in combined.visits if int(row["patient_id"][1:]) <= 150], self.baseline.visits)
    self.assertEqual(Counter(row["final_stage"] for row in combined.patients), {"0": 10, "0.5": 20, "1": 110, "2": 90, "3": 70})
    self.assertEqual(Counter(row["cohort_group"] for row in combined.patients), {"ad_progression": 248, "mixed": 52})
```

- [x] **Step 2: 写重复与完整验证失败测试**

```python
def test_combined_validation_and_duplicate_gate_are_clean(self):
    combined = self.extension.build_combined_dataset(self.baseline, self.extension.ExtensionConfig())
    validation = self.extension.validate_combined_dataset(combined.patients, combined.visits, combined.extension.paths)
    duplicates = self.extension.duplicate_signature_report(combined.patients, combined.visits)
    self.assertEqual(validation["errors"], [])
    self.assertEqual(duplicates["complete_duplicate_groups"], [])
```

- [x] **Step 3: 运行 Task 4 测试并验证 RED**

Expected: 缺少合并、验证或重复函数。

- [x] **Step 4: 实现 CombinedDataset 和合并**

```python
@dataclass
class CombinedDataset:
    patients: list[dict[str, str]]
    visits: list[dict[str, str]]
    extension: ExtensionResult
```

`build_combined_dataset()` 深复制基线行，追加新增患者和按 `(patient_id, visit_date)` 排序的新增访视。

- [x] **Step 5: 实现 300 例验证器**

`validate_combined_dataset()` 不直接调用原 150 例 `validate_dataset()`，而是按 300 例契约验证：连续 ID、精确 CDR/队列分布、3–6 次访视、跨度、截止日期、核心字段覆盖、单次字段首访限定、安全范围、事件日期、末次 CDR、总体路径精确计数与实际数值检测一致。

- [x] **Step 6: 实现完整重复签名**

为每位患者构造：

```python
patient_signature = tuple(row[field] for field in BASE_GENERATOR.PATIENT_HEADERS if field != "patient_id")
visit_signature = tuple(
    tuple(visit[field] for field in BASE_GENERATOR.VISIT_HEADERS if field != "patient_id")
    for visit in ordered_visits
)
```

按 `(patient_signature, visit_signature)` 分组，报告组内超过 1 人的 `complete_duplicate_groups`。

- [x] **Step 7: 运行 Task 4 测试并验证 GREEN**

Expected: 合并、基线保护、精确分布、验证和去重测试通过。

---

### Task 5: 构建五项审计产物和原子写入

**Files:**
- Modify: `scripts/extend_ad_longitudinal_to_300.py`
- Modify: `scripts/tests/test_extend_ad_longitudinal_to_300.py`
- Create: `data/generated/ad_longitudinal_300/patients.csv`
- Create: `data/generated/ad_longitudinal_300/visits.csv`
- Create: `data/generated/ad_longitudinal_300/quality_report.json`
- Create: `data/generated/ad_longitudinal_300/extracted_cases.json`
- Create: `data/generated/ad_longitudinal_300/DATA_PROVENANCE.md`

**Interfaces:**
- Consumes: `BaselineData`、`CombinedDataset`、`ExtensionConfig`。
- Produces: `build_quality_report()`、`build_extracted_cases()`、`build_provenance()`、`generate_and_write()`。

- [x] **Step 1: 写输出、审计和 provenance 失败测试**

```python
def test_quality_report_and_extracted_cases_describe_extension(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        report = json.loads(paths["quality"].read_text(encoding="utf-8"))
        extracted = json.loads(paths["extracted_cases"].read_text(encoding="utf-8"))
    self.assertEqual(report["patient_count"], 300)
    self.assertEqual(report["extension_patient_count"], 150)
    self.assertEqual(report["stage_counts"], {"0": 10, "0.5": 20, "1": 110, "2": 90, "3": 70})
    self.assertEqual(report["cohort_counts"], {"ad_progression": 248, "mixed": 52})
    self.assertEqual(report["path_counts"], {"r1": 50, "r2": 50, "r1_r2": 50, "non_rule_progression": 90, "stable": 60})
    self.assertEqual(report["validation"]["errors"], [])
    self.assertEqual(report["assigned_path_mismatches"], [])
    self.assertEqual(report["duplicate_check"]["complete_duplicate_groups"], [])
    self.assertEqual(extracted[:150], self.baseline.extracted_cases)
    self.assertEqual(len(extracted), 300)
    self.assertTrue(all(row["record_type"] == "stratified_recombination_extension" for row in extracted[150:]))
    self.assertTrue(all(row["source_case_id"] is None for row in extracted[150:]))
```

```python
def test_provenance_states_extension_and_clinical_boundary(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        provenance = paths["provenance"].read_text(encoding="utf-8")
    self.assertIn("P001–P150", provenance)
    self.assertIn("P151–P300", provenance)
    self.assertIn("分层重组", provenance)
    self.assertIn("不得作为真实世界临床证据", provenance)
    self.assertIn("R1", provenance)
    self.assertIn("R2", provenance)
```

- [x] **Step 2: 运行 Task 5 测试并验证 RED**

Expected: 缺少 writer/report/provenance 函数。

- [x] **Step 3: 实现质量报告**

`build_quality_report()` 合并基线质量报告中的路径分配与新增路径，写入：基线五项哈希、版本/种子、基线/新增/总体计数、ID 列表、路径审计、结局审计、来源组件、失访、缺失率、数值摘要、访视跨度、重复报告、允许/禁止用途和验证结果。路径统计必须精确等于批准分布。

- [x] **Step 4: 实现 extracted audit**

前 150 条通过 JSON round-trip 深复制；后 150 条写入：

```python
{
    "patient_id": profile.patient_id,
    "source_case_id": None,
    "record_type": "stratified_recombination_extension",
    "cohort_group": profile.cohort_group,
    "classification_reasons": list(profile.classification_reasons),
    "apoe": profile.apoe,
    "gene_mutation": profile.gene_mutation,
    "assigned_final_stage": profile.final_stage,
    "assigned_path": extension.paths[profile.patient_id],
    "outcome_source": profile.outcome_source,
    "source_components": dict(profile.source_components),
}
```

- [x] **Step 5: 实现 provenance**

写明基线五项哈希、P001–P150 原样继承、P151–P300 分层重组、精确新增分布、规则植入性质、允许用途及禁止临床用途；不嵌入绝对路径。

- [x] **Step 6: 实现确定性原子写入**

`generate_and_write(baseline_dir, output_dir, config=None)`：

1. 加载并验证基线；
2. 构建合并数据、质量报告、extracted audit 和 provenance；
3. 若 validation、mismatches 或 duplicates 非空则抛错；
4. 在输出目录同级使用 `tempfile.mkdtemp()`；
5. CSV 用 `lineterminator="\n"`，JSON 用 `ensure_ascii=False, indent=2, sort_keys=True` 并追加一个换行；
6. 所有五项完成后逐文件 `replace()` 到正式目录；
7. `finally` 清理临时目录。

- [x] **Step 7: 增加 CSV header 和五项存在性测试**

```python
def test_output_contains_five_artifacts_and_exact_headers(self):
    with tempfile.TemporaryDirectory() as temp:
        paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
        self.assertEqual(set(paths), {"patients", "visits", "quality", "extracted_cases", "provenance"})
        with paths["patients"].open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, self.extension.BASE_GENERATOR.PATIENT_HEADERS)
            self.assertEqual(len(list(reader)), 300)
        with paths["visits"].open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, self.extension.BASE_GENERATOR.VISIT_HEADERS)
```

- [x] **Step 8: 运行 Task 5 测试并验证 GREEN**

Expected: 输出、审计、provenance 和 header 测试全部通过。

---

### Task 6: 最终生成、全量验证和只读交叉评审

**Files:**
- Inspect: 本任务全部文件和产物；不新增生产代码。

**Interfaces:**
- Produces: 正式五项 SHA-256、基线不变证据、完整测试证据、工作区范围证据和独立评审结论。

- [x] **Step 1: 记录基线五项哈希**

使用扩展模块 `baseline_artifact_hashes()` 输出 `ad_longitudinal_150` 五项哈希并保存于验证记录中。

- [x] **Step 2: 运行完整测试**

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_extend_ad_longitudinal_to_300 -v
```

Expected: 零失败、零错误。

- [x] **Step 3: 运行原 AD 150 例回归测试**

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest scripts.tests.test_generate_ad_longitudinal -v
```

Expected: 30 项全部通过。

- [x] **Step 4: 生成正式五项产物**

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts/extend_ad_longitudinal_to_300.py `
  --baseline-dir data/generated/ad_longitudinal_150 `
  --output-dir data/generated/ad_longitudinal_300
```

Expected: 输出 300 例、精确 CDR/队列/路径统计和零验证错误。

- [x] **Step 5: 双次独立生成并比较五项 SHA-256**

在两个 `TemporaryDirectory` 子目录调用 `generate_and_write()`，计算五项 SHA-256；断言 run1、run2 和正式目录三者逐文件一致。

- [x] **Step 6: 重新计算基线哈希并比较**

再次调用 `baseline_artifact_hashes()`，与 Step 1 完全一致；若不同则停止验收。

- [x] **Step 7: 语法、空白和范围检查**

```powershell
& 'C:\Users\86182\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m py_compile `
  scripts/extend_ad_longitudinal_to_300.py `
  scripts/tests/test_extend_ad_longitudinal_to_300.py

git diff --check
git status --short
git diff --name-only -- `
  scripts/generate_ad_longitudinal.py `
  scripts/tests/test_generate_ad_longitudinal.py `
  data/generated/ad_longitudinal_150 `
  scripts/generate_fatty_liver_longitudinal.py `
  scripts/extend_fatty_liver_longitudinal_to_300.py `
  data/generated/longitudinal_150 `
  data/generated/longitudinal_300 `
  .claude/settings.local.json
```

Expected: 语法/空白检查成功；禁止路径 diff 无输出；状态只包含本任务文件与原有 `.claude/settings.local.json`。

- [x] **Step 8: 请求独立只读评审**

评审者重点检查：基线保护、精确分布、stable CDR 1 语义、R1/R2 数值时序、mixed 理由、APOE/基因组合、去重、多样性、审计边界、五项复现及禁止路径。修复所有 Critical/Important 时必须先新增失败测试。

- [ ] **Step 9: 用户审查后再提交**

本任务当前不提交、不推送。若项目所有者随后要求提交，精确暂存本任务文件，提交正文使用：

```text
AI-Agent: Codex
AI-Client: Codex-Desktop
Task-ID: ad-longitudinal-300-extension
```

未经单独推送授权不得推送。

---

## Plan Self-Review

- 规格 §1–§12 均有对应任务：基线保护（Task 1/4/6）、精确分布与特征池（Task 2）、轨迹路径（Task 3）、合并去重（Task 4）、五项审计产物（Task 5）、复现与评审（Task 6）。
- stable 30 例与 CDR 0/0.5 仅 15 例的矛盾已明确解决：另有 15 例基线至末次均为 CDR 1 的 stable 病例。
- 无 `TBD`、`TODO`、`implement later` 或未定义接口。
- 类型和接口链一致：`load_baseline` → `build_feature_pools`/`build_extension_profiles` → `assign_extension_paths`/`generate_extension` → `build_combined_dataset` → `build_quality_report`/`generate_and_write`。
- 原 AD 生成器只读复用，不列入修改文件。
- 计划中提交步骤服从项目所有者“不提交、不推送”的当前约束。
