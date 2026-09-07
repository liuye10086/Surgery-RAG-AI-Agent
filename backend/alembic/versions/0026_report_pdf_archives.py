"""Durable PDF originals, delivery facts and deletion compensation."""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

ARCHIVE_SQL = r"""
CREATE TABLE report_pdf_archives (
 report_id INTEGER PRIMARY KEY REFERENCES ai_reports(id) ON DELETE CASCADE,
 state VARCHAR(12) NOT NULL CHECK (state IN ('queued','rendering','ready','failed','missing','corrupt')),
 revision BIGINT NOT NULL DEFAULT 1 CHECK (revision>0),
 source_sha256 VARCHAR(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 source_integrity VARCHAR(16) NOT NULL CHECK (source_integrity IN ('valid','unverifiable')),
 renderer_sha256 VARCHAR(64) NOT NULL CHECK (renderer_sha256 ~ '^[0-9a-f]{64}$'),
 current_attempt_id INTEGER,
 published_attempt_id INTEGER,
 pdf_sha256 VARCHAR(64),
 size_bytes BIGINT,
 page_count INTEGER,
 archived_at TIMESTAMPTZ,
 delivery_count BIGINT NOT NULL DEFAULT 0 CHECK (delivery_count>=0),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 CONSTRAINT ck_pdf_published CHECK (
  (published_attempt_id IS NULL AND state IN ('queued','rendering','failed')
   AND pdf_sha256 IS NULL AND size_bytes IS NULL AND page_count IS NULL AND archived_at IS NULL)
  OR (published_attempt_id IS NOT NULL AND state IN ('ready','missing','corrupt')
   AND pdf_sha256 IS NOT NULL AND pdf_sha256 ~ '^[0-9a-f]{64}$'
   AND size_bytes IS NOT NULL AND size_bytes BETWEEN 1 AND 67108864
   AND page_count IS NOT NULL AND page_count BETWEEN 1 AND 200
   AND archived_at IS NOT NULL))
);
CREATE TABLE report_pdf_attempts (
 id SERIAL PRIMARY KEY,
 report_id INTEGER NOT NULL REFERENCES report_pdf_archives(report_id) ON DELETE CASCADE,
 status VARCHAR(12) NOT NULL CHECK (status IN ('queued','running','completed','failed')),
 phase VARCHAR(24) NOT NULL CHECK (phase IN
 ('queued','source_validation','html','browser_launch','fonts','print','storage','publish','terminal')),
 object_key VARCHAR(180) NOT NULL UNIQUE,
 source_sha256 VARCHAR(64) NOT NULL CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
 renderer_sha256 VARCHAR(64) NOT NULL CHECK (renderer_sha256 ~ '^[0-9a-f]{64}$'),
 queued_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 queue_deadline TIMESTAMPTZ NOT NULL,
 started_at TIMESTAMPTZ,
 finished_at TIMESTAMPTZ,
 heartbeat_at TIMESTAMPTZ,
 run_deadline TIMESTAMPTZ,
 lease_expires_at TIMESTAMPTZ,
 lease_owner VARCHAR(160),
 lease_token UUID,
 error_code VARCHAR(120),
 UNIQUE(report_id,id),
 CONSTRAINT ck_pdf_attempt_running CHECK (status!='running' OR
  (lease_token IS NOT NULL AND lease_owner IS NOT NULL AND run_deadline IS NOT NULL
   AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL)),
 CONSTRAINT ck_pdf_attempt_terminal CHECK (status NOT IN ('completed','failed') OR finished_at IS NOT NULL)
);
ALTER TABLE report_pdf_archives ADD CONSTRAINT fk_pdf_current_attempt
 FOREIGN KEY(report_id,current_attempt_id) REFERENCES report_pdf_attempts(report_id,id)
 DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE report_pdf_archives ADD CONSTRAINT fk_pdf_published_attempt
 FOREIGN KEY(report_id,published_attempt_id) REFERENCES report_pdf_attempts(report_id,id)
 DEFERRABLE INITIALLY DEFERRED;
CREATE UNIQUE INDEX uq_pdf_active_attempt ON report_pdf_attempts(report_id)
 WHERE status IN ('queued','running');
CREATE INDEX ix_pdf_queue ON report_pdf_attempts(queued_at,id) WHERE status='queued';
CREATE INDEX ix_pdf_lease ON report_pdf_attempts(lease_expires_at) WHERE status='running';
CREATE TABLE report_pdf_deliveries (
 delivery_id UUID PRIMARY KEY,
 report_id INTEGER NOT NULL REFERENCES report_pdf_archives(report_id) ON DELETE CASCADE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ix_pdf_deliveries_report ON report_pdf_deliveries(report_id);
CREATE TABLE report_file_cleanup_tasks (
 id BIGSERIAL PRIMARY KEY,
 report_id_snapshot INTEGER NOT NULL,
 object_key VARCHAR(180) NOT NULL UNIQUE,
 state VARCHAR(12) NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','running','settling','done')),
 next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 not_before_final_check TIMESTAMPTZ NOT NULL,
 lease_token UUID,
 lease_expires_at TIMESTAMPTZ,
 failure_count INTEGER NOT NULL DEFAULT 0 CHECK (failure_count>=0),
 error_code VARCHAR(120),
 created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
 completed_at TIMESTAMPTZ
);
CREATE INDEX ix_pdf_cleanup_pending ON report_file_cleanup_tasks(next_attempt_at,id)
 WHERE state!='done';
CREATE TABLE report_deletion_tombstones (
 report_id_snapshot INTEGER PRIMARY KEY,
 deleted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE FUNCTION enqueue_pdf_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO report_file_cleanup_tasks(report_id_snapshot,object_key,not_before_final_check)
 VALUES(OLD.report_id,OLD.object_key,
  GREATEST(clock_timestamp(),COALESCE(OLD.run_deadline,clock_timestamp()))+interval '60 seconds')
 ON CONFLICT(object_key) DO UPDATE SET
  state='pending',completed_at=NULL,
  next_attempt_at=clock_timestamp(),
  not_before_final_check=GREATEST(report_file_cleanup_tasks.not_before_final_check,EXCLUDED.not_before_final_check);
 RETURN OLD;
END $$;
CREATE TRIGGER report_pdf_attempt_cleanup BEFORE DELETE ON report_pdf_attempts
 FOR EACH ROW EXECUTE FUNCTION enqueue_pdf_cleanup();
CREATE FUNCTION remember_report_deletion() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 INSERT INTO report_deletion_tombstones(report_id_snapshot)
 VALUES(OLD.id) ON CONFLICT(report_id_snapshot) DO NOTHING;
 RETURN OLD;
END $$;
CREATE TRIGGER remember_report_deletion BEFORE DELETE ON ai_reports
 FOR EACH ROW EXECUTE FUNCTION remember_report_deletion();
"""

GUARD_SQL = r"""
ALTER TABLE report_pdf_attempts ADD CONSTRAINT ck_pdf_object_key CHECK
 (object_key ~ '^reports/[1-9][0-9]*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/document\.pdf$'
 AND split_part(object_key,'/',2)=report_id::text);
ALTER TABLE operator_idempotency_keys DROP CONSTRAINT ck_operator_idempotency_keys_scope_resource;
ALTER TABLE operator_idempotency_keys ADD CONSTRAINT ck_operator_idempotency_keys_scope_resource CHECK
 ((scope='create_longitudinal_case' AND resource_type='operator_case') OR
  (scope='create_longitudinal_report' AND resource_type='ai_report') OR
  (scope IN ('prepare_report_pdf','retry_report_pdf') AND resource_type='report_pdf_attempt'));
CREATE FUNCTION guard_pdf_original() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.published_attempt_id IS NOT NULL AND ROW(OLD.report_id,OLD.source_sha256,OLD.source_integrity,OLD.renderer_sha256,OLD.current_attempt_id,OLD.published_attempt_id,OLD.pdf_sha256,OLD.size_bytes,OLD.page_count,OLD.archived_at)
 IS DISTINCT FROM ROW(NEW.report_id,NEW.source_sha256,NEW.source_integrity,NEW.renderer_sha256,NEW.current_attempt_id,NEW.published_attempt_id,NEW.pdf_sha256,NEW.size_bytes,NEW.page_count,NEW.archived_at)
 THEN RAISE EXCEPTION 'pdf_original_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pdf_original_immutable BEFORE UPDATE ON report_pdf_archives FOR EACH ROW EXECUTE FUNCTION guard_pdf_original();
CREATE FUNCTION guard_pdf_delivery() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'pdf_delivery_immutable'; END $$;
CREATE TRIGGER pdf_delivery_immutable BEFORE UPDATE ON report_pdf_deliveries FOR EACH ROW EXECUTE FUNCTION guard_pdf_delivery();
CREATE FUNCTION guard_pdf_attempt_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF ROW(OLD.id,OLD.report_id,OLD.object_key,OLD.source_sha256,OLD.renderer_sha256)
 IS DISTINCT FROM ROW(NEW.id,NEW.report_id,NEW.object_key,NEW.source_sha256,NEW.renderer_sha256)
 OR (OLD.status IN ('completed','failed') AND OLD IS DISTINCT FROM NEW)
 THEN RAISE EXCEPTION 'pdf_attempt_immutable'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER pdf_attempt_identity_immutable BEFORE UPDATE ON report_pdf_attempts FOR EACH ROW EXECUTE FUNCTION guard_pdf_attempt_identity();
"""


def upgrade():
    op.execute(ARCHIVE_SQL)
    op.execute(GUARD_SQL)


def downgrade():
    bind = op.get_bind()
    for table in (
        "report_pdf_archives",
        "report_pdf_attempts",
        "report_pdf_deliveries",
        "report_file_cleanup_tasks",
        "report_deletion_tombstones",
    ):
        if bind.execute(sa.text(f"SELECT EXISTS(SELECT 1 FROM {table})")).scalar_one():
            raise RuntimeError("pdf_archive_facts_prevent_downgrade")
    if bind.execute(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM operator_idempotency_keys WHERE scope IN ('prepare_report_pdf','retry_report_pdf'))"
        )
    ).scalar_one():
        raise RuntimeError("pdf_idempotency_facts_prevent_downgrade")
    op.execute(
        "DROP TRIGGER remember_report_deletion ON ai_reports; DROP TABLE report_pdf_deliveries; ALTER TABLE report_pdf_archives DROP CONSTRAINT fk_pdf_current_attempt, DROP CONSTRAINT fk_pdf_published_attempt; DROP TABLE report_pdf_attempts; DROP TABLE report_pdf_archives; DROP TABLE report_file_cleanup_tasks; DROP TABLE report_deletion_tombstones; DROP FUNCTION enqueue_pdf_cleanup(); DROP FUNCTION remember_report_deletion(); DROP FUNCTION guard_pdf_original(); DROP FUNCTION guard_pdf_delivery(); DROP FUNCTION guard_pdf_attempt_identity();"
    )
    op.execute(
        "ALTER TABLE operator_idempotency_keys DROP CONSTRAINT ck_operator_idempotency_keys_scope_resource; ALTER TABLE operator_idempotency_keys ADD CONSTRAINT ck_operator_idempotency_keys_scope_resource CHECK ((scope='create_longitudinal_case' AND resource_type='operator_case') OR (scope='create_longitudinal_report' AND resource_type='ai_report'));"
    )
