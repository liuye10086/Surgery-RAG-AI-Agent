"""创建 AI 操作者账号。

用法：
  cd backend
  python ../scripts/create_ai_operator.py --username ai_op --email ai@example.com --password xxx [--real-name "AI操作者"]

未提供参数时交互式输入密码。
"""

import argparse
import getpass
import sys
import os

# 允许从项目根目录或 backend/ 运行
_BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND_DIR))

from app.core.security import get_password_hash
from app.db.models import User
from app.db.session import SessionLocal


def main():
    parser = argparse.ArgumentParser(description="创建 AI 操作者账号")
    parser.add_argument("--username", required=True, help="登录用户名")
    parser.add_argument("--email", required=True, help="邮箱地址")
    parser.add_argument("--password", default=None, help="密码（不提供则交互式输入）")
    parser.add_argument("--real-name", default=None, help="真实姓名（可选）")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("请输入密码: ")
        confirm = getpass.getpass("请再次输入密码: ")
        if password != confirm:
            print("错误：两次输入的密码不一致", file=sys.stderr)
            sys.exit(1)

    if len(password) < 6:
        print("错误：密码长度不能少于 6 位", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        # 检查重复
        if db.query(User).filter(User.username == args.username).first():
            print(f"错误：用户名 '{args.username}' 已存在", file=sys.stderr)
            sys.exit(1)
        if db.query(User).filter(User.email == args.email).first():
            print(f"错误：邮箱 '{args.email}' 已注册", file=sys.stderr)
            sys.exit(1)

        user = User(
            username=args.username,
            email=args.email,
            real_name=args.real_name or args.username,
            hashed_password=get_password_hash(password),
            role="ai_operator",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        print(f"AI 操作者账号创建成功！")
        print(f"  ID:       {user.id}")
        print(f"  用户名:   {user.username}")
        print(f"  邮箱:     {user.email}")
        print(f"  角色:     {user.role}")
    except Exception as exc:
        db.rollback()
        print(f"错误：创建账号失败 — {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
