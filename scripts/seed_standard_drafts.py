"""Create idempotent draft versions from explicit DOCX paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db.models import Document, Disease  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.standard_lifecycle import seed_standard_draft  # noqa: E402


def _document(db, path: Path) -> Document:
    if path.suffix.lower() != ".docx":
        raise ValueError(f"标准源文件只支持 DOCX：{path}")
    if not path.is_file():
        raise ValueError(f"标准文件不存在：{path}")
    item = db.query(Document).filter(Document.file_path == str(path)).first()
    if item is None:
        item = Document(filename=path.name, file_path=str(path), file_type="docx", file_size=path.stat().st_size, status="uploaded", access_scope="operator")
        db.add(item)
        db.commit()
        db.refresh(item)
    return item


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ad", required=True, type=Path)
    parser.add_argument("--fatty-liver", required=True, type=Path)
    parser.add_argument("--admin-id", required=True, type=int)
    args = parser.parse_args()
    with SessionLocal() as db:
        for disease_name, source, label in (("阿尔茨海默病", args.ad, "AD-2026-08-24"), ("脂肪肝", args.fatty_liver, "fatty-liver-2026-08-24")):
            disease = db.query(Disease).filter(Disease.name == disease_name).first()
            if disease is None:
                raise SystemExit(f"疾病不存在：{disease_name}")
            document = _document(db, source.resolve())
            version = seed_standard_draft(db, disease.id, document.id, label, admin_id=args.admin_id)
            print(f"{disease_name}: draft version {version.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
