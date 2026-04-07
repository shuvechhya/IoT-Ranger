import requests
import time
from pymongo import MongoClient
from datetime import datetime

# Local MongoDB on Pi
client = MongoClient('mongodb://localhost:27017/')
db = client.iot_logs
collection = db.logs

# Server Config from your screenshots
UBUNTU_API = "http://203.154.11.225:3000"
ADMIN_EMAIL = "st126665@ait.asia" # From your successful registration
ADMIN_PASSWORD = "1234"           # From your successful registration

def get_token():
    try:
        # The schema in your screenshot shows email/password JSON body
        payload = {
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD
        }
        
        # Using /auth/login based on your documentation screenshot
        response = requests.post(f"{UBUNTU_API}/login", json=payload, timeout=10)
        
        if response.status_code == 200:
            data =  response.json()
            # Successfully returns a JWT token valid for 7 days
            return data.get("access_token")
        else:
            print(f"❌ Login Failed: {response.status_code}")
            print(f"Response content: {response.text}")
            return None
    except Exception as e:
        print(f"❌ Connection Error during login: {e}")
        return None

print("📡 Pi Admin Fetcher Started...")

while True:
    token = get_token()
    if token:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            # Fetching projects (List all projects belonging to the user)
            response = requests.get(f"{UBUNTU_API}/projects", headers=headers, timeout=10)
            
            if response.status_code == 200:
                projects = response.json()
                for p in projects:
                    entry = {
                        "usern": "mark", # The owner from your registration
                        "device_id": str(p),  # This endpoint returns a list of strings
                        "status": "active",
                        "timestamp": datetime.utcnow()
                    }
                    collection.insert_one(entry)
                print(f"✅ Successfully synced {len(projects)} projects for user mark.")
            else:
                print(f"⚠️ Fetch Failed: Status {response.status_code}")
        except Exception as e:
            print(f"❌ Sync Error: {e}")
    
    # Wait 60 seconds before next sync
    time.sleep(30)
