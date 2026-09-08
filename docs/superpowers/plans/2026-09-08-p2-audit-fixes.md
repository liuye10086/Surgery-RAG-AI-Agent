# P2 审查问题修复计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** 修复已批准审查报告中的全部 12 个 P2，保留已完成的 P1，不开始 P3。

**Architecture:** 沿用既有接口和设计；以文档原序、独立事务和明确的请求/草稿身份修复数据一致性问题。每项先复现后修复，以实际组件和业务服务验证。

**Tech Stack:** Vue 3 / Pinia / Vitest、FastAPI / SQLAlchemy / pytest、python-docx / PaddleOCR 3.x、PostgreSQL。

## Global Constraints

- 用户已批准开始 P2；完成后须等待确认才能处理 P3。
- 不提交、不推送，不改业务数据库或原始病例 DOCX；保留当前 P1 未提交修改。
- 前端遵循 docs/DESIGN_SPEC.md，不更换风格；合成数据用于测试。
- 不修 operator_case_commands.py 仅访视更新时间问题（P3）。
- 先运行失败测试，再最小实现，最后相关测试与整体回归；不以 mock 替换被修的业务逻辑。

## Tasks

- [x] 1. DOCX 顺序：backend/app/ingestion/parser.py 统一按 body 子元素遍历 Paragraph/Table；backend/tests/test_ingestion_parser.py 构造 Case 1/table 1/Case 2/table 2 并验证实际 chunk_pages 的归属。
- [x] 2. WPS 修复：文本和图片共用修复后的文件流；测试 NULL 关系文档同时保留文字与真实内嵌图片。
- [x] 3. 回答事务：backend/app/api/chat.py 在成功流内提交回答，审计失败单独回滚，不能撤销已提交回答；用 SQLite 实际事务及合成 Runnable 测试新回答/重试回答在审计失败后仍持久化，以及回答提交失败不能发送 done。
- [x] 4. 用户导出：backend/app/api/user.py 用 ASCII 文件名回退加 UTF-8 filename*，测试中文/引号等用户名的响应及 JSON 内容。
- [x] 5. 检索降级：backend/app/rag/pipeline.py 各分支以 db.begin_nested() 保存点隔离失败，保留调用方事务；实际 PostgreSQL 验证失败分支后的全文查询可用，外层待提交数据不丢失。
- [x] 6. 聊天取消：frontend/src/stores/chat.ts 为请求建立代次/身份，abort 清 loading/占位状态并忽略迟到回调；真实 Pinia store 测试。
- [x] 7. 跨会话回调：切换会话取消当前请求，隔离所有回调，加载会话使用导航代次防止旧请求覆盖；标题、危险提示必须归属正确会话。
- [x] 8. 未确认发送重试：保留 client_request_id 及对应 userMessage；只有服务端正数 assistant ID 才走 retry_message_id，负数占位按原幂等键重发并正确更新用户 ID。
- [x] 9. 草稿保留：OperatorView/OperatorCaseWorkspace 在历史及报告切换后保留编辑内容；显式切换病例时处理草稿，不把 A 的草稿带到 B；保存成功重置草稿，新建和保存失败同样受保护。真实组件测试。
- [x] 10. 病例分页：operator store 保留 total/skip/limit，OperatorCaseList/OperatorView 提供分页入口，筛选重置页码、迟到列表不覆盖当前页；删除最后一页最后记录时回到有效页；组件/store 测试。
- [x] 11. OCR：parser.py 适配已安装 PaddleOCR 3.x 的 device/predict/rec_texts 契约，requirements 声明兼容 OCR 和 Paddle CPU 运行时；与官方文档及实际运行验证，使用合成图片。GPU 的安装方式记录在部署文档。
- [x] 12. 首次部署：docs/DEPLOY.md 在 postgres 管理员会话中创建 vector 扩展，再普通账号迁移；不提升应用账号为超级用户。

## Verification

逐项执行对应 pytest/Vitest；最终执行后端和脚本非 E2E 全量测试、前端 unit/contracts/build、本地模型 smoke 与隔离 PostgreSQL 集成测试。记录具体命令、结果及未能执行的边界。保留前次审查临时目录（删除曾被策略拦截，不尝试绕过）。

## Progress

- 初始状态：P1 两文件修改已完成，77 项相关测试通过。P2 尚未开始实现。


- 第一批验证：DOCX 2 passed；回答事务与用户消息 7 passed（后续新增 error 用户ID契约待统一重跑）；导出 4 passed；真实 PostgreSQL 降级+检索 20 passed。
- 聊天实现和独立复核通过：相关11项GREEN，待最终前后端统一验证。其余P2 9–12继续，P3未开始。
- 最终验证：后端与脚本 1390 passed / 24 subtests passed；真实 PostgreSQL 集成 60 passed；前端 108 单测、30 契约及 TypeScript/Vite 生产构建通过；本地模型 smoke 四场景通过。
- 真实 OCR：隔离 venv 安装 PaddleOCR 3.7.0 / PaddlePaddle 3.3.0，Windows 禁用 MKLDNN 后，生产 parser 对合成图片和扫描 PDF 均识别出 `TEST CASE 42 / ALT 42 U/L`。依赖声明和部署文档已同步；未修改全局 Python 环境。
- 普通数据库账号部署：旧流程创建 vector 扩展因权限不足失败；管理员预装后普通账号 Alembic 到达 0026，账号仍无超级用户权限。
- 集成全量有一条 Windows 子进程 GBK 解码告警；设置 PYTHONUTF8=1 并将线程告警视为错误后单独复跑迁移用例，1 passed、无告警。没有为测试环境告警修改业务代码。
- 聊天、病例工作区和后端三组独立复核均通过。P2 全部完成，P3 待用户确认；未提交或推送。详细本地记录：`.superpowers/p2/修复验证.md`。
