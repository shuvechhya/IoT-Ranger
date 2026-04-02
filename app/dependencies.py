import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import JWT_ALGORITHM, JWT_EXPIRY_DAYS, JWT_SECRET

security = HTTPBearer()


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token and return current user."""
    try:
        token = credentials.credentials
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return {"user_id": user_id, "username": payload.get("username")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def generate_device_jwt(device_id: str, project_id: str) -> str:
    """Generate a long-lived JWT for a device."""
    payload = {
        "device_id": device_id,
        "project_id": project_id,
        "exp": int(time.time()) + (JWT_EXPIRY_DAYS * 24 * 60 * 60),
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def generate_user_jwt(user_id: str, username: str, expiry_seconds: int = 7 * 24 * 60 * 60) -> str:
    """Generate a short-lived JWT for a user session."""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": int(time.time()) + expiry_seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
