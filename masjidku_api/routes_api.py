import os
import json
import base64
import re
import random
import time
import requests
import io
import pytesseract
import sys
from datetime import datetime
from threading import Thread
from collections import Counter

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel
from PIL import Image
from bs4 import BeautifulSoup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import midtransclient

# Import Firebase Admin
import firebase_admin
from firebase_admin import credentials, firestore

# ==============================================================================
# INITIALIZATION
# ==============================================================================
firebase_env = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")

if firebase_env:
    cred_dict = json.loads(firebase_env)
    cred = credentials.Certificate(cred_dict)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    cert_path = os.path.join(BASE_DIR, "serviceAccountKey.json")
    cred = credentials.Certificate(cert_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()
router = APIRouter()

# Midtrans Configuration
MIDTRANS_SERVER_KEY = os.getenv("MIDTRANS_SERVER_KEY")
MIDTRANS_CLIENT_KEY = os.getenv("MIDTRANS_CLIENT_KEY")

core = midtransclient.CoreApi(
    is_production=False,
    server_key=MIDTRANS_SERVER_KEY, 
    client_key=MIDTRANS_CLIENT_KEY
)

# ==============================================================================
# MODELS
# ==============================================================================
class DonasiRequest(BaseModel):
    amount: int
    user_id: str

class LaporanRequest(BaseModel):
    keterangan: str
    jumlah: int

# ==============================================================================
# BACKGROUND TASKS
# ==============================================================================
def auto_check_status():
    while True:
        try:
            pending_donations = db.collection('donations').where('status', '==', 'pending').stream()
            for doc in pending_donations:
                order_id = doc.id
                try:
                    status_response = core.transactions.status(order_id)
                    if status_response.get('transaction_status') in ['settlement', 'capture']:
                        doc.reference.update({'status': 'success'})
                except:
                    continue
        except Exception as e:
            print(f"Error auto_check: {e}")
        time.sleep(60)

Thread(target=auto_check_status, daemon=True).start()

# ==============================================================================
# ENDPOINTS (Ditambah endpoint yang tadinya 404)
# ==============================================================================

# 1. Endpoint yang sudah ada
@router.post("/sync-google")
async def sync_google(data: dict):
    email = data.get("email")
    if not email: return {"status": "error", "message": "Email kosong"}
    
    db.collection('logs').add({
        "email": email,
        "activity": data.get("activity", "Registrasi"),
        "timestamp": datetime.now(),
        "details": f"User {data.get('name')} melakukan sinkronisasi"
    })
    return {"status": "success"}

# 2. Endpoint Tambahan (Agar tidak 404 lagi)
@router.post("/log-activity")
async def log_activity(data: dict):
    # Menyimpan aktivitas ke log
    db.collection('logs').add(data)
    return {"status": "success"}

@router.get("/berita-populer")
async def get_berita_populer():
    # Mengambil berita dari Firestore
    berita = db.collection('berita').order_by("views", direction=firestore.Query.DESCENDING).limit(5).stream()
    data = [doc.to_dict() for doc in berita]
    return {"status": "success", "data": data}

@router.post("/donasi")
async def create_donation(request: DonasiRequest):
    try:
        server_key = os.getenv("MIDTRANS_SERVER_KEY")
        order_id = f"DONASI-{request.user_id.split('@')[0]}-{int(datetime.now().timestamp() * 1000)}"
        
        payload = {
            "transaction_details": {"order_id": order_id, "gross_amount": request.amount},
            "credit_card": {"secure": True}
        }
        
        auth_string = base64.b64encode(f"{server_key}:".encode()).decode()
        response = requests.post(
            "https://app.sandbox.midtrans.com/snap/v1/transactions",
            json=payload,
            headers={"Authorization": f"Basic {auth_string}", "Content-Type": "application/json"}
        )
        
        data = response.json()
        if response.status_code == 201:
            db.collection('donations').document(order_id).set({
                "user_id": request.user_id, "amount": request.amount, "status": "pending",
                "snap_token": data.get("token"), "redirect_url": data.get("redirect_url"), "timestamp": datetime.now()
            })
            return {"status": "success", "token": data.get("token"), "redirect_url": data.get("redirect_url")}
        return {"status": "error", "message": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/scan-struk")
async def scan_struk(file: UploadFile = File(...)):
    try:
        if sys.platform.startswith('linux'):
            pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'
        
        image = Image.open(io.BytesIO(await file.read())).convert('L')
        text = pytesseract.image_to_string(image)
        
        numbers = re.findall(r'\b\d{1,3}(?:\.\d{3})*(?:,\d+)?\b', text)
        nominal = max([int(re.sub(r'[^\d]', '', n)) for n in numbers if re.sub(r'[^\d]', '', n)]) if numbers else 0
        
        return {"status": "success", "nama_item": text.split('\n')[0], "nominal": nominal}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/simpan-laporan")
async def simpan_laporan(request: LaporanRequest):
    db.collection('laporan').add({
        "kategori": "Pengeluaran", "keterangan": request.keterangan, 
        "jumlah": request.jumlah, "tanggal": datetime.now()
    })
    return {"status": "success"}

# ==============================================================================
# SCRAPING BERITA
# ==============================================================================
async def run_auto_scraping():
    try:
        url = "https://www.republika.co.id/rss/khazanah"
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, features="xml")
            items = soup.findAll('item')
            if items:
                old_docs = db.collection('berita').stream()
                for doc in old_docs: doc.reference.delete()
                for item in items[:15]:
                    db.collection('berita').add({
                        "title": item.title.text,
                        "link": item.link.text,
                        "description": re.sub('<[^<]+>', '', item.description.text).strip(),
                        "views": random.randint(50, 1000)
                    })
    except Exception as e:
        print(f"Error scraping: {e}")

@router.get("/trigger-scraping")
async def trigger_scraping():
    await run_auto_scraping()
    return {"status": "Scraping dipicu"}

@router.on_event("startup")
async def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(run_auto_scraping, 'cron', hour=0, minute=0, timezone='Asia/Jakarta')
    scheduler.start()