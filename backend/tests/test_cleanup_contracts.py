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
            ".superpowers/sdd",
            ".vscode",
            "scripts/verify_2a.py",
            "evaluation/rag_baseline_10_report.json",
            "docs/superpowers/specs/2026-07-22-m5-design.md",
            "docs/superpowers/plans/2026-07-22-m5-implementation.md",
            "frontend/pnpm-lock.yaml",
            "frontend/pnpm-workspace.yaml",
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


if __name__ == "__main__":
    unittest.main()
