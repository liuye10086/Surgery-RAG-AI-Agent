import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from app.db.models import AuditLog, Chunk, Message, Session


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_revision(filename: str, module_name: str):
    path = BACKEND_ROOT / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载迁移文件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AlembicContractTests(unittest.TestCase):
    def test_alembic_files_exist(self):
        for relative_path in [
            "alembic.ini",
            "alembic/env.py",
            "alembic/script.py.mako",
            "alembic/versions/0001_current_business_schema.py",
            "alembic/versions/0002_enforce_foreign_keys_and_indexes.py",
        ]:
            self.assertTrue((BACKEND_ROOT / relative_path).is_file(), relative_path)

    def test_revision_chain_is_linear(self):
        baseline = _load_revision(
            "0001_current_business_schema.py", "migration_0001"
        )
        hardening = _load_revision(
            "0002_enforce_foreign_keys_and_indexes.py", "migration_0002"
        )
        self.assertEqual(baseline.revision, "0001")
        self.assertIsNone(baseline.down_revision)
        self.assertEqual(hardening.revision, "0002")
        self.assertEqual(hardening.down_revision, "0001")

        predictive = _load_revision(
            "0005_document_access_scope.py", "migration_0005"
        )
        self.assertEqual(predictive.revision, "0005")
        self.assertEqual(predictive.down_revision, "0004")

        predictive = _load_revision(
            "0006_ai_operator_predictive.py", "migration_0006"
        )
        self.assertEqual(predictive.revision, "0006")
        self.assertEqual(predictive.down_revision, "0005")

        standards = _load_revision(
            "0009_versioned_standard_rules.py", "migration_0009"
        )
        self.assertEqual(standards.revision, "0009")
        self.assertEqual(standards.down_revision, "0008")

    def test_dedicated_standard_documents_revision_follows_0009(self):
        migration = _load_revision(
            "0010_dedicated_standard_documents.py", "migration_0010"
        )
        self.assertEqual(migration.revision, "0010")
        self.assertEqual(migration.down_revision, "0009")

    def test_dedicated_standard_documents_upgrade_rejects_populated_versions_before_ddl(self):
        migration = _load_revision(
            "0010_dedicated_standard_documents.py", "migration_0010_upgrade_guard"
        )
        bind = MagicMock()
        count = MagicMock()
        count.scalar_one.return_value = 1
        bind.execute.return_value = count
        migration_op = MagicMock()
        migration_op.get_bind.return_value = bind

        with patch.object(migration, "op", migration_op):
            with self.assertRaisesRegex(
                RuntimeError,
                "0010 requires reference_standard_versions to be empty",
            ):
                migration.upgrade()

        self.assertEqual(migration_op.method_calls, [call.get_bind()])
        self.assertEqual(bind.execute.call_count, 1)
        self.assertIn("reference_standard_versions", str(bind.execute.call_args.args[0]))

    def test_dedicated_standard_documents_downgrade_rejects_populated_tables_before_ddl(self):
        scenarios = (
            ("reference_standard_versions", (1,), 1),
            ("standard_documents", (0, 1), 2),
        )

        for populated_table, row_counts, expected_bind_calls in scenarios:
            with self.subTest(populated_table=populated_table):
                migration = _load_revision(
                    "0010_dedicated_standard_documents.py",
                    f"migration_0010_downgrade_guard_{populated_table}",
                )
                bind = MagicMock()
                bind.execute.side_effect = [
                    MagicMock(scalar_one=MagicMock(return_value=count))
                    for count in row_counts
                ]
                migration_op = MagicMock()
                migration_op.get_bind.return_value = bind

                with patch.object(migration, "op", migration_op):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "0010 downgrade requires reference_standard_versions and standard_documents to be empty",
                    ):
                        migration.downgrade()

                self.assertEqual(
                    migration_op.method_calls,
                    [call.get_bind()] * expected_bind_calls,
                )
                self.assertEqual(bind.execute.call_count, expected_bind_calls)
                self.assertIn(populated_table, str(bind.execute.call_args.args[0]))

    def test_env_excludes_langchain_internal_tables(self):
        env_source = (BACKEND_ROOT / "alembic/env.py").read_text(encoding="utf-8")
        self.assertIn('name.startswith("langchain_pg_")', env_source)

    def test_foreign_key_indexes_are_declared_in_orm(self):
        expected = {
            "ix_chunks_document_id",
            "ix_sessions_user_id",
            "ix_messages_session_id",
            "ix_audit_logs_user_id",
            "ix_audit_logs_session_id",
        }
        actual = {
            index.name
            for table in (
                Chunk.__table__,
                Session.__table__,
                Message.__table__,
                AuditLog.__table__,
            )
            for index in table.indexes
        }
        self.assertTrue(expected.issubset(actual))

    def test_document_has_access_scope(self):
        from app.db.models import Document
        cols = {c.name: c for c in Document.__table__.columns}
        self.assertIn("access_scope", cols)
        self.assertEqual(cols["access_scope"].server_default.arg, "chat")

    def test_new_predictive_tables_declared(self):
        from app.db.models import CaseRecord, Disease, ReferenceRange
        self.assertIn("id", Disease.__table__.columns)
        self.assertIn("disease_id", CaseRecord.__table__.columns)
        self.assertIn("indicator_name", ReferenceRange.__table__.columns)

    def test_reference_range_inclusive_columns(self):
        from app.db.models import ReferenceRange
        cols = {c.name: c for c in ReferenceRange.__table__.columns}
        self.assertIn("lower_inclusive", cols)
        self.assertIn("upper_inclusive", cols)
        # 默认含边界（True），与迁移 server_default=true 一致
        self.assertEqual(cols["lower_inclusive"].server_default.arg, "true")
        self.assertEqual(cols["upper_inclusive"].server_default.arg, "true")

    def test_ai_report_predictive_columns(self):
        from app.db.models import AIReport
        cols = {c.name for c in AIReport.__table__.columns}
        self.assertTrue({"analysis_type", "disease_id", "indicators", "prediction_result"}.issubset(cols))

    def test_ai_report_json_columns_have_defaults(self):
        """indicators/prediction_result 必须有 server_default（旧行迁移后不得为 NULL）。"""
        import inspect
        from app.db.models import AIReport
        cols = {c.name: c for c in AIReport.__table__.columns}
        self.assertIsNotNone(cols["indicators"].server_default)
        self.assertIsNotNone(cols["prediction_result"].server_default)

        mig = _load_revision("0006_ai_operator_predictive.py", "migration_0006")
        source = inspect.getsource(mig.upgrade)
        self.assertIn("'[]'::jsonb", source)
        self.assertIn("'{}'::jsonb", source)


if __name__ == "__main__":
    unittest.main()
