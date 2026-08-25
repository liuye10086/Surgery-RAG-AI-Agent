from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings
from app.services import file_storage


@dataclass(frozen=True)
class StoredStandardFile:
    path: str
    file_type: str
    file_size: int
    content_hash: str


@dataclass(frozen=True)
class StandardFileRecoverySnapshot:
    original_path: str
    contents: bytes


def validate_standard_docx(filename: str | None) -> None:
    if not filename or Path(filename).suffix.lower() != ".docx":
        raise ValueError("标准源文件只支持 DOCX")


def hash_standard_file(path: str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_standard_upload(file: UploadFile) -> StoredStandardFile:
    validate_standard_docx(file.filename)
    path = file_storage.save_upload(file)
    try:
        file_size = file_storage.get_file_size(path)
        content_hash = hash_standard_file(path)
    except Exception:
        delete_standard_file(path)
        raise
    return StoredStandardFile(
        path=path,
        file_type="docx",
        file_size=file_size,
        content_hash=content_hash,
    )


def delete_standard_file(path: str) -> None:
    Path(path).unlink()


def snapshot_standard_file(path: str) -> StandardFileRecoverySnapshot:
    original = Path(path)
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    with original.open("rb") as stream:
        contents = stream.read(max_size + 1)
    if len(contents) > max_size:
        raise ValueError(
            f"标准文件大小超过恢复限制: {settings.MAX_UPLOAD_SIZE_MB} MB"
        )
    return StandardFileRecoverySnapshot(
        original_path=str(original),
        contents=contents,
    )


def restore_standard_file(snapshot: StandardFileRecoverySnapshot) -> None:
    original = Path(snapshot.original_path)
    temporary = original.with_name(f".{original.name}.{uuid4().hex}.restoring")
    try:
        with temporary.open("xb") as stream:
            stream.write(snapshot.contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, original)
    finally:
        temporary.unlink(missing_ok=True)
