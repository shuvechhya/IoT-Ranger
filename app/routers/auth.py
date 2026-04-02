import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db
from app.dependencies import generate_user_jwt, get_current_user
from app.models.schemas import UserLogin, UserRegister

router = APIRouter(prefix="/auth", tags=["Authentication"])

_USER_EXPIRY = 7 * 24 * 60 * 60  # 7 days


@router.post("/register", response_model=dict)
async def register_user(data: UserRegister):
    """Register a new user account."""
    db = get_db()
    if await db.users.find_one({"email": data.email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    if await db.users.find_one({"username": data.username}):
        raise HTTPException(status_code=400, detail="Username already taken")

    user_id = f"user_{uuid.uuid4().hex[:8]}"
    hashed_password = hashlib.sha256(data.password.encode()).hexdigest()

    from datetime import datetime, timezone
    await db.users.insert_one({
        "_id": user_id,
        "username": data.username,
        "email": data.email,
        "password": hashed_password,
        "created_at": datetime.now(timezone.utc),
    })

    return {"message": "User created", "user_id": user_id, "username": data.username, "email": data.email}


@router.post("/login", response_model=dict)
async def login_user(data: UserLogin):
    """Login with email and password. Returns a JWT access token valid for 7 days."""
    db = get_db()
    user = await db.users.find_one({"email": data.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    hashed_password = hashlib.sha256(data.password.encode()).hexdigest()
    if hashed_password != user["password"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = generate_user_jwt(user["_id"], user["username"], _USER_EXPIRY)

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _USER_EXPIRY,
        "expires_ago": f"{_USER_EXPIRY // 86400} days",
    }


@router.post("/refresh", response_model=dict)
async def refresh_token(current_user: dict = Depends(get_current_user)):
    """Refresh your access token before it expires."""
    token = generate_user_jwt(current_user["user_id"], current_user["username"], _USER_EXPIRY)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": _USER_EXPIRY,
        "expires_ago": f"{_USER_EXPIRY // 86400} days",
    }
