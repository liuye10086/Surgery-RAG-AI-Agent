import os
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import settings


def _sanitize_filename(filename: str | None) -> str:
    if not filename:
        return "unnamed"
    # 去掉路径分隔符和非法字符，仅保留安全字符
    filename = filename.strip().replace("\\", "_").replace("/", "_")
    # 限制长度
    name, ext = os.path.splitext(filename)
    if len(name) > 100:
        name = name[:100]
    return f"{name}{ext}"


def ensure_upload_dir() -> None:
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)


def validate_extension(filename: str | None) -> str:
    if not filename:
        raise ValueError("文件名不能为空")
    ext = Path(filename).suffix.lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(settings.ALLOWED_EXTENSIONS))
        raise ValueError(f"不支持的文件类型: {ext}，仅支持: {allowed}")
    return ext


def save_upload(file: UploadFile) -> str:
    ensure_upload_dir()

    filename = file.filename or "unnamed"
    ext = validate_extension(filename)

    safe_name = _sanitize_filename(filename)
    unique_name = f"{uuid.uuid4().hex}_{safe_name}"
    file_path = os.path.join(settings.UPLOAD_DIR, unique_name)

    # 先检查文件大小（避免大文件撑爆内存），再读取内容
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    chunk_size = 1024 * 1024  # 1 MiB per chunk
    chunks: list[bytes] = []
    total = 0
    while True:
        data = file.file.read(chunk_size)
        if not data:
            break
        total += len(data)
        if total > max_size:
            raise ValueError(
                f"文件大小超过限制: {settings.MAX_UPLOAD_SIZE_MB} MB"
            )
        chunks.append(data)
    contents = b"".join(chunks)

    with open(file_path, "wb") as f:
        f.write(contents)

    return file_path


def delete_upload(file_path: str | None) -> None:
    if not file_path:
        return
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        # 文件删除失败不影响数据库操作，记录即可
        pass


def delete_document_images(document_id: int) -> None:
    """删除文档解析生成的图片目录。"""
    images_dir = Path(settings.UPLOAD_DIR) / "images" / str(document_id)
    try:
        if images_dir.exists():
            shutil.rmtree(images_dir)
    except OSError:
        pass


def document_images_dir(document_id: int, generation: int) -> Path:
    return Path(settings.UPLOAD_DIR) / "images" / str(document_id) / str(generation)


def delete_document_generation_images(document_id: int, generation: int) -> None:
    images_dir = document_images_dir(document_id, generation)
    try:
        if images_dir.exists():
            shutil.rmtree(images_dir)
    except OSError:
        pass


def delete_all_document_images(document_id: int) -> None:
    delete_document_images(document_id)


def get_file_size(file_path: str) -> int:
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0
