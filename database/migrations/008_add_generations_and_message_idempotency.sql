-- 文档代次和聊天请求幂等字段。

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS active_generation INTEGER NOT NULL DEFAULT 1;

ALTER TABLE chunks
ADD COLUMN IF NOT EXISTS generation INTEGER NOT NULL DEFAULT 1;

ALTER TABLE messages
ADD COLUMN IF NOT EXISTS client_request_id VARCHAR(64);

CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_session_client_request
ON messages(session_id, client_request_id)
WHERE client_request_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_chunks_document_generation
ON chunks(document_id, generation);
