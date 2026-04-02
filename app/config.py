import os

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