from dataclasses import dataclass
import hashlib
from pathlib import Path

from fastapi import UploadFile

from app.services import file_storage


@dataclass(frozen=True)
class StoredStandardFile:
    path: str
    file_type: str
    file_size: int
    content_hash: str


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
    target = Path(path)
    if target.exists():
        target.unlink()
