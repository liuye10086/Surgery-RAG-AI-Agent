# 合成四任务离线组样、基线与评分实施计划

> Use subagent-driven-development for the independent numerical component and requesting-code-review for the completed package. 用户已要求执行上一包列明的下一步，本轮连续实施并交付，不再重复确认已选计算规则。

**Goal:** 消费已验收合成包，实际跑通AD/MMSE与ALT各6／12个月的输入组样、保持当前值／历史外推基线、患者等权评分和依赖组配对区间。

**Architecture:** 输入投影与预测函数只读自包含prediction_inputs，标签和pool只在组样／评分层连接；数值统计模块接收显式配对患者行。文件入口先复核来源包，按既有池分别报告，挑战池做工程独立评价演练，结果导出全新目录。

**Tech Stack:** 项目Python3.11.4、已有NumPy2.3.5与Pydantic，不新增依赖。绘图作为独立结果呈现，可用工作区自带绘图运行时读取已经计算的结果。

## 授权、阶段及具体设计

- 原正式路线仍在阶段二A3前；本包为合成工程分支，不把模拟量记入原第5节36项。原始临床C03四任务各4个数值、正式容差均保持待定。
- 依据总领§1.4、阶段二§7.45～7.50、§7.56和§7.63、生成器设计与上一包验收记录。用户现已明确要求继续“下一步”；本轮落实这些已确认算法，未选择新模型族、临床阈值、正式分区或嵌套方案。
- 从核验通过的`outputs/synthetic-prediction-cases/2026-09-14-v1`开始。该包240患者、480输入、66固定实例；禁止覆盖或改变源包、原有应用、现行生成器及其源码身份。
- 每患者固定同一主锚点；主分支用a，历史分支用最近严格较早且可比／已知的x。工程日期统一用真实日历差：`h=add_calendar_months(anchor,horizon)-anchor`、`d=anchor-prior_date`，`a+(a-x)*h/d`。这是本包明确日历日期的工程适配，既不月乘30，也不使用实际未来目标偏移；不批准真实来源的日月换算或窗口。
- 历史未知者的D03次数／跨度仍为null；确证零历史为0／0；D02有一条合格既往点且d>0才能预测。D03成对模型的输入表本轮形成，实际学习模型和训练内标准化由后续候选比较包实施，本轮不以基线替代D03模型比较。
- 输出有限原值，不裁剪；无历史为abstain，非有限输出／计算异常为error，不默默回退。输入资格先定，不根据未来缺失移动锚点。合成名义日目标才用于数值评分，偏移／发生性未知为pending，确证未测为absent。
- 患者等权，分病种／时距／pool／分支描述，不汇总跨病种或用不同子集差值证明历史增益。所有配对改善相对保持当前值基线。每患者及依赖组分别计数，状态与分母闭合，零分母比例null。
- 用显式`Generator(PCG64(20260910))`、ASCII组ID排序，每次`integers(0,G,size=G,dtype=int64)`，共2000次。每个任务／分支从独立的同种子实例开始，映射及完整抽样计划保存；共同组重数作用于患者，不对候选／基线分别抽样。仅挑战池计算工程CI；开发池只描述，不冒充独立评价。
- 所有统计按e=p-y；MAE、RMSE、偏差和配对MAE增益；校准点描述y=alpha+beta*p，预测恒定时两系数null。CI 95%、线性分位数。少于2组或任一抽样相应统计不可估计，则相应CI不可估计，保留尝试／有效／失败原因，无补抽。
- 性能判定：任何必要前提／门槛／区间缺失为not_assessable；完整输出失败仍记录；已知不满足单列。全部可判定后，U_M<=max_mae、L_gain>0且>=min_mae_gain、两项CI宽度分别<=上限，全部满足met否则not_met。实际合成运行clinical_validity_claim=false且clinical_prerequisites=false，16门槛null。
- 不拟合／发布模型、写数据库、调用外部LLM、变更前端或重算历史报告。不自动重试整包；本CLI只做本地确定性计算，失败安全退出并保留源文件。原R04基础设施允许一次重试不作为数据或统计失败的补抽规则。
- 当前功能分支就地增量，保留既有未提交文件；本轮不提交或推送。

## 任务1：数值评分与区间

文件：新增`backend/app/services/prediction_calculation_metrics.py`、`backend/tests/test_prediction_calculation_metrics.py`。

接口：`paired_statistics(rows, weights=None)->dict`；rows为`{subject_id, dependency_group_id, actual, prediction, baseline}`，每主体唯一。返回mae、rmse、bias、baseline_mae、mae_gain、alpha、beta、n_patients、n_groups及不可估计原因。`paired_bootstrap(rows, *, seed=20260910, iterations=2000, draw_indices=None)->dict`返回CI对象、完整indices、ordered_groups、attempted/valid/failed；允许给定索引用于字面回归，正式CLI固定2000。`performance_decision(summary, intervals, thresholds, *, prerequisites, complete_output)->dict`返回三态、missing与known_failures。

- [x] 测试先行：不等组大小仍患者等权、配对改善、alpha/beta恒定预测不可估计、组重复抽中、输入倒序不改计划、非有限统计失败不能补抽、缺门槛并保留已知失败、D05/06/07等号边界。

```python
rows = [{'subject_id': 'a', 'dependency_group_id': 'g1', 'actual': 0., 'prediction': 10., 'baseline': 12.},
        *[{'subject_id': str(i), 'dependency_group_id': 'g2', 'actual': 0., 'prediction': 1., 'baseline': 2.} for i in range(4)]]
assert paired_statistics(rows)['mae'] == 2.8
assert paired_statistics(rows)['mae_gain'] == 1.2
assert paired_bootstrap(rows, iterations=2, draw_indices=[[0,0],[1,1]])['attempted'] == 2
```

- [x] 实施并运行对应pytest；独立核对统计公式和失败路径。CI不能把组当成患者等权，也不能在一组样本上假称可靠区间。

## 任务2：输入投影、固定基线及组样分母

文件：新增`backend/app/services/prediction_calculation.py`、`backend/tests/test_prediction_calculation.py`。

接口：`project_calculation_inputs(packets)->list[dict]`；`predict_baselines(features)->list[dict]`；`build_engineering_samples(patients, packets, outcomes, audit)->list[dict]`；`evaluate_baselines(samples,predictions)->dict`。

features字段为sample_id、subject_id、dependency_group_id、task_id、horizon_months、anchor_date、horizon_days、anchor_value、history_state、n_pre、span_pre_days、trend_prior_value、trend_interval_days、input_status、input_reason、source；无pool、目标或潜在机制。predictions字段为sample_id、model_id(last_value/history_trend)、status(valid/abstain/error)、value、reason。samples保留features的控制身份并加pool、anchor_status(eligible/ineligible/pending)、label_status(valid/absent/pending/not_applicable)、label_reason、actual_date、actual及nominal_date。

- [x] 写字面回归：2023-07-31值24／锚点2024-01-31值22；6月h=182、d=184；删除未来后预测恒等。S02/S03、S10、S11、S17、S18与S20保持各自语义。

```python
assert trend_value == 22 + (22-24)*182/184
assert zero_features['n_pre'] == zero_features['span_pre_days'] == 0
assert unknown_features['n_pre'] is None
assert len(predict_baselines(project_calculation_inputs(packets))) == 2*len(packets)
```

- [x] 实施安全的预测输入投影，按实际输入计算基线。组样校验全量一对一关联、任务、锚点、subject/group/pool和来源；排除和pending不互换。缺预测记录计error，四种联合状态闭合；输出完整任务标记与共同可评分子集描述分开。
- [x] 每个pool／任务保存主、历史和D03资格分母；主分支描述last_value，历史子集配对history_trend与last_value。保存配对行用于复算、CI和校准散点，清楚标记未执行D03模型比较。

## 任务3：文件入口、实际运行与文档交付

文件：新增`backend/app/services/prediction_calculation_export.py`、`scripts/evaluate_synthetic_prediction_cases.py`及对应测试；不修改上一包文件。

接口：`evaluate_synthetic_package(source_dir: Path, output_dir: Path)->dict`；`verify_calculation_export(output_dir: Path)->dict`。先调用既有source验证器，status与integrity均passed才能消费；JSON行严格读取。只输出全新目录，用同父独占临时目录和Windows原子拒覆盖改名；清理时核对仅限本次目录。

- [x] 先测损坏／缺支持来源拒绝、输出不覆盖、实际CLI生成、两次结果一致、修改目标不能改features/predictions、错误信息不泄漏路径、源包哈希保全。
- [x] 导出manifest.json、features.jsonl、samples.jsonl、predictions.jsonl、paired_rows.jsonl、evaluation.json、bootstrap_plans.json、summary.md；图作为外部呈现制品独立保存，数值产物不依赖绘图环境。manifest绑定源码哈希、源包run/hash、固定算法参数及内容哈希。保存无临床通过声明的实际分母、统计、CI和三态结果。
- [x] CLI只接受`--source-dir`、`--output-dir`；0表示工程计算完整并验证通过（不代表临床met），2参数／既有目录错误，3来源或输出验收不合格，4运行/IO错误。输出只含代码／数量／哈希，不打印异常堆栈。
- [x] 运行新测试及受影响既有测试；独立审查后实际生成`outputs/synthetic-prediction-calculation/2026-09-14-v1`并验证，制作可读结果记录。
- [x] 更新用户指定两文档、README及结果记录，说明临床阶段二A3未放行；本轮工程组样／基线／评分完成。剩余：候选模型与D03成对比较（训练内标准化等）、最小应用及隔离E2E、真实A3/A4/A5与阶段三独立评价、阶段四集成及阶段五发布。具体最终阶段名以总领表为准。


## 本次完成记录

2026-09-14：上述任务已实施并完成独立代码审查。最终相关回归155项通过（37.39秒），其中本包30项；实际CLI退出0，结果独立复算及来源包复核通过。run_id为`calc-17dd1957ce45e9f0`；8幅预测—实测图已渲染检查。总领更新为v0.63，阶段二计划更新为v0.59／第7.64节，原第5节36项逐字保留。详细数值、命令、限制及剩余步骤见[验收记录](../notes/2026-09-14-synthetic-prediction-calculation-result.md)。

下一步为合成候选模型及D03成对比较；本包没有训练模型、执行应用全链路或放行真实阶段二。
