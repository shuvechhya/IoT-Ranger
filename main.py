import asyncio
import hashlib
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import jwt
import paho.mqtt.client as mqtt
import requests
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
EMQX_API_URL = os.getenv("EMQX_API_URL", "http://localhost:18083")
EMQX_USER = os.getenv("EMQX_USER", "admin")
EMQX_PASS = os.getenv("EMQX_PASS", "public")
MQTT_BROKER = os.getenv("MQTT_BROKER", "emqx")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
BACKEND_MQTT_USER = os.getenv("BACKEND_MQTT_USER", "backend")
BACKEND_MQTT_PASS = os.getenv("BACKEND_MQTT_PASS", "backend_secret_pass_123")
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-jwt-key-change-in-production")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "webhook-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 365

mongo_client = None
db = None
connected_websockets: dict[str, list] = {}
device_status_cache: dict[str, dict] = {}
mqtt_client = None
security = HTTPBearer()


class UserRegister(BaseModel):
    username: str
    email: str
    password: str


class UserLogin(BaseModel):
    email: str
    password: str


class ProjectCreate(BaseModel):
    name: str


class DeviceCreate(BaseModel):
    name: str


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token and return current user"""
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


class DeviceCreate(BaseModel):
    name: str


async def setup_emqx():
    """Set up EMQX HTTP webhook and JWT authentication"""
    try:
        login_resp = requests.post(
            f"{EMQX_API_URL}/api/v5/login",
            json={"username": EMQX_USER, "password": EMQX_PASS},
            timeout=10
        )
        if login_resp.status_code != 200:
            print(f"Failed to login to EMQX API: {login_resp.status_code}")
            return
        
        token = login_resp.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        # Configure JWT Authentication using EMQX HTTP auth endpoint
        # First, check existing authentication
        existing_auth = requests.get(
            f"{EMQX_API_URL}/api/v5/authentication",
            headers=headers,
            timeout=10
        )
        
        # Use HTTP authentication that calls our backend
        http_auth_data = {
            "mechanism": "password_based",
            "backend": "http",
            "method": "post",
            "url": "http://backend:8000/mqtt/auth",
            "headers": {
                "Content-Type": "application/json"
            },
            "body": {
                "username": "${username}",
                "password": "${password}"
            },
            "enable": True,
            "connect_timeout": 5000,
            "request_timeout": 5000
        }
        
        # Create new authentication
        auth_resp = requests.post(
            f"{EMQX_API_URL}/api/v5/authentication",
            headers=headers,
            json=http_auth_data,
            timeout=10
        )
        print(f"HTTP auth configured: {auth_resp.status_code}")
        
        # Create HTTP webhook connector
        connector_data = {
            "name": "http_webhook_connector",
            "type": "webhook",
            "server": "http://backend:8000",
            "headers": {
                "Content-Type": "application/json",
                "X-Webhook-Secret": WEBHOOK_SECRET
            },
            "connect_timeout": 5000,
            "request_timeout": 5000,
            "enable_pipelining": 100
        }
        
        requests.post(
            f"{EMQX_API_URL}/api/v5/connectors",
            headers=headers,
            json=connector_data,
            timeout=10
        )
        print(f"HTTP webhook connector created")
        
        # Delete old MQTT-based rules first
        rules_resp = requests.get(f"{EMQX_API_URL}/api/v5/rules", headers=headers, timeout=10)
        if rules_resp.status_code == 200:
            for rule in rules_resp.json().get("data", []):
                requests.delete(f"{EMQX_API_URL}/api/v5/rules/{rule['id']}", headers=headers, timeout=10)
        
        # Create HTTP webhook rule for client.connected
        rule_connected = {
            "name": "http_client_connected",
            "sql": "SELECT * FROM \"client.connected\"",
            "actions": [{
                "function": "webhook",
                "args": {
                    "connector": "http_webhook_connector",
                    "url": "http://backend:8000/webhook/emqx/events",
                    "method": "post",
                    "body": {
                        "event": "${event}",
                        "clientid": "${clientid}",
                        "username": "${username}",
                        "timestamp": "${timestamp}"
                    }
                }
            }]
        }
        
        resp = requests.post(
            f"{EMQX_API_URL}/api/v5/rules",
            headers=headers,
            json=rule_connected,
            timeout=10
        )
        print(f"HTTP connected rule created: {resp.status_code}")
        
        # Create HTTP webhook rule for client.disconnected
        rule_disconnected = {
            "name": "http_client_disconnected",
            "sql": "SELECT * FROM \"client.disconnected\"",
            "actions": [{
                "function": "webhook",
                "args": {
                    "connector": "http_webhook_connector",
                    "url": "http://backend:8000/webhook/emqx/events",
                    "method": "post",
                    "body": {
                        "event": "${event}",
                        "clientid": "${clientid}",
                        "username": "${username}",
                        "timestamp": "${timestamp}"
                    }
                }
            }]
        }
        
        resp = requests.post(
            f"{EMQX_API_URL}/api/v5/rules",
            headers=headers,
            json=rule_disconnected,
            timeout=10
        )
        print(f"HTTP disconnected rule created: {resp.status_code}")
        
    except Exception as e:
        print(f"Failed to setup EMQX: {e}")


def generate_jwt(device_id: str, project_id: str) -> str:
    """Generate JWT for a device"""
    payload = {
        "device_id": device_id,
        "project_id": project_id,
        "exp": int(time.time()) + (JWT_EXPIRY_DAYS * 24 * 60 * 60),
        "iat": int(time.time())
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def broadcast_message(project_id: str, message: dict):
    """Broadcast message to all WebSocket clients for a project"""
    if project_id in connected_websockets:
        dead_connections = []
        for ws in connected_websockets[project_id]:
            try:
                import asyncio
                asyncio.run(ws.send_json(message))
            except:
                dead_connections.append(ws)
        for ws in dead_connections:
            connected_websockets[project_id].remove(ws)


def on_mqtt_connect(client, userdata, flags, rc):
    print(f"MQTT Connected with result code {rc}")
    if rc == 0:
        client.subscribe("$events/client_connected")
        client.subscribe("$events/client_disconnected")
        print("Subscribed to EMQX event topics")


def on_mqtt_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = json.loads(msg.payload.decode())
        
        print(f"MQTT message: {topic} - {payload}")
        
        # Extract device info from username
        username = payload.get("username", "")
        clientid = payload.get("clientid", "")
        timestamp = payload.get("timestamp", "")
        
        device_id = None
        project_id = None
        
        if username and username.startswith("d_"):
            parts = username.split("_")
            if len(parts) >= 5:
                project_id = f"proj_{parts[2]}"
                device_id = f"dev_{parts[4]}"
        
        if not device_id or not project_id:
            return
        
        # Run async code in sync context
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if "$events/client_connected" in topic:
            loop.run_until_complete(handle_device_connected(device_id, project_id, timestamp))
        elif "$events/client_disconnected" in topic:
            loop.run_until_complete(handle_device_disconnected(device_id, project_id, timestamp))
        
        loop.close()
        
    except Exception as e:
        print(f"MQTT message error: {e}")


async def handle_device_connected(device_id, project_id, timestamp):
    try:
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"online": True, "last_seen": datetime.now(timezone.utc)}}
        )
        device_status_cache[device_id] = {"online": True, "last_seen": timestamp}
        broadcast_message(project_id, {
            "type": "device_status",
            "device_id": device_id,
            "online": True,
            "timestamp": timestamp
        })
        print(f"Device connected: {device_id}")
    except Exception as e:
        print(f"Handle connected error: {e}")


async def handle_device_disconnected(device_id, project_id, timestamp):
    try:
        await db.devices.update_one(
            {"device_id": device_id},
            {"$set": {"online": False, "last_seen": datetime.now(timezone.utc)}}
        )
        device_status_cache[device_id] = {"online": False, "last_seen": timestamp}
        broadcast_message(project_id, {
            "type": "device_status",
            "device_id": device_id,
            "online": False,
            "timestamp": timestamp
        })
        print(f"Device disconnected: {device_id}")
    except Exception as e:
        print(f"Handle disconnected error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mongo_client, db, mqtt_client
    
    print("=" * 50)
    print("STARTUP: Initializing IoT Platform Backend...")
    print("=" * 50)
    
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    db = mongo_client.iot_platform
    print(f"MongoDB connected: {MONGO_URL}")
    
    # Create backend user for EMQX MQTT connection
    await db.backend_users.update_one(
        {"username": BACKEND_MQTT_USER},
        {"$set": {"username": BACKEND_MQTT_USER, "password": BACKEND_MQTT_PASS}},
        upsert=True
    )
    print(f"Backend user created/updated: {BACKEND_MQTT_USER}")
    
    # Setup EMQX (skip for now - will configure via API later if needed)
    print(f"Skipping EMQX setup (using MQTT events instead)")
    
    # Connect to EMQX via MQTT for events
    mqtt_client = mqtt.Client(client_id=f"backend_{uuid.uuid4().hex[:8]}")
    mqtt_client.username_pw_set(BACKEND_MQTT_USER, BACKEND_MQTT_PASS)
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = on_mqtt_message
    
    try:
        print(f"Connecting to MQTT broker: {MQTT_BROKER}:{MQTT_PORT} as {BACKEND_MQTT_USER}")
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"MQTT connection failed: {e}")
    
    print("STARTUP: Complete!")
    print("=" * 50)
    
    yield
    
    if mqtt_client:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    if mongo_client:
        mongo_client.close()


app = FastAPI(
    title="IoT Platform API",
    description="""
## IoT Ranger Platform

### Features
- **User Authentication**: Register and login with email/password
- **Projects**: Create projects to organize your IoT devices
- **Devices**: Add ESP32 or other devices to projects
- **Real-time Status**: WebSocket updates for device online/offline status
- **JWT Auth**: Devices authenticate using JWT tokens

### Authentication
All endpoints (except `/auth/*` and `/webhook/emqx/events`) require:
```
Authorization: Bearer <your_jwt_token>
```

### Get Started
1. Register: `POST /auth/register`
2. Login: `POST /auth/login`
3. Create Project: `POST /projects`
4. Create Device: `POST /projects/{project_id}/devices`
5. Use device credentials in ESP32

### WebSocket
Connect to `ws://localhost:8000/ws/{project_id}` for real-time device status updates.
    """,
    version="2.0.0",
    lifespan=lifespan
)


@app.post("/mqtt/auth")
async def mqtt_auth(request: Request):
    """
    EMQX HTTP Authentication endpoint.
    Called when a device connects to MQTT broker.
    """
    try:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
        else:
            data = await request.form()
        
        username = data.get("username")
        password = data.get("password")
        
        if not username or not password:
            return {"result": "deny"}
        
        # Check backend user
        if username == "backend":
            backend_user = await db.backend_users.find_one({"username": "backend"})
            if backend_user and password == backend_user.get("password"):
                return {"result": "allow"}
            return {"result": "deny"}
        
        # Check device users - validate JWT
        try:
            payload = jwt.decode(password, JWT_SECRET, algorithms=[JWT_ALGORITHM])
            device_id = payload.get("device_id")
            project_id = payload.get("project_id")
            
            if device_id and project_id:
                # Verify device exists in database
                device = await db.devices.find_one({
                    "device_id": device_id,
                    "project_id": project_id,
                    "mqtt_username": username
                })
                if device:
                    # Update device to online
                    await db.devices.update_one(
                        {"device_id": device_id},
                        {"$set": {"online": True, "last_seen": datetime.now(timezone.utc)}}
                    )
                    device_status_cache[device_id] = {"online": True, "last_seen": str(datetime.now(timezone.utc))}
                    # Broadcast to WebSocket
                    broadcast_message(project_id, {
                        "type": "device_status",
                        "device_id": device_id,
                        "online": True,
                        "timestamp": str(datetime.now(timezone.utc))
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


@app.post("/webhook/emqx/events")
async def emqx_webhook_event(request: Request):
    """
    Handle EMQX HTTP webhook events (client connect/disconnect).
    Requires X-Webhook-Secret header for authentication.
    """
    # Verify webhook secret
    webhook_secret = request.headers.get("x-webhook-secret")
    if webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")
    
    try:
        data = await request.json()
        
        event = data.get("event", "")
        clientid = data.get("clientid", "")
        username = data.get("username", "")
        timestamp = data.get("timestamp", "")
        
        # Extract device info from username (format: d_proj_xxx_dev_yyy)
        # Example: d_proj_7d815797_dev_af2bcab9
        # parts = ["d", "proj", "7d815797", "dev", "af2bcab9"]
        device_id = None
        project_id = None
        
        if username and username.startswith("d_"):
            parts = username.split("_")
            if len(parts) >= 5:
                project_id = f"proj_{parts[2]}"
                device_id = f"dev_{parts[4]}"
        
        # Validate device exists
        if not device_id or not project_id:
            return {"result": "error", "message": "Invalid device username format"}
        
        device = await db.devices.find_one({"device_id": device_id, "project_id": project_id})
        if not device:
            return {"result": "error", "message": "Device not found"}
        
        if event == "client.connected":
            # Update device status in database
            await db.devices.update_one(
                {"device_id": device_id},
                {"$set": {"online": True, "last_seen": datetime.now(timezone.utc)}}
            )
            # Update cache
            device_status_cache[device_id] = {"online": True, "last_seen": timestamp}
            # Broadcast to WebSocket clients
            broadcast_message(project_id, {
                "type": "device_status",
                "device_id": device_id,
                "online": True,
                "timestamp": timestamp
            })
            print(f"Device connected: {device_id}")
        
        elif event == "client.disconnected":
            # Update device status in database
            await db.devices.update_one(
                {"device_id": device_id},
                {"$set": {"online": False, "last_seen": datetime.now(timezone.utc)}}
            )
            # Update cache
            device_status_cache[device_id] = {"online": False, "last_seen": timestamp}
            # Broadcast to WebSocket clients
            broadcast_message(project_id, {
                "type": "device_status",
                "device_id": device_id,
                "online": False,
                "timestamp": timestamp
            })
            print(f"Device disconnected: {device_id}")
        
        return {"result": "ok"}
    
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"result": "error", "message": str(e)}


@app.post("/auth/register", response_model=dict, tags=["Authentication"])
async def register_user(data: UserRegister):
    """
    Register a new user account.
    
    - **username**: Unique username (e.g., "john123")
    - **email**: Valid email address (e.g., "john@example.com")
    - **password**: Account password
    
    Returns user_id and confirmation message.
    """
    existing_email = await db.users.find_one({"email": data.email})
    if existing_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    existing_username = await db.users.find_one({"username": data.username})
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already taken")
    
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    hashed_password = hashlib.sha256(data.password.encode()).hexdigest()
    
    await db.users.insert_one({
        "_id": user_id,
        "username": data.username,
        "email": data.email,
        "password": hashed_password,
        "created_at": datetime.now(timezone.utc)
    })
    
    return {"message": "User created", "user_id": user_id, "username": data.username, "email": data.email}


@app.post("/auth/login", response_model=dict, tags=["Authentication"])
async def login_user(data: UserLogin):
    """
    Login with email and password.
    
    - **email**: Your registered email
    - **password**: Your account password
    
    Returns JWT access token. Use this token in Authorization header for other endpoints.
    Token expires in 7 days.
    """
    user = await db.users.find_one({"email": data.email})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    hashed_password = hashlib.sha256(data.password.encode()).hexdigest()
    if hashed_password != user["password"]:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    expiry = 7 * 24 * 60 * 60  # 7 days
    token = jwt.encode({
        "user_id": user["_id"],
        "username": user["username"],
        "exp": int(time.time()) + expiry
    }, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expiry,
        "expires_ago": f"{expiry // 86400} days"
    }


@app.post("/auth/refresh", response_model=dict, tags=["Authentication"])
async def refresh_token(current_user: dict = Depends(get_current_user)):
    """
    Refresh your access token.
    Use this when your current token is about to expire.
    """
    expiry = 7 * 24 * 60 * 60  # 7 days
    token = jwt.encode({
        "user_id": current_user["user_id"],
        "username": current_user["username"],
        "exp": int(time.time()) + expiry
    }, JWT_SECRET, algorithm=JWT_ALGORITHM)
    
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expiry,
        "expires_ago": f"{expiry // 86400} days"
    }


@app.get("/projects", response_model=list, tags=["Projects"])
async def list_projects(current_user: dict = Depends(get_current_user)):
    """
    List all projects for the current user.
    
    Returns list of project objects with id and name.
    """
    projects = await db.projects.find({"user_id": current_user["user_id"]}).to_list(100)
    return [{"id": str(p["_id"]), "name": p["name"]} for p in projects]


@app.post("/projects", response_model=dict, tags=["Projects"])
async def create_project(data: ProjectCreate, current_user: dict = Depends(get_current_user)):
    """
    Create a new project.
    
    - **name**: Project name (e.g., "My Sensors", "Home Automation")
    
    Returns the created project with its id.
    """
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    await db.projects.insert_one({
        "_id": project_id,
        "name": data.name,
        "user_id": current_user["user_id"],
        "created_at": datetime.now(timezone.utc)
    })
    return {"id": project_id, "name": data.name}


@app.get("/projects/{project_id}/devices", response_model=list, tags=["Devices"])
async def list_project_devices(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    List all devices in a project.
    
    Returns devices with their mqtt_username (use this as MQTT client ID).
    """
    project = await db.projects.find_one({"_id": project_id, "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    
    devices = await db.devices.find({"project_id": project_id}).to_list(100)
    return [{
        "id": dev["device_id"],
        "name": dev["name"],
        "mqtt_username": dev["mqtt_username"],
        "mqtt_topic": dev["device_id"],
        "project_id": dev["project_id"]
    } for dev in devices]


@app.get("/projects/{project_id}/devices/status", response_model=dict, tags=["Devices"])
async def get_project_devices_status(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Get online/offline status of all devices in a project.
    
    Returns list of devices with their online status and last_seen timestamp.
    """
    project = await db.projects.find_one({"_id": project_id, "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    
    devices = await db.devices.find({"project_id": project_id}).to_list(1000)
    
    device_list = []
    for dev in devices:
        device_status = device_status_cache.get(dev["device_id"], {})
        device_list.append({
            "device_id": dev["device_id"],
            "name": dev["name"],
            "online": device_status.get("online", False),
            "last_seen": str(dev.get("last_seen", "never"))
        })
    
    return {
        "project_id": project_id,
        "devices": device_list
    }


@app.get("/devices/{device_id}/status", response_model=dict, tags=["Devices"])
async def get_device_status(device_id: str, current_user: dict = Depends(get_current_user)):
    """
    Get online/offline status of a single device.
    
    Returns device status with online flag and last_seen timestamp.
    """
    device = await db.devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    project = await db.projects.find_one({"_id": device["project_id"], "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Device not found or access denied")
    
    device_status = device_status_cache.get(device_id, {})
    
    return {
        "device_id": device_id,
        "name": device["name"],
        "project_id": device["project_id"],
        "online": device_status.get("online", False),
        "last_seen": str(device.get("last_seen", "never"))
    }


@app.post("/projects/{project_id}/devices", response_model=dict, tags=["Devices"])
async def create_device(project_id: str, data: DeviceCreate, current_user: dict = Depends(get_current_user)):
    """
    Create a new device in a project.
    
    - **name**: Device name (e.g., "ESP32 #1", "Temperature Sensor")
    
    Returns device credentials:
    - **mqtt_username**: Use as MQTT client ID
    - **mqtt_password**: Use as MQTT password (JWT token)
    
    Use these credentials in your ESP32 or IoT device to connect via MQTT.
    """
    project = await db.projects.find_one({"_id": project_id, "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    
    device_id = f"dev_{uuid.uuid4().hex[:8]}"
    mqtt_username = f"d_{project_id}_{device_id}"
    
    jwt_token = generate_jwt(device_id, project_id)
    
    await db.devices.insert_one({
        "project_id": project_id,
        "device_id": device_id,
        "name": data.name,
        "mqtt_username": mqtt_username,
        "mqtt_password": jwt_token,
        "online": False,
        "created_at": datetime.now(timezone.utc)
    })
    
    return {
        "id": device_id,
        "name": data.name,
        "project_id": project_id,
        "mqtt_username": mqtt_username,
        "mqtt_password": jwt_token,
        "mqtt_topic": device_id
    }


@app.delete("/projects/{project_id}", response_model=dict, tags=["Projects"])
async def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a project and all its devices. Cannot be undone!"""
    project = await db.projects.find_one({"_id": project_id, "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or access denied")
    
    # Delete all devices in the project
    await db.devices.delete_many({"project_id": project_id})
    # Delete the project
    await db.projects.delete_one({"_id": project_id})
    
    return {"message": f"Project {project_id} deleted"}


@app.delete("/devices/{device_id}", response_model=dict, tags=["Devices"])
async def delete_device(device_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a device. Cannot be undone!"""
    device = await db.devices.find_one({"device_id": device_id})
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    project = await db.projects.find_one({"_id": device["project_id"], "user_id": current_user["user_id"]})
    if not project:
        raise HTTPException(status_code=404, detail="Access denied")
    
    await db.devices.delete_one({"device_id": device_id})
    
    return {"message": f"Device {device_id} deleted"}


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """
    WebSocket endpoint for real-time device status updates.
    
    Connect via: `ws://localhost:8000/ws/{project_id}`
    
    Messages received:
    - **init**: Initial device list with status
    - **device_status**: Device online/offline change
    
    Example:
    ```javascript
    const ws = new WebSocket("ws://localhost:8000/ws/proj_abc123");
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "init") {
            console.log("Devices:", data.devices);
        } else if (data.type === "device_status") {
            console.log(`${data.device_id} is now ${data.online ? "ONLINE" : "OFFLINE"}`);
        }
    };
    ```
    """
    await websocket.accept()
    
    if project_id not in connected_websockets:
        connected_websockets[project_id] = []
    connected_websockets[project_id].append(websocket)
    
    try:
        # Send initial device list with status
        devices = await db.devices.find({"project_id": project_id}).to_list(100)
        device_list = []
        for d in devices:
            status = device_status_cache.get(d["device_id"], {})
            device_list.append({
                "id": d["device_id"],
                "name": d["name"],
                "online": status.get("online", False)
            })
        
        await websocket.send_json({
            "type": "init",
            "devices": device_list
        })
        
        while True:
            await websocket.receive_text()
    
    except WebSocketDisconnect:
        if project_id in connected_websockets:
            connected_websockets[project_id].remove(websocket)


@app.get("/")
async def root():
    return {"message": "IoT Platform API", "version": "2.0.0", "auth": "JWT"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
