"""Durable report generation leases and scoped idempotency."""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

JOB_SCHEMA = """
CREATE TABLE report_generation_jobs (
    report_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    source_case_id INTEGER NOT NULL,
    generation_context JSONB NOT NULL,
    context_sha256 VARCHAR(64) NOT NULL,
    status VARCHAR(12) DEFAULT 'queued' NOT NULL,
    phase VARCHAR(24) DEFAULT 'queued' NOT NULL,
    revision BIGINT DEFAULT '1' NOT NULL,
    queued_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    queue_deadline TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    heartbeat_at TIMESTAMP WITH TIME ZONE,
    lease_expires_at TIMESTAMP WITH TIME ZONE,
    run_deadline TIMESTAMP WITH TIME ZONE,
    lease_owner VARCHAR(160),
    lease_token UUID,
    cancel_requested_at TIMESTAMP WITH TIME ZONE,
    error_code VARCHAR(120),
    PRIMARY KEY (report_id),
    CONSTRAINT ck_report_jobs_status CHECK (status IN ('queued','running','completed','failed','cancelled')),
    CONSTRAINT ck_report_jobs_phase CHECK (phase IN ('queued','model_loading','prediction','standard_evidence','rendering','persistence','terminal')),
    CONSTRAINT ck_report_jobs_revision CHECK (revision >= 1),
    CONSTRAINT ck_report_jobs_context CHECK (jsonb_typeof(generation_context) = 'object'),
    CONSTRAINT ck_report_jobs_context_hash CHECK (context_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_report_jobs_running CHECK (status != 'running' OR (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND started_at IS NOT NULL AND lease_expires_at IS NOT NULL AND run_deadline IS NOT NULL AND phase NOT IN ('queued','terminal'))),
    CONSTRAINT ck_report_jobs_terminal CHECK (status NOT IN ('completed','failed','cancelled') OR (finished_at IS NOT NULL AND phase = 'terminal')),
    CONSTRAINT ck_report_jobs_queued CHECK (status != 'queued' OR (started_at IS NULL AND phase = 'queued')),
    FOREIGN KEY(report_id) REFERENCES ai_reports (id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX ix_report_jobs_queued ON report_generation_jobs (queued_at, report_id) WHERE status = 'queued';
CREATE INDEX ix_report_jobs_running_lease ON report_generation_jobs (lease_expires_at) WHERE status = 'running';
CREATE INDEX ix_report_jobs_user_status ON report_generation_jobs (user_id, status);
CREATE UNIQUE INDEX uq_report_jobs_active_case ON report_generation_jobs (user_id, source_case_id) WHERE status IN ('queued','running');
"""


def upgrade():
    op.execute(JOB_SCHEMA)
    op.drop_constraint(
        "ck_operator_idempotency_keys_scope", "operator_idempotency_keys", type_="check"
    )
    op.drop_constraint(
        "ck_operator_idempotency_keys_resource_type",
        "operator_idempotency_keys",
        type_="check",
    )
    op.create_check_constraint(
        "ck_operator_idempotency_keys_scope_resource",
        "operator_idempotency_keys",
        "(scope = 'create_longitudinal_case' AND resource_type = 'operator_case') OR (scope = 'create_longitudinal_report' AND resource_type = 'ai_report')",
    )


def downgrade():
    # Fail if report tombstones exist; do not delete their history to downgrade.
    op.create_check_constraint(
        "ck_operator_idempotency_keys_scope",
        "operator_idempotency_keys",
        "scope = 'create_longitudinal_case'",
    )
    op.create_check_constraint(
        "ck_operator_idempotency_keys_resource_type",
        "operator_idempotency_keys",
        "resource_type = 'operator_case'",
    )
    op.drop_constraint(
        "ck_operator_idempotency_keys_scope_resource",
        "operator_idempotency_keys",
        type_="check",
    )
    op.drop_table("report_generation_jobs")
