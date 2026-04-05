from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, HTTPException, Request

from app.config import JWT_ALGORITHM, JWT_SECRET, WEBHOOK_SECRET
from app.database import get_db, device_status_cache
from app.services.broadcast import broadcast_message

router = APIRouter(tags=["Internal"])


def _parse_device_from_username(username: str) -> tuple[str | None, str | None]:
    """Extract device_id and project_id from MQTT username: d_proj_xxx_dev_yyy"""
    if not username or not username.startswith("d_"):
        return None, None
    parts = username.split("_")
    if len(parts) < 5:
        return None, None
    return f"dev_{parts[4]}", f"proj_{parts[2]}"


@router.post("/mqtt/auth")
async def mqtt_auth(request: Request):
    """
    EMQX HTTP authentication endpoint.
    Called by the broker whenever a client attempts to connect.
    """
    try:
        db = get_db()
        content_type = request.headers.get("content-type", "")
        data = await request.json() if "application/json" in content_type else await request.form()

        username = data.get("username")
        password = data.get("password")

        print(f"Auth attempt - Username: {username}, Password: {'***' if password else None}")	
        print(f"Auth data: {data}")

        if not username or not password:
            return {"result": "deny"}

        # Backend service account
        if username == "backend":
            backend_user = await db.backend_users.find_one({"username": "backend"})
            if backend_user and password == backend_user.get("password"):
                return {"result": "allow"}
            return {"result": "deny"}

        # Device — validate JWT
        try:
            payload = jwt.decode(password, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            device_id = payload.get("device_id")
            project_id = payload.get("project_id")

            if device_id and project_id:
                device = await db.devices.find_one({
                    "device_id": device_id,
                    "project_id": project_id,
                    "mqtt_username": username,
                })
                if device:
                    now = datetime.now(timezone.utc)
                    await db.devices.update_one(
                        {"device_id": device_id},
                        {"$set": {"online": True, "last_seen": now}},
                    )
                    device_status_cache[device_id] = {"online": True, "last_seen": str(now)}
                    broadcast_message(project_id, {
                        "type": "device_status",
                        "device_id": device_id,
                        "online": True,
                        "timestamp": str(now),
                    })
                    return {"result": "allow"}
        except jwt.ExpiredSignatureError:
            return {"result": "deny", "reason": "Token expired"}
        except jwt.InvalidTokenError:
            return {"result": "deny", "reason": "Invalid token"}

        return {"result": "deny"}

    except Exception as e:
        print(f"Auth error: {e}")
        return {"result": "deny"}


@router.post("/webhook/emqx/events")
async def emqx_webhook_event(request: Request):
    """
    EMQX HTTP webhook for client connect/disconnect events.
    Requires the X-Webhook-Secret header.
    """
    if request.headers.get("x-webhook-secret") != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    try:
        db = get_db()
        data = await request.json()
        event = data.get("event", "")
        username = data.get("username", "")
        timestamp = data.get("timestamp", "")

        device_id, project_id = _parse_device_from_username(username)
        if not device_id or not project_id:
            return {"result": "error", "message": "Invalid device username format"}

        device = await db.devices.find_one({"device_id": device_id, "project_id": project_id})
        if not device:
            return {"result": "error", "message": "Device not found"}

        online = event == "client.connected"
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"online": online, "last_seen": datetime.now(timezone.utc)}},
        )
        device_status_cache[device_id] = {"online": online, "last_seen": timestamp}
        broadcast_message(project_id, {
            "type": "device_status",
            "device_id": device_id,
            "online": online,
            "timestamp": timestamp,
        })

        action = "connected" if online else "disconnected"
        print(f"Device {action}: {device_id}")
        return {"result": "ok"}

    except Exception as e:
        print(f"Webhook error: {e}")
        return {"result": "error", "message": str(e)}
