"""Persist synthetic publication identity without weakening clinical statuses."""

from alembic import op
import sqlalchemy as sa

revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None

OLD = {
    'ck_ai_reports_fingerprint_version': "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2')",
    'ck_ai_reports_evidence_status': "evidence_status IS NULL OR evidence_status IN ('complete', 'partial')",
    'ck_ai_reports_standard_evidence_status': "standard_evidence_status IS NULL OR standard_evidence_status IN ('available', 'context_incomplete', 'not_applicable', 'conflict')",
    'ck_ai_reports_reference_case_status': "reference_case_status IS NULL OR reference_case_status IN ('available', 'no_eligible_cases', 'insufficient_comparability', 'reference_query_failed', 'reference_index_stale')",
}
SYNTHETIC = "generation_fingerprint_version IS DISTINCT FROM 'v3' OR (analysis_type = 'synthetic_numeric' AND status = 'completed' AND report_document IS NOT NULL AND report_document_sha256 IS NOT NULL AND generation_fingerprint IS NOT NULL AND input_snapshot IS NOT NULL AND input_snapshot_sha256 IS NOT NULL AND evidence_snapshot IS NOT NULL AND evidence_snapshot_sha256 IS NOT NULL AND report_document->>'schema_version' = 'synthetic_numeric_report_document.v1' AND evidence_status = 'not_requested' AND standard_evidence_status = 'not_requested' AND reference_case_status = 'not_requested') IS TRUE"
EVIDENCE = "(evidence_status IS DISTINCT FROM 'not_requested' AND standard_evidence_status IS DISTINCT FROM 'not_requested' AND reference_case_status IS DISTINCT FROM 'not_requested') OR (generation_fingerprint_version = 'v3') IS TRUE"


def upgrade():
    for name, expression in OLD.items():
        op.drop_constraint(name, 'ai_reports', type_='check')
        value = 'v3' if name == 'ck_ai_reports_fingerprint_version' else 'not_requested'
        op.create_check_constraint(name, 'ai_reports', expression[:-1] + ", '" + value + "')")
    op.create_check_constraint('ck_ai_reports_synthetic_publication', 'ai_reports', SYNTHETIC)
    op.create_check_constraint('ck_ai_reports_engineering_evidence', 'ai_reports', EVIDENCE)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM ai_reports WHERE generation_fingerprint_version='v3')")).scalar():
        raise RuntimeError('synthetic_publication_downgrade_would_discard_identity')
    op.drop_constraint('ck_ai_reports_engineering_evidence', 'ai_reports', type_='check')
    op.drop_constraint('ck_ai_reports_synthetic_publication', 'ai_reports', type_='check')
    for name, expression in OLD.items():
        op.drop_constraint(name, 'ai_reports', type_='check')
        op.create_check_constraint(name, 'ai_reports', expression)
