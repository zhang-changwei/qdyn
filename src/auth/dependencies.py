import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decode_token

_bearer_scheme = HTTPBearer()

_single_user_mode: bool = False
_SINGLE_USER_NAME = "admin"


def set_single_user_mode(enabled: bool) -> None:
    global _single_user_mode
    _single_user_mode = enabled


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(
        HTTPBearer(auto_error=False)
    ),
) -> str:
    """Extract and verify the JWT, returning the username.
    In single-user mode, always returns 'admin' without requiring a token."""
    if _single_user_mode:
        return _SINGLE_USER_NAME
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        username = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return username
