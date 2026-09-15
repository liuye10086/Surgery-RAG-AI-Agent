# 合成数值报告A包：契约与基线适配验收

日期：2026-09-14。状态：**A包实施与纯计算验收完成，尚未接入应用API／数据库／worker／界面／PDF。**

依据：[应用设计](../specs/2026-09-14-synthetic-prediction-application-design.md)、[A包实施计划](../plans/2026-09-14-synthetic-numeric-adapter.md)。用户审阅上一轮设计后要求“ok，开始下一步”，本次落实A包。

## 交付

- `backend/app/schemas/synthetic_numeric_prediction.py`：新增严格合成来源身份、双时距输入包、算法身份和数值结果契约。单病例必须同主体、依赖组、病种与锚点，恰好6／12月两个任务，两个包的预测输入一致。
- `backend/app/services/synthetic_numeric_prediction.py`：输入规范化及SHA256、固定算法身份、`predict_synthetic_numeric` 和 `validate_numeric_prediction`。复用既有输入投影／基线函数，仅导出 `last_value`。
- `backend/tests/test_synthetic_numeric_prediction.py`：82项新测试；包含两个病种字面期望、月底与闰年、缺失状态、单位／方法／时间、来源／任务关联、错误输出及版本一致性，以及66个已有固定场景逐主体适配。

有有效锚点时，6／12月值都保持锚点值；输入不可用则返回null及原具体原因。单位为MMSE“分”、ALT `U/L`。没有新增区间、概率、风险结论或候选模型选择。

源文件SHA256与实际加载函数／验证器代码一致性会在算法身份构造时检查；从固定源码编译CodeType用于比较，不执行源码。算法身份同时包含实际输入／结果schema和基线选择常量。已加载代码与磁盘变化不一致时拒绝；不能给旧运行代码配上新文件摘要。历史结果绑定接受调用方传入的保存算法身份，不查询当前算法或重新预测。

## 本次实际验证

运行时实测为Python 3.11.4，使用现有 `backend/.venv`。未安装或升级依赖。

| 检查 | 结果 |
| --- | --- |
| 修改前已有输入与计算基线 | 30 passed，2.34秒 |
| 首轮测试先行 | 新接口尚未实现，76项测试实际失败；随后首版76项通过 |
| 补充回归 | 实际复现磁盘变化／导入顺序与历史冲突状态漏洞，再修复；固定场景测试曾因双主体未分组失败，纠正夹具按主体分组 |
| 最终新模块独立测试 | 82 passed，2.09秒；独立审阅复跑82 passed，2.04秒 |
| 最终新旧关联回归 | **171 passed，32.93秒，0失败／0跳过** |
| 冻结合成输入包 | 240主体、480预测；每任务120条，全部值与原离线last_value一致，全部结果绑定校验通过 |
| 独立审阅 | 历史冲突和代码导入顺序问题均修复，最终无重要未解决问题；结论仅限A包 |

关联回归命令（backend目录）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_synthetic_numeric_prediction.py tests/test_prediction_calculation.py tests/test_prediction_calculation_export.py tests/test_prediction_calculation_metrics.py tests/test_synthetic_prediction_cases.py tests/test_synthetic_prediction_fixtures.py tests/test_synthetic_prediction_quality.py -q
```

## 冻结包核对身份

只读 `outputs/synthetic-prediction-cases/2026-09-14-v1/manifest.json` 与 `prediction_inputs.jsonl`；按主体组装输入，先核对文件字节数／摘要，再逐项对照原基线值并校验新结果与输入的绑定。未读取该包未来标签或生成机制，未重建旧包。详细本地核验收据为 `.tmp/synthetic-numeric-adapter-20260914/frozen-input-verification.json`。

| 身份 | 值 |
| --- | --- |
| 来源run ID | `syn-24928e18054e0ace` |
| manifest SHA256 | `ff4e33d675480b7dbd3c040ecbceaed0cd7b1fb8e2ef0e4a15287c3e47af0f5e` |
| prediction_inputs SHA256 | `4f139a4c98c905ce1502ec1398371f2540fce761ee1197ecb6940b8c590c9d91` |
| 本轮算法版本 | `synthetic_numeric.last_value.v1` |
| 实现身份SHA256 | `bbca542a99b18054ae856889851dbeb2e63fd8848ca8d5afb00586d19f912922` |
| 空参数SHA256 | `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` |

## 限制与剩余步骤

本包的来源校验是结构、字段关联和完整性校验，**不是来源认证、访问授权或数据库绑定**。纯服务只应由后续已鉴权并验证来源的接单／worker调用，不是可直接公开的HTTP接口。来源文件在受控目录内的验证、病例与输入投影绑定、禁止合成病例绕旧报告入口、病例编辑限制、幂等及持久化均留在B包及之后。

未运行数据库集成、真实worker、浏览器、前端构建或PDF验收，因为本轮没有对应改动。没有训练／发布模型、调用外部LLM、写业务数据库、改活动模型或旧预测实现；没有提交或推送。合成验证仍不能证明临床有效性或真实样本量充足。

**下一步：B包，实施服务端合成来源绑定、Alembic迁移文件、隔离种子及类型化鉴权接单。** 只在明确的隔离测试DB验收迁移与接单，不在现有业务库执行迁移。

剩余依次为C包worker／发布／历史、D包页面／PDF、E包隔离总验收。真实路线独立完成来源与定义补齐、A3组样及泄漏核查、A4完整评价合同、A5冻结，再进行阶段三独立比较、阶段四正式接入、阶段五获准发布。原第5节36项保持13满足、15缺条件、8未执行。
