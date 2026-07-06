from fastapi import APIRouter
from datetime import datetime
from pydantic import BaseModel
import requests
import base64

# ==============================================================================
# 1. DEFINISI PYDANTIC MODEL (Untuk Validasi Request Body Donasi)
# ==============================================================================
class DonasiRequest(BaseModel):
    amount: int
    user_id: str

# ==============================================================================
# HUBUNGKAN DENGAN FIREBASE ADMIN SDK KAMU
# ==============================================================================
# Pastikan inisialisasi Firebase Admin SDK sudah benar di project-mu.
# Jika kamu menginisialisasi db di file lain (misal config.py), silakan import:
# from config import db
#
# Jika belum ada, ini template standar inisialisasi Firestore:
import firebase_admin
from firebase_admin import credentials, firestore

if not firebase_admin._apps:
    cred = credentials.Certificate("serviceAccountKey.json") # Ganti dengan nama file key-mu
    firebase_admin.initialize_app(cred)

db = firestore.client()
# ==============================================================================

router = APIRouter()

# --- 1. ENDPOINT SINKRONISASI AKUN BARU ---
@router.post("/sync-google")
async def sync_google(data: dict):
    """
    Endpoint yang dipanggil oleh Flutter setelah user berhasil memverifikasi OTP
    dan terdaftar di Firebase Auth. Berfungsi mencatat log pendaftaran awal.
    """
    try:
        name = data.get("name")
        email = data.get("email")

        if not email:
            return {"status": "error", "message": "Email tidak boleh kosong"}

        # Catat Log Aktivitas Registrasi Berhasil ke koleksi 'logs'
        log_data = {
            "email": email,
            "activity": "Registrasi Akun Baru Berhasil",
            "timestamp": datetime.now(), 
            "details": f"User {name if name else 'Tanpa Nama'} telah menyelesaikan registrasi via aplikasi."
        }
        db.collection('logs').add(log_data)

        print(f"✅ LOG BACKEND: {email} berhasil disinkronkan.")
        return {"status": "success", "message": "Activity logged successfully"}
        
    except Exception as e:
        print(f"❌ ERROR SYNC: {str(e)}")
        return {"status": "error", "message": str(e)}


# --- 2. ENDPOINT PENCATATAN AKTIVITAS UMUM (Login, Reset Password, dll) ---
@router.post("/log-activity")
async def log_activity(data: dict):
    """
    Endpoint fleksibel untuk mencatat segala bentuk tindakan user dari Flutter,
    seperti 'Login Berhasil' or 'Reset Password Berhasil'.
    """
    try:
        email = data.get("email")
        action = data.get("action") 

        if not email or not action:
            return {"status": "error", "message": "Email dan action harus diisi"}

        log_data = {
            "email": email,
            "activity": action,
            "timestamp": datetime.now(),
            "details": f"User {email} melakukan tindakan: {action}"
        }
        db.collection('logs').add(log_data)
        
        print(f"✅ LOG BACKEND: Aktivitas '{action}' dari {email} berhasil dicatat.")
        return {"status": "success"}
        
    except Exception as e:
        print(f"❌ ERROR LOG: {str(e)}")
        return {"status": "error", "message": str(e)}


# --- 3. ENDPOINT AMBIL DATA LOGS (Untuk Ditampilkan di Web Dashboard) ---
@router.get("/logs")
async def get_logs():
    """
    Mengambil 10 riwayat aktivitas terbaru dari Firestore 
    untuk ditampilkan pada halaman dashboard web admin.
    """
    try:
        docs = db.collection('logs').order_by("timestamp", direction="DESCENDING").limit(10).stream()
        
        log_list = []
        for doc in docs:
            d = doc.to_dict()
            # Konversi objek datetime Python ke string ISO agar tidak error saat dikirim lewat JSON
            if "timestamp" in d and d["timestamp"]:
                d["timestamp"] = d["timestamp"].isoformat()
            log_list.append(d)
            
        return log_list
        
    except Exception as e:
        print(f"❌ ERROR GET LOGS: {str(e)}")
        return {"status": "error", "message": str(e)} 


# --- 4. ENDPOINT BARU: MEMBUAT TRANSAKSI DONASI MIDTRANS SNAP ---
@router.post("/donasi")
async def create_donation(request: DonasiRequest):
    """
    Endpoint baru untuk memproses request donasi dari aplikasi Flutter,
    menghubungkannya ke API Midtrans Sandbox, dan menghasilkan Token/Redirect URL Pembayaran.
    """
    try:
        # PENTING: Ganti dengan Server Key milik akun Midtrans Sandbox kamu sendiri
        MIDTRANS_SERVER_KEY = "MIDTRANS_SERVER_KEY"
        
        print(f"DEBUG DONASI: Rp{request.amount} dari User ID: {request.user_id}")

        # Membuat Order ID unik berbasis waktu supaya tidak bentrok di Midtrans
        order_id = f"DONASI-{request.user_id}-{int(datetime.now().timestamp())}"

        # Setup parameter standar transaksi Snap Midtrans
        payload = {
            "transaction_details": {
                "order_id": order_id,
                "gross_amount": request.amount
            },
            "credit_card": {
                "secure": True
            }
        }

        # Melakukan Encode Server Key untuk otentikasi Basic Auth API Midtrans
        auth_string = base64.b64encode(f"{MIDTRANS_SERVER_KEY}:".encode()).decode()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth_string}"
        }

        # Menembak server API Midtrans Sandbox
        response = requests.post(
            "https://app.sandbox.midtrans.com/snap/v1/transactions",
            json=payload,
            headers=headers
        )

        midtrans_data = response.json()

        if response.status_code == 201:
            # Simpan log inisiasi pembayaran sukses ke database lokal 'donations'
            db.collection('donations').document(order_id).set({
                "user_id": request.user_id,
                "amount": request.amount,
                "status": "pending",
                "snap_token": midtrans_data.get("token"),
                "redirect_url": midtrans_data.get("redirect_url"),
                "timestamp": datetime.now()
            })

            # Ikut catat ke dalam log aktivitas admin
            db.collection('logs').add({
                "email": request.user_id,
                "activity": f"Inisiasi Donasi Rp{request.amount}",
                "timestamp": datetime.now(),
                "details": f"Membuat transaksi donasi baru dengan ID: {order_id}"
            })

            print(f"✅ MIDTRANS SUCCESS: Token berhasil dibuat untuk {order_id}")
            return {
                "status": "success", 
                "token": midtrans_data.get("token"), 
                "redirect_url": midtrans_data.get("redirect_url")
            }
        else:
            print(f"❌ MIDTRANS ERROR RESP: {midtrans_data}")
            return {"status": "error", "message": midtrans_data.get("error_messages", ["Gagal terhubung ke Midtrans"])}

    except Exception as e:
        print(f"❌ ERROR SERVER DONASI: {str(e)}")
        return {"status": "error", "message": str(e)}