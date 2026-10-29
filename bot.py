import os
import sqlite3
import time
import threading
import html
import random
import logging
import requests
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo  # type: ignore

TZ_KG = ZoneInfo("Asia/Bishkek")  # Кыргызстан UTC+6

def now_kg():
    return datetime.now(TZ_KG)

from flask import Flask, send_from_directory, request, jsonify
import telebot
from telebot import types

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TOKEN_REF") or os.environ.get("TOKEN")
if not TOKEN or len(TOKEN) < 40:
    logger.error("ТОКЕН НЕ НАЙДЕН!")
    raise SystemExit("No token")

MAIN_ADMIN = 8992968778
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1905")
OPERATOR_ID = int(os.environ.get("OPERATOR_ID", "8610237951"))
SUPPORT = os.environ.get("SUPPORT", "DarkBossX7")

CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "razrab_botovKG")
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}"

# === НАСТРОЙКИ КАССЫ ===
CASSA_API_URL = os.environ.get("CASSA_API_URL", "https://api.yourcassa.kg/v1")
CASSA_API_KEY = "6aaf15bcc53bd241f4f2eb7cd20aaa4136307fc1019813b853a4ef35fc5fb163"

def support_url():
    if SUPPORT and str(SUPPORT).strip():
        u = str(SUPPORT).lstrip("@").strip()
        return f"https://t.me/{u}"
    return f"tg://user?id={OPERATOR_ID}"

BOT_NAME = "Kassa"
MIN_DEPOSIT = 50
MAX_DEPOSIT = 50000
BOT_USERNAME = "Kassa1xBetKG_BOT"
REFERRAL_BONUS_PERCENT = 5.0  # 5% бонус рефереру от пополнения друга
MIN_WITHDRAW_BONUS = 200.0    # Минимальная сумма вывода реферальных

WEBAPP_URL = os.environ.get("WEBAPP_URL", "").rstrip("/")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://api.dengi.o.kg/#00020101021132680012p2p.dengi.kg01048580111214680148545710129962221176241202111302123409%D0%A0%D1%83%D1%81%D0%BB%D0%B0%D0%BD%20%D0%A8.520473995303417540105906O%21Bank6304E60B",
)

bot = telebot.TeleBot(TOKEN, parse_mode='HTML')
app = Flask(__name__)

temp_data = {}
payment_timers = {}
DB_NAME = 'bot.db'

# --- ЭМОДЗИ ---
E_MELBET = '<tg-emoji emoji-id="5287450237135246599">💙</tg-emoji>'
E_LIGHTNING = '<tg-emoji emoji-id="5199785165735367039">⚡️</tg-emoji>'
E_MONEY = '<tg-emoji emoji-id="5863998851584627334">💰</tg-emoji>'
E_CARD = '<tg-emoji emoji-id="5472250091332993630">💳</tg-emoji>'
E_CASH = '<tg-emoji emoji-id="5201873447554145566">💵</tg-emoji>'
E_SUPPORT = '<tg-emoji emoji-id="5971889748615105853">💻</tg-emoji>'

def safe_html(text):
    return html.escape(str(text)) if text else ""

def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=15, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL;')
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        chat_id INTEGER PRIMARY KEY, join_date TEXT, balance REAL DEFAULT 0.0,
                        username TEXT, full_name TEXT, is_banned INTEGER DEFAULT 0, referred_by INTEGER)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS requisites (id INTEGER PRIMARY KEY AUTOINCREMENT, req_text TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deposits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
                        account_id TEXT, photo_id TEXT, status TEXT, date TEXT, timestamp INTEGER, pay_method TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS bonus_withdrawals (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
                        account_text TEXT, platform TEXT, status TEXT, date TEXT)''')
        
        try: c.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        except Exception: pass
        try: c.execute("ALTER TABLE users ADD COLUMN balance REAL DEFAULT 0.0")
        except Exception: pass
        try: c.execute("ALTER TABLE users ADD COLUMN referred_by INTEGER")
        except Exception: pass

        c.execute('INSERT OR IGNORE INTO admins (chat_id) VALUES (?)', (MAIN_ADMIN,))
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("bot_active", "True")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("auto_deposit", "True")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("melbet_active", "True")')
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES ("xbet_active", "True")')
        conn.commit()

def is_user_banned(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT is_banned FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        return row and row[0] == 1

def is_platform_active(platform_key):
    with get_db() as conn:
        row = conn.execute('SELECT value FROM settings WHERE key = ?', (platform_key,)).fetchone()
        return True if row is None or row[0] == 'True' else False

def set_platform_active(platform_key, status: bool):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (platform_key, str(status)))
        conn.commit()

def check_user_subscribed(user_id):
    if user_id in get_admins() or user_id == MAIN_ADMIN:
        return True
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return True

def send_subscription_request(chat_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_sub = types.InlineKeyboardButton("🔗 Подписаться на канал", url=CHANNEL_URL)
    btn_check = types.InlineKeyboardButton("✅ Проверить подписку", callback_data="check_subscription")
    markup.add(btn_sub, btn_check)
    send_msg(chat_id, "🔔 <b>Прежде чем продолжить, подпишись на наш канал!</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "check_subscription")
def callback_check_subscription(call):
    chat_id = call.message.chat.id
    if check_user_subscribed(chat_id):
        bot.answer_callback_query(call.id, "Подписка подтверждена!")
        try: bot.delete_message(chat_id, call.message.message_id)
        except Exception: pass
        send_msg(chat_id, "✅ <b>Спасибо за подписку!</b>", reply_markup=main_keyboard(chat_id))
        start_welcome(call.message)
    else:
        bot.answer_callback_query(call.id, "❌ Вы еще не подписались на канал!", show_alert=True)

# --- API КАССЫ ---

def api_check_player(account_id):
    if not CASSA_API_URL or "yourcassa.kg" in CASSA_API_URL:
        return True, f"Игрок #{account_id}"

    headers = {
        "Authorization": f"Bearer {CASSA_API_KEY}",
        "X-Api-Key": CASSA_API_KEY,
        "Content-Type": "application/json"
    }

    endpoints = [
        f"{CASSA_API_URL}/player/{account_id}",
        f"{CASSA_API_URL}/users/check/{account_id}",
        f"{CASSA_API_URL}/check?account_id={account_id}"
    ]

    for url in endpoints:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if isinstance(data, dict):
                    user_obj = data.get("data") or data.get("user") or data.get("player") or data
                    name = user_obj.get("name") or user_obj.get("username") or user_obj.get("fio") or user_obj.get("player_name")
                    if name:
                        return True, str(name)
                return True, f"Игрок #{account_id}"
        except Exception as e:
                logger.error(f"API error {url}: {e}")
    return True, f"ID: {account_id}"

def api_process_deposit(account_id, amount):
    if not CASSA_API_URL or "yourcassa.kg" in CASSA_API_URL:
        logger.info(f"[TEST] Зачисление {amount} KGS на аккаунт {account_id}")
        return True, "OK"
    
    try:
        headers = {
            "Authorization": f"Bearer {CASSA_API_KEY}",
            "X-Api-Key": CASSA_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"account_id": str(account_id), "amount": float(amount), "currency": "KGS"}
        res = requests.post(f"{CASSA_API_URL}/deposit", json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            if data.get("success") or data.get("status") in ["ok", "success"]:
                return True, "OK"
            return False, data.get("message", "Ошибка кассы")
        return False, f"HTTP код: {res.status_code}"
    except Exception as e:
        logger.error(f"Deposit API Exception: {e}")
        return False, str(e)

# --- РАБОТА С БД И ПОЛЬЗОВАТЕЛЯМИ ---

def get_requisites():
    with get_db() as conn:
        row = conn.execute('SELECT req_text FROM requisites ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else "Переведите сумму по реквизитам:"

def get_admins():
    with get_db() as conn:
        admins = [r[0] for r in conn.execute('SELECT chat_id FROM admins').fetchall()]
        if MAIN_ADMIN not in admins: admins.append(MAIN_ADMIN)
        return admins

def add_user(chat_id, username=None, full_name=None, referred_by=None):
    with get_db() as conn:
        exists = conn.execute('SELECT chat_id FROM users WHERE chat_id = ?', (chat_id,)).fetchone()
        if not exists:
            conn.execute('INSERT INTO users (chat_id, join_date, username, full_name, referred_by) VALUES (?, ?, ?, ?, ?)',
                         (chat_id, now_kg().strftime("%d.%m.%Y %H:%M"), username or "", full_name or "", referred_by))
            conn.commit()
            return True
        return False

def get_user_balance(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT balance FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        return row[0] if row and row[0] else 0.0

def update_user_balance(user_id, amount):
    with get_db() as conn:
        conn.execute('UPDATE users SET balance = balance + ? WHERE chat_id = ?', (amount, user_id))
        conn.commit()

def get_referral_count(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT COUNT(*) FROM users WHERE referred_by = ?', (user_id,)).fetchone()
        return row[0] if row else 0

def get_user_referrer(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT referred_by FROM users WHERE chat_id = ?', (user_id,)).fetchone()
        return row[0] if row and row[0] else None

def user_label(user_id):
    with get_db() as conn:
        row = conn.execute('SELECT username, full_name FROM users WHERE chat_id = ?', (user_id,)).fetchone()
    if not row: return f"<code>{user_id}</code>"
    uname, fname = row[0] or "", row[1] or ""
    parts = [f"<code>{user_id}</code>"]
    if uname: parts.append(f"@{safe_html(uname)}")
    if fname: parts.append(safe_html(fname))
    return " · ".join(parts)

def touch_user(msg):
    u = msg.from_user
    add_user(u.id, username=u.username or "", full_name=(u.full_name or u.first_name or ""))

def add_deposit(user_id, amount, account_id, photo_id, pay_method="O!Bank"):
    with get_db() as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO deposits (user_id, amount, account_id, photo_id, status, date, timestamp, pay_method)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, amount, account_id, photo_id, 'pending', now_kg().strftime("%d.%m.%Y %H:%M:%S"), int(time.time()), pay_method))
        dep_id = c.lastrowid
        conn.commit()
        return dep_id

def update_deposit_status(dep_id, status):
    with get_db() as conn:
        conn.execute('UPDATE deposits SET status = ? WHERE id = ?', (status, dep_id))
        conn.commit()

def get_deposit_status(dep_id):
    with get_db() as conn:
        row = conn.execute('SELECT status FROM deposits WHERE id = ?', (dep_id,)).fetchone()
        return row[0] if row else None

def get_last_qr():
    with get_db() as conn:
        row = conn.execute('SELECT file_id FROM qr_codes ORDER BY id DESC LIMIT 1').fetchone()
        return row[0] if row else None

def send_msg(chat_id, text, reply_markup=None):
    try: return bot.send_message(chat_id, text, reply_markup=reply_markup)
    except Exception as e:
        logger.warning(f"send_msg [{chat_id}]: {e}")
        return None

def send_media_bulletproof(chat_id, file_id, caption=None, reply_markup=None):
    if not file_id: return send_msg(chat_id, caption, reply_markup) if caption else None
    try: return bot.send_photo(chat_id, file_id, caption=caption, reply_markup=reply_markup)
    except Exception:
        try: return bot.send_document(chat_id, file_id, caption=caption, reply_markup=reply_markup, parse_mode='HTML')
        except Exception:
            if caption: return send_msg(chat_id, caption, reply_markup)
            return None

# --- КЛАВИАТУРЫ ---

def main_keyboard(user_id=None):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("💙 Melbet"),
        types.KeyboardButton("💚 1xBet")
    )
    markup.add(
        types.KeyboardButton("👥 Рефералы и бонус"),
        types.KeyboardButton("👨‍💻 Поддержка")
    )
    markup.add(types.KeyboardButton("📖 Инструкция"))
    if user_id and (user_id in get_admins() or user_id == MAIN_ADMIN):
        markup.add(types.KeyboardButton("⚙️ Админ-панель"))
    return markup

def platform_menu_keyboard(platform_name):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton(f"📥 Пополнить {platform_name}"),
        types.KeyboardButton(f"📤 Вывести {platform_name}")
    )
    markup.add(types.KeyboardButton("🔙 Главное меню"))
    return markup

def pay_methods_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(types.KeyboardButton("💳 O!Bank"))
    markup.add(types.KeyboardButton("↩️ Отмена"))
    return markup

def cancel_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("↩️ Отмена"))
    return markup

def admin_keyboard():
    mel_status = "🟢 ВКЛ" if is_platform_active("melbet_active") else "🔴 ВЫКЛ"
    xbet_status = "🟢 ВКЛ" if is_platform_active("xbet_active") else "🔴 ВЫКЛ"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton(f"Melbet: {mel_status}"), types.KeyboardButton(f"1xBet: {xbet_status}"))
    markup.add(types.KeyboardButton("🔙 Главное меню"))
    return markup

@bot.message_handler(commands=['start'])
def start(msg):
    chat_id = msg.chat.id
    if is_user_banned(chat_id):
        send_msg(chat_id, "❌ <b>Доступ ограничен.</b> Вы заблокированы.")
        return

    args = msg.text.split()
    ref_by = None
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            potential_ref = int(args[1].replace("ref", ""))
            if potential_ref != chat_id:
                ref_by = potential_ref
        except Exception:
            pass

    is_new = add_user(chat_id, username=msg.from_user.username or "", full_name=msg.from_user.full_name or "", referred_by=ref_by)
    if is_new and ref_by:
        try:
            bot.send_message(ref_by, "🎉 <b>По вашей реферальной ссылке зарегистрировался новый друг!</b>")
        except Exception:
            pass

    if not check_user_subscribed(chat_id):
        send_subscription_request(chat_id)
        return
    start_welcome(msg)

def start_welcome(msg):
    chat_id = msg.chat.id
    bot.clear_step_handler_by_chat_id(chat_id)
    temp_data[chat_id] = {}
    
    name = safe_html(msg.from_user.first_name or "Пользователь")
    
    text = (
        f"{E_MELBET} Добро пожаловать в <b>{BOT_NAME}</b>, <b>{name}</b>!\n\n"
        f"{E_LIGHTNING} Быстрый обмен и касса (O!Bank):\n"
        f" • Пополнение и вывод <b>Melbet / 1xBet</b>\n\n"
        f"👥 Приглашайте друзей и получайте <b>{REFERRAL_BONUS_PERCENT}%</b> бонуса от их пополнений на свой внутренний баланс! Вывод бонуса от 200 сом.\n\n"
        f"{E_SUPPORT} Поддержка: <a href=\"{support_url()}\">@{SUPPORT}</a>"
    )
    send_msg(chat_id, text, reply_markup=main_keyboard(chat_id))

@bot.message_handler(func=lambda m: m.text == "💙 Melbet")
def melbet_menu(msg):
    if not is_platform_active("melbet_active"):
        send_msg(msg.chat.id, "🔴 <b>Melbet временно не работает.</b> Приносим извинения за неудобства.")
        return
    send_msg(msg.chat.id, f"{E_MELBET} <b>Раздел Melbet:</b>", reply_markup=platform_menu_keyboard("Melbet"))

@bot.message_handler(func=lambda m: m.text == "💚 1xBet")
def xbet_menu(msg):
    if not is_platform_active("xbet_active"):
        send_msg(msg.chat.id, "🔴 <b>1xBet временно не работает.</b> Приносим извинения за неудобства.")
        return
    send_msg(msg.chat.id, f"💚 <b>Раздел 1xBet:</b>", reply_markup=platform_menu_keyboard("1xBet"))

@bot.message_handler(func=lambda m: m.text == "👥 Рефералы и бонус")
def referral_menu(msg):
    chat_id = msg.chat.id
    ref_count = get_referral_count(chat_id)
    balance = get_user_balance(chat_id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{chat_id}"
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("💸 Вывести реферальный бонус", callback_data="withdraw_bonus"))

    text = (
        f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА И БОНУСЫ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"📊 Приглашено друзей: <b>{ref_count}</b>\n"
        f"💰 Ваш бонусный баланс: <b>{balance:.2f} сом</b>\n"
        f"⚠️ <i>Минимальная сумма для вывода бонуса: <b>200 сом</b> (на 1xBet или Melbet).</i>"
    )
    send_msg(chat_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data == "withdraw_bonus")
def callback_withdraw_bonus(call):
    chat_id = call.message.chat.id
    balance = get_user_balance(chat_id)
    if balance < MIN_WITHDRAW_BONUS:
        bot.answer_callback_query(call.id, f"❌ Недостаточно средств! Минимальный вывод: {MIN_WITHDRAW_BONUS} сом.", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    send_msg(chat_id, f"🎁 <b>Вывод реферального бонуса</b>\n\nВаш баланс: <b>{balance:.2f} сом</b>\n\nВыберите платформу для получения выплаты:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2).add("1xBet", "Melbet", "↩️ Отмена"))
    bot.register_next_step_handler(call.message, choose_bonus_platform)

def choose_bonus_platform(msg):
    if not msg.text or "Отмена" in msg.text:
        start(msg); return
    platform = msg.text.strip()
    if platform not in ["1xBet", "Melbet"]:
        send_msg(msg.chat.id, "❌ Выберите платформу кнопкой ниже:", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, choose_bonus_platform)
        return
    
    temp_data[msg.chat.id] = {"bonus_platform": platform}
    send_msg(msg.chat.id, f"🆔 <b>Введите ваш ID {platform} для зачисления бонуса:</b>", reply_markup=cancel_keyboard())
    bot.register_next_step_handler(msg, process_bonus_withdrawal)

def process_bonus_withdrawal(msg):
    if not msg.text or "Отмена" in msg.text:
        start(msg); return
    acc_id = msg.text.strip()
    if not acc_id.isdigit():
        send_msg(msg.chat.id, "❌ ID должен состоять из цифр. Введите корректный ID:", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, process_bonus_withdrawal)
        return

    chat_id = msg.chat.id
    balance = get_user_balance(chat_id)
    platform = temp_data.get(chat_id, {}).get("bonus_platform", "1xBet")

    if balance < MIN_WITHDRAW_BONUS:
        send_msg(msg.chat.id, "❌ Ошибка: недостаточно средств.", reply_markup=main_keyboard(chat_id))
        return

    with get_db() as conn:
        conn.execute('UPDATE users SET balance = balance - ? WHERE chat_id = ?', (balance, chat_id))
        c = conn.cursor()
        c.execute('INSERT INTO bonus_withdrawals (user_id, amount, account_text, platform, status, date) VALUES (?, ?, ?, ?, ?, ?)',
                  (chat_id, balance, acc_id, platform, 'pending', now_kg().strftime("%d.%m.%Y %H:%M")))
        w_id = c.lastrowid
        conn.commit()

    admin_text = (
        f"🎁 <b>ЗАЯВКА НА ВЫВОД РЕФ. БОНУСА #{w_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Пользователь: {user_label(chat_id)}\n"
        f"💰 Сумма: <b>{balance:.2f} сом</b>\n"
        f"🎰 Платформа: {platform}\n"
        f"🆔 ID счета: <code>{acc_id}</code>"
    )
    for adm in get_admins():
        send_msg(adm, admin_text)

    send_msg(chat_id, f"✅ <b>Заявка на вывод бонуса #{w_id} создана!</b>\nСумма: {balance:.2f} сом. Ожидайте выплаты.", reply_markup=main_keyboard(chat_id))
    temp_data.pop(chat_id, None)

@bot.message_handler(func=lambda m: m.text in ["🔙 Главное меню", "🔙 Назад"] or "Отмена" in (m.text or ""))
def back_to_main(msg):
    start(msg)

@bot.message_handler(func=lambda m: m.text in ["📖 Инструкция", "Инструкция"])
def instruction_handler(msg):
    text = (
        f"📖 <b>ИНСТРУКЦИЯ КААССЫ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n\n"
        f"💳 <b>Пополнение и вывод:</b>\n"
        f"Выберите нужную букмекерскую контору в главном меню (Melbet или 1xBet) и следуйте подсказкам бота."
    )
    send_msg(msg.chat.id, text, reply_markup=main_keyboard(msg.chat.id))

@bot.message_handler(func=lambda m: m.text in ["👤 Поддержка", "👨‍💻 Поддержка", "Поддержка"])
def support_handler(msg):
    text = (
        f"👨‍💻 <b>СЛУЖБА ПОДДЕРЖКИ</b>\n\n"
        f"📩 Прямой контакт оператора: <a href=\"{support_url()}\">@{SUPPORT}</a>"
    )
    send_msg(msg.chat.id, text, reply_markup=main_keyboard(msg.chat.id))

# --- ПОПОЛНЕНИЕ (Общее для Melbet и 1xBet) ---

@bot.message_handler(func=lambda m: "Пополнить" in (m.text or ""))
def deposit_start(msg):
    platform = "1xBet" if "1xBet" in msg.text else "Melbet"
    if platform == "Melbet" and not is_platform_active("melbet_active"):
        send_msg(msg.chat.id, "🔴 Melbet временно не работает.")
        return
    if platform == "1xBet" and not is_platform_active("xbet_active"):
        send_msg(msg.chat.id, "🔴 1xBet временно не работает.")
        return

    temp_data[msg.chat.id] = {"platform": platform}
    send_msg(msg.chat.id, f"💳 <b>Выберите метод оплаты для {platform}:</b>", reply_markup=pay_methods_keyboard())
    bot.register_next_step_handler(msg, choose_pay_method)

def choose_pay_method(msg):
    if not msg.text or "Отмена" in msg.text:
        start(msg); return
    pay_method = msg.text.replace("💳", "").strip()
    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    temp_data[msg.chat.id]["pay_method"] = pay_method
    send_msg(msg.chat.id, f"🆔 <b>Отправьте ваш ID {platform}:</b>", reply_markup=cancel_keyboard())
    bot.register_next_step_handler(msg, verify_and_get_account_id)

def verify_and_get_account_id(msg):
    if not msg.text or "Отмена" in msg.text:
        start(msg); return
    acc_number = msg.text.strip()
    if not acc_number.isdigit():
        send_msg(msg.chat.id, "❌ ID должен состоять только из цифр. Введите заново:", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, verify_and_get_account_id)
        return

    platform = temp_data.get(msg.chat.id, {}).get("platform", "Melbet")
    sent_msg = send_msg(msg.chat.id, f"🔍 <i>Поиск игрока в системе {platform}...</i>")
    is_valid, player_name = api_check_player(acc_number)
    
    if sent_msg:
        try: bot.delete_message(msg.chat.id, sent_msg.message_id)
        except Exception: pass

    temp_data.setdefault(msg.chat.id, {})["account_id"] = f"{platform} | {acc_number}"
    send_msg(msg.chat.id, f"✅ <b>Игрок найден:</b> {player_name}\n\n{E_MONEY} <b>Введите сумму пополнения (от {MIN_DEPOSIT} до {MAX_DEPOSIT} сом):</b>", reply_markup=cancel_keyboard())
    bot.register_next_step_handler(msg, get_amount)

def get_amount(msg):
    if not msg.text or "Отмена" in msg.text:
        start(msg); return
    try:
        base = float(msg.text.replace(',', '.'))
    except Exception:
        send_msg(msg.chat.id, "❌ Введите корректную сумму числом:", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, get_amount); return

    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        send_msg(msg.chat.id, f"❌ Сумма от {MIN_DEPOSIT} до {MAX_DEPOSIT} сом!", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, get_amount); return

    final = round(base + round(random.randint(10, 99) / 100.0, 2), 2)
    user_id = msg.chat.id
    account_id = temp_data.get(user_id, {}).get("account_id", "")
    pay_method = temp_data.get(user_id, {}).get("pay_method", "O!Bank")
    temp_data[user_id]["amount"] = final

    qr = get_last_qr()
    if qr:
        send_media_bulletproof(user_id, qr, caption=f"📸 <b>QR для оплаты ({pay_method})</b>\nСумма: <b>{final:.2f} сом</b>")

    banks = types.InlineKeyboardMarkup(row_width=1)
    banks.add(types.InlineKeyboardButton(f"🔗 Оплатить через {pay_method}", url=PAY_LINK))

    reqs = get_requisites()
    text = (
        f"🧾 <b>СЧЕТ НА ОПЛАТУ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"{E_CASH} <b>Сумма:</b> <code>{final:.2f}</code> KGS\n"
        f"🆔 <b>Счет:</b> <code>{safe_html(account_id)}</code>\n\n"
        f"{E_CARD} <b>Реквизиты (O!Bank):</b>\n<code>{safe_html(reqs)}</code>\n\n"
        f"⚠️ <i>Переводите ТОЧНУЮ сумму с копейками! После отправьте чек сюда.</i>"
    )
    send_msg(user_id, text, reply_markup=banks)
    bot.register_next_step_handler(msg, get_check_photo)

def get_check_photo(msg):
    user_id = msg.chat.id
    if msg.text and "Отмена" in msg.text:
        start(msg); return

    photo_id = msg.photo[-1].file_id if msg.photo else (msg.document.file_id if msg.document else None)
    if not photo_id:
        send_msg(user_id, "❌ Пожалуйста, отправьте фото чека:", reply_markup=cancel_keyboard())
        bot.register_next_step_handler(msg, get_check_photo); return

    account_id = temp_data.get(user_id, {}).get("account_id")
    amount = temp_data.get(user_id, {}).get("amount")
    pay_method = temp_data.get(user_id, {}).get("pay_method", "O!Bank")
    
    if not account_id or not amount:
        send_msg(user_id, "❌ Сессия истекла. Начните заново.")
        start(msg); return

    touch_user(msg)
    dep_id = add_deposit(user_id, amount, account_id, photo_id, pay_method=pay_method)
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{dep_id}"),
        types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{dep_id}")
    )
    caption = (
        f"📥 <b>ПОПОЛНЕНИЕ #{dep_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Игрок: {user_label(user_id)}\n"
        f"💰 Сумма: <code>{amount:.2f}</code> KGS\n"
        f"🆔 Счет: <code>{safe_html(account_id)}</code>"
    )
    for admin in get_admins():
        send_media_bulletproof(admin, photo_id, caption=caption, reply_markup=markup)

    send_msg(user_id, f"✅ <b>Заявка #{dep_id} отправлена на проверку!</b> Ожидайте зачисления.", reply_markup=main_keyboard(user_id))
    temp_data.pop(user_id, None)

# --- АДМИН-ПАНЕЛЬ И РЕФЕРАЛЬНЫЙ БОНУС ---

@bot.message_handler(func=lambda m: m.text == "⚙️ Админ-панель" and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def admin_panel_handler(msg):
    send_msg(msg.chat.id, "⚙️ <b>Панель управления платформами:</b>", reply_markup=admin_keyboard())

@bot.message_handler(func=lambda m: ("Melbet:" in m.text or "1xBet:" in m.text) and (m.from_user.id in get_admins() or m.from_user.id == MAIN_ADMIN))
def toggle_platform_handler(msg):
    if "Melbet" in msg.text:
        current = is_platform_active("melbet_active")
        set_platform_active("melbet_active", not current)
    elif "1xBet" in msg.text:
        current = is_platform_active("xbet_active")
        set_platform_active("xbet_active", not current)
    send_msg(msg.chat.id, "✅ Статус платформ обновлен!", reply_markup=admin_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith(('approve_', 'reject_')))
def handle_admin_callbacks(call):
    if call.from_user.id not in get_admins() and call.from_user.id != MAIN_ADMIN:
        bot.answer_callback_query(call.id, "❌ Нет прав!"); return
    data = call.data

    if data.startswith('approve_'):
        dep_id = int(data.split('_')[1])
        status = get_deposit_status(dep_id)
        if status != 'pending':
            bot.answer_callback_query(call.id, "⚠️ Заявка уже обработана!", show_alert=True)
            return

        with get_db() as conn:
            row = conn.execute('SELECT user_id, amount, account_id FROM deposits WHERE id = ?', (dep_id,)).fetchone()
        
        if row:
            user_id, amount, account_id = row
            raw_acc_id = account_id.split("|")[-1].strip()
            
            success, api_msg = api_process_deposit(raw_acc_id, amount)
            if not success:
                bot.answer_callback_query(call.id, f"❌ Ошибка авто-кассы: {api_msg}", show_alert=True)
                return

            update_deposit_status(dep_id, "approved")

            # Начисление реферального бонуса пригласившему на баланс
            referrer_id = get_user_referrer(user_id)
            if referrer_id:
                bonus_amount = round(amount * (REFERRAL_BONUS_PERCENT / 100.0), 2)
                update_user_balance(referrer_id, bonus_amount)
                try:
                    bot.send_message(
                        referrer_id,
                        f"🎁 <b>Реферальный бонус зачислен!</b>\n\n"
                        f"Ваш друг пополнил баланс. Вам начислено <b>+{bonus_amount:.2f} сом</b> на ваш бонусный баланс! 💰"
                    )
                except Exception:
                    pass

            bot.answer_callback_query(call.id, "✅ Успешно зачислено!")
            try:
                bot.send_message(user_id, f"🎉 <b>Ваш баланс успешно пополнен на {amount:.2f} сом!</b> 🚀")
            except Exception: pass
            try: bot.edit_message_caption(f"✅ <b>Заявка #{dep_id} ОДОБРЕНА (Авто-пополнение выполнено)</b>", call.message.chat.id, call.message.message_id)
            except Exception: pass

    elif data.startswith('reject_'):
        dep_id = int(data.split('_')[1])
        with get_db() as conn:
            row = conn.execute('SELECT user_id, amount FROM deposits WHERE id = ?', (dep_id,)).fetchone()
        if row:
            user_id, amount = row
            update_deposit_status(dep_id, "rejected")
            bot.answer_callback_query(call.id, "❌ Заявка отклонена")
            try: bot.send_message(user_id, f"❌ <b>Ваша заявка на {amount:.2f} сом была отклонена.</b> Обратитесь в поддержку.")
            except Exception: pass
            try: bot.edit_message_caption(f"❌ <b>Заявка #{dep_id} ОТКЛОНЕНА</b>", call.message.chat.id, call.message.message_id)
            except Exception: pass

@app.route('/')
def home():
    return {"status": "ok", "bot": BOT_NAME}, 200

if __name__ == "__main__":
    try: bot.remove_webhook()
    except Exception: pass

    def run_flask():
        app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

    threading.Thread(target=run_flask, daemon=True).start()
    logger.info(f"{BOT_NAME} (@{BOT_USERNAME}) запущен")
    
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=40)
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)
