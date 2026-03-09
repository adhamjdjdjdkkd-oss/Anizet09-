import logging
import os
import sqlite3
import datetime
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import RetryAfter, TimedOut

# Bot tokeni
BOT_TOKEN = "8461887536:AAGpYdaJLskR2mcBDzEhG6BB9BZBnhpV4lY"
ADMIN_IDS = [7991544389]  # Sizning ID'ingiz
WEBAPP_URL = "https://anicrab.uz"  # Web sayt URL

# Papkalar
VIDEO_FOLDER = "anime_videos"
POSTER_FOLDER = "posters"
DB_FILE = "anicrab.db"

# Papkalarni yaratish
os.makedirs(VIDEO_FOLDER, exist_ok=True)
os.makedirs(POSTER_FOLDER, exist_ok=True)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
SEARCH_BY_CODE = 1
ADD_CHANNEL = 2
ADD_ANIME = 3
ADD_EPISODE = 4
BROADCAST = 5
EDIT_SETTINGS = 6

# ==================== MA'LUMOTLAR BAZASI ====================
class Database:
    def __init__(self):
        self.init_db()
    
    def init_db(self):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            
            # Foydalanuvchilar
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    join_date TEXT,
                    last_active TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    is_admin INTEGER DEFAULT 0
                )
            ''')
            
            # KANALLAR
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    channel_name TEXT,
                    channel_link TEXT,
                    is_active INTEGER DEFAULT 1,
                    added_by INTEGER,
                    added_date TEXT,
                    order_num INTEGER DEFAULT 0
                )
            ''')
            
            # Anime ma'lumotlari
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS anime (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE,
                    title TEXT,
                    title_ru TEXT,
                    title_en TEXT,
                    genre TEXT,
                    studio TEXT,
                    year INTEGER,
                    episodes INTEGER,
                    rating TEXT,
                    description TEXT,
                    language TEXT DEFAULT 'O\'zbekcha',
                    voice_actor TEXT,
                    poster TEXT,
                    channel_post_id INTEGER,
                    created_date TEXT,
                    views INTEGER DEFAULT 0
                )
            ''')
            
            # Anime qismlari
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    anime_id INTEGER,
                    episode_number INTEGER,
                    title TEXT,
                    video_path TEXT,
                    video_url TEXT,
                    duration TEXT,
                    file_size TEXT,
                    views INTEGER DEFAULT 0,
                    added_date TEXT,
                    FOREIGN KEY (anime_id) REFERENCES anime (id) ON DELETE CASCADE,
                    UNIQUE(anime_id, episode_number)
                )
            ''')
            
            # Favoritlar
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS favorites (
                    user_id INTEGER,
                    anime_id INTEGER,
                    added_date TEXT,
                    PRIMARY KEY (user_id, anime_id),
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (anime_id) REFERENCES anime (id)
                )
            ''')
            
            # Tarix
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    anime_id INTEGER,
                    episode_id INTEGER,
                    watched_date TEXT,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (anime_id) REFERENCES anime (id),
                    FOREIGN KEY (episode_id) REFERENCES episodes (id)
                )
            ''')
            
            # Sozlamalar
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Default sozlamalar
            default_settings = [
                ('bot_name', 'Anicrab.uz'),
                ('bot_username', 'anicrab_bot'),
                ('webapp_url', WEBAPP_URL),
                ('watch_button_text', '🎬 Tomosha qilish'),
                ('download_button_text', '📥 Yuklab olish'),
                ('welcome_message', '👋 Salom botimizga xush kelipsiz!'),
                ('maintenance_mode', 'off'),
                ('maintenance_message', '🔧 Botda texnik ishlar olib borilmoqda. Keyinroq urinib ko\'ring.')
            ]
            
            for key, value in default_settings:
                cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value))
            
            # Admin foydalanuvchi
            for admin_id in ADMIN_IDS:
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, username, first_name, join_date, is_admin)
                    VALUES (?, ?, ?, ?, 1)
                ''', (admin_id, 'admin', 'Admin', datetime.datetime.now().isoformat()))
            
            conn.commit()
    
    def execute(self, query: str, params: tuple = ()):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor
    
    def fetch_one(self, query: str, params: tuple = ()):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchone()
    
    def fetch_all(self, query: str, params: tuple = ()):
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()
    
    # ========== FOYDALANUVCHILAR ==========
    def add_user(self, user_id, username, first_name, last_name=None):
        """Yangi foydalanuvchi qo'shish"""
        now = datetime.datetime.now().isoformat()
        self.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, join_date, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, last_name, now, now))
    
    def update_user_activity(self, user_id):
        """Foydalanuvchi aktivligini yangilash"""
        self.execute('''
            UPDATE users SET last_active = ? WHERE user_id = ?
        ''', (datetime.datetime.now().isoformat(), user_id))
    
    def get_user(self, user_id):
        """Foydalanuvchi ma'lumotlarini olish"""
        return self.fetch_one('SELECT * FROM users WHERE user_id = ?', (user_id,))
    
    def get_all_users(self, limit=100):
        """Barcha foydalanuvchilarni olish"""
        return self.fetch_all('''
            SELECT user_id, username, first_name, join_date, last_active, is_blocked
            FROM users ORDER BY join_date DESC LIMIT ?
        ''', (limit,))
    
    def get_users_count(self):
        """Foydalanuvchilar soni"""
        return self.fetch_one("SELECT COUNT(*) FROM users")[0]
    
    def get_active_users_count(self, days=7):
        """Oxirgi kunlardagi aktiv foydalanuvchilar"""
        date = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
        return self.fetch_one('''
            SELECT COUNT(*) FROM users WHERE last_active > ?
        ''', (date,))[0]
    
    def block_user(self, user_id):
        """Foydalanuvchini bloklash"""
        self.execute('UPDATE users SET is_blocked = 1 WHERE user_id = ?', (user_id,))
    
    def unblock_user(self, user_id):
        """Foydalanuvchini blokdan chiqarish"""
        self.execute('UPDATE users SET is_blocked = 0 WHERE user_id = ?', (user_id,))
    
    # ========== KANALLAR ==========
    def get_active_channels(self):
        """Faol kanallarni olish"""
        return self.fetch_all('''
            SELECT channel_id, channel_name, channel_link FROM channels 
            WHERE is_active = 1
            ORDER BY order_num
        ''')
    
    def get_all_channels(self):
        """Barcha kanallarni olish"""
        return self.fetch_all('''
            SELECT id, channel_id, channel_name, channel_link, is_active 
            FROM channels
            ORDER BY is_active DESC, order_num
        ''')
    
    def toggle_channel(self, channel_id):
        """Kanal holatini o'zgartirish"""
        current = self.fetch_one("SELECT is_active FROM channels WHERE id = ?", (channel_id,))
        if current:
            new_status = 0 if current[0] == 1 else 1
            self.execute("UPDATE channels SET is_active = ? WHERE id = ?", (new_status, channel_id))
            return new_status
        return None
    
    def add_channel(self, channel_id, channel_name, channel_link, added_by):
        """Yangi kanal qo'shish"""
        self.execute('''
            INSERT INTO channels (channel_id, channel_name, channel_link, is_active, added_by, added_date)
            VALUES (?, ?, ?, 1, ?, ?)
        ''', (channel_id, channel_name, channel_link, added_by, datetime.datetime.now().isoformat()))
    
    def delete_channel(self, channel_id):
        """Kanalni o'chirish"""
        self.execute("DELETE FROM channels WHERE id = ?", (channel_id,))
    
    def get_channels_count(self):
        """Kanallar soni"""
        return self.fetch_one("SELECT COUNT(*) FROM channels WHERE is_active = 1")[0]
    
    # ========== ANIMELAR ==========
    def add_anime(self, code, title, genre, language, voice_actor, description="", year=2024, episodes=12, rating="N/A"):
        """Yangi anime qo'shish"""
        now = datetime.datetime.now().isoformat()
        self.execute('''
            INSERT INTO anime (code, title, genre, language, voice_actor, description, year, episodes, rating, created_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (code.upper(), title, genre, language, voice_actor, description, year, episodes, rating, now))
        return self.fetch_one("SELECT id FROM anime WHERE code = ?", (code.upper(),))[0]
    
    def get_anime_by_code(self, code: str):
        """Kod bo'yicha anime topish"""
        code = code.strip().upper()
        return self.fetch_one('''
            SELECT id, code, title, title_ru, title_en, genre, studio, 
                   year, episodes, rating, description, language, voice_actor, poster, views
            FROM anime WHERE code = ? OR code LIKE ? OR LOWER(code) = ?
        ''', (code, f'%{code}%', code.lower()))
    
    def get_anime_by_id(self, anime_id):
        """ID bo'yicha anime topish"""
        return self.fetch_one('''
            SELECT id, code, title, genre, year, episodes, rating, description, language, voice_actor, views
            FROM anime WHERE id = ?
        ''', (anime_id,))
    
    def get_all_anime(self, limit=100):
        """Barcha animelarni olish"""
        return self.fetch_all('''
            SELECT id, code, title, genre, year, episodes, rating, views
            FROM anime
            ORDER BY created_date DESC
            LIMIT ?
        ''', (limit,))
    
    def get_anime_count(self):
        """Animelar soni"""
        return self.fetch_one("SELECT COUNT(*) FROM anime")[0]
    
    def search_anime(self, query):
        """Anime qidirish"""
        query = f"%{query}%"
        return self.fetch_all('''
            SELECT id, code, title, genre, year, rating
            FROM anime
            WHERE title LIKE ? OR code LIKE ? OR genre LIKE ?
            ORDER BY views DESC
            LIMIT 20
        ''', (query, query, query))
    
    def increment_anime_views(self, anime_id):
        """Anime ko'rishlar sonini oshirish"""
        self.execute('UPDATE anime SET views = views + 1 WHERE id = ?', (anime_id,))
    
    # ========== EPISODES ==========
    def add_episode(self, anime_id, episode_number, title, video_path, duration="00:00", file_size="0 MB"):
        """Yangi qism qo'shish"""
        self.execute('''
            INSERT INTO episodes (anime_id, episode_number, title, video_path, duration, file_size, added_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (anime_id, episode_number, title, video_path, duration, file_size, datetime.datetime.now().isoformat()))
    
    def get_anime_episodes(self, anime_id: int):
        """Anime qismlarini olish"""
        return self.fetch_all('''
            SELECT id, episode_number, title, video_path, duration, file_size, views
            FROM episodes
            WHERE anime_id = ?
            ORDER BY episode_number
        ''', (anime_id,))
    
    def get_episode(self, episode_id):
        """Qism ma'lumotlarini olish"""
        return self.fetch_one('''
            SELECT id, anime_id, episode_number, title, video_path, duration, file_size, views
            FROM episodes WHERE id = ?
        ''', (episode_id,))
    
    def get_episodes_count(self):
        """Qismlar soni"""
        return self.fetch_one("SELECT COUNT(*) FROM episodes")[0]
    
    def increment_episode_views(self, episode_id):
        """Qism ko'rishlar sonini oshirish"""
        self.execute('UPDATE episodes SET views = views + 1 WHERE id = ?', (episode_id,))
    
    # ========== FAVORITLAR ==========
    def add_favorite(self, user_id, anime_id):
        """Favoritga qo'shish"""
        self.execute('''
            INSERT OR IGNORE INTO favorites (user_id, anime_id, added_date)
            VALUES (?, ?, ?)
        ''', (user_id, anime_id, datetime.datetime.now().isoformat()))
    
    def remove_favorite(self, user_id, anime_id):
        """Favoritdan o'chirish"""
        self.execute('DELETE FROM favorites WHERE user_id = ? AND anime_id = ?', (user_id, anime_id))
    
    def get_favorites(self, user_id):
        """Favoritlar ro'yxati"""
        return self.fetch_all('''
            SELECT a.id, a.code, a.title, a.genre, a.rating
            FROM favorites f
            JOIN anime a ON f.anime_id = a.id
            WHERE f.user_id = ?
            ORDER BY f.added_date DESC
        ''', (user_id,))
    
    def is_favorite(self, user_id, anime_id):
        """Favoritmi tekshirish"""
        result = self.fetch_one('SELECT 1 FROM favorites WHERE user_id = ? AND anime_id = ?', (user_id, anime_id))
        return result is not None
    
    def get_favorites_count(self):
        """Favoritlar soni"""
        return self.fetch_one("SELECT COUNT(*) FROM favorites")[0]
    
    # ========== TARIX ==========
    def add_to_history(self, user_id, anime_id, episode_id):
        """Tarixga qo'shish"""
        self.execute('''
            INSERT INTO history (user_id, anime_id, episode_id, watched_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, anime_id, episode_id, datetime.datetime.now().isoformat()))
    
    def get_history(self, user_id, limit=20):
        """Foydalanuvchi tarixi"""
        return self.fetch_all('''
            SELECT a.code, a.title, e.episode_number, h.watched_date, a.id
            FROM history h
            JOIN anime a ON h.anime_id = a.id
            JOIN episodes e ON h.episode_id = e.id
            WHERE h.user_id = ?
            ORDER BY h.watched_date DESC
            LIMIT ?
        ''', (user_id, limit))
    
    # ========== SOZLAMALAR ==========
    def get_setting(self, key):
        """Sozlama qiymatini olish"""
        result = self.fetch_one('SELECT value FROM settings WHERE key = ?', (key,))
        return result[0] if result else None
    
    def set_setting(self, key, value):
        """Sozlama qiymatini o'zgartirish"""
        self.execute('UPDATE settings SET value = ? WHERE key = ?', (value, key))
    
    def get_all_settings(self):
        """Barcha sozlamalar"""
        return self.fetch_all('SELECT key, value FROM settings ORDER BY key')

db = Database()

# ==================== ADMIN TEKSHIRISH ====================
async def is_admin(user_id: int) -> bool:
    """Foydalanuvchi adminligini tekshirish"""
    return user_id in ADMIN_IDS

# ==================== FOYDALANUVCHI MA'LUMOTLARINI YANGILASH ====================
async def update_user_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi ma'lumotlarini yangilash"""
    user = update.effective_user
    if user:
        db.add_user(user.id, user.username, user.first_name, user.last_name)
        db.update_user_activity(user.id)
    return True

# ==================== START KOMANDASI ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start komandasi"""
    await update_user_info(update, context)
    
    # Texnik xizmat rejimini tekshirish
    maintenance = db.get_setting('maintenance_mode')
    if maintenance == 'on' and not await is_admin(update.effective_user.id):
        message = db.get_setting('maintenance_message')
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    user = update.effective_user
    
    # /start code_10 formatidan kodni olish
    if context.args and context.args[0].startswith('code_'):
        code = context.args[0].replace('code_', '')
        anime = db.get_anime_by_code(code)
        if anime:
            await show_anime_episodes(update, context, anime)
            return
    
    # Oddiy start
    welcome = db.get_setting('welcome_message')
    bot_name = db.get_setting('bot_name')
    
    text = (
        f"👋 *{welcome}*\n\n"
        f"🤖 *{bot_name}* - Eng sara animelar\n\n"
        f"🔢 *Anime kodini yuboring* (masalan: `10`, `186`, `001`)\n\n"
        f"🌐 *Web sayt orqali* ham tomosha qilishingiz mumkin:\n"
        f"👉 {WEBAPP_URL}\n\n"
        f"👇 Quyidagi tugmalardan birini tanlang:"
    )
    
    # Faol kanallarni olish
    active_channels = db.get_active_channels()
    
    keyboard = [
        [InlineKeyboardButton("🔢 Kod bilan qidirish", callback_data='search_by_code')],
        [InlineKeyboardButton("📋 Barcha animelar", callback_data='list_anime_0')],
        [InlineKeyboardButton("⭐ Favoritlar", callback_data='my_favorites')],
        [InlineKeyboardButton("📜 Tarix", callback_data='my_history')],
        [InlineKeyboardButton("🌐 Web sayt", web_app=WebAppInfo(url=WEBAPP_URL))]
    ]
    
    # Faol kanallarga tugma qo'shish
    for channel in active_channels:
        channel_id, channel_name, channel_link = channel
        keyboard.append([InlineKeyboardButton(f"📢 {channel_name}", url=channel_link)])
    
    if await is_admin(user.id):
        keyboard.append([InlineKeyboardButton("👑 Admin panel", callback_data='admin_panel')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup, disable_web_page_preview=True)

# ==================== KOD BILAN QIDIRISH ====================
async def search_by_code_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kod bilan qidirish menyusi"""
    await update_user_info(update, context)
    
    query = update.callback_query
    awai
