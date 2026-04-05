import hashlib
import uuid

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_db
from app.dependencies import generate_user_jwt, get_current_user
from app.models.schemas import UserLogin, UserRegister
from app.services.firebase import verify_firebase_token

router = APIRouter(prefix="/auth", tags=["Authentication"])

_USER_EXPIRY = 7 * 24 * 60 * 60  # 7 days

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


@router.post("/firebase", response_model=dict)
async def firebase_login(request: Request):
    db = get_db()
    body = await request.json()
    id_token = body.get("id_token")

    decoded = verify_firebase_token(id_token) 

    uid = decoded["uid"]
    email = decoded.get("email")
    name = decoded.get("name") or decoded.get("display_name") or email.split("@")[0]

    # upsert — create user if first time, find if returning
    user = await db.users.find_one({"firebase_uid": uid})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        await db.users.insert_one({
            "_id": user_id,
            "firebase_uid": uid,
            "username": name,
            "email": email,
			"email_verified": decoded.get("email_verified", False),
            "auth_provider": decoded.get("firebase", {}).get("sign_in_provider", "unknown"),  # "google.com" or "password",
            "created_at": datetime.now(timezone.utc),
        })
    else:
        user_id = user["_id"]

    token = generate_user_jwt(user_id, name, _USER_EXPIRY)
    return {"access_token": token, "token_type": "bearer"}