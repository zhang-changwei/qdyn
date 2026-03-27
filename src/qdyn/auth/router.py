import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from ..database import qdyndb
from .dependencies import get_current_user
from .models import UserCreate, Token
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
    token = create_access_token(body.username)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(body: UserCreate):
    user = qdyndb.get_user(body.username)
    if not user or not verify_password(body.password, user["hashed_pw"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(body.username)
    return Token(access_token=token)


@router.get("/me")
async def get_current_user_info(
    username: str = Depends(get_current_user)
):
    """Get current logged-in user information."""
    return {"username": username}
