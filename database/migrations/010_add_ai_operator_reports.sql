-- 010: AI 操作者报告系统
-- 新增 ai_reports 表 + 索引
-- 注意：正式部署应使用 Alembic（backend/alembic/versions/0004_add_ai_reports.py）

-- 1. 报告表
CREATE TABLE IF NOT EXISTS ai_reports (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL,
    CONSTRAINT ai_reports_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(500),                          -- 报告标题（LLM 生成或用户输入截断）
    query           TEXT NOT NULL,                         -- 用户输入的原始分析问题
    department_ids  JSONB DEFAULT '[]'::jsonb,             -- 生成时选择的科室 ID 列表（空数组 = 全库）
    content         TEXT NOT NULL DEFAULT '',              -- 报告正文（Markdown）
    sources         JSONB DEFAULT '[]'::jsonb,             -- 引用的知识库来源
    retrieval_meta  JSONB DEFAULT '{}'::jsonb,             -- 检索元数据
    status          VARCHAR(50) DEFAULT 'generating',      -- pending | generating | completed | failed | cancelled
    error_message   TEXT,                                  -- 失败/取消原因
    download_count  INTEGER DEFAULT 0,                     -- 下载次数统计
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- 2. 索引
CREATE INDEX IF NOT EXISTS ix_ai_reports_user_id ON ai_reports(user_id);
CREATE INDEX IF NOT EXISTS ix_ai_reports_created_at ON ai_reports(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ai_reports_status ON ai_reports(status);
