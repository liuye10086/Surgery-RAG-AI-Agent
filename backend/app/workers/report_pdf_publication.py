"""Bounded publication process: file verification and DB commit share the deadline."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.schemas.report_pdf_archive import PdfClaim, PdfCandidate
from app.services.report_archive_storage import ArchiveStorage
from app.services.report_pdf_repository import publish_pdf
from app.services.report_pdf_errors import safe_pdf_code


def publish_pdf_candidate(payload, send):
    engine = None
    try:
        send({"kind": "phase", "phase": "publish"})
        engine = create_engine(
            payload["database_url"],
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        claim = PdfClaim.model_validate(payload["claim"])
        candidate = PdfCandidate.model_validate(payload["candidate"])
        with sessionmaker(bind=engine)() as db:
            accepted = publish_pdf(
                db,
                claim,
                candidate,
                ArchiveStorage(payload["archive_root"], create=False),
            )
        if accepted:
            send(
                {
                    "kind": "candidate",
                    "phase": "publish",
                    "candidate": candidate.model_dump(mode="json"),
                }
            )
        else:
            send({"kind": "error", "phase": "publish", "code": "pdf_lease_lost"})
    except Exception as error:
        send(
            {
                "kind": "error",
                "phase": "publish",
                "code": safe_pdf_code(getattr(error, "code", None)),
            }
        )
    finally:
        if engine is not None:
            engine.dispose()
