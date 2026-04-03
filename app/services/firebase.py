import firebase_admin
from firebase_admin import credentials, auth

def init_firebase():
    cred = credentials.Certificate("serviceAccountKey.json")
    firebase_admin.initialize_app(cred)

def verify_firebase_token(id_token: str) -> dict:
    return auth.verify_id_token(id_token, clock_skew_seconds=60)