# 合成预测病例首包实施与验收结果

日期：2026-09-14。状态：**离线首包已完成，默认生成与独立文件复核通过。尚未完成新四任务评分器或应用全链路验收。**

依据：[批准设计](../specs/2026-09-14-synthetic-prediction-cases-design.md)、[实施计划](../plans/2026-09-14-synthetic-prediction-cases-implementation.md)。用户在设计交付后确认“开始下一步”；本轮实施生成器、schema、固定场景、质量检查、目录导出及CLI。没有读取真实患者材料、训练或发布模型、写业务数据库、调用外部LLM或修改前端。

## 1. 实际交付

默认包位于 [2026-09-14-v1](../../../outputs/synthetic-prediction-cases/2026-09-14-v1/manifest.json)，目录属于本地生成制品，不自动提交版本库。固定种子为20260914，每病种120名虚构患者，其中开发池80人、挑战池40人；两个工程池不是正式评价分区。

| 项目 | 本次实际数量 |
| --- | ---: |
| 普通合成患者 | 240（AD／脂肪肝各120） |
| 原始观察记录 | 1,433（包括缺测状态记录） |
| 自包含预测输入包 | 480（每人6／12个月共用锚点） |
| 隔离的未来目标记录 | 480 |
| 固定场景 | 20类、66个实例（AD 34、脂肪肝32） |
| 患者生成审计 | 240 |
| 导出文件 | 9 |

九个文件是manifest、patients、observations、prediction_inputs、followup_outcomes、fixtures、expected_results、generation_audit和quality_report。正常队列与故意无效的固定反例分开；每个普通患者、观察及输入带合成来源和run_id。API样例标明合成用途，由后续隔离环境绑定疾病ID。

`prediction_inputs.jsonl`已经内嵌锚点时可用的观察，后续预测无需为取数回读含未来信息的全量观察表。全量观察、未来目标、生成机制和池归属仅供对应的组样或审计职责使用；关联ID和患者profile不是默认获准的学习特征，后续消费者仍须采用白名单。

## 2. 质量结果

[本次质量报告](../../../outputs/synthetic-prediction-cases/2026-09-14-v1/quality_report.json)的结构、投影、重复诊断、标签捷径、再生成、固定离线场景及当前API纯校验七项均为`passed`。这些都是软件验收条件，没有模型性能或临床用途合格声明。

| 病种 | 默认120人的唯一完整指标序列 | 扩至240人的唯一完整指标序列 |
| --- | ---: | ---: |
| AD/MMSE | 118 | 235 |
| 脂肪肝/ALT | 120 | 240 |

计数按两池并集计算，忽略患者ID和年龄；没有为去重删除患者。短整数MMSE序列自然相同并不等于同一个患者。报告还保存相对时间与指标序列指纹、近形状碰撞和相应时间。

作为失败对照，测试实际调用旧`build_demonstration_case_rows`：从每病种30人扩到300人，AD仍为5套、脂肪肝仍为7套；改变种子不改变日期或数值。相同的序列／种子门禁判定该对照失败，没有修补旧空单位或把旧病例加入新队列。

仅按阶段与可用既往测量次数建立开发池查表后，挑战池已见键的方向命中数如下：AD 6个月14/31、12个月5/27；ALT 6个月12/26、12个月15/27。四任务均有足够开发支持的歧义键，且查表不能完全命中；AD 6个月还有1例未见键，其他任务0例。这是`sign(y-a)`的标签捷径诊断，没有拟合模型，也没有临床容差含义。

未来记录状态为：名义日有效334、偏离名义日待窗口确认95、发生性待确认26、确证未测25；合计480。不同状态保留，不用另一时距的结果补齐。名义日是工程日期，不表示已批准临床随访窗口。

## 3. 验证与修复

实际执行新包77项测试及相关已有48项回归，共 **125 passed in 10.88s**，没有失败或跳过。独立审查方另行执行新包77项，全部通过。命令在`backend`目录运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_synthetic_prediction_cases.py tests/test_synthetic_prediction_fixtures.py tests/test_synthetic_prediction_quality.py tests/test_synthetic_prediction_case_export.py ../scripts/tests/test_build_synthetic_prediction_cases.py tests/test_operator_case_validation.py tests/test_operator_visit_context.py tests/test_longitudinal_task_routing.py tests/test_longitudinal_demonstration_data.py -q --tb=short
```

测试实际覆盖：种子复现与生效、扩量稳定、月底闰日、未来变换不影响两个输入、未知历史与确证零历史、同源副本不重复计数、当前API接受／拒绝、跨池依赖、旧模板失败对照、查表全命中失败、场景缺失不能通过、既有目录与并发写入保护、IO清理、文件损坏及更新哈希后的伪造PASS。

独立审查发现并已修复：同日冲突在筛选前被丢弃、获准单位别名离线拒绝、可得时间早于测量时间被接受、空场景或同步删除场景仍被判通过。集成时也修复了JSON键类型导致报告读回不相等的问题。修复均有实际行为回归。

在项目根目录实际运行以下命令，退出码为 **0**：

```powershell
.\backend\.venv\Scripts\python.exe scripts/build_synthetic_prediction_cases.py --output-dir outputs/synthetic-prediction-cases/2026-09-14-v1
```

该目录已经存在，重复执行会按设计返回2；再次生成时指定全新目录。CLI仅接受`--output-dir`、`--seed`、`--patients-per-disease`、`--challenge-per-disease`。0表示全部工程质量项通过，2表示使用错误，3表示保留了失败／缺支持诊断包，4表示文件或运行错误。

导出后再次调用只读`verify_synthetic_case_export`，完整性与工程质量均为`passed`。记录如下：

- run_id：`syn-24928e18054e0ace`
- 数据内容SHA-256：`c6d6323a3cb997ab5b501edbd17187849c04fa7deb48797f2c200c89c2da03ff`
- Python 3.11.4，NumPy 2.3.5；manifest另记Git版本及实际相关源码哈希。

验证器要求相关源码哈希匹配，重建输入／目标和质量结论，不能只信任保存的`passed`。生成器更新后应生成新目录和新run_id。小规模缺支持的包已经验证会保留且返回3，不因文件完整而当成质量通过。

## 4. 下一步与剩余步骤

**下一步：用本次通过检查的合成包实施新四任务的离线组样、保持当前值基线、历史分支及评分器，并落实已确认的计算规则。** 首先用固定字面样例核对算术和分母，再跑模拟队列。D05～D07、R01／R04／R05和计算包决定沿用原批准记录；训练数据标准化、个人点预测、总体区间等规则不会因合成样例而重新选择。

之后按顺序完成：

1. 最小应用接入，以及隔离数据库中的病例、预测、持久任务、历史和PDF原件验收。
2. 真实病例到位后，单独接收新数据版本，核对时间、单位、可得性和依赖组，再逐任务评价和替换相应用途。

本轮没有运行模型评分、数据库／浏览器／worker／PDF全链路；上述范围不能由77项新包测试代替。临床A3／A4／A5仍按真实证据推进，临床容差和16项C03门槛保持待定。阶段二原第5节36项内容保留：13满足、15缺条件、8未执行。旧合成来源、现有模型、历史报告和PDF没有被覆盖，也未提交或推送代码。
