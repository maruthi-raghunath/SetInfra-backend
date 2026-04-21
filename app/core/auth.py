from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import api_error

security = HTTPBearer(auto_error=False)

def create_access_token(subject: str | Any, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=60 * 24 * 7) # 1 week
    
    to_encode = {"sub": str(subject), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm="HS256")
    return encoded_jwt

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise api_error(401, "UNAUTHORIZED", "Missing bearer token.")

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except JWTError as exc:
        raise api_error(401, "UNAUTHORIZED", "Invalid or expired token.") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise api_error(401, "UNAUTHORIZED", "Token payload missing user identity.")

    return str(user_id)
