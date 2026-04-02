from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGO_URL

mongo_client: AsyncIOMotorClient = None
db = None

# In-memory caches
connected_websockets: dict[str, list] = {}
device_status_cache: dict[str, dict] = {}


async def connect():
    global mongo_client, db
    mongo_client = AsyncIOMotorClient(MONGO_URL)
    db = mongo_client.iot_platform
    print(f"MongoDB connected: {MONGO_URL}")


async def disconnect():
    global mongo_client
    if mongo_client:
        mongo_client.close()


def get_db():
    return db
