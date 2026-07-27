"""文档代次暂存、激活和清理辅助函数。"""

from sqlalchemy.orm import Session

from app.db.models import Chunk, Document


def next_generation(db: Session, doc: Document) -> int:
    has_current = (
        db.query(Chunk.id)
        .filter(Chunk.document_id == doc.id, Chunk.is_current.is_(True))
        .first()
        is not None
    )
    return doc.active_generation + 1 if has_current else doc.active_generation


def staged_generation(db: Session, doc: Document) -> int | None:
    row = (
        db.query(Chunk.generation)
        .filter(Chunk.document_id == doc.id, Chunk.is_current.is_(False))
        .order_by(Chunk.generation.desc())
        .first()
    )
    return int(row[0]) if row else None


def activate_generation(db: Session, doc: Document, generation: int) -> None:
    db.query(Chunk).filter(Chunk.document_id == doc.id).update(
        {"is_current": False}, synchronize_session=False
    )
    db.query(Chunk).filter(
        Chunk.document_id == doc.id,
        Chunk.generation == generation,
    ).update({"is_current": True}, synchronize_session=False)
    doc.active_generation = generation
    doc.status = "indexed"
    doc.error_message = None
    db.flush()


def delete_generation_chunks(
    db: Session,
    document_id: int,
    generation: int,
) -> None:
    db.query(Chunk).filter(
        Chunk.document_id == document_id,
        Chunk.generation == generation,
    ).delete(synchronize_session=False)


def delete_obsolete_chunks(
    db: Session,
    document_id: int,
    active_generation: int,
) -> None:
    db.query(Chunk).filter(
        Chunk.document_id == document_id,
        Chunk.generation != active_generation,
    ).delete(synchronize_session=False)
