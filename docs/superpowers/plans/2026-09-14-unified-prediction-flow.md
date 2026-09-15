# 统一预测主流程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 合成及真实来源通过同一版本化导入／预测契约、新生成入口、报告页面和PDF模板；来源只保存在服务端事实中，旧报告及原件继续可读。

**Architecture:** 新生成使用`numeric_prediction`，来源与数值任务分开。冻结的synthetic v1／v3和旧临床v1／v2保留历史兼容，新输入／上下文／文档及v4发布严格校验；复用现有队列、归属、审计与归档机制。第1步仍明确执行last_value，第2步接通训练模型、RAG和LLM。

**Tech Stack:** 项目Python3.11.4／venv，Vue3／TypeScript，Node22.15.0／npm10.9.2，现有PostgreSQL及Playwright PDF。

## 全局边界

- 用户已批准来源在后端保留而不在产品界面／新PDF显示；该新要求取代此前合成专用提示的设计。数值、缺失与实际执行状态不得虚构。
- 使用当前`codex/prediction-phase-2-evaluation`工作区，保留累计未提交实现；不另建空分支丢失前序工作，不提交／推送／部署。旧输入与算法源码、冻结输出、历史PDF不覆写。
- 业务数据库不写；迁移只执行于已有任务私有本机测试实例。所有重型测试串行。实例、API、worker、Vite由任务启停，凭据不写输出。
- UI遵循完整DESIGN_SPEC暖杏蓝及现有组件；新报告复用一个`report_pdf.html`模板。旧模板文件作为已有资源保留，主渲染入口不再按来源选模板。
- 来源无证明不能默认认定真实。统一导入只由受控服务端CLI读取显式版本包，普通客户端不得提交来源绑定；不从上传的SHA推断可信身份。

## 1. 来源无关契约与版本导入

Files: 新增`backend/app/schemas/numeric_prediction.py`、`schemas/prediction_case_source.py`、`services/numeric_prediction.py`、`services/prediction_case_source.py`、`scripts/import_prediction_cases.py`及对应单元／脚本测试。ORM和迁移由步骤2处理。

接口：`NumericInput`／`NumericPrediction`沿用旧双时距字段结构，schema为`numeric_input.v1`／`numeric_prediction.v1`。`PredictionSource`包含source_kind(synthetic/real)、严格is_synthetic、dataset_id、dataset_version、run_id、generator_version(真实为空)、manifest_sha256、input_file_sha256。任务和单位校验继承既有严格验证；来源字段覆盖为新契约，不能将真实来源伪装成旧synthetic。

```python
numeric = validate_prediction_case(case)
result = predict_numeric(numeric, expected_algorithm=numeric_algorithm_identity())
assert {p.horizon_months for p in result.predictions} == {6, 12}
```

- [x] 先写两病种、两种来源及错标志／未来观测／单位／不可用结果的失败回归；运行项目pytest确认失败。
- [x] 实现`numeric_input_sha256`、`numeric_algorithm_identity`、`predict_numeric`及保存结果校验；复用严格输入规则与基线计算原理，不改旧源码哈希。
- [x] 实现`convert_legacy_input`与`validate_prediction_case`：有新prediction_source则验证新绑定；仅有旧engineering_source时先验证原绑定再转换，绝不静默改原记录。两种来源经同一输入／结果服务。
- [x] 实现`build_prediction_binding`及版本包导入CLI：显式用户、来源版本、文件摘要；原子建立病例／访视／绑定；重复导入和中途失败无重复／残留；未知来源拒绝。真实来源契约仅用明确虚构fixture验证，真实数据未到位不宣称已导入。

## 2. 统一接单、发布、历史与数据库

Files: 新增`schemas/numeric_report.py`、`services/numeric_report_admission.py`、`services/numeric_report_publication.py`、`workers/numeric_report_execution.py`及迁移0029；修改现有请求、readiness、队列发布、完整性、历史和审计分派，扩展DTO生成器。

接口：请求`report_kind=numeric_prediction`；病例输出新增安全`prediction={verified,input_readonly,report_kind,enabled}`，不暴露绑定原文；配置`NUMERIC_REPORTS_ENABLED=False`。新快照`numeric_report_input.v1`、上下文`numeric_generation_context.v1`、文档`numeric_report_document.v1`、模板`numeric_report.zh-CN.v1`、指纹v4。上下文绑定`source_binding_sha256`、`numeric_input_sha256`和算法。旧显式请求及既有幂等摘要保留兼容，前端新请求统一使用numeric_prediction。

```python
assert hash_report_request(case_id, {'report_kind': 'numeric_prediction'}) != hash_report_request(case_id, {})
assert detail.generation_fingerprint_version == 'v4'
assert detail.report_document['schema_version'] == 'numeric_report_document.v1'
```

- [x] 写新类型接单与旧请求摘要兼容的失败回归，包含归属、角色、疾病、开关、来源、并发幂等及快照变化。
- [x] 添加可空`OperatorCase.prediction_source`与v4精确约束，not_requested仅对指定数值版本合法；downgrade在有事实时拒绝。
- [x] 实现固定输入／上下文／文档／证据和v4指纹，正文使用“数值预测报告”，不显示来源专用提示；本阶段如实说明末次值保持及未执行证据评价。
- [x] 接入实际worker，原子发布重建比对、租约／取消／事务要求保留。历史只验证保存事实，不运行当前算法；未知版本、改来源、改行身份或降级均拒绝。
- [x] 跨用户、取消、错误来源／日期／数值、断开当前算法依赖的历史读取、真实spawn及旧v3回归通过。

## 3. 统一页面与PDF

Files: `frontend/src/api/operator.ts`、`api/report-generation.ts`、病例／生成store、OperatorView、病例workspace、数值报告／历史／审计组件和测试；`services/pdf_generator.py`、`services/report_pdf_renderer_manifest.py`、`templates/report_pdf.html`。

- [x] 先写新numeric请求及双来源相同页面的行为测试。病例只读理由改为固定版本输入；不显示“合成／工程”标签。未绑定来源的普通录入不冒充已具备数值契约，readiness明确阻断。
- [x] 新数值文档和历史v3按一个数值组件展示；页面不展示来源标记，保留日期／单位／缺失／实测与预测区分。未知文档禁止旧模板回退及导出。重试类型与幂等键保持。
- [x] 生成联合DTO，禁止手改；新PDF校验保存v4事实后复用`report_pdf.html`；v1／v3旧正文仍按保存事实处理，旧ready原件不重渲染。
- [x] 构建独立renderer并以实际Chromium生成两病种PDF，文本及逐页视觉检查；同源字节下载、跨用户拒绝、损坏恢复和旧v3原件保持。

## 4. 集成验收与交付

- [x] 相关后端pytest、隔离PostgreSQL集成串行通过；保存失败、跳过及最终结果，不用mock代替真实持久链路。
- [x] 前端`npm run test:unit -- --maxWorkers=1 --minWorkers=1`、`npm run test:contracts`、`npm run build`。
- [x] 实际API／Vite／浏览器检查病例、报告、历史、下载和关闭开关，合成与真实来源契约fixture走相同流程；不宣称真实数据性能验证。
- [x] 独立代码复审，核对旧输出和第5节36项保全，停本轮私有进程，更新结果与索引。交付只说明第1步结果，下一步“接通完整能力”，其后“总验收”。

分工：来源契约／导入子任务与前端子任务由独立实现者负责；主流程负责发布、历史、PDF及集成验收。共享schema修改由主流程协调，测试窗口串行分配。

## 第1步完成记录

2026-09-14：本计划全部完成。280项后端、91个不同隔离集成场景、139项前端单元、30项契约及生产构建通过；实际浏览器双来源路径与4份单页PDF已检查。详情及失败修复见[验收记录](../notes/2026-09-14-unified-prediction-flow-result.md)。下一步接通完整能力，其后统一总验收；本次没有执行训练、LLM调用或业务库上线。
