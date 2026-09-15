# Synthetic Prediction Stability Implementation Plan

> **For agentic workers:** Use subagent-driven-development for the bounded split/evaluation core and requesting-code-review for final verification. 用户已要求连续执行本实验。保留当前功能分支及所有未提交工作，不提交或推送。

**Goal:** 完成已固定的3种子、3嵌套训练规模实验，判断误差和波动如何随训练支持变化。

**Architecture:** 新增独立分组／评价核心和CLI实验制品层，复用全部已有训练、组样和指标模块，不修改旧源码。

**Tech Stack:** 既有Python3.11.4、NumPy2.3.5、scikit-learn1.9.0。

## Global Constraints

严格执行[实验设计](../specs/2026-09-14-synthetic-prediction-stability-design.md)。种子20260914/15/16；每病种最大1200、挑战400，开发组20%固定验证；训练64/320/640组。三角色分开。无调参或临床有效性声明。

## Task 1：分组、角色评分和跨种子汇总

新增`backend/app/services/prediction_stability.py`及`backend/tests/test_prediction_stability.py`。

接口：`build_partitions(samples, seed, *, train_group_sizes=(64,320,640), validation_fraction=.2)`返回`validation_groups, challenge_groups, training_groups`（后者以组预算字符串为键的组ID列表），均跨疾病合并但逐疾病选定。`evaluate_role(samples,predictions,baselines,role)`返回旧评分结构，仅32个非空目标角色比较，明确source_pool/evaluation_role，配对ID一致；role限training/internal_validation/challenge。`aggregate_runs(runs)`按role/task/family/branch/kind及scale汇总3种子指标，不混患者，缺指标显式有效数。

- [x] 测试先红：分组互斥、训练嵌套、目标与行顺序扰动、共享组跟随、同分按ID；身份错误、预算不足、角色分母、D03参考、缺种子。
- [x] 实施核心并运行`backend/.venv/Scripts/python.exe -m pytest backend/tests/test_prediction_stability.py -q`。独立审查接口。

```python
assert set(parts['training_groups']['2']) < set(parts['training_groups']['4'])
assert not set(parts['validation_groups']) & set(parts['training_groups']['4'])
assert scored['evaluation']['comparisons'][0]['evaluation_role'] == 'internal_validation'
```

## Task 2：实验CLI、制品与重算

新增`scripts/run_synthetic_prediction_stability.py`及`scripts/tests/test_run_synthetic_prediction_stability.py`。

- [x] 先红测试协议冻结、目录拒覆盖、哈希篡改、首次失败保留、CLI错误码；实际小型虚构单元核对成功和失败行为。
- [x] `run_experiment(output_dir)`固定协议，不开放调参；`verify_experiment(output_dir)`核对协议／运行时／源码和重新生成数值，成功模型重新拟合，失败不重试。逐文件独占写入、异常保留不完整包；CLI支持`--output-dir`或`--verify-dir`，互斥必选；0完整、2参数／已有目录、3验证失败／工程不完整、4运行异常。
- [x] 实际新目录运行9单元、216模型，随后独立新进程复核。记录所有失败，禁止省略单元或调低验收。

```python
assert run_experiment(destination)['status'] == 'passed'
assert verify_experiment(destination)['status'] == 'passed'
with pytest.raises(FileExistsError): run_experiment(destination)
```

## Task 3：结果、图表与交付

- [x] 根据已保存比较生成规模曲线及3种子范围，实际训练人数另表，读取渲染结果检查。
- [x] 运行新增测试和训练／评价相关回归，独立最终审查，核对旧源码／输出哈希保全。
- [x] 更新README、总领、阶段二§7.67及新验收记录；保持原36项逐字不变。完成后列明下一步和剩余步骤。

## 执行记录

2026-09-14：协议先于本轮拟合落盘，全部任务完成并审查。实际9单元、216模型、194688候选及64896基线预测、864比较；新进程完整重生成、重拟合和重算通过。run_id=`stab-32e4433498f772da`，59项相关测试通过（212.48秒）。审查发现的完整基线归档缺口已先红后绿修复并复查关闭；结果表述限定本轮规模及固定验证／挑战集合。16面板图已渲染检查，分析与数值核对通过；旧718文件、96输出及原36项验收保持，只更新3份计划／索引文档。未提交或推送。详见[验收记录](../notes/2026-09-14-synthetic-prediction-stability-result.md)。
