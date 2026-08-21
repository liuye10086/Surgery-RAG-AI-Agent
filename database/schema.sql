-- Surgery RAG Agent 数据库初始脚本
-- 运行方式：在 Navicat 中连接 PostgreSQL 后，新建查询并执行本文件
-- 注意：需要先启用 pgvector 扩展

-- 1. 启用扩展
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. 用户表
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    real_name VARCHAR(100),
    hashed_password VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. 科室表
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 4. 文档表
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500),
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000),
    file_type VARCHAR(50),
    file_size INTEGER,
    status VARCHAR(50) DEFAULT 'pending',
    error_message TEXT,
    version INTEGER DEFAULT 1,
    active_generation INTEGER NOT NULL DEFAULT 1,
    is_current BOOLEAN DEFAULT TRUE,
    department_id INTEGER REFERENCES departments(id) ON DELETE RESTRICT,
    access_scope VARCHAR(20) NOT NULL DEFAULT 'chat',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_department_id ON documents(department_id);

-- 5. 文档片段表（仅保留内容和元数据，embedding 交给 LangChain PGVector）
CREATE TABLE IF NOT EXISTS chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    page_number INTEGER,
    chunk_index INTEGER,
    generation INTEGER NOT NULL DEFAULT 1,
    is_current BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 6. 疾病 / 病例 / 参考范围表（AI 操作者预测分析）
CREATE TABLE IF NOT EXISTS diseases (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS case_records (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL REFERENCES diseases(id) ON DELETE CASCADE,
    patient_label VARCHAR(100),
    indicators JSONB NOT NULL DEFAULT '[]',
    confirmed BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_case_records_disease_id ON case_records(disease_id);

CREATE TABLE IF NOT EXISTS reference_ranges (
    id SERIAL PRIMARY KEY,
    indicator_name VARCHAR(100) NOT NULL,
    name_cn VARCHAR(200),
    unit VARCHAR(50),
    lower DOUBLE PRECISION,
    upper DOUBLE PRECISION,
    lower_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    upper_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    sex VARCHAR(10),
    category VARCHAR(100),
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_reference_ranges_indicator ON reference_ranges(indicator_name);

-- 7. AI 操作者报告表（0004 创建；0006 追加预测分析列）
CREATE TABLE IF NOT EXISTS ai_reports (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    query TEXT NOT NULL,
    department_ids JSONB DEFAULT '[]',
    content TEXT NOT NULL DEFAULT '',
    sources JSONB DEFAULT '[]',
    retrieval_meta JSONB DEFAULT '{}',
    status VARCHAR(50) DEFAULT 'generating',
    error_message TEXT,
    download_count INTEGER DEFAULT 0,
    analysis_type VARCHAR(50) NOT NULL DEFAULT 'retrospective',
    disease_id INTEGER REFERENCES diseases(id) ON DELETE SET NULL,
    indicators JSONB DEFAULT '[]',
    prediction_result JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ai_reports_user_id ON ai_reports(user_id);
CREATE INDEX IF NOT EXISTS ix_ai_reports_created_at ON ai_reports(created_at);
CREATE INDEX IF NOT EXISTS ix_ai_reports_status ON ai_reports(status);

-- 8. 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 9. 消息表（新增 lc_message JSONB 用于 LangChain 标准消息格式）
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    lc_message JSONB,
    sources JSONB DEFAULT '[]',
    is_error BOOLEAN DEFAULT FALSE,
    is_no_knowledge BOOLEAN DEFAULT FALSE,
    client_request_id VARCHAR(64),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_session_client_request
ON messages(session_id, client_request_id)
WHERE client_request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_document_generation
ON chunks(document_id, generation);

CREATE INDEX IF NOT EXISTS ix_chunks_document_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS ix_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS ix_messages_session_id ON messages(session_id);

-- 10. 审计日志表
CREATE TABLE IF NOT EXISTS audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    request_body JSONB,
    retrieved_chunk_ids JSONB DEFAULT '[]',
    response_text TEXT,
    latency_ms INTEGER,
    safety_flags JSONB DEFAULT '{}',
    model VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_session_id ON audit_logs(session_id);

-- 11. 全文检索索引
--    langchain-postgres 自动管理 langchain_pg_collection 和 langchain_pg_embedding 表。
--    启动时由 ensure_vectorstore_tables() 在 langchain_pg_embedding.document 列上
--    创建 pg_trgm GIN 索引（idx_langchain_embedding_document_trgm），
--    同时清理旧版 tsvector 索引。
