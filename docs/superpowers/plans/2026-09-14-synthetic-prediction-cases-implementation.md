# 合成预测病例首包实施计划

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 按已批准设计交付可运行、可复现、带20类固定场景和质量门禁的离线合成病例生成器。

**Architecture:** 独立schema与患者生成核心构造明确合成的观察，再投影锚点可用输入并分离未来目标。固定场景、质量诊断、目录导出各自负责一件事，不调用业务数据库或旧事件builder。

**Tech Stack:** Python 3.11.4、现有Pydantic／NumPy、pytest；不新增依赖。

## Global Constraints

- 依据 `docs/superpowers/specs/2026-09-14-synthetic-prediction-cases-design.md` v0.1；用户2026-09-14“开始下一步”确认进入实现。
- 仅文件生成；不训练、发布、写数据库、调用外部LLM或改前端。旧数据、模型和报告保留。
- 固定seed 20260914；每病种120人，其中40人为challenge_pool；工程池不等于正式分区。
- 保留临床容差及16个C03门槛为null，不以模拟指标批准临床用途。
- 不覆盖用户未提交修改；当前 `codex/prediction-phase-2-evaluation` 功能分支就地增量工作。新增文件独立，未授权提交／推送不执行。
- 本轮连续完成首包，不在计划写完后再次询问是否继续。需要实质范围修改时先说明证据。

## 任务1：schema、独立生成与信息投影

文件：新增 `backend/app/schemas/synthetic_prediction_cases.py`、`backend/app/services/synthetic_prediction_cases.py`、`backend/tests/test_synthetic_prediction_cases.py`。

接口：`GenerationConfig(seed=20260914, patients_per_disease=120, challenge_per_disease=40)`；`generate_cohort(config) -> dict`，集合键为patients、observations、prediction_inputs、followup_outcomes、generation_audit，集合元素为规范JSON字典。`build_prediction_inputs(patients, observations) -> list[dict]`为可单独检验的时间投影；`build_followup_outcomes(patients, observations) -> list[dict]`只负责工程状态。`canonical_json(value) -> str`及`add_calendar_months(date, int) -> date`供本包复用。

患者字段：subject_id、dependency_group_id、disease、age、sex、baseline_stage、diagnosis_status、anchor_date、diagnosis_known_on、history_coverage、source。source固定is_synthetic/source_kind/generator_version；run_id由导出层补充。观察字段：observation_id、subject_id、indicator、measured_on、known_on、value、unit、method、observation_kind、role、horizon_months、observation_status、source。role为history/anchor/followup；后两类horizon规则分别为null和6/12。input_observations只复制历史／锚点可得投影，不保留role、horizon、未来状态。包保留subject_id、dependency_group_id、task_id、horizon_months、anchor_date、anchor_observation_id、input_observations、history_coverage。目标包保留sample_id、subject_id、horizon_months、nominal_date、observation_id、actual_date、value、status。

- [x] 先写复现、换seed、扩量前缀稳定、月末闰日和未来变换不影响输入的测试，并运行见到缺功能失败。

```python
assert add_calendar_months(date(2023, 8, 31), 6) == date(2024, 2, 29)
assert generate_cohort(config) == generate_cohort(config)
assert build_prediction_inputs(patients, changed_future) == original_inputs
```

- [x] 实施设计中的PCG64分组件种子、轨迹公式、日期／缺失机制及严格schema。生成主体不含任何真实患者源信息。记录历史未知与确定零历史的区别。
- [x] 运行 `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_synthetic_prediction_cases.py -q`；断言集合关联、时间边界、来源和同锚点双时距的实际值。
- [x] 对任务1代码进行规格及质量审查并修正问题。

## 任务2：固定场景与字面预期

文件：新增 `backend/app/services/synthetic_prediction_fixtures.py`、`backend/tests/test_synthetic_prediction_fixtures.py`，必要时静态fixture文件位于 `backend/tests/fixtures/synthetic_prediction/`。

接口：`build_fixed_fixtures() -> tuple[list[dict], list[dict]]` 返回fixtures和expected_results。每例包含fixture_id、scenario_id、disease、variant、patients、observations及api_request（可为null）。api_request不含固定disease_id，由消费者绑定。预期字典按fixture_id关联，含current_api（accept/reject/not_run及具体原因）、offline（显式target状态／变换不变量）、expected_counts或expected_values。各例必须提供实际可运行负例或变体，不能只返回20个名字。

- [x] 先测S01字面基线误差1/3及5/10、S02与S03区别、S12未来变体输入恒等、S18两个患者一组与同源副本；运行确认缺功能失败。
- [x] 实施S01～S20与每病种的实际数据；补齐空值、非有限、非法单位、重复日、月底、比较方法和病因／阶段反例。期望不调用生成轨迹函数获得。
- [x] 使用真实 `OperatorCaseCreate`、`normalize_operator_timeline`、`validate_operator_case_profile`核对适用的API接受／拒绝路径；只模拟本机disease_id绑定，不连接数据库。

```python
assert {f['scenario_id'] for f in fixtures} == {f'S{i:02d}' for i in range(1, 21)}
assert len({f['disease'] for f in fixtures}) == 2
assert len({p['subject_id'] for p in related}) == 2
assert len({p['dependency_group_id'] for p in related}) == 1
```

- [x] 运行对应pytest并独立审查；控制台只输出汇总结果。

## 任务3：质量检查、导出和CLI

文件：新增 `backend/app/services/synthetic_prediction_quality.py`、`backend/app/services/synthetic_prediction_case_export.py`、`scripts/build_synthetic_prediction_cases.py`及对应backend／scripts测试。

接口：`assess_cohort(cohort: dict) -> dict`检查schema/关联、输入时间边界、依赖跨池、轨迹重复及按阶段／复查次数查表捷径；`assess_generation(config, cohort) -> dict`额外核验复现、不同seed和扩量。质量条目含status（passed/failed/not_assessable）、分母、计数和原因；总status由所有必需条目决定。

`export_synthetic_cases(config, output_dir: Path) -> dict`组装9个设计文件，只接受新目录，内容哈希排除运行时间。`verify_synthetic_case_export(output_dir: Path) -> dict`校验文件长度/哈希、关联和质量状态，不仅信任manifest中的passed。CLI `main(argv=None) -> int`只接受已批准的4个参数，0/2/3/4退出码与设计一致。

- [x] 先写旧模板应暴露重复／捷径、被篡改未来输入应失败、跨池同组应失败、目录不覆盖、损坏文件应被发现、CLI小规模缺支持非成功等测试，并运行确认失败。
- [x] 实现质量条目。旧模板的历史问题作为对照证据；不为默认队列失败更换seed、删样本或降低门禁。缺支持与失败分开，所有诊断保留。
- [x] 实现独占临时目录、原子改名、失败清理和安全错误输出；清理目标解析后必须在本次创建的临时目录边界内，不能删除既有输出。

```python
with pytest.raises(FileExistsError):
    export_synthetic_cases(config, existing_dir)
assert existing_file.read_bytes() == before
assert verify_synthetic_case_export(tampered_dir)['status'] == 'failed'
```

- [x] 运行新包完整pytest，再在 `outputs/synthetic-prediction-cases/` 下生成本次全新包；读取实际quality_report与验证器结果，记录未通过项而不假称成功。
- [x] 进行整包代码审查，复核输入／目标隔离、来源、错误处理及只读验证器，完成必要修复与针对性回归。

## 交付检查

- [x] 默认240名虚构患者、480个双时距输入包；真实数量以最终导出为准，固定场景单独计数。
- [x] 记录新测试数量及实际CLI退出码、质量结果、制品SHA，不把合成指标当临床证据。
- [x] 更新设计状态、总领文档／阶段二最新记录及README导航；原第5节36项和旧评估文档保持原样。
- [x] 最终说明首包已完成内容，以及新四任务评分器、应用全链路、真实数据接入的剩余顺序。

## 本轮完成记录

全部首包步骤完成。新包77项与相关已有48项合计125项通过；独立审查复跑77项通过。持久生成退出0，文件完整性和工程质量复核通过；详见[验收记录](../notes/2026-09-14-synthetic-prediction-cases-result.md)。源码未提交／推送，真实病例、模型训练及系统全链路属于后续范围。
