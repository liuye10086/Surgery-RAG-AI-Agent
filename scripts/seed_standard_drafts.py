"""Create idempotent draft versions from explicit DOCX paths."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.db.models import Disease  # noqa: E402
from app.db.models import StandardDocument  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services.standard_document_storage import hash_standard_file  # noqa: E402
from app.services.standard_lifecycle import seed_standard_draft  # noqa: E402


def _standard_document(db, path: Path, admin_id: int) -> StandardDocument:
    if path.suffix.lower() != ".docx":
        raise ValueError(f"标准源文件只支持 DOCX：{path}")
    if not path.is_file():
        raise ValueError(f"标准文件不存在：{path}")
    digest = hash_standard_file(str(path))
    item = db.query(StandardDocument).filter(
        StandardDocument.content_hash == digest
    ).first()
    if item is None:
        item = StandardDocument(
            title=path.name,
            filename=path.name,
            file_path=str(path),
            file_type="docx",
            file_size=path.stat().st_size,
            content_hash=digest,
            uploaded_by=admin_id,
        )
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
        for disease_code, source, label in (("ad", args.ad, "AD-2026-08-24"), ("fatty_liver", args.fatty_liver, "fatty-liver-2026-08-24")):
            disease = db.query(Disease).filter(Disease.code == disease_code).first()
            if disease is None:
                raise SystemExit(f"疾病代码不存在：{disease_code}")
            document = _standard_document(db, source.resolve(), args.admin_id)
            version = seed_standard_draft(db, disease.id, document.id, label, admin_id=args.admin_id)
            print(f"{disease.name}: draft version {version.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
