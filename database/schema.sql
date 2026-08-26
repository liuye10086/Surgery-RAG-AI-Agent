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

-- 7. AI 操作者纵向病例和访视表（0008）
CREATE TABLE IF NOT EXISTS operator_cases (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    disease_id INTEGER NOT NULL REFERENCES diseases(id) ON DELETE CASCADE,
    patient_label VARCHAR(100) NOT NULL,
    sex VARCHAR(10),
    baseline_stage VARCHAR(100),
    notes TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_operator_cases_user_id ON operator_cases(user_id);
CREATE INDEX IF NOT EXISTS ix_operator_cases_disease_id ON operator_cases(disease_id);

CREATE TABLE IF NOT EXISTS operator_case_visits (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES operator_cases(id) ON DELETE CASCADE,
    visit_date DATE NOT NULL,
    visit_index INTEGER NOT NULL,
    indicators JSONB NOT NULL DEFAULT '[]',
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_operator_case_visits_case_date UNIQUE (case_id, visit_date)
);

CREATE INDEX IF NOT EXISTS ix_operator_case_visits_case_id ON operator_case_visits(case_id);
CREATE INDEX IF NOT EXISTS ix_operator_case_visits_visit_date ON operator_case_visits(visit_date);

-- 8. AI 操作者报告表（0004 创建；0006/0008 追加预测分析列）
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
    operator_case_id INTEGER REFERENCES operator_cases(id) ON DELETE SET NULL,
    indicators JSONB DEFAULT '[]',
    prediction_result JSONB DEFAULT '{}',
    input_snapshot JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_ai_reports_user_id ON ai_reports(user_id);
CREATE INDEX IF NOT EXISTS ix_ai_reports_created_at ON ai_reports(created_at);
CREATE INDEX IF NOT EXISTS ix_ai_reports_status ON ai_reports(status);
CREATE INDEX IF NOT EXISTS ix_ai_reports_operator_case_id ON ai_reports(operator_case_id);

-- 9. 会话表
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 10. 消息表（新增 lc_message JSONB 用于 LangChain 标准消息格式）
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

-- 11. 审计日志表
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

-- 12. 版本化标准规则层
CREATE TABLE IF NOT EXISTS reference_standards (
    id SERIAL PRIMARY KEY,
    disease_id INTEGER NOT NULL CONSTRAINT reference_standards_disease_id_fkey REFERENCES diseases(id) ON DELETE RESTRICT,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    current_version_id INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_reference_standards_disease UNIQUE (disease_id)
);

CREATE TABLE IF NOT EXISTS standard_documents (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500),
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    file_size INTEGER NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    uploaded_by INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_standard_documents_content_hash UNIQUE (content_hash),
    CONSTRAINT fk_standard_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS reference_standard_versions (
    id SERIAL PRIMARY KEY,
    standard_id INTEGER NOT NULL REFERENCES reference_standards(id) ON DELETE CASCADE,
    standard_document_id INTEGER NOT NULL,
    version_label VARCHAR(100) NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    parser_version VARCHAR(100) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    supersedes_version_id INTEGER REFERENCES reference_standard_versions(id) ON DELETE SET NULL,
    effective_from TIMESTAMP WITH TIME ZONE,
    retired_at TIMESTAMP WITH TIME ZONE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT ck_reference_standard_versions_status
        CHECK (status IN ('draft', 'review', 'approved', 'retired')),
    CONSTRAINT uq_reference_standard_versions_standard_document
        UNIQUE (standard_document_id),
    CONSTRAINT fk_reference_standard_versions_standard_document
        FOREIGN KEY (standard_document_id) REFERENCES standard_documents(id) ON DELETE RESTRICT
);

ALTER TABLE reference_standards
    ADD CONSTRAINT fk_reference_standards_current_version
    FOREIGN KEY (current_version_id)
    REFERENCES reference_standard_versions(id)
    ON DELETE SET NULL;

CREATE OR REPLACE FUNCTION enforce_reference_standard_current_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM reference_standards rs
    LEFT JOIN reference_standard_versions v ON v.id = rs.current_version_id
    WHERE rs.current_version_id IS NOT NULL
      AND (v.id IS NULL OR v.standard_id <> rs.id OR v.status <> 'approved')
  ) THEN
    RAISE EXCEPTION 'current_version_id must reference an approved version of the same standard'
      USING ERRCODE = '23514';
  END IF;
  RETURN NULL;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'ck_reference_standards_current_version_deferred'
  ) THEN
    CREATE CONSTRAINT TRIGGER ck_reference_standards_current_version_deferred
    AFTER INSERT OR UPDATE OF current_version_id ON reference_standards
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'ck_reference_standard_versions_current_target_deferred'
  ) THEN
    CREATE CONSTRAINT TRIGGER ck_reference_standard_versions_current_target_deferred
    AFTER INSERT OR UPDATE OR DELETE ON reference_standard_versions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION enforce_reference_standard_current_version();
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS ix_reference_standard_versions_standard_status
ON reference_standard_versions(standard_id, status);

CREATE TABLE IF NOT EXISTS standard_indicators (
    id SERIAL PRIMARY KEY,
    canonical_key VARCHAR(200) NOT NULL,
    name_en VARCHAR(200) NOT NULL,
    name_cn VARCHAR(200),
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    domain VARCHAR(100),
    specimen_or_modality VARCHAR(100),
    data_type VARCHAR(50) NOT NULL DEFAULT 'qualitative',
    scale_or_method VARCHAR(200),
    default_unit VARCHAR(50),
    clinical_dimension VARCHAR(100),
    allows_numeric_comparison BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_standard_indicators_canonical_key UNIQUE (canonical_key)
);

CREATE TABLE IF NOT EXISTS standard_segments (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    section_title VARCHAR(300),
    paragraph_index INTEGER,
    table_index INTEGER,
    row_index INTEGER,
    column_index INTEGER,
    raw_text TEXT NOT NULL,
    segment_type VARCHAR(50) NOT NULL,
    parse_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    review_status VARCHAR(50) NOT NULL DEFAULT 'pending',
    source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_segments_version_location
ON standard_segments(version_id, table_index, row_index);

CREATE TABLE IF NOT EXISTS standard_parse_candidates (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    segment_id INTEGER NOT NULL REFERENCES standard_segments(id) ON DELETE CASCADE,
    source_type VARCHAR(50) NOT NULL,
    parser_version VARCHAR(100) NOT NULL,
    model_name VARCHAR(100),
    prompt_version VARCHAR(100),
    raw_output TEXT,
    candidate_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_parse_candidates_segment
ON standard_parse_candidates(segment_id);

CREATE TABLE IF NOT EXISTS standard_rules (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    indicator_id INTEGER REFERENCES standard_indicators(id) ON DELETE SET NULL,
    source_segment_id INTEGER REFERENCES standard_segments(id) ON DELETE SET NULL,
    rule_type VARCHAR(50) NOT NULL,
    comparator VARCHAR(5),
    lower DOUBLE PRECISION,
    upper DOUBLE PRECISION,
    lower_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    upper_inclusive BOOLEAN NOT NULL DEFAULT TRUE,
    unit VARCHAR(50),
    sex VARCHAR(10),
    category VARCHAR(100),
    applicability JSONB NOT NULL DEFAULT '{}'::jsonb,
    target_state_type VARCHAR(50) NOT NULL,
    target_state_value VARCHAR(200),
    clinical_dimension VARCHAR(100),
    evidence_type VARCHAR(100),
    machine_actionability VARCHAR(50) NOT NULL DEFAULT 'evidence-only',
    interpretation TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    conflict_group VARCHAR(100),
    framework VARCHAR(100),
    biomarker_axis VARCHAR(10),
    biomarker_state VARCHAR(100),
    stage VARCHAR(100),
    clinical_function TEXT,
    conditions JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_rules_version_indicator
ON standard_rules(version_id, indicator_id);

CREATE INDEX IF NOT EXISTS ix_standard_rules_conflict_group
ON standard_rules(version_id, conflict_group);

CREATE TABLE IF NOT EXISTS standard_rule_conditions (
    id SERIAL PRIMARY KEY,
    rule_id INTEGER NOT NULL REFERENCES standard_rules(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES standard_rule_conditions(id) ON DELETE CASCADE,
    node_type VARCHAR(50) NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_standard_rule_conditions_rule_parent
ON standard_rule_conditions(rule_id, parent_id);

CREATE TABLE IF NOT EXISTS standard_change_logs (
    id SERIAL PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES reference_standard_versions(id) ON DELETE CASCADE,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER NOT NULL,
    action VARCHAR(50) NOT NULL,
    before_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_standard_change_logs_entity
ON standard_change_logs(entity_type, entity_id);

ALTER TABLE reference_ranges
    ADD COLUMN IF NOT EXISTS standard_id INTEGER REFERENCES reference_standards(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS standard_version_id INTEGER REFERENCES reference_standard_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS standard_rule_id INTEGER REFERENCES standard_rules(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS applicability_hash VARCHAR(64),
    ADD COLUMN IF NOT EXISTS is_current_projection BOOLEAN NOT NULL DEFAULT FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS uq_reference_ranges_current_projection
ON reference_ranges(standard_id, indicator_name, sex, category, applicability_hash)
WHERE is_current_projection IS TRUE;

-- 12. 全文检索索引
--    langchain-postgres 自动管理 langchain_pg_collection 和 langchain_pg_embedding 表。
--    启动时由 ensure_vectorstore_tables() 在 langchain_pg_embedding.document 列上
--    创建 pg_trgm GIN 索引（idx_langchain_embedding_document_trgm），
--    同时清理旧版 tsvector 索引。
