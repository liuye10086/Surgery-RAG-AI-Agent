"""交互式创建或提升管理员账户。"""

import getpass
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.security import get_password_hash  # noqa: E402
from app.db.models import User  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


def main() -> int:
    username = input("管理员用户名: ").strip()
    email = input("管理员邮箱: ").strip()
    real_name = input("姓名（可留空）: ").strip() or None
    password = getpass.getpass("密码: ")
    confirm = getpass.getpass("确认密码: ")

    if not username or not email or not password:
        print("用户名、邮箱和密码不能为空。", file=sys.stderr)
        return 1
    if password != confirm:
        print("两次密码不一致。", file=sys.stderr)
        return 1
    if len(password) < 8:
        print("密码至少需要 8 个字符。", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        email_owner = db.query(User).filter(User.email == email).first()
        if email_owner and (not user or email_owner.id != user.id):
            print("该邮箱已被其他账户使用。", file=sys.stderr)
            return 1

        if user:
            user.email = email
            user.real_name = real_name
            user.hashed_password = get_password_hash(password)
            user.role = "admin"
            action = "已更新并提升"
        else:
            db.add(User(
                username=username,
                email=email,
                real_name=real_name,
                hashed_password=get_password_hash(password),
                role="admin",
            ))
            action = "已创建"
        db.commit()

    print(f"{action}管理员账户: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
