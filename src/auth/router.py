import sqlite3

from fastapi import APIRouter, HTTPException, status

from .database import get_db, create_user, get_user
from .models import UserCreate, Token
from .security import hash_password, verify_password, create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=201)
def register(body: UserCreate):
    conn = get_db()
    if get_user(conn, body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )
    hashed = hash_password(body.password)
    create_user(conn, body.username, hashed)
    token = create_access_token(body.username)
    return Token(access_token=token)


@router.post("/login", response_model=Token)
def login(body: UserCreate):
    conn = get_db()
    user = get_user(conn, body.username)
    if not user or not verify_password(body.password, user["hashed_pw"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    token = create_access_token(body.username)
    return Token(access_token=token)
