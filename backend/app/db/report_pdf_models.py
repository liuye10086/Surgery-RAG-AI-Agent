"""Static ORM contract for migration 0026 (no runtime reflection)."""

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    DateTime,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base


class ReportPdfArchive(Base):
    __tablename__ = "report_pdf_archives"
    __table_args__ = (
        CheckConstraint(
            "published_attempt_id IS NULL AND (state::text = ANY (ARRAY['queued'::character varying, 'rendering'::character varying, 'failed'::character varying]::text[])) AND pdf_sha256 IS NULL AND size_bytes IS NULL AND page_count IS NULL AND archived_at IS NULL OR published_attempt_id IS NOT NULL AND (state::text = ANY (ARRAY['ready'::character varying, 'missing'::character varying, 'corrupt'::character varying]::text[])) AND pdf_sha256 IS NOT NULL AND pdf_sha256::text ~ '^[0-9a-f]{64}$'::text AND size_bytes IS NOT NULL AND size_bytes >= 1 AND size_bytes <= 67108864 AND page_count IS NOT NULL AND page_count >= 1 AND page_count <= 200 AND archived_at IS NOT NULL",
            name="ck_pdf_published",
        ),
        CheckConstraint(
            "delivery_count >= 0", name="report_pdf_archives_delivery_count_check"
        ),
        CheckConstraint(
            "renderer_sha256::text ~ '^[0-9a-f]{64}$'::text",
            name="report_pdf_archives_renderer_sha256_check",
        ),
        CheckConstraint("revision > 0", name="report_pdf_archives_revision_check"),
        CheckConstraint(
            "source_integrity::text = ANY (ARRAY['valid'::character varying, 'unverifiable'::character varying]::text[])",
            name="report_pdf_archives_source_integrity_check",
        ),
        CheckConstraint(
            "source_sha256::text ~ '^[0-9a-f]{64}$'::text",
            name="report_pdf_archives_source_sha256_check",
        ),
        CheckConstraint(
            "state::text = ANY (ARRAY['queued'::character varying, 'rendering'::character varying, 'ready'::character varying, 'failed'::character varying, 'missing'::character varying, 'corrupt'::character varying]::text[])",
            name="report_pdf_archives_state_check",
        ),
        ForeignKeyConstraint(
            ["report_id", "current_attempt_id"],
            ["report_pdf_attempts.report_id", "report_pdf_attempts.id"],
            name="fk_pdf_current_attempt",
            initially="DEFERRED",
            deferrable=True,
        ),
        ForeignKeyConstraint(
            ["report_id", "published_attempt_id"],
            ["report_pdf_attempts.report_id", "report_pdf_attempts.id"],
            name="fk_pdf_published_attempt",
            initially="DEFERRED",
            deferrable=True,
        ),
        ForeignKeyConstraint(
            ["report_id"],
            ["ai_reports.id"],
            name="report_pdf_archives_report_id_fkey",
            ondelete="CASCADE",
        ),
    )
    report_id = Column(Integer, nullable=False, primary_key=True)
    state = Column(String(12), nullable=False)
    revision = Column(BigInteger, nullable=False, server_default=text("1"))
    source_sha256 = Column(String(64), nullable=False)
    source_integrity = Column(String(16), nullable=False)
    renderer_sha256 = Column(String(64), nullable=False)
    current_attempt_id = Column(Integer, nullable=True)
    published_attempt_id = Column(Integer, nullable=True)
    pdf_sha256 = Column(String(64), nullable=True)
    size_bytes = Column(BigInteger, nullable=True)
    page_count = Column(Integer, nullable=True)
    archived_at = Column(DateTime(timezone=True), nullable=True)
    delivery_count = Column(BigInteger, nullable=False, server_default=text("0"))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )


class ReportPdfAttempt(Base):
    __tablename__ = "report_pdf_attempts"
    __table_args__ = (
        CheckConstraint(
            "status::text <> 'running'::text OR lease_token IS NOT NULL AND lease_owner IS NOT NULL AND run_deadline IS NOT NULL AND lease_expires_at IS NOT NULL AND started_at IS NOT NULL",
            name="ck_pdf_attempt_running",
        ),
        CheckConstraint(
            "(status::text <> ALL (ARRAY['completed'::character varying, 'failed'::character varying]::text[])) OR finished_at IS NOT NULL",
            name="ck_pdf_attempt_terminal",
        ),
        CheckConstraint(
            "object_key::text ~ '^reports/[1-9][0-9]*/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/document\\.pdf$'::text AND split_part(object_key::text, '/'::text, 2) = report_id::text",
            name="ck_pdf_object_key",
        ),
        CheckConstraint(
            "phase::text = ANY (ARRAY['queued'::character varying, 'source_validation'::character varying, 'html'::character varying, 'browser_launch'::character varying, 'fonts'::character varying, 'print'::character varying, 'storage'::character varying, 'publish'::character varying, 'terminal'::character varying]::text[])",
            name="report_pdf_attempts_phase_check",
        ),
        CheckConstraint(
            "renderer_sha256::text ~ '^[0-9a-f]{64}$'::text",
            name="report_pdf_attempts_renderer_sha256_check",
        ),
        CheckConstraint(
            "source_sha256::text ~ '^[0-9a-f]{64}$'::text",
            name="report_pdf_attempts_source_sha256_check",
        ),
        CheckConstraint(
            "status::text = ANY (ARRAY['queued'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying]::text[])",
            name="report_pdf_attempts_status_check",
        ),
        ForeignKeyConstraint(
            ["report_id"],
            ["report_pdf_archives.report_id"],
            name="report_pdf_attempts_report_id_fkey",
            ondelete="CASCADE",
        ),
        UniqueConstraint("object_key", name="report_pdf_attempts_object_key_key"),
        UniqueConstraint(
            "report_id", "id", name="report_pdf_attempts_report_id_id_key"
        ),
        Index(
            "ix_pdf_lease",
            "lease_expires_at",
            unique=False,
            postgresql_where=text("((status)::text = 'running'::text)"),
        ),
        Index(
            "ix_pdf_queue",
            "queued_at",
            "id",
            unique=False,
            postgresql_where=text("((status)::text = 'queued'::text)"),
        ),
        Index(
            "uq_pdf_active_attempt",
            "report_id",
            unique=True,
            postgresql_where=text(
                "((status)::text = ANY ((ARRAY['queued'::character varying, 'running'::character varying])::text[]))"
            ),
        ),
    )
    id = Column(Integer, nullable=False, primary_key=True)
    report_id = Column(Integer, nullable=False)
    status = Column(String(12), nullable=False)
    phase = Column(String(24), nullable=False)
    object_key = Column(String(180), nullable=False)
    source_sha256 = Column(String(64), nullable=False)
    renderer_sha256 = Column(String(64), nullable=False)
    queued_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    queue_deadline = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    heartbeat_at = Column(DateTime(timezone=True), nullable=True)
    run_deadline = Column(DateTime(timezone=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    lease_owner = Column(String(160), nullable=True)
    lease_token = Column(UUID(as_uuid=True), nullable=True)
    error_code = Column(String(120), nullable=True)


class ReportPdfDelivery(Base):
    __tablename__ = "report_pdf_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id"],
            ["report_pdf_archives.report_id"],
            name="report_pdf_deliveries_report_id_fkey",
            ondelete="CASCADE",
        ),
        Index("ix_pdf_deliveries_report", "report_id", unique=False),
    )
    delivery_id = Column(UUID(as_uuid=True), nullable=False, primary_key=True)
    report_id = Column(Integer, nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )


class ReportFileCleanupTask(Base):
    __tablename__ = "report_file_cleanup_tasks"
    __table_args__ = (
        CheckConstraint(
            "failure_count >= 0", name="report_file_cleanup_tasks_failure_count_check"
        ),
        CheckConstraint(
            "state::text = ANY (ARRAY['pending'::character varying, 'running'::character varying, 'settling'::character varying, 'done'::character varying]::text[])",
            name="report_file_cleanup_tasks_state_check",
        ),
        UniqueConstraint("object_key", name="report_file_cleanup_tasks_object_key_key"),
        Index(
            "ix_pdf_cleanup_pending",
            "next_attempt_at",
            "id",
            unique=False,
            postgresql_where=text("((state)::text <> 'done'::text)"),
        ),
    )
    id = Column(BigInteger, nullable=False, primary_key=True)
    report_id_snapshot = Column(Integer, nullable=False)
    object_key = Column(String(180), nullable=False)
    state = Column(
        String(12), nullable=False, server_default=text("'pending'::character varying")
    )
    next_attempt_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    not_before_final_check = Column(DateTime(timezone=True), nullable=False)
    lease_token = Column(UUID(as_uuid=True), nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, nullable=False, server_default=text("0"))
    error_code = Column(String(120), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)


class ReportDeletionTombstone(Base):
    __tablename__ = "report_deletion_tombstones"
    __table_args__ = ()
    report_id_snapshot = Column(Integer, nullable=False, primary_key=True)
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    )
