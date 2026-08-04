"""基于用户历史引用的病例文档与图片访问控制。

documents.access_scope 取值：chat（默认，聊天可检索/读取）、operator（仅操作者可读）、both（双方可读）。
operator 文档对普通聊天用户（doctor/patient 等）一律拒绝全文与图片读取，
仅 ai_operator / admin 可读，防止通过历史引用绕过检索隔离。
"""

from sqlalchemy.orm import Session

from app.db.models import Document, Message, Session as ChatSession, User


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
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return False
    if doc.access_scope == "operator":
        # operator 专属文档仅 ai_operator/admin 可读，普通聊天用户不可读
        return user.role == "ai_operator"
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
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return False
    if doc.access_scope == "operator":
        return user.role == "ai_operator"
    return any(
        source_grants_image(source, document_id, generation, filename)
        for (sources,) in _user_sources(db, user.id)
        for source in (sources or [])
        if isinstance(source, dict)
    )
