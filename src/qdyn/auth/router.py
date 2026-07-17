import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..database import qdyndb
from .dependencies import get_current_user
from .models import UserCreate, Token, UserInfo
from .security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=201)
def register(body: UserCreate):
    if qdyndb.get_user(body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    hashed = hash_password(body.password)
    qdyndb.create_user(body.username, hashed)
    qdyndb.log_audit(body.username, "register", target=body.username)
    token = create_access_token(body.username)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(body: UserCreate):
    user = qdyndb.get_user(body.username)
    if not user or not verify_password(body.password, user["hashed_pw"]):
        qdyndb.log_audit(body.username, "login_failed", target=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    qdyndb.log_audit(body.username, "login", target=body.username)
    token = create_access_token(body.username)
    return Token(access_token=token)


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(
    username: str = Depends(get_current_user),
) -> UserInfo:
    """Get current logged-in user information, including admin status."""
    user = qdyndb.get_user(username)
    is_admin = bool(user.get("is_admin")) if user else False
    return UserInfo(username=username, is_admin=is_admin)
