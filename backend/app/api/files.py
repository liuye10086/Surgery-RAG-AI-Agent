"""受认证的病例图片访问接口。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services.source_access import source_grants_image, user_can_access_image

router = APIRouter(prefix="/files", tags=["files"])


def _source_grants_image(source: dict, document_id: int, filename: str) -> bool:
    """兼容旧测试和内部调用的第一代图片授权包装。"""
    return source_grants_image(source, document_id, None, filename)


def _image_response(
    document_id: int,
    generation: int | None,
    filename: str,
    current_user: User,
    db: Session,
):
    safe_filename = Path(filename).name
    if safe_filename != filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="非法文件名")

    if not user_can_access_image(
        db, current_user, document_id, generation, safe_filename
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该病例图片")

    image_root = (Path(settings.UPLOAD_DIR) / "images" / str(document_id)).resolve()
    candidates = []
    if generation is None:
        candidates.extend((image_root / "1" / safe_filename, image_root / safe_filename))
    else:
        candidates.append(image_root / str(generation) / safe_filename)

    for candidate in candidates:
        image_path = candidate.resolve()
        if image_root in image_path.parents and image_path.is_file():
            return FileResponse(image_path)

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="图片不存在")


@router.get("/images/{document_id}/{generation}/{filename}")
def get_versioned_case_image(
    document_id: int,
    generation: int,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _image_response(
        document_id, generation, filename, current_user, db
    )


@router.get("/images/{document_id}/{filename}")
def get_case_image(
    document_id: int,
    filename: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _image_response(document_id, None, filename, current_user, db)
