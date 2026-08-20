# 纵向数据集导入 AI 操作者端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把两套已审核的 300 例纵向数据集（脂肪肝 `longitudinal_300`、阿尔茨海默病 `ad_longitudinal_300`）以"每访视一行快照"的方式导入 AI 操作者端 `case_records`，使预测引擎的模式匹配参考基于真实纵向病例，并保留时间/结局/溯源语义。

**Architecture:** 新建独立导入脚本 `scripts/import_longitudinal.py`（可导入模块 + CLI），只读加载数据集 CSV 与 extracted_cases 溯源，构建每访视一条 CaseRecord（metadata 承载 visit_date/结局/人口学/溯源），通过现有 ORM 写入 `case_records`。零 schema 改动、不改预测引擎。支持幂等重跑与同事务 `--reset`。

**Tech Stack:** Python 3.11、SQLAlchemy（复用 `backend/app/db/models.py` 的 `Disease`/`CaseRecord`）、PostgreSQL、标准库 `csv/json/unittest`、现有 `scripts/create_admin.py` 模式。

**Design Spec:** [2026-08-20-longitudinal-import-design.md](../specs/2026-08-20-longitudinal-import-design.md)

---

## Global Constraints

- 采用简化流程，在当前 `main` 工作区实施；不创建分支或 worktree。
- 不提交、不推送、不清理工作区，除非项目所有者另行明确授权。
- **零 schema 改动**：不新增 Alembic 迁移，不修改 `backend/app/db/models.py`、`backend/app/services/prediction_engine.py`、`backend/app/api/operator.py`。
- 不修改任何数据生成器、扩展器及 `data/generated/` 下四项产物。
- 不修改、暂存或删除 `.claude/settings.local.json`。
- `case_records` 写入契约：每访视一行、`patient_label`=patient_id、`indicators` 只含非空指标、`metadata` 必含 `source_dataset`/`visit_date`/`is_synthetic`；有原始文档溯源时含 `source_document`。
- confirmed 语义：脂肪肝 `final_stage ∈ {cirrhosis, hcc}` → true；AD `final_stage`(CDR) ≥ 1 → true；否则 false。
- P151–P300 必须标记 `is_synthetic=true`（依据 DATA_PROVENANCE），不得声称真实病例。
- 幂等：同一 `(source_dataset, patient_label, visit_date)` 不重复插入；`--reset` 与重导必须同一事务，失败可整体回滚。

---

## File Structure

- `scripts/import_longitudinal.py`：导入脚本（模块 + CLI）。
- `scripts/tests/test_import_longitudinal.py`：单元测试（CSV 加载、indicator/metadata 构造、confirmed 判定、幂等、synthetic 标记、事务原子性、溯源）。
- `docs/superpowers/specs/2026-08-20-longitudinal-import-design.md`：已批准设计规格。
- `docs/superpowers/plans/2026-08-20-longitudinal-import.md`：本实施计划。

---

### Task 1: 脚本骨架 + CSV 读取契约

**Files:**
- Create: `scripts/import_longitudinal.py`
- Create: `scripts/tests/test_import_longitudinal.py`

**Interfaces:**
- Consumes: `data/generated/longitudinal_300/`、`data/generated/ad_longitudinal_300/` 的 `patients.csv`/`visits.csv`。
- Produces: `IMPORT_VERSION`、`DATASETS`、`load_patients()`、`load_visits()`。

- [x] **Step 1-4：CSV 读取模块（RED→GREEN）**

`load_patients()`/`load_visits()` 用 `csv.DictReader` 读取；测试验证脂肪肝 300 患者/1354 访视、AD 300 患者/1365 访视行数正确。

---

### Task 2: indicators 与 metadata 构造（纯函数）

**Files:**
- Modify: `scripts/import_longitudinal.py`
- Modify: `scripts/tests/test_import_longitudinal.py`

**Interfaces:**
- Produces: `group_visits_by_patient()`、`build_indicators()`、`build_case_metadata()`、`is_synthetic()`。

- [x] **Step 1-4：分组与构造纯函数（RED→GREEN）**

`build_indicators()` 只保留非空字段并转 float；`build_case_metadata()` 组装 visit_date/visit_index/total_visits/patient_age/sex/cohort_group/final_stage/event_dates/source_dataset/is_synthetic/import_version；`is_synthetic()` 按 patient_id 序号 ≥151 判定（P001–P150 为基线，P151–P300 为分层重组合成）。

---

### Task 3: confirmed 判定 + 幂等写入逻辑

**Files:**
- Modify: `scripts/import_longitudinal.py`
- Modify: `scripts/tests/test_import_longitudinal.py`

**Interfaces:**
- Produces: `should_mark_confirmed()`、`import_dataset()`、`_existing_signatures()`。

- [x] **Step 1-5：confirmed 判定与幂等写入（RED→GREEN）**

`import_dataset()` 取/建 Disease，按 `(source_dataset, patient_label, visit_date)` 签名去重，逐患者按 visit_date 升序生成 CaseRecord。SQLite 内存库验证幂等（重跑 inserted=0）。

---

### Task 4: CLI 主入口

**Files:**
- Modify: `scripts/import_longitudinal.py`

**Interfaces:**
- Produces: `main(argv=None)`。

- [x] **Step 1-3：CLI 实现与验证**

`--dataset fatty_liver|ad|all`、`--reset`、`--db-url`（缺省读 `backend/.env`）。

---

### Task 5: 真实 PostgreSQL 集成验证（首轮）

- [x] **Step 1-6：首轮验证**

单元测试全绿；真实 PG 导入脂肪肝 1354 + AD 1365 = 2719 条；confirmed 分布符合语义；幂等验证；存量后端 127 passed 无回归；预测引擎冒烟通过。

- [x] **Step 7：请求独立只读评审**

评审交接信息已发送 Codex。**评审结果：需要修改后再通过**（2 个 P2 + 2 个 P3，详见 Task 6）。

- [ ] **Step 8：用户审查后再提交**

（待 Task 6 修复通过后再走此步）

---

### Task 6: Codex 评审修复（首轮）

**Codex 评审发现 4 项问题：**

| 级别 | 问题 | 位置 |
|---|---|---|
| P2 | `--reset` 删除与重导不同事务，中途失败旧数据已丢失 | `main()` |
| P2 | 未写入 `extracted_cases.json` 的 `source_document` 溯源字段 | `build_case_metadata()` |
| P3 | `patient_age` 落库为字符串而非规格约定的数值 | `build_case_metadata()` |
| P3 | 交接信息声明的计划文件缺失 | 本文件（当时未创建） |

**Files:**
- Modify: `scripts/import_longitudinal.py`
- Modify: `scripts/tests/test_import_longitudinal.py`
- Create: `docs/superpowers/plans/2026-08-20-longitudinal-import.md`（本文件，本轮补建）

**Interfaces:**
- Produces: `load_source_documents()`、`reset_and_import()`、`_to_int()`。
- Modifies: `build_case_metadata()`（新增 `source_document` 参数、`patient_age` 转 int）、`import_dataset()`（新增 `source_documents` 参数）、`reset_dataset()`（删除后 `flush()`）、`main()`（改用 `reset_and_import()` 同事务提交/回滚）。

- [x] **Step 1: 写失败测试**

新增 9 项测试（另有 1 项 `test_reset_removes_only_that_dataset` 改造为含另一数据集的隔离对照，非新增）。原 13 项 + 新增 9 项 = 22 项：

- `test_reset_and_import_same_transaction_reinserts_correctly`（复现生产 `autoflush=False` 会话，验证 reset 后 import 不会因脏读误跳过重导）
- `test_reset_and_import_rolls_back_together_on_failure`（导入中途失败，`db.rollback()` 后旧数据仍在）
- `test_build_case_metadata_converts_age_to_int` / `test_build_case_metadata_age_missing_is_none`
- `test_build_case_metadata_includes_source_document_when_present` / `test_build_case_metadata_omits_source_document_when_absent`
- `test_load_source_documents_reads_ad_extracted_cases`（验证 AD P001 有溯源、P151 合成病例无）
- `test_load_source_documents_empty_when_field_absent`（验证脂肪肝数据集无该字段返回空字典）
- `test_import_dataset_attaches_source_document_for_real_ad_cases`

- [x] **Step 2: 运行测试验证 RED**

9 errors + 1 failure（缺函数/参数、age 类型断言失败），符合预期。

- [x] **Step 3: 实现修复**

1. **事务原子性**：新增 `reset_and_import(db, dataset, reset=False, ...)`，`reset_dataset()` 内删除后立即 `db.flush()`（避免 `main()` 的 `autoflush=False` 会话中，紧接着的 `_existing_signatures()` 查询脏读到"待删记录"而误判为已存在、跳过重导）。`main()` 改为单个 `with Session()` 块内调用 `reset_and_import()`，只在成功后统一 `commit()`，异常时 `rollback()` 后重新抛出。
2. **溯源字段**：新增 `load_source_documents(dataset_dir)` 读取 `extracted_cases.json`（若存在），仅收录 `source_document` 非空的记录（脂肪肝该文件无此字段则返回空字典，AD 合成病例 P151+ 的 `source_document=None` 不收录）。`import_dataset()` 新增 `source_documents` 参数（缺省自动加载），透传给 `build_case_metadata()`；`source_document` 为空时不写入该 key（保持 metadata 精简）。
3. **年龄类型**：新增 `_to_int()` 安全转换（非法/缺失返回 `None`），`patient_age` 落库为 `int`。
4. 清理文件末尾重复的 `if __name__ == "__main__": pass` 死代码块。

- [x] **Step 4: 运行测试验证 GREEN**

`python -m unittest scripts.tests.test_import_longitudinal -v` → **22 项全部 `ok`**（原 13 项 + 新增 9 项，`test_reset_removes_only_that_dataset` 改造复用不计入新增）。

- [x] **Step 5: 重新导入真实 PostgreSQL（--reset 刷新为修复后数据）**

```powershell
python scripts/import_longitudinal.py --dataset all --reset
```

结果：脂肪肝 removed=1354/inserted=1354，AD removed=1365/inserted=1365，均无残留/无重复。DB 验证：`jsonb_typeof(metadata->'patient_age')` = `number`；AD P001 含 `source_document="AD病例（1-73例）.docx"`；P151、脂肪肝全部记录正确不含 `source_document` 键；confirmed 分布与首轮一致（FL 675:679, AD 1233:132）。

- [x] **Step 6: 存量后端回归 + 语法检查**

```powershell
python -m pytest backend/tests -v
python -m py_compile scripts/import_longitudinal.py scripts/tests/test_import_longitudinal.py
git status --short
```

结果：127 passed 无回归；py_compile 通过；`git status` 仅本任务 4 个文件。

- [x] **Step 7: 二轮评审交接**

修复交接信息已发送 Codex。**二轮评审结果：代码级问题全部通过**（事务边界、flush 时机、失败回滚、source_document 条件写入、年龄数值转换、测试注入隔离均符合预期）；提出 2 项 P3 文档纠正（本文件 `is_synthetic` 边界描述、测试数量算术），已在本次编辑中修正。

- [ ] **Step 8: 用户审查后再提交**

本任务不提交、不推送。若项目所有者随后要求提交，精确暂存本任务文件，提交正文：

```text
AI-Agent: Claude-Code
AI-Client: VS-Code
Task-ID: longitudinal-import-001
```

---

## Plan Self-Review

- 规格 §2–§7 均有对应任务；Task 6 补齐 Codex 首轮评审的 4 项修复，含失败测试先行（RED→GREEN）。
- 零 schema 改动保持不变；预测引擎、operator API、前端均未触碰。
- 类型链：`load_patients`/`load_visits`/`load_source_documents` → `group_visits_by_patient`/`build_indicators`/`build_case_metadata` → `import_dataset`/`reset_dataset` → `reset_and_import` → `main`。
- 事务原子性、溯源字段、类型转换均有明确契约与回归测试覆盖。
- 计划中提交步骤服从"不提交、不推送"约束；本文件为 Codex P3 意见（计划文件缺失）的直接修复。
