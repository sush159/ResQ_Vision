from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from google.oauth2 import id_token
from google.auth.transport import requests
from jose import jwt
from pydantic import BaseModel
import os
from dotenv import load_dotenv

# Import your existing modules
from pipeline import run_pipeline
from notifier import send_notification
from hospitals import get_nearest_hospital

load_dotenv()

app = FastAPI()
security = HTTPBearer()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
JWT_SECRET = os.getenv("JWT_SECRET", "resqvision-secret")
ADMIN_EMAILS = os.getenv("ADMIN_EMAILS", "").split(",")  # comma separated in .env

app.add_middleware(CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Auth ────────────────────────────────────────────────

class GoogleTokenRequest(BaseModel):
    token: str

@app.post("/api/auth/google")
async def google_auth(body: GoogleTokenRequest):
    try:
        info = id_token.verify_oauth2_token(
            body.token, requests.Request(), GOOGLE_CLIENT_ID
        )
        email = info["email"]
        name  = info.get("name", "")
        picture = info.get("picture", "")
        role  = "admin" if email in ADMIN_EMAILS else "user"

        token = jwt.encode(
            {"email": email, "name": name, "role": role, "picture": picture},
            JWT_SECRET, algorithm="HS256"
        )
        return {"access_token": token, "role": role, "name": name, "picture": picture}
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid Google token")

def get_current_user(token=Depends(security)):
    try:
        return jwt.decode(token.credentials, JWT_SECRET, algorithms=["HS256"])
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

def require_admin(user=Depends(get_current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admins only")
    return user

# ─── RESQ Vision Routes ──────────────────────────────────

@app.get("/api/accidents")
async def get_accidents(user=Depends(get_current_user)):
    # Any logged-in user (responder/viewer)
    return {"status": "ok", "accidents": []}

@app.post("/api/notify")
async def notify(user=Depends(get_current_user)):
    # Trigger emergency notification
    return {"status": "notified"}

@app.get("/api/admin/logs")
async def get_logs(user=Depends(require_admin)):
    # Admin only - full system logs
    return {"logs": []}

@app.get("/api/admin/cameras")
async def get_cameras(user=Depends(require_admin)):
    # Admin only - manage camera feeds
    return {"cameras": []}