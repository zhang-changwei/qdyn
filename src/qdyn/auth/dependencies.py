import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..database import qdyndb
from .security import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer_scheme),
) -> str:
    """Extract and verify the JWT, returning the username for an existing user."""
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
    if qdyndb.get_user(username) is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists",
        )
    return username


def get_current_admin(
    username: str = Depends(get_current_user),
) -> str:
    """Verify the current user is an admin, returning the username.

    Always queries the database for the is_admin flag — never trusts
    the JWT claim alone.  Returns the admin username so callers can
    use it for self-deletion checks.
    """
    user = qdyndb.get_user(username)
    if user is None or not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return username
