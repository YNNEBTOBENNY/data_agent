from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import generate_token, hash_password, verify_password
from ..db import get_db
from ..models import Role, User
from .deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(username: str, password: str, role: str = "member", db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    pwd_hash, salt = hash_password(password)
    user = User(
        username=username,
        password_hash=f"{salt}${pwd_hash}",
        password_version=1,
        role=Role(role),
    )
    db.add(user)
    db.commit()
    return {"id": user.id, "username": user.username, "role": user.role.value}


@router.post("/login")
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    salt, pwd_hash = user.password_hash.split("$", 1)
    if not verify_password(password, pwd_hash, salt):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = generate_token(user.id, user.password_version)
    return {"token": token, "username": user.username, "role": user.role.value}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username, "role": user.role.value}
