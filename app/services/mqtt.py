import asyncio
import json
import uuid

import paho.mqtt.client as mqtt

from app.config import BACKEND_MQTT_PASS, BACKEND_MQTT_USER, MQTT_BROKER, MQTT_PORT
from app.database import get_db, device_status_cache
from app.services.broadcast import broadcast_message
from datetime import datetime, timezone

mqtt_client: mqtt.Client = None


def _parse_device_from_username(username: str) -> tuple[str | None, str | None]:
    """Extract device_id and project_id from MQTT username format: d_proj_xxx_dev_yyy"""
    if not username or not username.startswith("d_"):
        return None, None
    parts = username.split("_")
    if len(parts) < 5:
        return None, None
    project_id = f"proj_{parts[2]}"
    device_id = f"dev_{parts[4]}"
    return device_id, project_id


async def _handle_device_connected(device_id: str, project_id: str, timestamp: str):
    try:
        db = get_db()
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"online": True, "last_seen": datetime.now(timezone.utc)}},
        )
        device_status_cache[device_id] = {"online": True, "last_seen": timestamp}
        broadcast_message(project_id, {
            "type": "device_status",
            "device_id": device_id,
            "online": True,
            "timestamp": timestamp,
        })
        print(f"Device connected: {device_id}")
    except Exception as e:
        print(f"Handle connected error: {e}")


async def _handle_device_disconnected(device_id: str, project_id: str, timestamp: str):
    try:
        db = get_db()
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"online": False, "last_seen": datetime.now(timezone.utc)}},
        )
        device_status_cache[device_id] = {"online": False, "last_seen": timestamp}
        broadcast_message(project_id, {
            "type": "device_status",
            "device_id": device_id,
            "online": False,
            "timestamp": timestamp,
        })
        print(f"Device disconnected: {device_id}")
    except Exception as e:
        print(f"Handle disconnected error: {e}")


def on_connect(client, userdata, flags, rc):
    print(f"MQTT Connected with result code {rc}")
    if rc == 0:
        client.subscribe("$events/client_connected")
        client.subscribe("$events/client_disconnected")
        print("Subscribed to EMQX event topics")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print(f"MQTT message: {msg.topic} - {payload}")

        username = payload.get("username", "")
        timestamp = payload.get("timestamp", "")
        device_id, project_id = _parse_device_from_username(username)

        if not device_id or not project_id:
            return

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        if "$events/client_connected" in msg.topic:
            loop.run_until_complete(_handle_device_connected(device_id, project_id, timestamp))
        elif "$events/client_disconnected" in msg.topic:
            loop.run_until_complete(_handle_device_disconnected(device_id, project_id, timestamp))

        loop.close()
    except Exception as e:
        print(f"MQTT message error: {e}")


def connect():
    global mqtt_client
    mqtt_client = mqtt.Client(client_id=f"backend_{uuid.uuid4().hex[:8]}")
    mqtt_client.username_pw_set(BACKEND_MQTT_USER, BACKEND_MQTT_PASS)
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    try:
        print(f"Connecting to MQTT broker: {MQTT_BROKER}:{MQTT_PORT} as {BACKEND_MQTT_USER}")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"MQTT connection failed: {e}")


def disconnect():
    global mqtt_client
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
