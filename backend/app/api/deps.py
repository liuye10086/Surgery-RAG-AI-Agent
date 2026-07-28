from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decode_token
from app.db.models import User
from app.db.session import get_db


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token, settings.JWT_SECRET, settings.JWT_ALGORITHM)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin required"
        )
    return current_user


def require_ai_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """要求 ai_operator 或 admin 角色。

    admin 继承 ai_operator 权限（可访问 operator 模块），
    但 ai_operator 不可访问 admin 模块（由 require_admin 单独限制）。
    """
    if current_user.role not in ("ai_operator", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI operator or admin required",
        )
    return current_user


def require_not_ai_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """拒绝 ai_operator 角色访问聊天/患者功能。

    admin 不受此限制（admin 可正常使用聊天功能）。
    """
    if current_user.role == "ai_operator":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI operator accounts cannot access chat features",
        )
    return current_user
