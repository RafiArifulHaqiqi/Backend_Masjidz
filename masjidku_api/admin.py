from firebase_config import db

def create_admin():
    admin_data = {
        "name": "Administrator Utama",
        "email": "admin@gmail.com",
        "password": "admin123", # Password untuk login ke web dashboard
        "role": "admin",        # Syarat wajib agar bisa masuk dashboard
        "uid": "admin_manual_01"
    }
    
    # Simpan ke koleksi users di Firestore
    db.collection("users").document("admin_01").set(admin_data)
    print("✅ Akun Admin berhasil dibuat!")
    print("Email: admin@gmail.com | Password: admin123")

if __name__ == "__main__":
    create_admin()