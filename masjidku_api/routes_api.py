from fastapi import APIRouter
from firebase_config import db
from datetime import datetime

router = APIRouter(prefix="/api", tags=["JSON Data API"])

@router.post("/sync-google")
def sync_google(data: dict):
    try:
        name = data.get("name")
        email = data.get("email")

        # 1. Catat Log Aktivitas ke koleksi 'logs'
        log_data = {
            "email": email,
            "activity": "Registration Verified (OTP Success)",
            "timestamp": datetime.now(), # Mencatat waktu server
            "details": f"User {name} has completed registration."
        }
        db.collection('logs').add(log_data)

        print(f"LOG: {email} berhasil verifikasi dan terdaftar.")
        return {"status": "success", "message": "Activity logged successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
@router.post("/log-activity")
def log_activity(data: dict):
    try:
        email = data.get("email")
        action = data.get("action") # Contoh: "Reset Password" atau "Login"

        log_data = {
            "email": email,
            "activity": action,
            "timestamp": datetime.now(),
            "details": f"User {email} melakukan tindakan: {action}"
        }
        db.collection('logs').add(log_data)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# Endpoint untuk Dashboard memantau log
@router.get("/logs")
def get_logs():
    docs = db.collection('logs').order_by("timestamp", direction="DESCENDING").limit(10).stream()
    return [doc.to_dict() for doc in docs]