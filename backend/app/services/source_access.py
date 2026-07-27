"""基于用户历史引用的病例文档与图片访问控制。"""

from sqlalchemy.orm import Session

from app.db.models import Message, Session as ChatSession, User


def source_grants_document(source: dict, document_id: int) -> bool:
    return source.get("document_id") == document_id


def source_grants_image(
    source: dict,
    document_id: int,
    generation: int | None,
    filename: str,
) -> bool:
    if not source_grants_document(source, document_id):
        return False

    normalized_filename = filename.replace("\\", "/")
    if generation is None:
        expected_suffixes = (
            f"/images/{document_id}/{normalized_filename}",
            f"/images/{document_id}/1/{normalized_filename}",
        )
    else:
        expected_suffixes = (
            f"/images/{document_id}/{generation}/{normalized_filename}",
        )

    for image in source.get("images") or []:
        url = str(image.get("url", "")).replace("\\", "/")
        if url.endswith(expected_suffixes):
            return True
    return False


def _user_sources(db: Session, user_id: int):
    return (
        db.query(Message.sources)
        .join(ChatSession, ChatSession.id == Message.session_id)
        .filter(
            ChatSession.user_id == user_id,
            Message.role == "assistant",
        )
        .all()
    )


def user_can_access_document(
    db: Session,
    user: User,
    document_id: int,
) -> bool:
    if user.role == "admin":
        return True

    return any(
        source_grants_document(source, document_id)
        for (sources,) in _user_sources(db, user.id)
        for source in (sources or [])
        if isinstance(source, dict)
    )


def user_can_access_image(
    db: Session,
    user: User,
    document_id: int,
    generation: int | None,
    filename: str,
) -> bool:
    if user.role == "admin":
        return True

    return any(
        source_grants_image(source, document_id, generation, filename)
        for (sources,) in _user_sources(db, user.id)
        for source in (sources or [])
        if isinstance(source, dict)
    )
