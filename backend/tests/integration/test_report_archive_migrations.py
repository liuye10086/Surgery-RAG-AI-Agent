"""Fresh SQL snapshot / migration equivalence and data-preserving downgrade gates."""
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine,text,inspect
from sqlalchemy.engine import make_url
from scripts.seed_operator_report_e2e import require_test_database


def test_clean_schema_matches_migrations_and_refuses_fact_loss():
    root=Path(__file__).resolve().parents[3]
    url=make_url(os.environ['TEST_DATABASE_URL']);require_test_database(str(url))
    names=['archive_schema_'+uuid4().hex+'_test','archive_migration_'+uuid4().hex+'_test']
    admin=create_engine(url.set(database='postgres'),isolation_level='AUTOCOMMIT')
    engines=[];result={}
    try:
        for name in names:
            with admin.connect() as conn:conn.execute(text('CREATE DATABASE "'+name+'"'))
            engines.append(create_engine(url.set(database=name)))
        with engines[0].begin() as conn:conn.execute(text((root/'database/schema.sql').read_text(encoding='utf-8')))
        result['schema_clean_install']=True
        env={**os.environ,'DATABASE_URL':url.set(database=names[1]).render_as_string(hide_password=False)}
        def migrate(command,revision):
            return subprocess.run(['python','-m','alembic',command,revision],cwd=root/'backend',env=env,capture_output=True,text=True)
        for command,revision in [('upgrade','head'),('downgrade','0024'),('upgrade','head')]:
            executed=migrate(command,revision);assert executed.returncode==0,executed.stderr[-2000:]
        result['migration_empty_roundtrip']=True
        tables=['report_generation_jobs','report_generation_audit_events','report_pdf_archives','report_pdf_attempts','report_pdf_deliveries','report_file_cleanup_tasks','report_deletion_tombstones']
        with engines[0].connect() as left,engines[1].connect() as right:
            a,b=inspect(left),inspect(right)
            def columns(inspector,table):return sorted((c['name'],str(c['type']),c['nullable']) for c in inspector.get_columns(table))
            for table in tables:
                assert columns(a,table)==columns(b,table),table
                assert {c['sqltext'] for c in a.get_check_constraints(table)}=={c['sqltext'] for c in b.get_check_constraints(table)},table
        result.update(columns_equal=True,checks_equal=True)
        with engines[1].begin() as conn:conn.execute(text('INSERT INTO report_deletion_tombstones(report_id_snapshot) VALUES(17)'))
        assert migrate('downgrade','0025').returncode!=0
        with engines[1].connect() as conn:
            assert conn.execute(text('SELECT report_id_snapshot FROM report_deletion_tombstones')).scalar_one()==17
            assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0026'
        result['downgrade_preserves_facts']=True
        output=root/'outputs/operator-history-pdf/migration-verification.json'
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result),encoding='utf-8')
    finally:
        for engine in engines:engine.dispose()
        for name in names:
            assert name.endswith('_test') and name!=url.database
            with admin.connect() as conn:conn.execute(text('DROP DATABASE IF EXISTS "'+name+'" WITH (FORCE)'))
        admin.dispose()
