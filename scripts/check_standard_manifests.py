"""Lint a standard manifest and deterministically render its review document."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for item in (PROJECT_ROOT, BACKEND_ROOT):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from app.services.standard_manifest import load_standard_manifest, render_standard_review_markdown


def configure_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def build_plan(manifest_path: Path, source_path: Path, review_output: Path) -> dict[str, object]:
    manifest = load_standard_manifest(manifest_path)
    rendered = render_standard_review_markdown(manifest)
    drift = review_output.exists() and review_output.read_text(encoding="utf-8") != rendered
    return {
        "status": "drift" if drift else "dry_run",
        "manifest": str(manifest_path),
        "source": str(source_path),
        "review_output": str(review_output),
        "review_state": manifest.review_state,
        "entry_count": len(manifest.entries),
        "markdown_drift": drift,
        "rendered_markdown": rendered,
    }


def main(argv: list[str] | None = None) -> int:
    configure_stdout_utf8()
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--review-output", required=True, type=Path)
    parser.add_argument("--write-review", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.manifest, args.source, args.review_output)
        if args.write_review:
            args.review_output.parent.mkdir(parents=True, exist_ok=True)
            args.review_output.write_text(str(plan["rendered_markdown"]), encoding="utf-8")
            plan["status"] = "written"
        elif args.check and plan.get("markdown_drift"):
            plan["status"] = "drift"
        print(json.dumps({key: value for key, value in plan.items() if key != "rendered_markdown"}, ensure_ascii=False, sort_keys=True))
        return 1 if args.check and (plan.get("markdown_drift") or plan.get("status") == "drift") else 0
    except ValueError:
        print(json.dumps({"status": "blocked", "error": "validation_failed"}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({"status": "error", "error": "runtime_error"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
