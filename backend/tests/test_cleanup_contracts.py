import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


class CleanupContractTests(unittest.TestCase):
    def test_removed_files_do_not_exist(self):
        removed = [
            ".vscode",
            "scripts/verify_2a.py",
            "evaluation/rag_baseline_10_report.json",
            "docs/superpowers/specs/2026-07-22-m5-design.md",
            "docs/superpowers/plans/2026-07-22-m5-implementation.md",
            "frontend/pnpm-lock.yaml",
            "frontend/pnpm-workspace.yaml",
            "backend/app/services/progression_engine.py",
            "backend/app/services/risk_bands.py",
            "backend/app/schemas/progression.py",
            "backend/tests/test_progression_engine.py",
            "backend/tests/test_progression_api.py",
            "scripts/train_progression_model.py",
            "scripts/tests/test_train_progression_model.py",
            "scripts/tests/fixtures/model-artifact-baseline.json",
            "backend/app/ml_models/ad_progression_model.joblib",
            "backend/app/ml_models/ad_progression_model.meta.json",
            "backend/app/ml_models/fatty_liver_progression_model.joblib",
            "backend/app/ml_models/fatty_liver_progression_model.meta.json",
            "CLAUDE.md",
            ".claude",
            "DEPLOYMENT_PLAN.md",
            "database/migrations",
            "tmp/pdfs",
            "output/pdf",
            "output/evidence",
            "docs/superpowers/reviews",
            "docs/superpowers/validation",
            "docs/superpowers/notes/2026-08-21-reference-standard-pipeline-audit.md",
            "docs/superpowers/notes/2026-08-24-versioned-standard-rules-layer-recommendation.md",
        ]
        for relative_path in removed:
            self.assertFalse((PROJECT_ROOT / relative_path).exists(), relative_path)

    def test_old_chat_and_vector_functions_are_removed(self):
        chat_api = _function_names(PROJECT_ROOT / "backend/app/api/chat.py")
        frontend_chat = (
            PROJECT_ROOT / "frontend/src/api/chat.ts"
        ).read_text(encoding="utf-8")
        vectorstore = _function_names(PROJECT_ROOT / "backend/app/rag/vectorstore.py")
        parser = _function_names(PROJECT_ROOT / "backend/app/ingestion/parser.py")

        self.assertNotIn("create_message", chat_api)
        self.assertNotIn("createMessage", frontend_chat)
        self.assertNotIn("delete_chunks", vectorstore)
        self.assertNotIn("delete_collection", vectorstore)
        self.assertNotIn("deidentify_text", parser)

    def test_unused_schema_types_are_removed(self):
        chat_types = _class_names(PROJECT_ROOT / "backend/app/schemas/chat.py")
        user_types = _class_names(PROJECT_ROOT / "backend/app/schemas/user.py")
        document_types = _class_names(PROJECT_ROOT / "backend/app/schemas/document.py")

        self.assertNotIn("MessageCreate", chat_types)
        self.assertNotIn("UserCreate", user_types)
        self.assertNotIn("DocumentStatus", document_types)

    def test_runtime_data_and_tools_remain(self):
        self.assertTrue((PROJECT_ROOT / "uploads").is_dir())
        self.assertTrue((PROJECT_ROOT / "scripts/check_documents.py").is_file())
        self.assertTrue((PROJECT_ROOT / "scripts/create_admin.py").is_file())
        self.assertTrue((PROJECT_ROOT / "scripts/evaluate_rag.py").is_file())
        self.assertTrue((PROJECT_ROOT / "evaluation/rag_baseline_10.json").is_file())

    def test_cleanup_preserves_development_and_runtime_assets(self):
        preserved = [
            "AGENTS.md",
            ".agents/skills/git-commit/SKILL.md",
            "backend/.env",
            "uploads",
            "frontend/node_modules",
            "frontend/dist",
            "data/generated/longitudinal_150",
            "data/generated/longitudinal_300",
            "data/generated/ad_longitudinal_150",
            "data/generated/ad_longitudinal_300",
            "research/main.py",
            "research/tests",
            "outputs/report_method_validation.md",
            "backend/app/ml_models/datasets",
            "backend/app/ml_models/bundles",
            "backend/app/ml_models/release_sets",
            "backend/app/ml_models/active/fatty_liver.json",
            "backend/app/ml_models/active/ad.json",
            "backend/app/ml_models/reviews",
            "backend/app/ml_models/activation_log",
            "docs/superpowers/plans",
            "docs/superpowers/specs/2026-08-18-real-longitudinal-data-collection-spec.md",
            "docs/superpowers/specs/2026-08-27-project-structure-cleanup-design.md",
            "docs/superpowers/notes/2026-08-25-longitudinal-report-improvement-roadmap.md",
            "docs/superpowers/notes/2026-08-26-ad-stage-transition-future-design-note.md",
        ]
        for relative_path in preserved:
            self.assertTrue((PROJECT_ROOT / relative_path).exists(), relative_path)

    def test_only_current_cleanup_specs_remain(self):
        spec_dir = PROJECT_ROOT / "docs/superpowers/specs"
        remaining = {path.name for path in spec_dir.glob("*.md")}
        self.assertEqual(
            remaining,
            {
                "2026-08-18-real-longitudinal-data-collection-spec.md",
                "2026-08-27-project-structure-cleanup-design.md",
                "2026-09-01-operator-case-age-design.md",
                "2026-09-01-operator-disease-permission-design.md",
                "2026-09-01-operator-case-status-design.md",
            },
        )

    def test_old_progression_endpoint_and_imports_are_removed(self):
        operator_source = (
            PROJECT_ROOT / "backend/app/api/operator.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("/progression-predictions", operator_source)
        self.assertNotIn("schemas.progression", operator_source)
        self.assertNotIn("predict_progression", operator_source)
        self.assertNotIn("_PROGRESSION_DATASETS", operator_source)


if __name__ == "__main__":
    unittest.main()
