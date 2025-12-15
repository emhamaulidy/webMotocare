import streamlit as st
from sqlalchemy import create_engine, Column, Integer, String, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.ext.declarative import declarative_base
from werkzeug.security import generate_password_hash, check_password_hash
import datetime
import requests
import smtplib
from email.message import EmailMessage
import base64 # NEW: Untuk menyimpan foto bengkel
import io # NEW: Untuk membaca bytes foto

# ====================================================================
# 0. KONFIGURASI DAN UTILITY (EMAIL, BACKGROUND)
# ====================================================================

# --- KONFIGURASI LOGO ---
# ⚠️ GANTI "nama_file_logo_anda.png" dengan NAMA FILE LOGO ANDA (.png/.jpg)
LOGO_FILE_PATH = "logo.png" 

# --- KONFIGURASI SMTP EMAIL ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
# GANTI INI DENGAN KREDENSIAL ASLI ANDA!
SENDER_EMAIL = "motocare.app.demo@gmail.com"
SENDER_PASSWORD = "YOUR_APP_PASSWORD"
# ------------------------------

def send_welcome_email(recipient_email, username):
    """Mengirim email selamat datang kepada pengguna baru."""
    
    msg = EmailMessage()
    msg['Subject'] = 'Selamat Datang di MotoCare App!'
    msg['From'] = SENDER_EMAIL
    msg['To'] = recipient_email
    
    body = f"""
    Halo {username},

    Selamat! Akun Anda di MotoCare App telah berhasil dibuat.

    Detail Akun Anda:
    - Nama Pengguna: {username}
    - Email Login: {recipient_email}
    
    Anda sekarang dapat login dan mulai mencatat riwayat service motor Anda.

    Terima kasih,
    Tim MotoCare App
    """
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        # print(f"Gagal mengirim email: {e}")
        return False


def set_background_image(image_url):
    """Menyuntikkan CSS kustom untuk mengatur gambar atau warna latar belakang."""
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-image: url("{image_url}");
            background-size: cover;
            background-repeat: no-repeat;
            background-attachment: fixed;
        }}
        
        div[data-testid="stSidebarContent"] * {{
             color: white !important;
        }}
        
        div[data-testid="stSidebar"] {{
             background-color: rgba(20, 20, 20, 0.7);
        }}

        [data-testid="stExpander"] div:first-child {{
            background-color: #333333;
            color: white;
        }}
        [data-testid="stExpander"] div:first-child p,
        [data-testid="stExpander"] div:first-child h3,
        [data-testid="stExpander"] div:first-child h4 {{
            color: white !important;
        }}
        </style>
        """,
        unsafe_allow_html=True
    )


# ====================================================================
# 1. KONFIGURASI DATABASE & MODEL
# ====================================================================

DATABASE_URL = "sqlite:///motocare.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- MODEL DATABASE ---

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    password = Column(String)
    is_admin = Column(Boolean, default=False)
    motors = relationship("Motor", back_populates="owner")

class Motor(Base):
    __tablename__ = "motors"
    id = Column(Integer, primary_key=True, index=True)
    brand = Column(String, nullable=False)
    model = Column(String, nullable=False)
    year = Column(Integer)
    plate_number = Column(String) # NEW: Kolom Nomor Plat
    current_km = Column(Integer, default=0)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="motors")
    services = relationship("Service", back_populates="motor")
    schedule = relationship("Schedule", back_populates="motor", uselist=False)

class Service(Base):
    __tablename__ = "services"
    id = Column(Integer, primary_key=True, index=True)
    service_date = Column(String, nullable=False)
    km_at_service = Column(Integer)
    description = Column(String)
    cost = Column(Integer)
    workshop_name = Column(String) # NEW: Nama Bengkel
    workshop_address = Column(String) # NEW: Alamat Bengkel
    workshop_photo_base64 = Column(String) # NEW: Foto Bengkel (dalam format Base64)

    motor_id = Column(Integer, ForeignKey("motors.id"))

    motor = relationship("Motor", back_populates="services")

class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, index=True)

    time_interval_months = Column(Integer, default=2)
    km_interval = Column(Integer, default=2000)

    motor_id = Column(Integer, ForeignKey("motors.id"), unique=True)

    motor = relationship("Motor", back_populates="schedule")


Base.metadata.create_all(bind=engine)

# ====================================================================
# 2. FUNGSI DATABASE HELPERS
# ====================================================================

def get_db():
    """Membuat koneksi database yang aman."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_count(db: Session):
    """Menghitung total semua pengguna dalam database."""
    return db.query(User).count()

def get_admin_count(db: Session):
    """Menghitung total pengguna yang berstatus admin."""
    return db.query(User).filter(User.is_admin == True).count()

def create_new_user(db, username, email, password):
    """Mendaftarkan pengguna baru ke database."""
    hashed_password = generate_password_hash(password)
    # Aturan Admin: Hanya user pertama yang otomatis jadi admin (Super Admin)
    is_first_user = db.query(User).count() == 0

    db_user = User(
        username=username,
        email=email,
        password=hashed_password,
        is_admin=is_first_user
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def delete_user_and_data(db: Session, user_id):
    """Menghapus user dan SEMUA data motor, service, dan jadwal terkait."""

    motors = db.query(Motor).filter(Motor.owner_id == user_id).all()
    for motor in motors:
        db.query(Schedule).filter(Schedule.motor_id == motor.id).delete(synchronize_session=False)
        db.query(Service).filter(Service.motor_id == motor.id).delete(synchronize_session=False)

    db.query(Motor).filter(Motor.owner_id == user_id).delete(synchronize_session=False)

    user = db.query(User).filter(User.id == user_id).first()
    if user:
        db.delete(user)
        db.commit()
        return True
    return False

def toggle_user_admin_status(db: Session, user_id):
    """Mengubah status is_admin seorang user."""
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_admin = not user.is_admin
        db.commit()
        return user.is_admin
    return None

def get_motors_by_owner(db, owner_id):
    return db.query(Motor).filter(Motor.owner_id == owner_id).all()

# MODIFIED: Menambahkan plate_number
def create_new_motor(db, owner_id, brand, model, year, current_km, plate_number):
    db_motor = Motor(
        owner_id=owner_id,
        brand=brand,
        model=model,
        year=year,
        plate_number=plate_number, # NEW
        current_km=current_km
    )
    db.add(db_motor)
    db.commit()
    db.refresh(db_motor)

    db_schedule = Schedule(
        motor_id=db_motor.id,
        time_interval_months=2,
        km_interval=2000
    )
    db.add(db_schedule)
    db.commit()
    db.refresh(db_motor)

    return db_motor

# MODIFIED: Menambahkan detail bengkel dan foto
def create_new_service(db, motor_id, service_date, km_at_service, description, cost, workshop_name, workshop_address, workshop_photo_base64):
    db_service = Service(
        motor_id=motor_id,
        service_date=service_date,
        km_at_service=km_at_service,
        description=description,
        cost=cost,
        workshop_name=workshop_name, # NEW
        workshop_address=workshop_address, # NEW
        workshop_photo_base64=workshop_photo_base64 # NEW
    )
    db.add(db_service)
    db.commit()
    db.refresh(db_service)
    return db_service

def update_motor_km(db, motor_id, new_km):
    motor = db.query(Motor).filter(Motor.id == motor_id).first()
    if motor and new_km > motor.current_km:
        motor.current_km = new_km
        db.commit()
        return True
    return False

def get_services_by_motor(db, motor_id):
    return db.query(Service).filter(Service.motor_id == motor_id).order_by(Service.service_date.desc()).all()

def get_total_service_cost(db, motor_id):
    total_cost = db.query(Service).filter(Service.motor_id == motor_id).with_entities(Service.cost).all()
    return sum(cost[0] for cost in total_cost)

def get_average_service_cost(db, motor_id):
    costs = db.query(Service).filter(Service.motor_id == motor_id).with_entities(Service.cost).all()
    if not costs:
        return 0
    total_cost = sum(cost[0] for cost in costs)
    num_services = len(costs)
    return round(total_cost / num_services)

def delete_motor(db, motor_id):
    db.query(Schedule).filter(Schedule.motor_id == motor_id).delete(synchronize_session=False)
    db.query(Service).filter(Service.motor_id == motor_id).delete(synchronize_session=False)
    motor = db.query(Motor).filter(Motor.id == motor_id).first()
    if motor:
        db.delete(motor)
        db.commit()
        return True
    return False

def delete_service_record(db, service_id):
    service_record = db.query(Service).filter(Service.id == service_id).first()
    if service_record:
        db.delete(service_record)
        db.commit()
        return True
    return False

def update_motor_schedule(db, motor_id, time_months, km_interval):
    schedule = db.query(Schedule).filter(Schedule.motor_id == motor_id).first()
    if schedule:
        schedule.time_interval_months = time_months
        schedule.km_interval = km_interval
        db.commit()
        return True
    return False

def get_schedule_by_motor(db, motor_id):
    return db.query(Schedule).filter(Schedule.motor_id == motor_id).first()


def calculate_next_service_date(db, motor_id):
    schedule = get_schedule_by_motor(db, motor_id)
    interval_months = schedule.time_interval_months if schedule else 2

    last_service = db.query(Service).filter(Service.motor_id == motor_id).order_by(Service.service_date.desc()).first()

    if last_service:
        last_date_str = last_service.service_date
    else:
        last_date_str = datetime.date.today().strftime("%Y-%m-%d")

    try:
        last_date = datetime.datetime.strptime(last_date_str, "%Y-%m-%d").date()
    except ValueError:
        last_date = datetime.date.today()

    year = last_date.year
    month = last_date.month + interval_months

    while month > 12:
        month -= 12
        year += 1

    day = min(last_date.day, 28 if month == 2 else 30 if month in [4, 6, 9, 11] else 31)

    next_date = datetime.date(year, month, day)

    if not last_service and next_date <= datetime.date.today():
         today = datetime.date.today()

         year = today.year
         month = today.month + interval_months
         while month > 12:
            month -= 12
            year += 1
         day = min(today.day, 28 if month == 2 else 30 if month in [4, 6, 9, 11] else 31)
         next_date = datetime.date(year, month, day)

    return next_date

def calculate_next_service_km(db, motor_id):
    schedule = get_schedule_by_motor(db, motor_id)
    km_interval = schedule.km_interval if schedule else 2000

    motor = db.query(Motor).filter(Motor.id == motor_id).first()
    current_km = motor.current_km if motor else 0

    last_service = db.query(Service).filter(Service.motor_id == motor_id).order_by(Service.km_at_service.desc()).first()
    last_km = last_service.km_at_service if last_service else 0

    next_km = last_km + km_interval

    if not last_service:
        next_km = current_km + km_interval

    return next_km
# =======================================================================


# ====================================================================
# 3. FUNGSI EKSTERNAL (API)
# ====================================================================

def search_nearby_workshops(api_key, location_query, radius=5000):
    """Mencari bengkel motor/mobil terdekat menggunakan Google Places API. (Simulasi)"""

    if "jakarta" in location_query.lower():
        lat, lng = -6.175110, 106.865036
    elif "surabaya" in location_query.lower():
        lat, lng = -7.257472, 112.752090
    else:
        lat, lng = -6.175110, 106.865036

    simulated_results = [
        {"name": "Bengkel Ahli Motor (Simulasi)", "address": "Jl. Merdeka No. 12, Jakarta", "rating": 4.5},
        {"name": "Service Cepat Jaya (Simulasi)", "address": "Jl. Sudirman Kav. 5, Jakarta", "rating": 4.1},
        {"name": "Ganti Oli 24 Jam (Simulasi)", "address": "Jl. MH Thamrin, Jakarta", "rating": 4.7},
    ]

    return simulated_results

# ====================================================================
# 4. FUNGSI TAMPILAN (FORMS & PAGES)
# ====================================================================

def admin_login_form(db: Session):
    st.title("Admin Panel Login 🔑")

    with st.form("admin_login_form"):
        email = st.text_input("Email Admin")
        password = st.text_input("Password Admin", type="password")

        submitted = st.form_submit_button("Login")

        if submitted:
            user = get_user_by_email(db, email)

            # Periksa: Apakah pengguna ada DAN apakah is_admin = True
            is_valid_admin = (
                user is not None and
                user.is_admin and
                check_password_hash(user.password, password)
            )

            if is_valid_admin:
                # Set Session State untuk Admin
                st.session_state['logged_in'] = True
                st.session_state['user_id'] = user.id
                st.session_state['username'] = user.username
                st.session_state['is_admin'] = True
                st.success(f"Selamat datang, Admin {user.username}!")
                st.rerun()
            else:
                st.error("Kredensial tidak valid atau pengguna bukan Admin.")


def register_form(db: Session):
    """Menampilkan formulir pendaftaran, dan form pembuatan admin jika sudah login admin."""
    st.title("DAFTAR AKUN BARU")

    # Cek apakah ini pengguna pertama (untuk Super Admin setup)
    is_first_user = get_user_count(db) == 0
    current_admin_count = get_admin_count(db)

    # 1. FORM REGISTRASI PENGGUNA BIASA
    with st.form("register_form"):
        username = st.text_input("Nama Pengguna")
        email = st.text_input("Email")
        password = st.text_input("Kata Sandi", type="password")
        confirm_password = st.text_input("Konfirmasi Kata Sandi", type="password")

        submitted = st.form_submit_button("Daftar")

        if submitted:
            if not username or not email or not password or not confirm_password:
                 st.error("Semua kolom harus diisi.")
                 return

            if password != confirm_password:
                st.error("Konfirmasi kata sandi tidak cocok.")
                return

            if get_user_by_email(db, email):
                st.error("Email sudah terdaftar. Silakan gunakan email lain.")
            else:
                new_user = create_new_user(db, username, email, password)

                email_sent = send_welcome_email(email, username)

                if new_user.is_admin:
                    st.success("Pendaftaran berhasil! Anda adalah **Admin** pertama! Silakan masuk melalui Login Admin.")
                elif email_sent:
                    st.success("Pendaftaran berhasil! Silakan masuk. Cek email Anda untuk konfirmasi.")
                else:
                    st.success("Pendaftaran berhasil! Silakan masuk. (Peringatan: Gagal mengirim email konfirmasi, periksa pengaturan SMTP.)")

                st.rerun()

    # 2. FORM PEMBUATAN ADMIN (Hanya terlihat jika admin sedang login)
    if st.session_state.get('is_admin'):
        st.markdown("---")

        if current_admin_count < 3:
            st.subheader(f"🔑 Admin Creation (Admin saat ini: {current_admin_count}/3)")
            with st.expander("Buat Akun Admin Tambahan"):
                 with st.form("create_admin_form"):
                    admin_username = st.text_input("Username Admin")
                    admin_email = st.text_input("Email Admin")
                    admin_password = st.text_input("Password Admin", type="password")

                    admin_submitted = st.form_submit_button("Buat Admin Baru")

                    if admin_submitted:
                        if current_admin_count >= 3:
                            st.error("Batas maksimal **3 Admin** sudah tercapai.")
                        elif get_user_by_email(db, admin_email):
                            st.warning("Email Admin sudah terdaftar.")
                        else:
                            # Buat pengguna baru dengan is_admin=True
                            new_admin = User(
                                username=admin_username,
                                email=admin_email,
                                password=generate_password_hash(admin_password),
                                is_admin=True
                            )
                            db.add(new_admin)
                            db.commit()
                            st.success(f"Akun admin '{admin_username}' berhasil dibuat. Total admin: {current_admin_count + 1}/3")
                            st.rerun()
        else:
            st.info(f"Batas maksimal 3 Admin sudah tercapai. Total admin: {current_admin_count}/3")


def login_form(db: Session):
    """Menampilkan formulir login pengguna biasa."""
    st.title("MASUK KE AKUN ANDA")

    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Kata Sandi", type="password")

        submitted = st.form_submit_button("Masuk")

        if submitted:
            user = get_user_by_email(db, email)

            # Hanya izinkan login jika bukan admin atau admin yang login melalui halaman regular
            if user and check_password_hash(user.password, password):
                st.session_state['logged_in'] = True
                st.session_state['username'] = user.username
                st.session_state['user_id'] = user.id
                st.session_state['is_admin'] = user.is_admin

                if user.is_admin:
                     st.warning("Anda login sebagai Admin. Direkomendasikan menggunakan 'Login Admin' untuk akses penuh.")
                else:
                    st.success("Login berhasil! Mengarahkan ke Dashboard...")

                st.rerun()
            else:
                st.error("Email atau kata sandi salah. Silakan coba lagi.")


def admin_dashboard(db: Session):
    """Menampilkan halaman untuk Admin mengelola pengguna."""
    st.title("⚙️ PANEL ADMINISTRATOR")
    st.warning("Halaman ini hanya untuk Administrator. Gunakan dengan hati-hati!")
    st.write("---")

    total_users = db.query(User).count()
    total_motors = db.query(Motor).count()

    col1, col2 = st.columns(2)
    col1.metric("Total Pengguna", total_users)
    col2.metric("Total Motor Terdaftar", total_motors)

    # Panggil Form Registrasi untuk fungsi membuat admin tambahan
    register_form(db)

    st.subheader("Kelola Pengguna Terdaftar")

    all_users = db.query(User).order_by(User.id).all()
    current_admin_id = st.session_state.get('user_id')

    # Header Tabel
    col_id, col_email, col_admin, col_action = st.columns([0.5, 2, 1, 2])
    col_id.markdown("**ID**")
    col_email.markdown("**Nama (Email)**")
    col_admin.markdown("**Status Admin**")
    col_action.markdown("**Aksi**")
    st.markdown("---")

    for user in all_users:
        col_id, col_email, col_admin, col_action = st.columns([0.5, 2, 1, 2])

        col_id.write(user.id)
        col_email.write(f"{user.username} ({user.email})")
        col_admin.write("Admin ✅" if user.is_admin else "Pengguna 👤")

        with col_action:
            if user.id != current_admin_id: # Admin tidak bisa menghapus/mengubah status dirinya sendiri
                col_btn1, col_btn2 = st.columns(2)

                # Tombol Toggle Admin (Hanya jika total admin tidak mencapai batas 3)
                is_max_admin = get_admin_count(db) >= 3 and not user.is_admin

                btn_label = "Hapus Admin" if user.is_admin else "Jadikan Admin"
                if col_btn1.button(btn_label, key=f"toggle_{user.id}", type="secondary", disabled=is_max_admin):
                    new_status = toggle_user_admin_status(db, user.id)
                    st.success(f"Status admin untuk {user.username} diubah menjadi {'Admin' if new_status else 'Pengguna'}.")
                    st.rerun()
                elif is_max_admin:
                    col_btn1.write("Batas Admin Tercapai")

                # Tombol Hapus User
                if col_btn2.button("Hapus User", key=f"del_user_admin_{user.id}", type="primary"):
                    if st.session_state.get(f'confirm_del_user_{user.id}') is True:
                        if delete_user_and_data(db, user.id):
                            st.success(f"Pengguna {user.username} dan semua datanya berhasil dihapus.")
                        else:
                            st.error("Gagal menghapus pengguna.")
                        st.session_state.pop(f'confirm_del_user_{user.id}')
                        st.rerun()
                    else:
                        st.session_state[f'confirm_del_user_{user.id}'] = True
                        st.error("Tekan 'Hapus User' lagi untuk **KONFIRMASI PENGHAPUSAN PERMANEN**.")
                        st.rerun()
            else:
                st.write("Anda (Admin Aktif)")

    st.markdown("---")


def display_motors(db):
    st.subheader("Daftar Motor Saya 🏍️")
    owner_id = st.session_state.get('user_id')
    motors = get_motors_by_owner(db, owner_id)
    if not motors:
        st.info("Anda belum memiliki motor terdaftar. Silakan tambahkan motor Anda!")
    else:
        for motor in motors:
            is_confirming = st.session_state.get(f'confirm_delete_{motor.id}', False)
            total_cost = get_total_service_cost(db, motor.id)
            # MODIFIED: Judul expander menampilkan Nomor Plat
            with st.expander(f"**{motor.brand} {motor.model}** ({motor.plate_number})"):
                st.markdown(f"**Merek:** {motor.brand}")
                st.markdown(f"**Model:** {motor.model}")
                st.markdown(f"**Tahun:** {motor.year}")
                st.markdown(f"**Nomor Plat:** {motor.plate_number}") # NEW: Tampilkan Nomor Plat
                st.markdown(f"**Kilometer Saat Ini:** {motor.current_km:,} KM")
                st.markdown(f"**Total Biaya Service:** **Rp {total_cost:,}** 💸")
                st.markdown("---")
                col1, col2, col3, col4 = st.columns([1, 1, 1, 1])
                with col1:
                    if st.button(f"Catat Service", key=f"service_{motor.id}"):
                        st.session_state['action'] = 'catat_service'
                        st.session_state['selected_motor_id'] = motor.id
                        st.rerun()
                with col2:
                    if st.button(f"Lihat Riwayat", key=f"history_{motor.id}"):
                        st.session_state['action'] = 'view_history'
                        st.session_state['selected_motor_id'] = motor.id
                        st.rerun()
                with col3:
                    if st.button("Kelola Pengingat", key=f"schedule_{motor.id}", type="secondary"):
                        st.session_state['action'] = 'manage_schedule'
                        st.session_state['selected_motor_id'] = motor.id
                        st.rerun()
                with col4:
                    if is_confirming:
                        if st.button("KONFIRMASI HAPUS!", key=f"confirm_delete_btn_{motor.id}", type="primary"):
                            if delete_motor(db, motor.id):
                                st.success(f"Motor {motor.model} berhasil dihapus.")
                            else:
                                st.error("Gagal menghapus motor.")
                            st.session_state.pop(f'confirm_delete_{motor.id}')
                            st.rerun()
                        st.button("Batal", key=f"cancel_delete_{motor.id}", on_click=lambda m_id=motor.id: st.session_state.pop(f'confirm_delete_{m_id}'), args=[])
                    else:
                        if st.button("Hapus Motor", key=f"delete_{motor.id}", type="secondary"):
                            st.session_state[f'confirm_delete_{motor.id}'] = True
                            st.warning("Tekan 'KONFIRMASI HAPUS' di atas untuk menghapus motor dan semua data servicenya.")
                            st.rerun()

def add_motor_form(db):
    st.subheader("Tambahkan Motor Baru Anda")
    owner_id = st.session_state.get('user_id')
    with st.form("motor_form"):
        brand = st.text_input("Merek (Contoh: Yamaha, Honda)", max_chars=50)
        model = st.text_input("Model (Contoh: NMax, Beat)", max_chars=50)
        plate_number = st.text_input("Nomor Plat Motor (Contoh: B 1234 ABC)", max_chars=15).upper() # NEW: Input Nomor Plat
        year = st.number_input("Tahun Pembelian", min_value=1990, max_value=datetime.date.today().year + 1, value=datetime.date.today().year)
        current_km = st.number_input("Kilometer Saat Ini", min_value=0, value=0)
        submitted = st.form_submit_button("Simpan Motor")
        if submitted:
            # MODIFIED: Tambah validasi Nomor Plat
            if not brand or not model or not plate_number:
                st.error("Merek, Model, dan Nomor Plat harus diisi.")
                return
            # MODIFIED: Tambah plate_number ke fungsi create_new_motor
            create_new_motor(db, owner_id, brand, model, year, current_km, plate_number)
            st.success(f"Motor {brand} {model} berhasil ditambahkan!")
            st.rerun()

def service_form(db):
    st.subheader("Catat Service Motor")
    if st.button("← Kembali ke Daftar Motor", key="back_from_service_form"):
        st.session_state['action'] = 'view_motors'
        st.session_state.pop('selected_motor_id', None)
        st.rerun()
    owner_id = st.session_state.get('user_id')
    motors = get_motors_by_owner(db, owner_id)
    if not motors:
        st.warning("Anda belum memiliki motor terdaftar. Silakan tambahkan motor terlebih dahulu.")
        return
    # MODIFIED: Tampilkan Nomor Plat di pilihan motor
    motor_options = {f"{m.brand} {m.model} ({m.plate_number})": m.id for m in motors}
    selected_motor_display = st.selectbox(
        "Pilih Motor yang Diservice:",
        options=list(motor_options.keys())
    )
    selected_motor_id = motor_options[selected_motor_display]
    avg_cost = get_average_service_cost(db, selected_motor_id)

    if avg_cost > 0:
        st.info(f"Biaya Rata-Rata Service sebelumnya: **Rp {avg_cost:,}**")
    else:
        st.info("Belum ada riwayat biaya service. Catatan ini akan menjadi yang pertama!")

    with st.form("service_entry_form"):
        service_date = st.date_input("Tanggal Service", value=datetime.date.today()).strftime("%Y-%m-%d")
        km_at_service = st.number_input("Kilometer Saat Service", min_value=1)
        cost = st.number_input("Biaya Service (Rp)", min_value=0)
        description = st.text_area("Deskripsi Pekerjaan/Part yang Diganti")

        # --- NEW: INPUT DETAIL BENGKEL DAN FOTO ---
        st.markdown("---")
        st.markdown("**Detail Bengkel (Dokumentasi Service)**")
        workshop_name = st.text_input("Nama Bengkel", max_chars=100)
        workshop_address = st.text_area("Alamat Bengkel")
        workshop_photo = st.file_uploader("Upload Foto Bengkel/Kwitansi Service (Opsional)", type=['jpg', 'jpeg', 'png'])

        # Logic to convert photo to Base64 for storage
        photo_base64 = None
        if workshop_photo is not None:
            photo_bytes = workshop_photo.read()
            photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        # ----------------------------------------

        submitted = st.form_submit_button("Simpan Catatan Service")

        if submitted:
            if not service_date or not description:
                st.error("Tanggal dan Deskripsi harus diisi.")
                return

            # MODIFIED: Tambah parameter detail bengkel dan foto ke fungsi create_new_service
            create_new_service(db, selected_motor_id, service_date, km_at_service, description, cost, workshop_name, workshop_address, photo_base64)
            is_km_updated = update_motor_km(db, selected_motor_id, km_at_service)
            if is_km_updated:
                st.success(f"Catatan service untuk {selected_motor_display} berhasil disimpan! Kilometer motor diperbarui menjadi {km_at_service:,} KM. ✅")
            else:
                st.warning(f"Catatan service berhasil disimpan, tetapi Kilometer motor TIDAK diperbarui karena KM service ({km_at_service:,} KM) lebih kecil dari KM saat ini.")
            st.rerun()

def display_service_history(db, motor_id, motor_display_name):
    st.subheader(f"Riwayat Service: {motor_display_name}")
    services = get_services_by_motor(db, motor_id)
    if not services:
        st.info("Belum ada riwayat service yang dicatat untuk motor ini.")
        if st.button(f"Catat Service Sekarang untuk {motor_display_name}", key=f"quick_service_{motor_id}"):
            st.session_state['action'] = 'catat_service'
            st.session_state['selected_motor_id'] = motor_id
            st.rerun()
    else:
        # MODIFIED: Sesuaikan lebar kolom untuk mengakomodasi expander
        col_date, col_km, col_desc_summary, col_cost, col_action = st.columns([1.5, 1, 2.5, 1.5, 1])
        col_date.markdown("**Tanggal**")
        col_km.markdown("**KM**")
        col_desc_summary.markdown("**Detail Service**") # Judul untuk kolom Expander
        col_cost.markdown("**Biaya (Rp)**")
        col_action.markdown("**Aksi**")
        st.markdown("---")
        for s in services:
            col_date, col_km, col_desc_summary, col_cost, col_action = st.columns([1.5, 1, 2.5, 1.5, 1])
            col_date.write(s.service_date)
            col_km.write(f"{s.km_at_service:,}")

            # NEW: Gunakan expander untuk menampilkan detail service, termasuk info bengkel dan foto
            with col_desc_summary:
                with st.expander(f"Detail Service - {s.service_date}"):
                    st.markdown(f"**Deskripsi Pekerjaan:** {s.description}")
                    st.markdown("---")
                    st.markdown("**Detail Bengkel:**")
                    st.write(f"**Nama Bengkel:** {s.workshop_name or '-'}")
                    st.write(f"**Alamat Bengkel:** {s.workshop_address or '-'}")

                    if s.workshop_photo_base64:
                        st.markdown("---")
                        st.markdown("**Foto/Kwitansi Dokumentasi:**")
                        try:
                            # Reconstruct image from base64
                            img_data = base64.b64decode(s.workshop_photo_base64)
                            # Pastikan data bisa di-display sebagai gambar
                            st.image(io.BytesIO(img_data), caption="Dokumentasi Service", use_column_width=True)
                        except Exception as e:
                            st.error("Gagal menampilkan foto dokumentasi.")
                    else:
                        st.info("Tidak ada foto dokumentasi service.")

            col_cost.write(f"Rp {s.cost:,}")

            with col_action:
                if st.button("Hapus", key=f"del_svc_{s.id}", type="secondary"):
                    if st.session_state.get(f'confirm_del_svc_{s.id}') is True:
                        if delete_service_record(db, s.id):
                            st.success("Catatan service berhasil dihapus.")
                        else:
                            st.error("Gagal menghapus catatan service.")
                        st.session_state.pop(f'confirm_del_svc_{s.id}')
                        st.rerun()
                    else:
                        st.session_state[f'confirm_del_svc_{s.id}'] = True
                        st.warning("Tekan 'Hapus' lagi untuk konfirmasi!")
                        st.rerun()
    st.markdown("---")
    if st.button("← Kembali ke Daftar Motor", key="back_to_motors_from_history"):
        st.session_state['action'] = 'view_motors'
        st.session_state.pop('view_history', None)
        st.rerun()

def manage_schedule_form(db, motor_id, motor_display_name):
    st.subheader(f"Kelola Pengingat Service: {motor_display_name}")
    if st.button("← Kembali ke Daftar Motor", key="back_from_schedule_form"):
        st.session_state['action'] = 'view_motors'
        st.session_state.pop('selected_motor_id', None)
        st.rerun()
    st.markdown("---")
    schedule = get_schedule_by_motor(db, motor_id)
    current_time = schedule.time_interval_months if schedule else 2
    current_km = schedule.km_interval if schedule else 2000
    st.info("Pengingat dihitung berdasarkan **mana yang lebih dulu tercapai** antara interval Waktu atau Jarak.")
    with st.form("schedule_config_form"):
        st.markdown("**1. Pengaturan Berdasarkan Waktu**")
        new_time_interval = st.number_input(
            "Service Berkala Setiap (Bulan):",
            min_value=1,
            max_value=12,
            value=current_time
        )
        st.markdown("---")
        st.markdown("**2. Pengaturan Berdasarkan Jarak Tempuh**")
        new_km_interval = st.number_input(
            "Service Berkala Setiap (KM):",
            min_value=500,
            step=500,
            value=current_km
        )
        submitted = st.form_submit_button("Simpan Pengaturan")
        if submitted:
            if update_motor_schedule(db, motor_id, new_time_interval, new_km_interval):
                st.success(f"Pengaturan pengingat untuk {motor_display_name} berhasil diperbarui!")
            else:
                st.error("Gagal memperbarui pengaturan jadwal.")
            st.rerun()

def nearby_workshop_page():
    st.subheader("📍 Temukan Bengkel Terdekat")
    st.info("Fitur ini memerlukan **API Key Google Maps** yang terpisah untuk berfungsi penuh. Saat ini menampilkan data simulasi.")
    with st.form("workshop_search_form"):
        location_query = st.text_input("Masukkan Lokasi Anda (Contoh: Jakarta Pusat)", "Jakarta")
        search_radius = st.slider("Jarak Pencarian Maksimal (meter)", min_value=1000, max_value=10000, value=5000, step=1000)
        google_api_key = st.text_input("API Key Google Maps (Opsional untuk simulasi)", "INPUT_API_KEY_ANDA_DI_SINI", type="password")
        submitted = st.form_submit_button("Cari Bengkel")
    if submitted:
        if google_api_key == "INPUT_API_KEY_ANDA_DI_SINI":
             st.warning("Menggunakan data simulasi karena API Key belum dimasukkan.")
        results = search_nearby_workshops(google_api_key, location_query, search_radius)
        if results:
            st.success(f"Ditemukan {len(results)} bengkel di dekat {location_query} (radius {search_radius}m).")
            for i, workshop in enumerate(results):
                st.markdown(f"**{i+1}. {workshop['name']}**")
                st.write(f"Alamat: {workshop['address']}")
                st.write(f"Rating: ⭐ {workshop.get('rating', 'N/A')}")
                st.markdown("---")
        else:
            st.warning(f"Tidak ada bengkel ditemukan di dekat {location_query} dengan radius {search_radius}m.")

def display_reminders(db, owner_id):
    st.subheader("🔔 Pengingat Service Anda")
    motors = get_motors_by_owner(db, owner_id)
    today = datetime.date.today()
    if not motors:
        st.info("Tambahkan motor untuk melihat pengingat service Anda.")
        return
    col_motor, col_next_date, col_next_km, col_status = st.columns([2, 1.5, 1.5, 2])
    col_motor.markdown("**Motor**")
    col_next_date.markdown("**Jatuh Tempo (Waktu)**")
    col_next_km.markdown("**Jatuh Tempo (KM)**")
    col_status.markdown("**Status**")
    st.markdown("---")
    needs_attention = False
    for motor in motors:
        next_date = calculate_next_service_date(db, motor.id)
        next_km = calculate_next_service_km(db, motor.id)
        days_left = (next_date - today).days
        km_left = next_km - motor.current_km

        # MODIFIED: Tampilkan Nomor Plat di daftar pengingat
        motor_display = f"{motor.brand} {motor.model} ({motor.plate_number})"

        if days_left <= 0 or km_left <= 0:
            status = f"**HARUS SERVICE!** 🚨"
            needs_attention = True
        elif days_left <= 14 or km_left <= 500:
            status = f"**Mendekati Jatuh Tempo** ⚠️"
            needs_attention = True
        else:
            status = f"Aman ✅"
        col_motor.write(motor_display)
        col_next_date.write(next_date.strftime("%d %b %Y"))
        col_next_km.write(f"{next_km:,} KM")
        col_status.markdown(status)
    if needs_attention:
        st.warning("Perhatikan motor dengan status **HARUS SERVICE** atau **Mendekati Jatuh Tempo**.")
    st.markdown("---")

def dashboard_page():
    """Menampilkan halaman utama setelah login."""

    db_generator = get_db()
    db = next(db_generator)

    is_admin = st.session_state.get('is_admin', False)

    st.title(f"Selamat Datang, {st.session_state['username']}! 👋")
    st.write("---")

    # --- NAVIGASI ADMIN/USER ---
    if is_admin:
        menu_options = ["Motor Saya", "Catat Service Baru", "Tambah Motor", "Cari Bengkel", "Admin Panel"]
    else:
        menu_options = ["Motor Saya", "Catat Service Baru", "Tambah Motor", "Cari Bengkel"]

    dashboard_menu = st.sidebar.radio("Menu Dashboard", menu_options, key='dashboard_menu_radio')
    # -----------------------------

    current_action = st.session_state.get('action')
    selected_motor_id = st.session_state.get('selected_motor_id')

    # ADMIN PANEL CHECK
    if dashboard_menu == "Admin Panel" and is_admin:
        st.session_state['action'] = 'admin_panel'
        admin_dashboard(db)
        return # Hentikan eksekusi dashboard normal

    # Tampilkan Pengingat di bagian atas dashboard normal
    display_reminders(db, st.session_state.get('user_id'))

    if current_action == 'view_history' and selected_motor_id:
        motor = db.query(Motor).filter(Motor.id == selected_motor_id).first()
        if motor:
            display_service_history(db, selected_motor_id, f"{motor.brand} {motor.model}")

    elif current_action == 'catat_service':
        service_form(db)

    elif current_action == 'manage_schedule' and selected_motor_id:
        motor = db.query(Motor).filter(Motor.id == selected_motor_id).first()
        if motor:
            manage_schedule_form(db, selected_motor_id, f"{motor.brand} {motor.model}")

    elif dashboard_menu == "Tambah Motor":
        st.session_state['action'] = 'add_motor'
        add_motor_form(db)

    elif dashboard_menu == "Catat Service Baru":
        st.session_state['action'] = 'catat_service_menu'
        service_form(db)

    elif dashboard_menu == "Cari Bengkel":
        st.session_state['action'] = 'find_workshop'
        nearby_workshop_page()

    elif dashboard_menu == "Motor Saya":
        st.session_state['action'] = 'view_motors'
        display_motors(db)

    else: # Default view
        display_motors(db)

    st.write("---")
    if st.button("Keluar (Logout)", type="primary"):
        st.session_state['logged_in'] = False
        st.session_state.pop('username', None)
        st.session_state.pop('user_id', None)
        st.session_state.pop('is_admin', None)
        st.rerun()


# ====================================================================
# 5. LOGIKA APLIKASI UTAMA
# ====================================================================

def main():
    # MODIFIED: Menambahkan page_icon untuk favicon
    st.set_page_config(layout="centered", page_title="MotoCare App", page_icon="🏍️")

    # --- PANGGIL FUNGSI BACKGROUND DAN TEMA ---
    set_background_image("https://upload.wikimedia.org/wikipedia/commons/thumb/d/d3/Solid_black.svg/2048px-Solid_black.svg.png")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['action'] = None
        st.session_state['is_admin'] = False

    db_generator = get_db()
    db = next(db_generator)

    # NEW: Menampilkan logo di Sidebar
    try:
        # Menampilkan gambar dengan lebar 200px. Ganti lebar jika terlalu besar/kecil
        st.sidebar.image(LOGO_FILE_PATH, width=200)
        # Hapus title lama jika logo sudah tampil
        # st.sidebar.title("MotoCare App") 
    except FileNotFoundError:
        st.sidebar.warning(f"File logo '{LOGO_FILE_PATH}' tidak ditemukan.")
        st.sidebar.title("MotoCare App") # Fallback jika file tidak ada

    st.sidebar.info("Aplikasi Monitoring Service Motor")

    if st.session_state['logged_in']:
        dashboard_page()
    else:
        # st.sidebar.title("MotoCare App") # Pindah ke atas/dihapus
        
        page = st.sidebar.radio("Pilih Aksi", ["Login Pengguna", "Daftar", "Login Admin"], key='main_nav_radio')

        if page == "Daftar":
            register_form(db)
        elif page == "Login Pengguna":
            login_form(db)
        elif page == "Login Admin":
            admin_login_form(db)

if __name__ == "__main__":
    main()