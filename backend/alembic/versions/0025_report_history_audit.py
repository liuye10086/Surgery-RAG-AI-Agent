"""Bounded generation audit and historical report indexes."""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TABLE report_generation_jobs ADD COLUMN last_execution_phase VARCHAR(24);
ALTER TABLE report_generation_jobs ADD COLUMN failure_phase VARCHAR(24);
ALTER TABLE report_generation_jobs ADD COLUMN audit_event_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE report_generation_jobs ADD COLUMN audit_bytes BIGINT NOT NULL DEFAULT 0;
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_audit_limits
 CHECK (audit_event_count BETWEEN 0 AND 256 AND audit_bytes BETWEEN 0 AND 8388608);
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_last_phase
 CHECK (last_execution_phase IS NULL OR last_execution_phase IN ('queued','model_loading','prediction','standard_evidence','rendering','persistence'));
ALTER TABLE report_generation_jobs ADD CONSTRAINT ck_report_jobs_failure_phase
 CHECK (failure_phase IS NULL OR failure_phase IN ('queued','model_loading','prediction','standard_evidence','rendering','persistence','unknown'));
CREATE TABLE report_generation_audit_events (
 report_id INTEGER NOT NULL REFERENCES report_generation_jobs(report_id) ON DELETE CASCADE,
 event_seq INTEGER NOT NULL CHECK (event_seq BETWEEN 1 AND 256),
 generation_batch_id UUID NOT NULL,
 event_kind VARCHAR(24) NOT NULL CHECK (event_kind IN ('phase_entered','input_prepared','invocation_started','task_finished','evidence_resolved','terminal')),
 phase VARCHAR(24) NOT NULL CHECK (phase IN ('queued','model_loading','prediction','standard_evidence','rendering','persistence','terminal','unknown')),
 task VARCHAR(160),
 payload JSONB NOT NULL CHECK (jsonb_typeof(payload)='object' AND octet_length(payload::text)<=262144),
 payload_bytes INTEGER NOT NULL CHECK (payload_bytes BETWEEN 1 AND 262144),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY (report_id,event_seq)
);
CREATE FUNCTION prevent_report_audit_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'report_audit_immutable'; END $$;
CREATE TRIGGER report_audit_immutable BEFORE UPDATE ON report_generation_audit_events
 FOR EACH ROW EXECUTE FUNCTION prevent_report_audit_update();
CREATE INDEX ix_report_history_owner_order ON ai_reports(user_id,analysis_type,created_at DESC,id DESC);
CREATE INDEX ix_report_history_owner_code ON ai_reports(user_id,(input_snapshot->>'anonymous_case_code'),created_at DESC,id DESC);
"""


def upgrade():
    op.execute(UPGRADE_SQL)


def downgrade():
    bind = op.get_bind()
    if bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM report_generation_audit_events) OR EXISTS (SELECT 1 FROM report_generation_jobs WHERE last_execution_phase IS NOT NULL OR failure_phase IS NOT NULL OR audit_event_count <> 0 OR audit_bytes <> 0)"
        )
    ).scalar_one():
        raise RuntimeError("report_audit_facts_prevent_downgrade")
    op.execute(
        "DROP TABLE report_generation_audit_events; DROP FUNCTION prevent_report_audit_update(); DROP INDEX ix_report_history_owner_order; DROP INDEX ix_report_history_owner_code;"
    )
    for name in (
        "ck_report_jobs_audit_limits",
        "ck_report_jobs_last_phase",
        "ck_report_jobs_failure_phase",
    ):
        op.drop_constraint(name, "report_generation_jobs", type_="check")
    for column in (
        "last_execution_phase",
        "failure_phase",
        "audit_event_count",
        "audit_bytes",
    ):
        op.drop_column("report_generation_jobs", column)
