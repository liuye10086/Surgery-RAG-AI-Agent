# P0-07 完整纵向报告模板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为脂肪肝和 AD 生成可阅读、可追溯的完整纵向报告，并保证网页、数据库、历史记录和 PDF 使用同一份持久化正文。

**Architecture:** 保留 P0-06 的 `progression_signals` 作为唯一信号来源。后端生成一次确定性的中文报告并保存 `AIReport.content`；前端、历史详情和 PDF 只读取保存结果。图表只展示满足安全条件的已观察数据，模板不重算业务规则。

**Tech Stack:** Python/FastAPI/Pydantic/SQLAlchemy/pytest；Vue 3/TypeScript/Element Plus；现有 PDF HTML 工具、浏览器和 Poppler 渲染。

## Global Constraints

- 使用实际日期 2026-08-27；不自动 commit 或 push。
- UI 修改前严格遵守 `docs/DESIGN_SPEC.md` 暖杏蓝规范。
- 不修改生产模型、数据库 schema/Alembic migration、旧 progression engine 和旧 `/progression-predictions` API。
- 不调用 LLM 生成事实、信号或临床结论。
- `progression_signals` 是唯一信号判断来源；`model_contribution` 保持 `null`；CDR 只能是阶段相关观察。
- 至少 3 次有效观察才形成信号；使用全部有效观察；不为凑数生成信号。
- 模型、标准、单位或数据不足时说明影响，不猜测、不伪造。
- 历史报告只读生成时保存的正文和输入快照，不随病例修改变化。

## 文件范围与职责

- `backend/app/services/longitudinal_report_generator.py`：完整章节、中文状态转换、观察图表/表格展示模型、正文持久化。
- `backend/app/api/operator.py`：历史详情和 PDF 下载只读取保存正文，维持安全权限和错误。
- `frontend/src/views/OperatorView.vue`、`frontend/src/stores/operator.ts`、`frontend/src/api/operator.ts`：独立报告页、历史状态清理、生成/下载流程。
- `frontend/src/components/LongitudinalPredictionSummary.vue` 或新报告组件：三状态摘要、目录、11 节正文、图表和表格。
- `backend/app/templates/report_pdf.html`、`backend/app/services/pdf_generator.py`：同正文的 PDF 图表、表格和分页。
- `backend/tests/test_longitudinal_report_generator.py`、`backend/tests/test_longitudinal_end_to_end.py`、`backend/tests/test_longitudinal_pdf_contract.py`，必要时新增报告模板/持久化/验收测试。

---

### Task 1: 建立完整中文报告渲染契约

**Files:**
- Modify: `backend/tests/test_longitudinal_report_generator.py`
- Create: `backend/tests/test_longitudinal_report_template_contract.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`

**Interfaces:**
- Consumes: `LongitudinalPredictionResultV2.model_dump(mode="json")`、`sources`、`input_snapshot`。
- Produces: `build_report_view(prediction, sources, input_snapshot)` 与 `render_longitudinal_markdown(prediction, sources=None, input_snapshot=None) -> str`。

- [ ] **Step 1: 写失败测试**

```python
def test_complete_report_has_eleven_sections_and_plain_language():
    content = render_longitudinal_markdown(prediction_v2(), sources(), snapshot())
    for title in (
        "报告摘要", "病例与预测范围", "数据质量与适用性", "已观察到的纵向变化",
        "未来 365 天进展风险", "阶段模型和下一次随访趋势的可用状态", "关键进展信号",
        "参考标准和相似病例", "不确定性与局限性", "人工复核重点", "模型和数据技术附录",
    ):
        assert title in content
    assert "progression_signal" not in content
    assert "likely_rising" not in content
    assert "direction_only" not in content
    assert "数据够用" in content
    assert "模型" in content and "不可用" in content
```

另加脂肪肝、AD、stage 不可用、标准缺失、单位冲突和无信号用例；断言不出现没有解释的“未估计”，也不把 `model_contribution` 渲染为数值。

- [ ] **Step 2: 运行失败测试**

运行：`pytest backend/tests/test_longitudinal_report_template_contract.py -q`。

预期：FAIL，因为当前模板仍是旧章节和调试式文本。

- [ ] **Step 3: 最小实现**

只从结构化 prediction、sources 和 snapshot 读取数据。通过固定字典把内部状态转为中文；实现 11 个固定章节，摘要先回答数据、模型、信号三个问题。禁止在此层重新判断方向、三次规则、单位冲突或信号等级。

- [ ] **Step 4: 运行通过**

运行：`pytest backend/tests/test_longitudinal_report_template_contract.py backend/tests/test_longitudinal_report_generator.py -q`。

预期：新增契约和旧生成测试 PASS。

### Task 2: 增加观察图表、完整指标表格和安全降级

**Files:**
- Modify: `backend/tests/test_longitudinal_report_template_contract.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`

**Interfaces:**
- Consumes: `observation`、`progression_signals` 和 omitted 信息。
- Produces: 每个指标的 `render_mode`（图+表、仅表-观察不足、仅表-单位问题）及中文说明。

- [ ] **Step 1: 写失败测试**

```python
def test_safe_chart_scope_keeps_all_indicators_in_table():
    view = build_report_view(prediction_with_alt_weight_and_unit_conflict(), [], {})
    assert view.observed_series["ALT"].render_mode == "chart_and_table"
    assert view.indicator_table["体重"].render_mode == "table_only_insufficient_observations"
    assert view.indicator_table["甘油三酯"].render_mode == "table_only_unit_problem"
    assert "单位不一致" in render_longitudinal_markdown(...)
```

测试三次以上时使用全部有效观察，不截取最近三次；不满足条件的指标仍进入表格；图表说明明确“不是模型预测”。

- [ ] **Step 2: 运行失败测试**

运行：`pytest backend/tests/test_longitudinal_report_template_contract.py -k chart -q`。

预期：FAIL，因为当前模板没有展示模型。

- [ ] **Step 3: 最小实现**

依据 P0-06 已保存的有效次数和单位状态选择 `render_mode`。若单位缺失、冲突或不受支持，禁止趋势线和范围异常判断；若次数不足，显示完整原始值但不连线。不得在模板层计算新信号。

- [ ] **Step 4: 运行通过**

运行：`pytest backend/tests/test_longitudinal_report_template_contract.py -k "chart or observation" -q`。

预期：PASS。

### Task 3: 固化保存、历史查看和 PDF 读取边界

**Files:**
- Create: `backend/tests/test_longitudinal_report_persistence.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`
- Modify: `backend/app/api/operator.py`
- Modify: `backend/app/services/longitudinal_report_generator.py`

**Interfaces:**
- Consumes: `AIReport.content`、`prediction_result`、`input_snapshot`。
- Produces: 报告完成时一次保存正文；历史详情和 PDF 只读保存正文；历史打开不调用预测。

- [ ] **Step 1: 写失败测试**

```python
def test_history_report_does_not_change_after_case_edit(client, db, completed_report):
    before = client.get(f"/operator/reports/{completed_report.id}").json()["content"]
    edit_case_after_report_creation(db, completed_report.operator_case_id)
    after = client.get(f"/operator/reports/{completed_report.id}").json()["content"]
    assert after == before

def test_history_open_does_not_call_prediction(monkeypatch, client, completed_report):
    monkeypatch.setattr("app.services.longitudinal_prediction.run_longitudinal_prediction", fail_if_called)
    assert client.get(f"/operator/reports/{completed_report.id}").status_code == 200
```

另测非本人报告、无权限 PDF、生成中/失败状态和错误响应不泄露 traceback。

- [ ] **Step 2: 运行失败测试**

运行：`pytest backend/tests/test_longitudinal_report_persistence.py -q`。

预期：FAIL，直到读取路径和前端状态完全分离。

- [ ] **Step 3: 最小实现**

确认详情接口只返回保存的正文/快照；PDF 入口只接受 `report.content`。前端 store 增加 `loadSavedReport(reportId)`，先清理实时预测和生成流，再设置历史正文。

- [ ] **Step 4: 运行通过**

运行：`pytest backend/tests/test_longitudinal_report_persistence.py backend/tests/test_longitudinal_end_to_end.py -q`。

### Task 4: 实现独立报告阅读页

**Files:**
- Modify: `frontend/src/views/OperatorView.vue`
- Modify: `frontend/src/stores/operator.ts`
- Modify: `frontend/src/api/operator.ts`
- Create/Modify: `frontend/src/components/LongitudinalReportView.vue`
- Modify: 现有前端 Node 合约测试

**Interfaces:**
- Consumes: 保存的报告详情、`content`、结构化观察/信号和来源。
- Produces: 独立阅读页，三状态摘要、快速目录、11 节连续正文、图表、完整表格、人工复核和下载入口。

- [ ] **Step 1: 写失败合约**

断言模板包含“报告摘要”“数据够不够”“模型是否可用”“实际看到了哪些信号”“报告目录”及 11 节标题；断言打开历史时清理实时预测对象。

- [ ] **Step 2: 运行失败合约**

先读取 `frontend/package.json` 的实际脚本，再运行对应 `npm run test:contracts` 或仓库已有 Node 命令。预期：FAIL。

- [ ] **Step 3: 最小实现**

严格使用 `docs/DESIGN_SPEC.md` 变量、现有 Element Plus 和图标库。报告页不嵌在编辑区下方；图表只显示安全 `render_mode`，表格显示全部指标及降级原因；历史页不显示上一病例残留预测。

- [ ] **Step 4: 类型检查、构建和浏览器检查**

运行实际 `npm run type-check`、`npm run build` 和 Node 合约；浏览器检查桌面与移动宽度，无溢出、遮挡、错位。

### Task 5: 重构 PDF 并逐页视觉验收

**Files:**
- Modify: `backend/app/templates/report_pdf.html`
- Modify: `backend/app/services/pdf_generator.py`
- Modify: `backend/tests/test_longitudinal_pdf_contract.py`
- Create: `backend/tests/test_longitudinal_pdf_visual_cases.py`

- [ ] **Step 1: 写失败测试**

断言 PDF 含 11 节、中文状态、图表标题、完整表格；摘要、关键信号和人工复核块包含不可拆分页样式；生成函数不重新调用预测。

- [ ] **Step 2: 运行失败测试**

运行：`pytest backend/tests/test_longitudinal_pdf_contract.py backend/tests/test_longitudinal_pdf_visual_cases.py -q`。预期：FAIL。

- [ ] **Step 3: 最小实现**

复用已保存报告视图生成图表、表格和章节；使用 `break-inside: avoid`、重复表头和页码；不在 PDF 层生成第二份事实文本。

- [ ] **Step 4: 运行契约与视觉检查**

运行 PDF 契约测试；按 PDF skill 生成脂肪肝和 AD 匿名样例，逐页渲染 PNG 检查中文、分页、表格、页脚和空白。保存不含身份和本机路径的证据。

### Task 6: 双疾病端到端验收

**Files:**
- Create: `backend/tests/test_longitudinal_report_acceptance.py`
- Modify: `backend/tests/test_longitudinal_end_to_end.py`

- [ ] **Step 1: 写失败验收测试**

覆盖脂肪肝三访视、AD 三访视、outcome 可用/stage 不可用、标准缺失、单位问题、模型异常、生成中断、保存、历史、PDF 权限、病例修改后历史不变、页面/数据库/历史/PDF 内容一致、CDR 阶段相关观察、`model_contribution is None` 和不凑信号。

- [ ] **Step 2: 运行失败验收测试**

运行：`pytest backend/tests/test_longitudinal_report_acceptance.py -q`。预期：FAIL。

- [ ] **Step 3: 最小修复并运行通过**

只修复测试明确指出的报告、持久化、前端或 PDF 问题；运行：`pytest backend/tests/test_longitudinal_report_acceptance.py backend/tests/test_longitudinal_end_to_end.py -q`。

### Task 7: 全量验证和路线图更新

**Files:**
- Modify: `docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md`
- Create: 匿名验收证据索引

- [ ] **Step 1: 运行专项后端测试**

运行报告生成、模板、持久化、端到端、PDF 和验收测试，记录实际通过数量。

- [ ] **Step 2: 运行前端、Node、旧 API 和 P0-06 回归**

运行仓库实际存在的类型检查、构建、Node 合约、存量纵向报告接口、P0-06 和旧 progression API 测试。

- [ ] **Step 3: 运行全量 pytest**

若 `.superpowers/sdd` 仍失败，记录真实失败数量和原因，不声称全量通过。

- [ ] **Step 4: 运行保护检查**

运行 `git diff --check`，确认 diff 未触及生产模型、schema/migration 或旧 progression 文件。

- [ ] **Step 5: 更新路线图和交付说明**

填写 P0-07 实际状态、测试数量、匿名样例和 PDF 证据路径、已知失败以及“新生产模型未上线”的说明；最终用通俗中文交付，不自动 commit/push。

## 实施顺序

按 Task 1 → 2 → 3 → 4 → 5 → 6 → 7 执行。每个 Task 都必须先写失败测试、运行确认失败，再写最小实现并运行通过；在后端持久化、前端页面和 PDF 视觉检查点分别停下来确认结果。
