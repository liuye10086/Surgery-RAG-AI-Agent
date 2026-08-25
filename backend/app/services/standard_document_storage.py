from dataclasses import dataclass
import hashlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.services import file_storage


@dataclass(frozen=True)
class StoredStandardFile:
    path: str
    file_type: str
    file_size: int
    content_hash: str


@dataclass(frozen=True)
class StagedStandardFileDeletion:
    original_path: str
    staged_path: str


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
    return StoredStandardFile(
        path=path,
        file_type="docx",
        file_size=file_storage.get_file_size(path),
        content_hash=hash_standard_file(path),
    )


def delete_standard_file(path: str) -> None:
    Path(path).unlink()


def stage_standard_file_deletion(path: str) -> StagedStandardFileDeletion:
    original = Path(path)
    staged = original.with_name(f".{original.name}.{uuid4().hex}.deleting")
    original.replace(staged)
    return StagedStandardFileDeletion(
        original_path=str(original),
        staged_path=str(staged),
    )


def restore_standard_file_deletion(staged: StagedStandardFileDeletion) -> None:
    original = Path(staged.original_path)
    if original.exists():
        raise FileExistsError(f"Cannot restore over existing file: {original}")
    Path(staged.staged_path).replace(original)
