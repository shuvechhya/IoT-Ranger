import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.database import get_db, device_status_cache
from app.dependencies import generate_device_jwt, get_current_user
from app.models.schemas import DeviceCreate

router = APIRouter(tags=["Devices"])


async def _get_project_or_404(project_id: str, user_id: str):
    db = get_db()
    project = await db.projects.find_one({"_id": project_id, "user_id": user_id})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    return project


@router.get("/projects/{project_id}/devices", response_model=list)
async def list_project_devices(project_id: str, current_user: dict = Depends(get_current_user)):
    """List all devices in a project."""
    db = get_db()
    await _get_project_or_404(project_id, current_user["user_id"])
    devices = await db.devices.find({"project_id": project_id}).to_list(100)
    return [{
        "id": dev["device_id"],
        "name": dev["name"],
        "mqtt_username": dev["mqtt_username"],
        "mqtt_topic": dev["device_id"],
        "project_id": dev["project_id"],
    } for dev in devices]


@router.get("/projects/{project_id}/devices/status", response_model=dict)
async def get_project_devices_status(project_id: str, current_user: dict = Depends(get_current_user)):
    """Get online/offline status of all devices in a project."""
    db = get_db()
    await _get_project_or_404(project_id, current_user["user_id"])
    devices = await db.devices.find({"project_id": project_id}).to_list(1000)
    device_list = [{
        "device_id": dev["device_id"],
        "name": dev["name"],
        "online": device_status_cache.get(dev["device_id"], {}).get("online", False),
        "last_seen": str(dev.get("last_seen", "never")),
    } for dev in devices]
    return {"project_id": project_id, "devices": device_list}


@router.post("/projects/{project_id}/devices", response_model=dict)
async def create_device(project_id: str, data: DeviceCreate, current_user: dict = Depends(get_current_user)):
    """
    Create a new device. Returns MQTT credentials to use on your ESP32:
    - **mqtt_username**: use as the MQTT client ID
    - **mqtt_password**: JWT token used as the MQTT password
    """
    await _get_project_or_404(project_id, current_user["user_id"])

    device_id = f"dev_{uuid.uuid4().hex[:8]}"
    mqtt_username = f"d_{project_id}_{device_id}"
    jwt_token = generate_device_jwt(device_id, project_id)
    
    db = get_db()
    await db.devices.insert_one({
        "project_id": project_id,
        "device_id": device_id,
        "name": data.name,
        "mqtt_username": mqtt_username,
        "mqtt_password": jwt_token,
        "online": False,
        "created_at": datetime.now(timezone.utc),
    })

    return {
        "id": device_id,
        "name": data.name,
        "project_id": project_id,
        "mqtt_username": mqtt_username,
        "mqtt_password": jwt_token,
        "mqtt_topic": device_id,
    }


@router.get("/devices/{device_id}/status", response_model=dict)
async def get_device_status(device_id: str, current_user: dict = Depends(get_current_user)):
    """Get online/offline status of a single device."""
    db = get_db()
    device = await db.devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await _get_project_or_404(device["project_id"], current_user["user_id"])

    status = device_status_cache.get(device_id, {})
    return {
        "device_id": device_id,
        "name": device["name"],
        "project_id": device["project_id"],
        "online": status.get("online", False),
        "last_seen": str(device.get("last_seen", "never")),
    }


@router.delete("/devices/{device_id}", response_model=dict)
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a device. Cannot be undone."""
    db = get_db()
    device = await db.devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    await _get_project_or_404(device["project_id"], current_user["user_id"])
    await db.devices.delete_one({"device_id": device_id})

    return {"message": f"Device {device_id} deleted"}
