import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# Module-level settings, populated by configure()
_secret_key: str = ""
_token_expire_hours: int = 24
_ALGORITHM = "HS256"


def configure(secret_key: str, token_expire_hours: int = 24) -> str:
    """Set the secret key and expiry. Returns the (possibly generated) key."""
    global _secret_key, _token_expire_hours
    _secret_key = secret_key or secrets.token_urlsafe(64)
    _token_expire_hours = token_expire_hours
    return _secret_key


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=_token_expire_hours)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, _secret_key, algorithm=_ALGORITHM)


def decode_token(token: str) -> str:
    """Decode JWT and return the username. Raises jwt.PyJWTError on failure."""
    payload = jwt.decode(token, _secret_key, algorithms=[_ALGORITHM])
    username: str = payload["sub"]
    return username
