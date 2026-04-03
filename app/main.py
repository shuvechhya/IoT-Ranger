from contextlib import asynccontextmanager

from fastapi import FastAPI
from app.services.firebase import init_firebase

from app import database
from app.config import BACKEND_MQTT_PASS, BACKEND_MQTT_USER
from app.routers import auth, devices, internal, projects, websockets
from app.services import mqtt as mqtt_service
from fastapi.middleware.cors import CORSMiddleware 

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("=" * 50)
    print("STARTUP: Initializing IoT Platform Backend...")
    print("=" * 50)

    await database.connect()

    # Ensure backend MQTT user exists
    await database.db.backend_users.update_one(
        {"username": BACKEND_MQTT_USER},
        {"$set": {"username": BACKEND_MQTT_USER, "password": BACKEND_MQTT_PASS}},
        upsert=True,
    )
    print(f"Backend MQTT user ready: {BACKEND_MQTT_USER}")

    init_firebase()

    mqtt_service.connect()

    print("STARTUP: Complete!")
    print("=" * 50)

    yield

    mqtt_service.disconnect()
    await database.disconnect()


app = FastAPI(
    title="IoT Platform API",
    description="""
## IoT Ranger Platform

### Get Started
1. Register: `POST /auth/register`
2. Login: `POST /auth/login`
3. Create Project: `POST /projects`
4. Create Device: `POST /projects/{project_id}/devices`
5. Flash credentials to your ESP32

### Authentication
All endpoints (except `/auth/*` and `/mqtt/auth`, `/webhook/*`) require:
```
Authorization: Bearer <your_jwt_token>
```

### WebSocket
Connect to `ws://localhost:3000/ws/{project_id}` for real-time device status.
    """,
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(devices.router)
app.include_router(websockets.router)
app.include_router(internal.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health"])
async def root():
    return {"message": "IoT Platform API", "version": "2.0.0", "auth": "JWT"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=3000)
