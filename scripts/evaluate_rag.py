"""运行 RAG 基线，输出检索分数和规则命中结果。"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from langchain_core.documents import Document  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.rag.pipeline import hybrid_search  # noqa: E402
from app.services.content_filter import detect_dangerous_symptoms, filter_input  # noqa: E402
from app.services.llm_client import _has_sufficient_knowledge_for_docs  # noqa: E402


def _as_document(result) -> Document:
    return Document(
        page_content=result.chunk.content,
        metadata={
            "document_title": result.chunk.document.title or result.chunk.document.filename,
            "vector_score": result.vector_score,
            "vector_rank": result.vector_rank,
            "fulltext_score": result.fulltext_score,
            "fulltext_rank": result.fulltext_rank,
            "rrf_score": result.score,
        },
    )


def evaluate_case(db, case: dict) -> dict:
    input_result = filter_input(case["question"])
    danger = detect_dangerous_symptoms(case["question"])
    check_retrieval = case.get("check_retrieval", True)
    results = hybrid_search(db, case["question"]) if check_retrieval else []
    documents = [_as_document(result) for result in results]
    sufficient = _has_sufficient_knowledge_for_docs(documents)
    titles = [doc.metadata["document_title"] for doc in documents]
    keywords = case.get("expected_title_keywords", [])
    title_hit = not keywords or any(
        keyword in title for keyword in keywords for title in titles
    )

    checks = {
        "answer_decision": (
            sufficient == case["should_answer"] if check_retrieval else True
        ),
        "title_hit": (
            title_hit if check_retrieval and case.get("should_answer") else True
        ),
        "danger_level": danger.level == case.get("expected_danger_level", ""),
        "input_flag": input_result.flag_reason == case.get("expected_input_flag", ""),
    }
    return {
        "id": case["id"],
        "category": case["category"],
        "passed": all(checks.values()),
        "checks": checks,
        "decision": "answer" if sufficient else "no_knowledge",
        "danger_level": danger.level,
        "input_flag": input_result.flag_reason,
        "results": [
            {
                "title": doc.metadata["document_title"],
                "vector_score": doc.metadata["vector_score"],
                "vector_rank": doc.metadata["vector_rank"],
                "fulltext_score": doc.metadata["fulltext_score"],
                "fulltext_rank": doc.metadata["fulltext_rank"],
                "rrf_score": doc.metadata["rrf_score"],
            }
            for doc in documents
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evaluation" / "rag_baseline_10.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        report = [evaluate_case(db, case) for case in cases]

    passed = sum(item["passed"] for item in report)
    payload = {"passed": passed, "total": len(report), "cases": report}
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if passed == len(report) else 1


if __name__ == "__main__":
    raise SystemExit(main())
