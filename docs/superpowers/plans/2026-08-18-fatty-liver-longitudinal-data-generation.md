# Fatty Liver Longitudinal Data Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate reproducible, case-constrained `patients.csv` and `visits.csv` files for exactly 150 retained fatty-liver case segments, plus provenance and machine-readable quality reports.

**Architecture:** A single focused Python generator parses both DOCX inputs into stable case records, extracts demographic/date/laboratory anchors, classifies cohort membership, assigns deterministic outcome paths, and generates irregular longitudinal visits with a fixed NumPy seed. A separate pytest module tests parsing, exclusions, schemas, temporal invariants, clinical value constraints, outcome distribution, source-anchor preservation, and byte-for-byte reproducibility.

**Tech Stack:** Bundled Python 3, `python-docx`, `numpy`, Python standard-library `csv`, `datetime`, `hashlib`, `json`, and `pytest`.

## Global Constraints

- Use the simplified collaboration flow in the current workspace.
- Retain exactly 150 case segments after excluding A27, A30, A32, A34, and A35.
- Output `patient_id` values `P001` through `P150` in stable source order.
- Use fixed random seed `20260818`.
- Generate 3–6 visits per patient with at least 24 months between first and last visit.
- Provide at least 3 non-empty values per patient for `plt`, `hba1c`, and `afp`.
- Generate 72–78 progression events, targeting 50 `cirrhosis` and 25 `hcc` final stages.
- Preserve exact CSV column order from the collection specification.
- Write UTF-8 CSV without BOM and represent missing values as empty cells.
- Do not change database code, APIs, RAG code, or import generated rows into the database.
- Do not add source/provenance columns to the two import CSV files.

---

### Task 1: Define executable contracts for parsing and generation

**Files:**
- Create: `scripts/tests/test_generate_fatty_liver_longitudinal.py`
- Test: `scripts/tests/test_generate_fatty_liver_longitudinal.py`

**Interfaces:**
- Consumes: two DOCX paths and `GenerationConfig`.
- Produces: test expectations for `parse_case_documents`, `generate_dataset`, `validate_dataset`, and `write_outputs`.

- [ ] **Step 1: Write failing parser tests**

```python
def test_parse_retains_exactly_150_cases():
    cases = parse_case_documents(DOC_A, DOC_B)
    assert len(cases) == 150
    assert {c.source_case_id for c in cases}.isdisjoint({"A27-1", "A30-1", "A32-1", "A34-1", "A35-1"})
    assert cases[0].patient_id == "P001"
    assert cases[-1].patient_id == "P150"
```

- [ ] **Step 2: Run the parser test and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py::test_parse_retains_exactly_150_cases -v
```

Expected: collection/import failure because the generator module does not exist.

- [ ] **Step 3: Write failing output-contract tests**

```python
def test_generated_dataset_meets_collection_contract():
    patients, visits, report = generate_dataset(parse_case_documents(DOC_A, DOC_B), GenerationConfig())
    validate_dataset(patients, visits)
    assert len(patients) == 150
    assert sum(p["final_stage"] in {"cirrhosis", "hcc"} for p in patients) in range(72, 79)
    assert sum(p["final_stage"] == "cirrhosis" for p in patients) == 50
    assert sum(p["final_stage"] == "hcc" for p in patients) == 25
```

- [ ] **Step 4: Run the complete test file and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -v
```

Expected: FAIL because generator interfaces are missing.

### Task 2: Parse stable case records and source anchors

**Files:**
- Create: `scripts/generate_fatty_liver_longitudinal.py`
- Modify: `scripts/tests/test_generate_fatty_liver_longitudinal.py`

**Interfaces:**
- Produces: `CaseRecord`, `GenerationConfig`, `parse_case_documents(doc_a, doc_b) -> list[CaseRecord]`.
- `CaseRecord` contains stable patient/source identifiers, full case text, extracted age/sex, date anchors, lab anchors, diagnosis text, and cohort classification inputs.

- [ ] **Step 1: Implement DOCX segmentation and fixed exclusions**

Use `病例<number>` paragraphs as segment boundaries, track duplicate-number occurrence order, exclude the five exact source IDs, and assign stable sequential patient IDs.

- [ ] **Step 2: Implement demographic and date extraction**

Extract explicit ages and sex from opening paragraphs. Normalize supported dates to `date` values and preserve all explicit dates for later anchoring.

- [ ] **Step 3: Implement laboratory anchor extraction**

Extract named measurements only when the indicator name and value occur together. Normalize equivalent PLT and AFP units; do not convert prose conclusions into numbers.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -k "parse or extract" -v
```

Expected: all selected parser/extraction tests pass.

### Task 3: Generate deterministic patients and longitudinal visits

**Files:**
- Modify: `scripts/generate_fatty_liver_longitudinal.py`
- Modify: `scripts/tests/test_generate_fatty_liver_longitudinal.py`

**Interfaces:**
- Consumes: `list[CaseRecord]`, `GenerationConfig(seed=20260818)`.
- Produces: `generate_dataset(...) -> tuple[list[dict], list[dict], dict]`.

- [ ] **Step 1: Add failing outcome and timeline tests**

Test exact stage counts, 3–6 strictly ordered visits, minimum 24-month span, final follow-up equality, and event-date ordering.

- [ ] **Step 2: Run targeted tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -k "outcome or timeline" -v
```

Expected: FAIL because generation functions are incomplete.

- [ ] **Step 3: Implement cohort and outcome allocation**

Classify documented fatty-liver cases with common metabolic comorbidities as `fatty_liver_progression`. Reserve `mixed` for explicit competing liver etiologies, acute/genetic/structural dominant narratives, absent fatty-liver evidence, or advanced-stage first presentation without a documented fatty-liver prephase. Persist structured classification reasons outside the two import CSVs. Rank remaining patients with a deterministic evidence/risk score; preserve explicit cirrhosis/HCC evidence and allocate exact final-stage counts of 50/25/75.

- [ ] **Step 4: Implement irregular visit dates and event dates**

Generate 3–6 visits spanning 24–60 months, use explicit dates as feasible anchors, ensure all dates are no later than 2026-08-18, and align cirrhosis/HCC dates with visit nodes.

- [ ] **Step 5: Implement correlated indicator trajectories**

Generate baseline values from documented anchors and clinical context, then apply stable, R1, R2, combined, or non-rule progression paths. Add patient-specific and visit-specific variation while enforcing broad clinical bounds.

- [ ] **Step 6: Implement missingness**

Apply deterministic context-dependent missingness to non-core indicators. Keep at least three values for every core indicator and never use zero as a missing sentinel.

- [ ] **Step 7: Run generation tests and verify GREEN**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -k "outcome or timeline or indicator or missing" -v
```

Expected: all selected tests pass.

### Task 4: Validate and write final artifacts

**Files:**
- Modify: `scripts/generate_fatty_liver_longitudinal.py`
- Create: `data/generated/longitudinal_150/patients.csv`
- Create: `data/generated/longitudinal_150/visits.csv`
- Create: `data/generated/longitudinal_150/DATA_PROVENANCE.md`
- Create: `data/generated/longitudinal_150/quality_report.json`

**Interfaces:**
- Produces: `validate_dataset(patients, visits) -> dict` and `write_outputs(output_dir, ...) -> dict[str, Path]`.

- [ ] **Step 1: Add failing validator and serialization tests**

Test exact schemas, types, allowed values, relationships, UTF-8 without BOM, blank missing cells, no orphan visits, and deterministic CSV bytes.

- [ ] **Step 2: Run serialization tests and verify RED**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -k "validate or csv or reproduc" -v
```

Expected: FAIL because validation/output functions are incomplete.

- [ ] **Step 3: Implement validation and reporting**

Create a quality report containing source counts, exclusions, cohort/stage counts, visit counts, span statistics, missingness, indicator quantiles, R1/R2 path statistics, anchor counts, and validation errors.

- [ ] **Step 4: Implement CSV and provenance writers**

Use `csv.DictWriter(..., lineterminator="\n")` with exact headers and `encoding="utf-8", newline=""`. Record document SHA-256 hashes, seed, mappings, generation rules, aggregate statistics, and usage boundary in the provenance document.

- [ ] **Step 5: Run all generator tests and verify GREEN**

Run:

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Generate final artifacts**

Run:

```powershell
python scripts/generate_fatty_liver_longitudinal.py --doc-a "C:\Users\86182\Desktop\脂肪肝相关病例（1-78例）.docx" --doc-b "C:\Users\86182\Desktop\脂肪肝病例-2026.8.7.docx" --output-dir "data\generated\longitudinal_150"
```

Expected: five final artifacts written and summary reports 150 patients with approximately 50 cirrhosis and 25 HCC cases, without overriding explicit source outcomes.

### Task 5: Independent final verification

**Files:**
- Verify: `scripts/generate_fatty_liver_longitudinal.py`
- Verify: `scripts/tests/test_generate_fatty_liver_longitudinal.py`
- Verify: `data/generated/longitudinal_150/*`

**Interfaces:**
- Consumes all final files; produces fresh evidence for completion.

- [ ] **Step 1: Run the focused test suite**

```powershell
python -m pytest scripts/tests/test_generate_fatty_liver_longitudinal.py -v
```

Expected: zero failures.

- [ ] **Step 2: Run the generator twice into separate temporary directories**

Generate twice with identical inputs and seed, calculate SHA-256 for all five artifacts (`patients.csv`, `visits.csv`, `quality_report.json`, `DATA_PROVENANCE.md`, and `extracted_cases.json`), and require matching hashes.

- [ ] **Step 3: Inspect final CSV structure and statistics**

Confirm 150 patient rows, 450–900 visit rows, exact headers, stage counts 75/50/25, allowed categorical values, visit counts 3–6, minimum span at least 24 months, and core completeness.

- [ ] **Step 4: Run repository diff checks**

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only task files plus pre-existing unrelated changes are reported.

- [ ] **Step 5: Report completion without push**

List generated deliverables, exact verification results, and note that Git commit/push was not performed because repository metadata is not writable in the current permission profile.
