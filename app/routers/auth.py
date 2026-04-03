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

# @router.post("/register", response_model=dict)
# async def register_user(data: UserRegister):
#     """Register a new user account."""
#     db = get_db()
#     if await db.users.find_one({"email": data.email}):
#         raise HTTPException(status_code=400, detail="Email already registered")
#     if await db.users.find_one({"username": data.username}):
#         raise HTTPException(status_code=400, detail="Username already taken")

#     user_id = f"user_{uuid.uuid4().hex[:8]}"
#     hashed_password = hashlib.sha256(data.password.encode()).hexdigest()

#     from datetime import datetime, timezone
#     await db.users.insert_one({
#         "_id": user_id,
#         "username": data.username,
#         "email": data.email,
#         "password": hashed_password,
#         "created_at": datetime.now(timezone.utc),
#     })

#     return {"message": "User created", "user_id": user_id, "username": data.username, "email": data.email}


# @router.post("/login", response_model=dict)
# async def login_user(data: UserLogin):
#     """Login with email and password. Returns a JWT access token valid for 7 days."""
#     db = get_db()
#     user = await db.users.find_one({"email": data.email})
#     if not user:
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     hashed_password = hashlib.sha256(data.password.encode()).hexdigest()
#     if hashed_password != user["password"]:
#         raise HTTPException(status_code=401, detail="Invalid credentials")

#     token = generate_user_jwt(user["_id"], user["username"], _USER_EXPIRY)

#     return {
#         "access_token": token,
#         "token_type": "bearer",
#         "expires_in": _USER_EXPIRY,
#         "expires_ago": f"{_USER_EXPIRY // 86400} days",
#     }


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
    name = decoded.get("name", email)

    # upsert — create user if first time, find if returning
    user = await db.users.find_one({"firebase_uid": uid})
    if not user:
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        await db.users.insert_one({
            "_id": user_id,
            "firebase_uid": uid,
            "username": name,
            "email": email,
            "created_at": datetime.now(timezone.utc),
        })
    else:
        user_id = user["_id"]

    token = generate_user_jwt(user_id, name, _USER_EXPIRY)
    return {"access_token": token, "token_type": "bearer"}