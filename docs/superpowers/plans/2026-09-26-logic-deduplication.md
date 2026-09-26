# 保持现有行为的逻辑去重

> 执行：使用 subagent-driven-development 分工实施，由独立审查检查行为等价性。用户已授权直接执行；不提交或推送。

**目标：** 合并聊天链路和阶段/趋势训练中已核实的相同实现，减少重复维护。

**方案：** 聊天前后端只提取文件内私有函数；两个训练入口复用一个仅负责构造 sklearn Pipeline 的小模块。不统一存在业务差异的报告状态机或结局模型预处理器。

**环境：** Python 3.11.4、项目 backend/.venv；Node.js 22.15.0、npm 10.9.2。

## 约束

- 保留上一轮全部未提交清理改动；本轮开工前源文件副本位于 `.tmp/logic-refactor-20260926/before`。
- 不改变接口、权限、错误码/文本、事件顺序、事务顺序、取消/重试/幂等或历史报告和 PDF 归档行为。
- 不改冻结源码清单内的 35 个文件，不更新模型/数据/renderer 身份或制品；不调用外部 LLM、不写业务数据库、不运行训练或发布命令。
- 不新增依赖、配置、通用框架或界面设计；不再尝试删除被工具策略阻止的缓存。
- 本轮为重构：先用行为测试刻画已有结果并在原实现上验证，再改实现并运行相同测试；不通过修改断言改变预期。

## 任务 1：聊天后端

文件：`backend/app/api/chat.py`、`backend/tests/test_chat_stream_transactions.py`。

- [x] 复用临时 SQLite fixture，覆盖三个入口对他人/缺失会话的相同 404，及普通失败、重试更新、重试未命中、history 初始化失败时错误消息的实际内容和 ID。
- [x] 将 get_session/delete_session/ask 的相同查询提为 `_session_or_404(db, session_id, user_id)`；同时保留 id/user_id 条件和原调用位置。
- [x] 错误消息先设 `existing = None`，仅按原条件查询；合并两个新建分支。更新仍 commit 后取 ID，新建仍 add/commit/refresh 后取 ID。
- [x] 运行 `tests/test_chat_stream_transactions.py tests/test_chat_persistence.py tests/test_rag_logic.py tests/test_cleanup_contracts.py`。

## 任务 2：聊天前端

文件：`frontend/src/stores/chat.ts`、`frontend/src/stores/__tests__/chat.spec.ts`。

- [x] 补充 done/error 终态 ID、危险提示、标题、迟到事件与同步回调的行为覆盖，原实现先通过。
- [x] 提取本 store 私有消息工厂，保留 user 创建/入列再 assistant 创建/入列，独立负 ID、时间戳和 reactive 对象。
- [x] buildCallbacks 内提取终态收尾函数，依次处理消息 ID、用户 ID/危险提示迁移、标题、loading、取消句柄、activeRequest；各回调保留 isCurrent 和专属正文处理。
- [x] 运行聊天 store/API 测试；整合后执行全部 test:unit、test:contracts 和 build。

## 任务 3：阶段/趋势模型构造器

文件：`backend/app/services/longitudinal_stage_training.py`、`longitudinal_trend_training.py`；新增同目录 `longitudinal_training_pipeline.py` 和适用行为测试。

- [x] 核对 Pipeline 参数、输出列顺序、缺失值/未知类别、候选顺序和随机种子；原实现先通过行为刻画。
- [x] 新模块以 numeric_features、categorical_features、seed 为输入构造候选 Pipeline；两个入口直接复用，删除重复私有构造器及专属导入。
- [x] 保留 numeric/categorical 分支、imputer/scaler/onehot/preprocess/classifier 步骤名，以及原逻辑回归/随机森林全部参数；每次构造返回独立对象。
- [x] 不改 FeatureCatalog 类、已有序列化类路径、标签/特征生成、训练选择、阈值或发布机制；outcome 预处理仍独立。
- [x] 运行 stage/trend/outcome 训练模块测试、两个训练脚本测试、suite 脚本测试及冻结源码测试。

## 验收

- [x] 独立审查本轮增量 diff，确认无行为变化或无关修改。
- [x] 后端按 DEVELOPMENT.md 执行全部本地测试，排除 integration/E2E，单独报告跳过项。
- [x] 前端全部单元/契约测试和构建；浏览器用合成响应检查聊天创建、流式回答及终态。
- [x] `git diff --check`，记录生产代码删减量、实际测试结果及未验证范围。

## 结果

实现、独立审查和本次本地验收均已完成。

- 本轮生产代码共净减少 73 行：聊天后端 22 行、聊天前端 11 行、训练构造器 40 行（已计入新增共享模块）。另新增行为测试，不以仓库总行数下降作为验收标准。
- 新测试先在原实现上通过：聊天后端相关 44 passed、7 warnings；聊天前端相关 21 passed；训练构造器刻画 14 passed。重构后同一行为断言均通过，训练相关扩大回归 76 passed。
- 后端全量本地回归（排除 integration/E2E）：2526 passed、59 skipped、46 warnings、24 subtests passed，耗时 1027.68 秒，退出码 0。58 项跳过因未配置原始 DOCX；1 项因符号链接创建不可用。新增 owner ask 测试额外触发一次既有 LangChain 弃用警告，未更改无关依赖或实现。
- 前端全量：23 文件 / 185 tests passed；契约 30 passed；build 成功。保留现有注释位置与大 chunk 警告；源文件最终恢复原 CRLF，内容未变。
- 构建产物的本地浏览器合成检查通过：新建会话、成对消息、成功/错误/无知识终态、危险提示归属迁移、错误消息重试复用、迟到 delta 忽略；无页面异常或未预期请求，真实后端请求为 0。已检查截图，未修改界面样式。
- 阶段/趋势共 32 组快照对照验证未拟合 pickle 字节、转换矩阵和特征顺序一致；24 组非空特征组合的预测和概率精确一致。全部为空的分支仅比较预处理，不放宽分类器条件。35 项冻结源码身份保持不变。
- 聊天任务及最终整体独立审查均通过，无 Critical/Important/Minor 项。已核对工厂依赖无循环、sklearn 序列化类路径、训练选择与重新拟合流程，以及聊天权限和事务/事件顺序。
- 首次训练构造器抽取曾误删后续函数声明，定向测试出现语法失败；已恢复声明，未改变断言，重跑 76 项及快照对照通过。整仓测试启动后源文件未再编辑。
- 未执行 PostgreSQL 集成/E2E、真实模型训练/发布、外部 LLM 或业务数据库操作；不声称已验证运行耗时改善。
