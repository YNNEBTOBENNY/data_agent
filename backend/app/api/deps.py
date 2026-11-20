from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_token
from ..db import get_db
from ..models import User


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.removeprefix("Bearer ").strip()
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = db.get(User, payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    # password_version 吊销补偿：签发后若用户改过口令，旧令牌失效
    if user.password_version != payload.get("pv"):
        raise HTTPException(status_code=401, detail="口令已更新，请重新登录")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role.value != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    return user
