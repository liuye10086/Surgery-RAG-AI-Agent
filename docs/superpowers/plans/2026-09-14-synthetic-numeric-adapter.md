# 合成数值报告A包实施计划

> **For agentic workers:** 按本计划在当前会话顺序执行；输入契约与适配强关联，不拆成并行实现。使用 test-driven-development；交付前使用 requesting-code-review。

**Goal:** 将已确认的合成四任务设计落实为可独立测试的严格输入／结果契约及末次值保持适配。

**Architecture:** 新模块包装现有 `PredictionInput`、`project_calculation_inputs` 和 `predict_baselines`，保留离线实现。一次输入只有一个病种、一个主体／锚点及两个时距；新结果携带来源、输入摘要与算法身份。来源验证只涵盖结构与关联，服务端数据库绑定属于B包。

**Tech Stack:** Python 3.11.4，项目 `backend/.venv`、Pydantic、pytest，既有数值依赖。

## Global Constraints

- 范围仅A包，不改API、业务DB、模型活动指针、worker、前端或PDF。
- 四任务和6／12日历月固定，MMSE为分、ALT为U/L；不补值、换单位、生成概率或区间。
- 来源明确合成，缺失run ID拒绝；不把结构校验或自报SHA256视为可信来源认证。
- 保留所有既有未提交文件；不训练、下载、调用外部LLM、提交或推送。
- 原阶段二第5节36项原文及13／23勾选不变。

## Task A：严格契约、计算适配和回归

**Files:**
- 新建 `backend/app/schemas/synthetic_numeric_prediction.py`：来源、输入包、双时距输入、算法身份、任务结果和整体结果。
- 新建 `backend/app/services/synthetic_numeric_prediction.py`：输入规范化摘要、固定本地实现身份、计算、结果与输入绑定校验。
- 新建 `backend/tests/test_synthetic_numeric_prediction.py`：字面输入、四任务、日历、关联负例、状态与算法身份、旧模块复用。
- 更新README／总领／阶段二进度，增加本轮结果记录；不改既有计算代码。

**Interfaces:**
- `SyntheticNumericInput.model_validate(raw)`：验证单主体、同锚点、所属病种恰好6／12月两个包；单位／指标／日期／来源／缺失状态一致。
- `SyntheticNumericPrediction.model_validate(raw)`：验证两个结果的日期、单位、状态、有限值及来源。
- `numeric_input_sha256(raw)`：规范化后SHA256，包及观察列表输入顺序不影响摘要。
- `numeric_algorithm_identity()`：返回 `last_value` 固定版本、实现文件摘要、参数摘要、输入契约版本及禁止临床有效性／生产用途声明。
- `predict_synthetic_numeric(raw, *, expected_algorithm=None)`：返回结构化双时距结果；有固定算法期望时检查与本地实现相同，不接受任意模型选项。
- `validate_numeric_prediction(result, raw_input, expected_algorithm)`：检查保存／发布前的输入摘要、主体／病种／锚点／来源／算法和实际基线值或拒绝原因。

- [x] 1. 写测试并运行RED。使用独立字面2023-08-31锚点，MMSE22／ALT47.5，期望目标2024-02-29与2024-08-31，两时距数值不变。

```python
def test_calendar_and_constant_values():
    result = service().predict_synthetic_numeric(literal_input())
    assert [(r.horizon_months, r.target_date.isoformat(), r.value)
            for r in result.predictions] == [(6, '2024-02-29', 22.0), (12, '2024-08-31', 22.0)]
```

还需测试错任务／病种／时距／主体／依赖组／来源、双包不一致、日期穿越、错单位／方法、重复任务／观察、缺锚点、空原因、无历史与未知历史、非有限／布尔数值、错误输出与算法不匹配。新增功能不存在时测试在函数内导入并实际失败，不使用skip。

- [x] 2. 实现严格契约。继承离线输入类型并只收紧应用边界；两个包去除sample/task/horizon后应相同。保持未来输入拒绝和原因，不把正常不可用状态变成计算失败。
- [x] 3. 实现适配。先验证并规范化输入，再调用既有投影／基线函数，只导出 `last_value`；对结构损坏及计算异常明确报错。输入不可用时保留具体input_reason，输出null。
- [x] 4. 运行新测试，修复实现后运行新旧关联回归；增加独立审阅发现问题的回归用例。

```powershell
# 在backend目录
.\.venv\Scripts\python.exe -m pytest tests/test_synthetic_numeric_prediction.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_synthetic_numeric_prediction.py tests/test_prediction_calculation.py tests/test_prediction_calculation_export.py tests/test_prediction_calculation_metrics.py tests/test_synthetic_prediction_cases.py tests/test_synthetic_prediction_fixtures.py tests/test_synthetic_prediction_quality.py -q
```

- [x] 5. 检查实际冻结合成输入包逐主体适配及已有文件保全；只读旧输入，不读取未来结果。更新本轮结果、索引、下一步与剩余步骤，执行 `git diff --check`。本包不进行DB或应用端到端验收，不自动提交。

**下一步：**B包来源绑定、隔离迁移／种子、权限与接单。后续C包worker／保存／历史、D包页面／PDF、E包隔离总验收；真实临床路线仍独立推进。

执行结果：本轮完成上述五步，最终171项相关测试通过；新增模块82项测试，冻结包240主体／480条数值对照通过。见[结果记录](../notes/2026-09-14-synthetic-numeric-adapter-result.md)。未提交或推送。
