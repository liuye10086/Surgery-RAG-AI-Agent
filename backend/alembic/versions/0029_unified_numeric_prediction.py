"""Add source-independent case bindings and v4 publications."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None
SOURCE = "prediction_source IS NULL OR (engineering_source IS NULL AND jsonb_typeof(prediction_source) = 'object' AND (prediction_source->>'schema_version' = 'prediction_case_source.v1') IS TRUE AND ((prediction_source->>'source_kind' = 'synthetic' AND prediction_source->'is_synthetic' = 'true'::jsonb) OR (prediction_source->>'source_kind' = 'real' AND prediction_source->'is_synthetic' = 'false'::jsonb)) IS TRUE)"
OLD_FP = "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2', 'v3')"
FP = "generation_fingerprint_version IS NULL OR generation_fingerprint_version IN ('v1', 'v2', 'v3', 'v4')"
OLD_EV = "(evidence_status IS DISTINCT FROM 'not_requested' AND standard_evidence_status IS DISTINCT FROM 'not_requested' AND reference_case_status IS DISTINCT FROM 'not_requested') OR (generation_fingerprint_version = 'v3') IS TRUE"
EV = "(evidence_status IS DISTINCT FROM 'not_requested' AND standard_evidence_status IS DISTINCT FROM 'not_requested' AND reference_case_status IS DISTINCT FROM 'not_requested') OR (generation_fingerprint_version IN ('v3', 'v4')) IS TRUE"
NUMERIC = "generation_fingerprint_version IS DISTINCT FROM 'v4' OR (analysis_type = 'numeric_prediction' AND status = 'completed' AND report_document IS NOT NULL AND report_document_sha256 IS NOT NULL AND generation_fingerprint IS NOT NULL AND input_snapshot IS NOT NULL AND input_snapshot_sha256 IS NOT NULL AND evidence_snapshot IS NOT NULL AND evidence_snapshot_sha256 IS NOT NULL AND report_document->>'schema_version' = 'numeric_report_document.v1' AND evidence_status = 'not_requested' AND standard_evidence_status = 'not_requested' AND reference_case_status = 'not_requested') IS TRUE"

def upgrade():
    op.add_column('operator_cases', sa.Column('prediction_source', postgresql.JSONB(none_as_null=True), nullable=True))
    op.create_check_constraint('ck_operator_cases_prediction_source', 'operator_cases', SOURCE)
    for name, expression in [('ck_ai_reports_fingerprint_version', FP), ('ck_ai_reports_engineering_evidence', EV)]:
        op.drop_constraint(name, 'ai_reports', type_='check')
        op.create_check_constraint(name, 'ai_reports', expression)
    op.create_check_constraint('ck_ai_reports_numeric_publication', 'ai_reports', NUMERIC)

def downgrade():
    if op.get_bind().execute(sa.text("SELECT EXISTS (SELECT 1 FROM operator_cases WHERE prediction_source IS NOT NULL) OR EXISTS (SELECT 1 FROM ai_reports WHERE generation_fingerprint_version='v4' OR analysis_type='numeric_prediction' OR input_snapshot->>'report_kind'='numeric_prediction') OR EXISTS (SELECT 1 FROM report_generation_jobs WHERE generation_context->>'schema_version'='numeric_generation_context.v1')")).scalar():
        raise RuntimeError('numeric_downgrade_would_discard_saved_facts')
    op.drop_constraint('ck_ai_reports_numeric_publication', 'ai_reports', type_='check')
    for name, expression in [('ck_ai_reports_fingerprint_version', OLD_FP), ('ck_ai_reports_engineering_evidence', OLD_EV)]:
        op.drop_constraint(name, 'ai_reports', type_='check')
        op.create_check_constraint(name, 'ai_reports', expression)
    op.drop_constraint('ck_operator_cases_prediction_source', 'operator_cases', type_='check')
    op.drop_column('operator_cases', 'prediction_source')
