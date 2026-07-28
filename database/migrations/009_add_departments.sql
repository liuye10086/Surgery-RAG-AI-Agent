-- 009: 科室分类筛选
-- 新增 departments 表 + documents 表 department_id 外键 + 种子数据

-- 1. 科室表
CREATE TABLE IF NOT EXISTS departments (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. 文档表新增科室外键
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'documents' AND column_name = 'department_id'
    ) THEN
        ALTER TABLE documents ADD COLUMN department_id INTEGER
            REFERENCES departments(id) ON DELETE RESTRICT;
    END IF;
END $$;

-- 3. 索引
CREATE INDEX IF NOT EXISTS idx_documents_department_id ON documents(department_id);

-- 4. 种子数据（使用 ON CONFLICT 保证幂等）
INSERT INTO departments (name) VALUES
    ('肝胆外科'),
    ('神经外科'),
    ('骨科'),
    ('心胸外科'),
    ('泌尿外科'),
    ('胃肠外科'),
    ('甲状腺乳腺外科'),
    ('血管外科'),
    ('烧伤整形外科'),
    ('麻醉科'),
    ('其他')
ON CONFLICT (name) DO NOTHING;
