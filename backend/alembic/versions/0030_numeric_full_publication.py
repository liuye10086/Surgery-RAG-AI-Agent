"""Allow v5 trained numeric publications without changing saved v1-v4 facts."""
from alembic import op
import sqlalchemy as sa

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None
OLD_FP = "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2', 'v3', 'v4')"
FP = "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2', 'v3', 'v4', 'v5')"
OLD_EV = "(evidence_status IS DISTINCT FROM 'not_requested' AND standard_evidence_status IS DISTINCT FROM 'not_requested' AND reference_case_status IS DISTINCT FROM 'not_requested') OR (generation_fingerprint_version IN ('v3', 'v4')) IS TRUE"
EV = "(evidence_status IS DISTINCT FROM 'not_requested' AND standard_evidence_status IS DISTINCT FROM 'not_requested' AND reference_case_status IS DISTINCT FROM 'not_requested') OR (generation_fingerprint_version IN ('v3', 'v4', 'v5')) IS TRUE"
FULL = "generation_fingerprint_version IS DISTINCT FROM 'v5' OR (analysis_type = 'numeric_prediction' AND status = 'completed' AND report_document IS NOT NULL AND report_document_sha256 IS NOT NULL AND generation_fingerprint IS NOT NULL AND input_snapshot IS NOT NULL AND input_snapshot_sha256 IS NOT NULL AND evidence_snapshot IS NOT NULL AND evidence_snapshot_sha256 IS NOT NULL AND report_document->>'schema_version' = 'numeric_report_document.v2' AND evidence_status IN ('complete', 'partial') AND standard_evidence_status = 'not_requested' AND reference_case_status IN ('available', 'no_eligible_cases', 'reference_query_failed')) IS TRUE"


def upgrade():
    for name, expression in [('ck_ai_reports_fingerprint_version', FP), ('ck_ai_reports_engineering_evidence', EV)]:
        op.drop_constraint(name, 'ai_reports', type_='check')
        op.create_check_constraint(name, 'ai_reports', expression)
    op.create_check_constraint('ck_ai_reports_numeric_full_publication', 'ai_reports', FULL)


def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM ai_reports WHERE generation_fingerprint_version='v5' OR report_document->>'schema_version'='numeric_report_document.v2') OR EXISTS (SELECT 1 FROM report_generation_jobs WHERE generation_context->>'schema_version'='numeric_generation_context.v2')")).scalar():
        raise RuntimeError('numeric_full_downgrade_would_discard_saved_facts')
    op.drop_constraint('ck_ai_reports_numeric_full_publication', 'ai_reports', type_='check')
    for name, expression in [('ck_ai_reports_fingerprint_version', OLD_FP), ('ck_ai_reports_engineering_evidence', OLD_EV)]:
        op.drop_constraint(name, 'ai_reports', type_='check')
        op.create_check_constraint(name, 'ai_reports', expression)
