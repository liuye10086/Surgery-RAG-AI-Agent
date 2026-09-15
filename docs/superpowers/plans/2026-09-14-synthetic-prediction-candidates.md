# 合成候选训练与D03成对比较实施计划

> **For agentic workers:** Use subagent-driven-development for the bounded training component and requesting-code-review for task and final reviews. 用户已确认设计并要求开始实施，连续完成本包，不再次请求模型方案确认。

**Goal:** 在已验收合成包上完成固定Ridge／随机森林训练、D03成对比较、可复算导出，并回答现有合成规模的适用边界。

**Architecture:** 训练层仅接收开发数据白名单矩阵；预测仅接收特征和固定模型；评价层连接目标和工程池。独立导出层验证两来源、输出新目录、保存模型和重新拟合复算结果。

**Tech Stack:** Python3.11.4、NumPy2.3.5、scikit-learn1.9.0、joblib1.5.3，项目已有依赖。

## Global Constraints

- 设计依据：[已确认设计](../specs/2026-09-14-synthetic-prediction-candidates-design.md)，用户本轮明确“ok，开始下一步”。不改变既有临床规则或活动模型。
- 继续现有`codex/prediction-phase-2-evaluation`功能分支的未提交实施包，就地增量，不提交／推送／移动或覆盖已有工作。
- 仅合成离线拟合与工程验证，无业务数据库／外部LLM／模型下载／前端修改。
- 不修改上一包生成／计算源码及结果身份。来源目录分别为`outputs/synthetic-prediction-cases/2026-09-14-v1`与`outputs/synthetic-prediction-calculation/2026-09-14-v1`。
- 四任务独立拟合；现有80／40工程池不重划。Ridge alpha1、svd；RF200棵、depth4、leaf3、seed20260914、n_jobs1，其他配置按设计固定。
- 标准化限对应开发子集、ddof0、零标准差scale1；D03两侧完全相同训练子集。原单位、不插补／裁剪／校正／调参。
- 临床前提false、16门槛null、临床状态不可判定。区间95%、2000次依赖组同抽配对、PCG64种子20260910、线性分位数、失败不补抽。

## Task 1：训练、标准化与预测

文件：新增`backend/app/services/prediction_candidate_training.py`及`backend/tests/test_prediction_candidate_training.py`。

接口固定：

```python
FAMILIES = ('ridge', 'random_forest')
BRANCH_FEATURES = {'main_anchor': ('anchor_value',),
                  'd03_anchor': ('anchor_value',),
                  'd03_augmented': ('anchor_value', 'n_pre', 'span_pre_days')}
def candidate_model_id(family, branch): return family + ':' + branch
def fit_candidate_models(features, samples, *, recorded_fit_errors=()): ...  # {'models': JSON records, 'estimators': {task_id+':'+model_id: estimator}}
def predict_candidate_models(features, models, estimators): ...  # JSON list
```

模型记录包括`task_id, model_id, family, branch, status(fitted/error), reason, feature_names, training_sample_ids, training_subject_ids, training_dependency_groups, training_identity_sha256, training_data_sha256, mean, std, scale, constant_columns, parameters`；Ridge另含`coef, intercept`。预测记录包括`sample_id, task_id, model_id, status(valid/abstain/error), value, reason`。全部4×2×3模型尝试保留；纯预测不接收samples／未来目标。

- [x] 先写失败测试：字面Ridge数值、训练内／常量标准化、D03同训练集、挑战目标／输入隔离、行逆序、未知历史及零历史、缺模型、非有限、跨池依赖与重复主体。

```python
assert model['mean'] == [1.0]
assert model['scale'] == [1.0]
assert model['coef'][0] == pytest.approx(2/3)
assert prediction['value'] == pytest.approx(10/3)  # X train [0,2], y [1,3], predict X=3
assert anchor['training_sample_ids'] == augmented['training_sample_ids']
```

- [x] 在backend执行`.\.venv\Scripts\python.exe -m pytest tests/test_prediction_candidate_training.py -q --tb=short`，确认缺实现失败后实现。白名单读取；主集label valid，D03再限known history；少于2依赖组不拟合；输入/目标非有限或模型异常保留稳定错误码。
- [x] 通过测试、记录实际失败及通过输出，独立审查训练文件；不修改其他模块。记录任务完成至`.tmp/synthetic-candidates-20260914/progress.md`。

## Task 2：候选评分与D03语义

文件：新增`backend/app/services/prediction_candidate_evaluation.py`、`backend/tests/test_prediction_candidate_evaluation.py`。

消费Task1的候选model_id和预测；接口`evaluate_candidates(samples,predictions,baseline_predictions)->dict`返回`evaluation, paired_rows, bootstrap_plans`。评价48个任务／池／族／分支vs-last比较及16个D03流程比较；保存`mae_gain_vs_last`和`flow_mae_gain`的不同参考。每条配对行带comparison_id/sample_id/subject/group/actual/prediction/reference及reference_model_id。调用已有paired_statistics/paired_bootstrap但适配键名，D03不进入C03判定器。

- [x] 写并运行失败字面测试，含患者等权、D03增益区别、负增益、缺标签仍预测、缺记录、同伴失败、联合四态、资格与标签及全输出计数、未知历史、零分母和重复主体。

```python
# two patients: y [10,20], last [8,17], d03_anchor [9,18], augmented [10,19]
assert augmented_summary['mae_gain_vs_last'] == 2.0
assert flow_summary['flow_mae_gain'] == 1.0
assert flow_summary['reference_model_id'] == 'ridge:d03_anchor'
```

- [x] 用已有统计内核实施；完整性逐全部branch合格锚点检查，不只label有效交集；全输入输出状态单列；只challenge计算2000抽样，四态和零分母保持显式。
- [x] 运行本模块及既有metrics/calculation相关测试，独立审查差值语义和失败路径。

## Task 3：导出、CLI、真实运行与交付

文件：新增`backend/app/services/prediction_candidate_export.py`、`scripts/evaluate_synthetic_prediction_candidates.py`及各自测试。接口`evaluate_candidate_package(source_dir, calculation_dir, output_dir)->dict`、`verify_candidate_export(output_dir)->dict`。

- [x] 先测试两来源拒绝／输出拒覆盖、来源内输出、CLI参数／失败码、数值复算、修改统计后重写hash仍拒绝、runtime/code/source绑定、缺模型文件、并发及IO清理。临时IO不自动重试。
- [x] 实施独占临时目录及Windows原子拒覆盖改名；清理限定本次临时目录。manifest绑定完整源码、两来源run/hash和运行时。JSON制品含models/features/samples/predictions/paired_rows/evaluation/bootstrap_plans/summary；各森林joblib可回读，仅对本进程刚生成可信文件load，外部验证通过重新拟合重建验证，不执行不可信pickle。
- [x] CLI仅`--source-dir --calculation-dir --output-dir`；0工程完整且所有预声明拟合／必需输出成功，2参数或既有目录，3来源／制品验收失败或候选未完整，4运行IO。失败不能省略模型或当成功。
- [x] 实际生成`outputs/synthetic-prediction-candidates/2026-09-14-v2`并新进程复算；相关回归及独立最终审查通过，原两来源再验收。生成并渲染预测散点和D03结果摘要。
- [x] 核查120／600／1200每病种的生成及合格量（明确不同机制／缺失／池）；仅把扩量诊断作为用户问题的工程证据，不把扩量合成成绩当真实样本量依据或改本包固定输入。若需更多规模／多种子模型稳定性实验，列为下一步建议，不隐式调参。
- [x] 更新设计已授权状态、README、总领、阶段二§7.66及验收记录。保全原第5节36项和非本轮既有文件，说明本次结果、未验证项、立即下一步及剩余正式步骤。

## 执行记录

2026-09-14：上述工作已完成，训练、集成和最终修复复查通过。最终53项候选测试通过（382.49秒），加本轮此前155项相关回归共208项不同测试。实际v2包run_id为`cand-22836cc1cfb5fcc4`，新进程复核通过，24模型与全部数值制品和修复前v1逐字节一致。最终审查发现的首次失败被重试问题已按先红后绿修复，失败只核对输入／配置且保持incomplete。两来源身份及716个既有非本轮文档文件、v1的33文件保持，原临床36项不变；图已渲染检查，规模核查只生成／组样未扩大拟合。详见[验收记录](../notes/2026-09-14-synthetic-prediction-candidates-result.md)。未提交或推送。
