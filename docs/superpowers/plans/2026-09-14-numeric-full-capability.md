# 统一数值报告第2步：接通完整能力

> 按已确认的 unified-prediction-report-direction 执行；使用 subagent-driven-development，测试和实际任务串行，不另行开启字母包。

**Goal:** 把重构后MMSE/ALT四任务的训练评价、固定模型推理、实际检索与DeepSeek说明接入统一numeric_prediction持久报告、历史和单一PDF模板。

**Architecture:** 保留v1基线及旧v1-v4历史；新增numeric_generation_context.v2、numeric_prediction.v2、numeric_report_document.v2及v5发布。新请求在服务端配置固定模型包时使用完整路径；未配置时显式保持已知基线路径。固定可复现Ridge main_anchor作为首个训练推理候选，保留last_value比较值；不声称胜过基线或完成正式模型选优。模型包包含四任务参数、训练/评价来源、评价结果和摘要，工作进程不训练。RAG复用BGE-M3、PGVector、pg_trgm和RRF，限定固定的可访问病种/科室/版本chunk集合；LLM只组织已给定事实与引用，不能覆盖计算表。

## 边界与验收

- 本轮授权包含训练和目标链路的DeepSeek调用。仅向已配置DeepSeek发送本轮合成病例及受控合成参考片段，不发送原真实患者资料；密钥不输出、不修改.env。既有本地BGE缓存可用，不下载或升级依赖。
- 所有数据库写入、参考索引和模型切换演练仅在任务私有本机*_test库及新制品目录中执行，不触碰业务库/现有发布指针。不提交推送部署。
- 冻结既有synthetic源码/输出及第1步v1保存契约、历史PDF；版本变化采用新增v2/v5解析，不重算历史。新的输入仍为numeric_input.v1。
- 参考材料由已验收合成数据的开发池输入事实构成，不导入其随访目标。病种、来源版本、访问范围、当前文档代次、科室和主体排除均保留；无证据不能捏造。
- schema驱动生成前端DTO，UI遵循DESIGN_SPEC、同一NumericReportView，PDF沿用report_pdf.html。LLM失败或校验拒绝必须让任务明确失败，不生成伪LLM成功文本。
- 全部重型测试/训练/嵌入/浏览器串行安排；每步记录执行证据，最终停任务进程。

## 1. 固定模型包（独立实现）

新增 schemas/numeric_model_bundle.py、services/numeric_model_bundle.py、scripts/build_numeric_model_bundle.py 及测试。

接口：NumericModelBundle、load_numeric_model_bundle(path)、bundle_sha256(bundle)、build_numeric_model_bundle(source_dir,calculation_dir,output_dir)、predict_numeric_bundle(numeric,bundle)。输出TrainedNumericPrediction（numeric_prediction.v2），输入NumericInput不变。algorithm含固定ridge身份及bundle_sha256，predictions沿用双时距状态/单位/日期，并提供baseline_predictions。模型包以严格JSON参数运行，不反序列化任意pickle；训练复用原候选训练/评价函数，仅开发池拟合，挑战池评价照实保存；四任务ridge:main_anchor必须齐全，预测不接收标签，不截断或填造非法值。

- [x] 先测试输入/制品损坏、错误单位/任务、开发/挑战隔离及预测固定性。
- [x] 实现包构建/严格加载/固定推理/CLI，输出新版本目录，不覆盖旧目录。
- [x] 本轮实际训练评价并保存制品；记录候选未必胜过基线。

## 2. 固定证据检索和LLM（独立实现）

新增 schemas/numeric_report_evidence.py、services/numeric_report_evidence.py、services/numeric_report_narrative.py、scripts/seed_numeric_reference_corpus.py 及测试。必要增量修改rag/pipeline.py，新增allowed_chunk_ids约束在向量和全文取top-k之前应用；旧调用默认行为不变。

接口：capture_numeric_references(db,numeric)->NumericReferenceContext；retrieve_numeric_evidence(db,numeric,context)->NumericRagEvidence；generate_numeric_narrative(numeric,prediction,evidence,*,llm_model)->NumericNarrative。context固定候选chunk内容摘要、代次、病种、科室和数据版本；检索时再次验证，实际结果保存分支分数/秩及片段。来源在元数据保留，可见材料不写来源专用标签。检索须排除本人及同依赖组、锚点时未知资料，并在空或失败时提供准确状态。LLM复用DeepSeek配置和医疗过滤，严格结构化内容、合法引用和数值约束，无自动重试。

- [x] 写权限/病种/版本/内容变动/同主体/未知引用/篡改数值/LLM异常的红灯测试。
- [x] 实现来源可追溯的受控参考语料种子（只隔离库），复用现有嵌入与检索。
- [x] 实现固定证据与LLM服务，保留输入/响应摘要、模型名称和实际调用状态。

## 3. 主流程v2与v5（主任务）

新增schemas/numeric_report_v2.py、services/numeric_report_v2.py、workers/numeric_report_v2.py、迁移0030；修改新接单上下文分派、模型包配置、publication/parser/integrity/history/PDF/renderer、类型生成器。v5发布完整校验输入/固定模型包/预测/证据/LLM/正文/行身份；历史校验仅使用保存事实，不加载当前模型、DB资料或LLM。受理固定模型版本与参考候选，事务前重核漂移，旧幂等重放不受配置切换影响。

- [x] 先写v2/v5发布及损坏/版本兼容回归。
- [x] 接通模型、检索、LLM实际worker及审计（prediction、standard_evidence、rendering阶段），保留租约/取消/事务语义。
- [x] 扩展单一页面和PDF，展示模型预测、基线对照、引用片段与LLM说明，来源标记仍只在后端。

## 4. 实际链路验证与交付（主任务）

- [x] 隔离数据库迁移；生成参考向量；真实模型包+真实BGE/PGVector/RRF+真实DeepSeek至少两病种各一次，记录实际执行结果。
- [x] 单元、适用隔离集成、前端Vitest/契约/构建及实际浏览器/PDF验收，LLM异常和保存事实损坏拒绝测试。
- [x] 独立复审，冻结文件/既有输出/第5节保全，停任务私有服务，更新主计划和验收记录。

本步之后只有第3步统一总验收与数据/模型版本切换演练；真实临床模型性能评价仍需真实资料到位。

## 完成记录

本步已实施并实际验证，详见[验收记录](../notes/2026-09-14-numeric-full-capability-result.md)。旧来源摘要差异通过隔离源码精确复现处理；首轮LLM方法描述不准确后修正并重新执行。真实DeepSeek和BGE/PGVector、两病种报告/历史/PDF均已验收。下一步仅为第3步统一总验收及版本切换演练。
