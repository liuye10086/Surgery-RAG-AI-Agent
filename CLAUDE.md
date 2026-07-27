# CLAUDE.md

> 开始任何项目操作前，必须先完整阅读并遵守 `AI_COLLABORATION.md` 中的多角色协作规范。

## 项目概述

Surgery RAG Agent — 外科领域垂直 RAG AI Agent。前端 Vue 3 + TypeScript + Element Plus，后端 Python FastAPI + LangChain PGVector（`langchain-postgres`）+ DeepSeek LLM。

核心技术栈：LangChain LCEL 链编排、`RunnableWithMessageHistory` 自动历史管理、`langchain-postgres` PGVector 向量存储、BGE-M3 Embeddings（1024 维）、混合检索（向量 + PostgreSQL 全文 + RRF 融合）。

## 前端 UI 修改规则

**此后进行任何 UI 修改前，必须先读取 `docs/DESIGN_SPEC.md` 并严格遵循其中的全部规范**，除非用户明确要求更改风格。

`docs/DESIGN_SPEC.md` 包含：
- 完整的色彩体系（暖杏蓝方案）
- 排版、间距、圆角、阴影、动效规范
- 组件特定变体定义（对话气泡、引用卡片、输入框、按钮等）
- 布局尺寸规范（侧边栏 260/64px、内容区 max 880px、顶部栏 56px 等）
- 双角色体验（医生/患者）的差异化设计

所有 CSS 变量已定义在 `docs/DESIGN_SPEC.md` 第 10 节，实现时应优先使用这些变量。

## 通用规则

如果信息不够完善或在多种实施方案间存在歧义，请先向我提问澄清，不要自行猜测或假设。
