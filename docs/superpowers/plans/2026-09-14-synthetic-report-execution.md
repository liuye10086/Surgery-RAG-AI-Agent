# 合成数值报告C包实施计划

> 使用subagent-driven-development按独立任务实施与复审；本轮不提交或推送。

**Goal:** 完成已接单合成数值报告的实际worker执行、原子发布和不可变历史读取。

**Architecture:** 保留现有临床Publication和v1/v2摘要，增加严格数值文档／Publication及独立v3摘要；父子进程显式版本分派。沿用租约、取消、超时和原子事务；历史校验只依赖保存的输入、上下文和结果。

**Tech Stack:** 项目Python 3.11.4虚拟环境、SQLAlchemy/Alembic、pytest，Node22.15.0/npm10.9.2用于受影响类型验证。

## 全局边界

- 接续已确认应用设计第7节C包；不训练、不调用LLM或临床参考检索、不改变A包算法及已冻结输出。
- 不写已有业务库；数据库迁移及集成仅用任务私有本机测试实例。
- 不做D包页面／PDF，PDF入口对新文档应明确拒绝，不能误走旧模板。
- 工程证据明确not_requested，不冒充临床证据complete；必要数据库状态约束通过0028迁移。
- 源病例或当前算法变化不影响已完成历史；不重新推理补齐历史。

## 任务1：严格文档及发布契约

文件：新增`backend/app/schemas/synthetic_report_context.py`，扩展`backend/app/schemas/report_document.py`，新增`backend/app/services/synthetic_report_publication.py`和对应单元测试。

- [x] 将B包上下文类型移至纯schema并保留原字段字节规则；新增严格数值身份、证据说明、文档和Publication，旧类型不变。
- [x] 实现`build_synthetic_document(report_id, created_at, snapshot, context, prediction)`和`build_synthetic_publication(snapshot, prediction, document)`；同时验证batch、病种、来源、主体、任务、单位、日历日期及显示输入与固定输入一致。Publication仅包含现有可写DB列，fingerprint_version为v3。
- [x] 先运行身份错配、篡改正文／结果／证据和历史无当前算法依赖的失败测试，再实现固定中文渲染、摘要及校验；不含诊疗建议或虚构置信区间。

## 任务2：worker、状态迁移和历史分派

文件：worker execution/process_control、report_job_repository、report_integrity/read_service、report_generation_audit、models和0028迁移。

- [x] 先编写新文档执行和父侧解析负例；用`execute_report(payload, send)`产生数值Publication，父侧按文档版本解析并再次从固定输入重建校验。
- [x] 解除B包队列排除；固定算法匹配后执行；证据审计`not_requested`，不用临床标准模块。扩展DB枚举约束并保留旧分支限制，downgrade有v3事实时拒绝。
- [x] 历史、失败／取消输入审计识别新上下文，完成报告绑定DB行身份与上下文；未知版本、篡改或错型继续拒绝，PDF在D包前不可准备。

## 任务3：实际隔离验收及交付

文件：新增`backend/tests/integration/test_synthetic_report_execution.py`，更新B包临时误领测试和相关历史测试，记录结果文档和项目进度。

- [x] 实际HTTP接单→独立worker子进程→DB完成→HTTP历史读取，覆盖两病种四任务及无当前代码／病例依赖。
- [x] 真实事务测试取消、过期租约／超时、父进程终止、原子发布失败；错batch/task/date/unit/source和来源丢失拒绝。旧worker／历史回归继续通过。
- [x] 执行相关后端pytest和适用前端契约／构建；独立复审，保全原文件、模型及阶段二第5节36项原文，停止测试实例。

相关验证在backend下用`.venv/Scripts/python.exe -m pytest`；集成由私有启动器注入TEST_DATABASE_URL和DATABASE_URL，禁止回退业务库。

下一步D包页面及PDF，之后E包隔离总验收；真实A2–A5及正式比较／接入／发布独立推进。

执行状态：C包全部完成，证据与未验证边界见[验收记录](../notes/2026-09-14-synthetic-report-execution-result.md)。原始设计／计划不代表D包或产品总验收完成。
