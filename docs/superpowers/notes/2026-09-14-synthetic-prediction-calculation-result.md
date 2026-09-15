# 合成四任务离线组样、基线与评分验收记录

日期：2026-09-14。范围：AD/MMSE与脂肪肝ALT各6／12个月，合成工程验证。

**本步已完成：使用已验收的240名虚构患者，跑通四任务输入组样、两种固定基线、患者等权评分、依赖组配对区间及可复算导出。155项相关测试通过，实际结果包复核通过。下一步是合成候选模型与D03历史流程信息的成对比较。**

正式路线仍在阶段二：A2必要事实／定义尚未闭合，A3正式组样未放行，随后还有A4评估契约和A5冻结。原第5节36项保持13满足、15缺条件、8未执行。新增合成数据使工程实现可以继续，不能据此宣称真实任务已冻结或模型通过临床评价。

## 1. 本次交付

实施依据为[本步计划](../plans/2026-09-14-synthetic-prediction-calculation.md)、[阶段二已确认计算规则及最新进度](../plans/2026-09-09-prediction-model-refactor-phase-2-task-evaluation.md#764-合成四任务离线组样基线与评分验收2026-09-14)和[生成器首包结果](2026-09-14-synthetic-prediction-cases-result.md)。本轮新增离线模块及测试，不修改现有报告业务契约。

| 组件 | 实际行为 |
| --- | --- |
| 输入投影与组样 | 预测仅使用自包含输入；未来标签与工程池在组样／评价时连接。锚点固定，资格、缺失、待定和不可用状态分开计数 |
| 固定基线 | 保持当前值；最近可比既往点的历史外推。按日历名义目标的实际天数外推，不读取实际未来测量日期，不裁剪有限输出，无历史时弃权 |
| 评分与不确定性 | 患者等权MAE、RMSE、预测减实测偏差、相同患者的配对MAE改善；挑战池95%区间、2,000次依赖组配对重采样、种子20260910、线性分位数插值。开发池仅作描述 |
| 精度／性能判定 | 误差区间上界不超过门槛；改善下界大于0且允许恰好达到最低改善；两项区间宽度各自检查。缺少必要条件为不可判定，同时保留已知不满足原因 |
| D03准备 | 形成次数／跨度输入；确证零历史为0，未知为null。尚未拟合D03成对模型，也尚未进行训练内标准化 |
| D04描述 | 保存预测—实测配对行、散点、恒等线及偏移／斜率点描述；没有增加预测校正模型、系数区间或个人预测区间 |
| 导出与复核 | 源包先验收，输出只允许全新目录；绑定源包、源码与配置身份。复核器重新计算并比较完整结果，修改分数后重新写哈希也不能绕过检查 |

代码入口为`backend/app/services/prediction_calculation.py`、`prediction_calculation_metrics.py`、`prediction_calculation_export.py`及`scripts/evaluate_synthetic_prediction_cases.py`。使用项目Python 3.11.4及已有依赖；图由工作区自带ReportLab读取保存结果呈现，没有新增项目依赖。

## 2. 实际结果与身份

来源包：[合成病例清单](../../../outputs/synthetic-prediction-cases/2026-09-14-v1/manifest.json)。源run_id为`syn-24928e18054e0ace`，数据内容SHA-256为`c6d6323a3cb997ab5b501edbd17187849c04fa7deb48797f2c200c89c2da03ff`。本轮未改动源包及其生成代码，计算后重新验收仍通过。

结果包：[结果摘要](../../../outputs/synthetic-prediction-calculation/2026-09-14-v1/summary.md)、[结果清单](../../../outputs/synthetic-prediction-calculation/2026-09-14-v1/manifest.json)。计算run_id为`calc-17dd1957ce45e9f0`，数据内容SHA-256为`2939e7fc1a8b62611f1a1cccef41b2a1325e2fae66bcbc6a5ab0d5bf33014547`。

目录内8个文件：`manifest.json`、`features.jsonl`、`samples.jsonl`、`predictions.jsonl`、`paired_rows.jsonl`、`evaluation.json`、`bootstrap_plans.json`、`summary.md`。共480行输入特征、480行组样、960条基线输出记录、608条配对评价记录、16组比较及8份完整重采样计划。输出记录包含有效／弃权／失败状态；608条配对记录跨任务、分支和工程池重复使用患者，不等于608名独立患者。

下表只列挑战池；MMSE为分，ALT为U/L。主分支采用保持当前值；历史分支只在有合格既往测量且目标有效的共同患者上配对。两分支人群不同，不能直接相减两列MAE来计算历史增益。

| 任务 | 主分支合格／配对人数 | 当前值MAE | 历史分支合格／配对人数 | 历史外推MAE | 历史配对MAE改善及95%工程区间 |
| --- | --- | --- | --- | --- | --- |
| AD/MMSE 6个月 | 40／32 | 1.4375 | 33／26 | 3.6509 | −2.1509［−3.2585，−1.2268］ |
| AD/MMSE 12个月 | 40／27 | 2.2222 | 33／20 | 6.3683 | −4.1683［−6.7046，−1.7216］ |
| ALT 6个月 | 40／26 | 15.0385 | 30／19 | 135.5585 | −121.3269［−341.1339，−7.1448］ |
| ALT 12个月 | 40／27 | 17.5074 | 30／21 | 231.7664 | −214.5283［−600.8550，−11.2078］ |

本次合成挑战池中，简单历史外推的误差更大；负改善及极端有限预测值全部保留。这不能证明真实历史信息没有价值，也不能替代后续候选模型／D03对照。D03挑战池可用输入为每个时距AD 22人、脂肪肝26人，其余历史范围未知，未静默编码为零。

8组挑战比较的5项指标区间均完成2,000次重采样且可估计；这只说明本次数值流程完整，不证明临床覆盖率。16项临床门槛均未填入，临床前提未满足，所有临床性能状态均为`not_assessable`。不以CLI退出0或测试通过替代临床`met`。

[预测—实测对照图（SVG）](../../../outputs/synthetic-prediction-calculation/2026-09-14-v1-calibration.svg)及[PNG预览](../../../outputs/synthetic-prediction-calculation/2026-09-14-v1-calibration.png)包含8幅图、198条挑战池配对记录；保留所有有限点、各图相同横纵尺度及恒等线，并标注人群数、偏移和斜率。跨图坐标范围不同。图已实际渲染并检查，保存在结果目录外，不改变8文件验收清单。

## 3. 验证与复现

项目根目录实际运行：

```powershell
.\backend\.venv\Scripts\python.exe scripts/evaluate_synthetic_prediction_cases.py --source-dir outputs/synthetic-prediction-cases/2026-09-14-v1 --output-dir outputs/synthetic-prediction-calculation/2026-09-14-v1
```

退出0，工程状态`passed`。随后单独调用`verify_calculation_export`重新读取来源并复算结果，状态`passed`；原来源的质量与完整性复核也为`passed`。以上输出目录已存在；再次生成时须使用全新目录，不能覆盖验收产物。

在`backend`目录实际运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_prediction_calculation.py tests/test_prediction_calculation_metrics.py tests/test_prediction_calculation_export.py ../scripts/tests/test_evaluate_synthetic_prediction_cases.py tests/test_synthetic_prediction_cases.py tests/test_synthetic_prediction_fixtures.py tests/test_synthetic_prediction_quality.py tests/test_synthetic_prediction_case_export.py ../scripts/tests/test_build_synthetic_prediction_cases.py tests/test_operator_case_validation.py tests/test_operator_visit_context.py tests/test_longitudinal_task_routing.py tests/test_longitudinal_demonstration_data.py -q --tb=short
```

**155 passed in 37.39s，无失败或跳过**；其中本包30项，来源包及相关既有回归125项。覆盖字面数值、日历外推、未来隔离、未知历史、依赖组重采样、等号边界、缺输出／缺分母、统计失败不补抽、篡改复算拒绝、并发拒覆盖及来源保全。

独立审查与回归修复了有限大数的统计溢出、配对改善浮点抵消、历史分支缺基线仍误记完整、输出目录嵌入来源包导致源包损坏四类问题。最终代码审查无未解决问题；图和文档另作交付检查。前端、隔离数据库、worker、浏览器与PDF全链路未执行，不能用本轮纯离线测试替代。

## 4. 下一步与剩余步骤

1. **立即下一步：合成候选模型与D03成对对照。** 先把具体简单候选、超参数及工程训练／评价流程写成实施方案；仅在开发数据拟合及计算标准化参数，在相同患者子集比较获准输入与加入历史次数／跨度的模型，并运行既定评分与失败分析。本轮尚未选模型、拟合或查看候选结果；已查看固定基线结果的挑战池仍只作工程演练，不宣称真实独立评价。
2. **合成应用链路验收。** 按新四任务契约完成最小接入，使用明确隔离的测试环境验证病例输入、权限、预测、持久任务、历史读取和PDF归档。旧任务及旧报告身份继续保留。
3. **真实病例路线完成阶段二。** 真实资料到位后，以独立新数据版本确认A2事实／定义，完成A3主体、锚点、目标、可得性、纳排及泄漏核查；A4落实样本支持、实际分区、临床门槛及完整契约；A5全量标签审核、正式反例和逐任务冻结。可与前两项并行准备，合成结果不替代这些条件。
4. **阶段三正式离线比较。** 在冻结真实版本上重跑基线、候选与历史增量实验，开展独立评价和失败分析，按事先确定的标准决定是否接入。
5. **阶段四接入与阶段五获准发布。** 通过真实评价的任务完成契约／报告及兼容验收，再按获准环境发布、验证回退并持续收集真实结局。工程接入可复用实现，正式准入仍需单独满足。

本轮未训练或发布模型、写业务数据库、调用外部LLM、访问真实患者资料、提交或推送代码。真实病例后续改变的是新版本的数据与证据，不原地替换旧合成来源或历史报告／PDF原件。
