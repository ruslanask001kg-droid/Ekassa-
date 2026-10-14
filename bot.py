import asyncio
import logging
import os
import random
import string
import sqlite3
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ErrorEvent,
)
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramNetworkError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger(__name__)

# ================= CONFIG =================
def _token() -> str:
    for k in ("TOKEN", "BOT_TOKEN", "TELEGRAM_TOKEN", "TOKEN_REF"):
        v = (os.environ.get(k) or "").strip().strip('"').strip("'")
        if len(v) >= 40 and ":" in v:
            return v
    return ""

def _parse_admins() -> list[int]:
    raw = (os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID") or "8992968778").strip()
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.isdigit():
            n = int(part)
            if n not in ids:
                ids.append(n)
    if not ids:
        ids = [8992968778]
    return ids[:1]  # только один админ

BOT_TOKEN = _token()
ADMIN_IDS = _parse_admins()
MAIN_ADMIN = ADMIN_IDS[0]
BOT_NAME = "EkassaKG"
PLATFORM = "1XBET"
MIN_DEPOSIT = 35
MAX_DEPOSIT = 100_000
MIN_WITHDRAW = 100
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@ekassaNews").strip()
CHANNEL_URL = os.environ.get("CHANNEL_LINK", "https://t.me/ekassaNews").strip()
SUPPORT = os.environ.get("SUPPORT", "@Ekassahelp_bot")
SUPPORT_URL = os.environ.get("SUPPORT_URL", "https://t.me/Ekassahelp_bot")
PAY_LINK = os.environ.get(
    "PAY_LINK",
    "https://app.mbank.kg/qr/#00020101021132440012c2c.mbank.kg01020210129965025060881302125204999953034175910AIYMKUL%20A.6304ef96",
)
TZ = ZoneInfo("Asia/Bishkek")

def pe(eid: str, fb: str) -> str:
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>'

E = {
    "star": pe("5379607913046242841", "❄️"),
    "vip": pe("5400373628950840597", "❄️"),
    "gem": pe("5399942684817258282", "❄️"),
    "spark": pe("5379943126653761268", "❄️"),
    "rocket": pe("5188481279963715781", "🚀"),
    "check": pe("6273749318717412886", "✅"),
    "money": pe("5224257782013769471", "💰"),
    "cash": pe("5197434882321567830", "💵"),
    "withdraw": pe("5201691993775818138", "🛫"),
    "wallet": pe("5215420556089776398", "👛"),
    "support": pe("5472239203590888751", "📩"),
    "admin": pe("5193177581888755275", "💻"),
    "fire": pe("5201945242227472933", "⚡️"),
    "zap": pe("5226830214020999125", "⚡️"),
    "web": pe("5201732344993576400", "🌐"),
    "stats": pe("5224588661999282075", "💲"),
    "write": pe("5197269100878907942", "✍️"),
    "wave": "👋",
    "cross": "❌",
}

if not BOT_TOKEN:
    raise SystemExit("TOKEN missing. Set Env TOKEN=... on Render.")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ================= DB =================
conn = sqlite3.connect("ekassa.db", check_same_thread=False)
cur = conn.cursor()
cur.executescript("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    account_id TEXT,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS admins (chat_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT,
    user_id INTEGER,
    account_id TEXT,
    amount REAL,
    photo_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    ts INTEGER
);
CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT,
    user_id INTEGER,
    account_id TEXT,
    amount REAL,
    qr_file_id TEXT,
    code_txt TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    message TEXT,
    photo_id TEXT,
    status TEXT DEFAULT 'new',
    created_at TEXT
);
""")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_active', '1')")
cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('auto_topup', '1')")
for a in ADMIN_IDS:
    cur.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (a,))
conn.commit()

# ================= HELPERS =================
def now_kg() -> datetime:
    return datetime.now(TZ)

def code_gen(n: int = 5) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=n))

def get_admins() -> list[int]:
    cur.execute("SELECT chat_id FROM admins")
    ids = [r[0] for r in cur.fetchall()]
    for a in ADMIN_IDS:
        if a not in ids:
            ids.append(a)
    return ids

def is_admin(uid: int) -> bool:
    return uid in get_admins()

def bot_on() -> bool:
    cur.execute("SELECT value FROM settings WHERE key='bot_active'")
    r = cur.fetchone()
    return (r[0] if r else "1") == "1"

def set_bot(on: bool):
    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('bot_active',?)", ("1" if on else "0"))
    conn.commit()

def auto_on() -> bool:
    cur.execute("SELECT value FROM settings WHERE key='auto_topup'")
    r = cur.fetchone()
    return (r[0] if r else "1") == "1"

def set_auto(on: bool):
    cur.execute("INSERT OR REPLACE INTO settings (key,value) VALUES ('auto_topup',?)", ("1" if on else "0"))
    conn.commit()

def ensure_user(uid: int, uname: str = "", name: str = ""):
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (uid,))
    if cur.fetchone():
        cur.execute(
            "UPDATE users SET username=COALESCE(?,username), full_name=COALESCE(?,full_name) WHERE user_id=?",
            (uname or None, name or None, uid),
        )
    else:
        cur.execute(
            "INSERT INTO users (user_id,username,full_name,created_at) VALUES (?,?,?,?)",
            (uid, uname, name, now_kg().strftime("%d.%m.%Y %H:%M")),
        )
    conn.commit()

def save_account(uid: int, account_id: str):
    acc = (account_id or "").strip()
    if not acc:
        return
    cur.execute("UPDATE users SET account_id=? WHERE user_id=?", (acc, uid))
    conn.commit()

def get_account(uid: int) -> str:
    cur.execute("SELECT account_id FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    return (r[0] or "").strip() if r and r[0] else ""

def label(uid: int) -> str:
    cur.execute("SELECT username, full_name FROM users WHERE user_id=?", (uid,))
    r = cur.fetchone()
    p = [f"<code>{uid}</code>"]
    if r:
        if r[0]:
            p.append(f"@{r[0]}")
        if r[1]:
            p.append(r[1])
    return " · ".join(p)

async def notify_admins(text: str = None, photo: str = None, reply_markup=None):
    for aid in get_admins():
        try:
            if photo:
                await bot.send_photo(aid, photo, caption=text, reply_markup=reply_markup, parse_mode="HTML")
            elif text:
                await bot.send_message(aid, text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception as e:
            log.warning("notify %s: %s", aid, e)

async def subscribed(uid: int) -> bool:
    """True если подписан на канал (админы всегда проходят)."""
    if is_admin(uid):
        return True
    if not CHANNEL_USERNAME:
        return True
    try:
        m = await bot.get_chat_member(CHANNEL_USERNAME, uid)
        return m.status in ("creator", "administrator", "member", "restricted")
    except TelegramForbiddenError:
        # Бот не админ канала — пропускаем, иначе всех заблокирует
        log.error("Бот не админ канала %s — добавьте бота админом!", CHANNEL_USERNAME)
        return True
    except Exception as e:
        log.warning("sub check uid=%s: %s", uid, e)
        return False

async def require_sub(message: types.Message) -> bool:
    """Если не подписан — показать кнопки и вернуть False."""
    uid = message.from_user.id
    if await subscribed(uid):
        return True
    await message.answer(
        f"🔒 <b>Подписка обязательна</b>\n\n"
        f"Подпишитесь на канал и нажмите «Проверить подписку»:\n"
        f"{CHANNEL_URL}",
        reply_markup=kb_sub(),
        parse_mode="HTML",
    )
    return False

# ================= KEYBOARDS =================
def kb_sub():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟠 Подписаться на канал", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")],
    ])

def kb_main(uid: int | None = None):
    rows = [
        [KeyboardButton(text="📥 Пополнить"), KeyboardButton(text="📤 Вывести")],
        [KeyboardButton(text="💬 Поддержка")],
    ]
    if uid is not None and is_admin(uid):
        rows.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

def kb_back():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🔙 Главное меню")]], resize_keyboard=True)

def kb_cancel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
    ])

def kb_amounts_dep():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="100", callback_data="amt_100"),
         InlineKeyboardButton(text="500", callback_data="amt_500")],
        [InlineKeyboardButton(text="1000", callback_data="amt_1000"),
         InlineKeyboardButton(text="5000", callback_data="amt_5000")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def kb_amounts_wd():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="500", callback_data="amt_500"),
         InlineKeyboardButton(text="1000", callback_data="amt_1000")],
        [InlineKeyboardButton(text="5000", callback_data="amt_5000"),
         InlineKeyboardButton(text="10000", callback_data="amt_10000")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
    ])

def kb_banks():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Мбанк — оплатить", url=PAY_LINK)],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")],
    ])

def kb_dep(dep_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Одобрить", callback_data=f"dep_ok_{dep_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dep_no_{dep_id}"),
    ]])

def kb_wd(w_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Готово", callback_data=f"wd_ok_{w_id}"),
        InlineKeyboardButton(text="❌ Отказать", callback_data=f"wd_no_{w_id}"),
    ]])

def kb_admin():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Заявки", callback_data="adm_deps"),
         InlineKeyboardButton(text="📈 Статистика", callback_data="adm_stats")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast")],
        [InlineKeyboardButton(
            text="🔴 Выключить бота" if bot_on() else "🟢 Включить бота",
            callback_data="adm_toggle_bot")],
        [InlineKeyboardButton(
            text="🟢 Автопополнение (Вкл)" if auto_on() else "🔴 Автопополнение (Выкл)",
            callback_data="adm_toggle_auto")],
        [InlineKeyboardButton(text="➕ Админ", callback_data="adm_add"),
         InlineKeyboardButton(text="➖ Удалить", callback_data="adm_del")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="adm_back")],
    ])

# ================= STATES =================
class Dep(StatesGroup):
    account = State()
    amount = State()
    receipt = State()

class Wd(StatesGroup):
    account = State()
    amount = State()
    qr = State()
    code = State()

class Broadcast(StatesGroup):
    content = State()

class AdminAdd(StatesGroup):
    uid = State()

class AdminDel(StatesGroup):
    uid = State()

# ================= START / SUB =================
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    if not bot_on() and not is_admin(uid):
        await message.answer("⚠️ Бот на техническом обслуживании. Попробуйте позже.")
        return
    if not await subscribed(uid):
        await message.answer(
            f"👋 Добро пожаловать в <b>{BOT_NAME}</b>!\n\n"
            f"🔒 Для использования бота подпишитесь на канал:\n{CHANNEL_URL}\n\n"
            f"После подписки нажмите «Проверить подписку».",
            reply_markup=kb_sub(), parse_mode="HTML",
        )
        return
    await show_main(message)

@dp.callback_query(F.data == "check_sub")
async def cb_sub(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    if await subscribed(call.from_user.id):
        await call.answer("✅ Подписка подтверждена!")
        try:
            await call.message.edit_text(
                f"✅ Подписка подтверждена!\n\nДобро пожаловать в <b>{BOT_NAME}</b>.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        await show_main(call.message)
    else:
        await call.answer("❌ Вы ещё не подписались на канал!", show_alert=True)
        try:
            await call.message.edit_text(
                f"🔒 <b>Подписка не найдена</b>\n\n"
                f"1. Нажмите «Подписаться на канал»\n"
                f"2. Подпишитесь\n"
                f"3. Вернитесь и нажмите «Проверить подписку»\n\n"
                f"Канал: {CHANNEL_URL}",
                reply_markup=kb_sub(),
                parse_mode="HTML",
            )
        except Exception:
            pass

async def show_main(message: types.Message):
    uid = getattr(message.from_user, "id", None)
    name = getattr(message.from_user, "first_name", None) or "друг"
    auto = "🟢 Активно" if auto_on() else "🔴 Отключено"
    text = (
        f"{E['wave']} Привет, <b>{name}</b>!\n\n"
        f"{E['gem']} Добро пожаловать в <b>{BOT_NAME}</b>\n\n"
        f"{E['money']} Пополнение — быстро\n"
        f"{E['withdraw']} Вывод — до 3 часов\n"
        f"{E['zap']} Автопополнение: {auto}\n\n"
        f"{E['support']} Поддержка: {SUPPORT}"
    )
    await message.answer(text, reply_markup=kb_main(uid), parse_mode="HTML")

@dp.message(F.text == "🔙 Главное меню")
@dp.callback_query(F.data.in_({"main_menu", "cancel"}))
async def back_main(event: types.Message | types.CallbackQuery, state: FSMContext):
    await state.clear()
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        await show_main(event.message)
    else:
        await show_main(event)

# ================= DEPOSIT =================
@dp.message(F.text.in_({"📥 Пополнить", "Пополнить"}))
async def dep_start(message: types.Message, state: FSMContext):
    if not await require_sub(message):
        return
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании.")
        return
    await state.set_state(Dep.account)
    saved = get_account(message.from_user.id)
    extra = f"\n\nСохранённый ID: <code>{saved}</code>\nОтправьте его или введите новый." if saved else ""
    await message.answer(
        f"{E['money']} <b>ПОПОЛНЕНИЕ СЧЁТА ({PLATFORM})</b>\n\n"
        f"{E['wallet']} Введите ID игрового счёта (только цифры):{extra}",
        parse_mode="HTML", reply_markup=kb_back(),
    )

@dp.message(Dep.account)
async def dep_acc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    acc = (message.text or "").strip()
    if not acc.isdigit():
        await message.answer("⚠️ ID только из цифр. Попробуйте снова:")
        return
    save_account(message.from_user.id, acc)
    await state.update_data(account_id=acc)
    await state.set_state(Dep.amount)
    auto = "🟢 Активно" if auto_on() else "🔴 Отключено"
    await message.answer(
        f"{E['check']} ID: <code>{acc}</code>\n"
        f"{E['zap']} Автопополнение: {auto}\n\n"
        f"Мин: {MIN_DEPOSIT} · Макс: {MAX_DEPOSIT} сом\n"
        f"{E['cash']} Введите сумму или выберите кнопку:",
        reply_markup=kb_amounts_dep(), parse_mode="HTML",
    )

@dp.callback_query(F.data.startswith("amt_"), Dep.amount)
async def dep_amt_btn(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("action") == "withdraw":
        return
    amount = float(call.data.replace("amt_", ""))
    final = round(amount + random.randint(10, 99) / 100.0, 2)
    await call.answer()
    await send_pay(call.message, state, final)

@dp.message(Dep.amount)
async def dep_amt_txt(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    try:
        base = float((message.text or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer("⚠️ Введите число!")
        return
    if not (MIN_DEPOSIT <= base <= MAX_DEPOSIT):
        await message.answer(f"⚠️ От {MIN_DEPOSIT} до {MAX_DEPOSIT}")
        return
    final = round(base + random.randint(10, 99) / 100.0, 2)
    await send_pay(message, state, final)

async def send_pay(message: types.Message, state: FSMContext, amount: float):
    data = await state.get_data()
    acc = data.get("account_id", "")
    await state.update_data(amount=amount)
    await state.set_state(Dep.receipt)
    await message.answer(
        f"{E['wallet']} ID: <code>{acc}</code>\n"
        f"{E['cash']} К оплате: <b>{amount:.2f} сом</b>\n\n"
        f"{E['zap']} Реквизиты актуальны <b>5 минут</b>.\n"
        f"Оплатите по кнопке ниже.\n\n"
        f"{E['write']} После оплаты отправьте <b>скриншот чека</b>.",
        reply_markup=kb_banks(), parse_mode="HTML",
    )
    await message.answer(f"{E['write']} После оплаты — фото чека 👇", reply_markup=kb_back(), parse_mode="HTML")

@dp.message(Dep.receipt, F.photo | F.document)
async def dep_receipt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    acc = data.get("account_id", "")
    amount = float(data.get("amount") or 0)
    if not acc or amount < MIN_DEPOSIT:
        await message.answer("Данные утеряны. Нажмите 📥 Пополнить")
        await state.clear()
        return
    photo = message.photo[-1].file_id if message.photo else message.document.file_id
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    c = code_gen()
    cur.execute(
        """INSERT INTO deposits (code,user_id,account_id,amount,photo_id,status,created_at,ts)
           VALUES (?,?,?,?,?,'pending',?,?)""",
        (c, uid, acc, amount, photo, now_kg().strftime("%d.%m.%Y %H:%M"), int(time.time())),
    )
    dep_id = cur.lastrowid
    conn.commit()
    await message.answer(
        f"{E['check']} Заявка <b>{c}</b> принята!\n\n"
        f"🆔 {PLATFORM}: <code>{acc}</code>\n"
        f"{E['cash']} {amount:.2f} сом\n"
        f"{E['money']} Комиссия: 0%\n\n"
        f"{E['zap']} Ожидайте зачисления.\n{E['support']} {SUPPORT}",
        parse_mode="HTML", reply_markup=kb_main(uid),
    )
    cap = (
        f"{E['fire']} <b>ЗАЯВКА #{dep_id}</b> · <code>{c}</code>\n\n"
        f"👤 {label(uid)}\n{E['cash']} <b>{amount:.2f} сом</b>\n"
        f"🆔 {PLATFORM} | <code>{acc}</code>"
    )
    await notify_admins(text=cap, photo=photo, reply_markup=kb_dep(dep_id))
    await state.clear()

@dp.callback_query(F.data.startswith("dep_ok_") | F.data.startswith("dep_no_"))
async def dep_mod(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True)
        return
    ok = call.data.startswith("dep_ok_")
    dep_id = int(call.data.split("_")[-1])
    cur.execute("SELECT user_id, amount, account_id, status, ts, code FROM deposits WHERE id=?", (dep_id,))
    row = cur.fetchone()
    if not row or row[3] != "pending":
        await call.answer("Уже обработано")
        return
    uid, amount, acc, _, ts, code = row
    cur.execute("UPDATE deposits SET status=? WHERE id=?", ("approved" if ok else "rejected", dep_id))
    conn.commit()
    await call.answer("OK")
    if ok:
        elapsed = int(time.time()) - (ts or int(time.time()))
        try:
            await bot.send_message(
                uid,
                f"{E['check']} <b>Баланс пополнен!</b>\n\n{E['cash']} <b>{amount:.2f} сом</b>\n"
                f"🆔 {PLATFORM} | <code>{acc}</code>\n⏱ {elapsed} сек\n\n"
                f"{E['rocket']} Спасибо, что выбрали <b>{BOT_NAME}</b>!",
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await call.message.edit_caption(caption=f"✅ #{dep_id} {code} ОДОБРЕНА")
        except Exception:
            pass
    else:
        try:
            await bot.send_message(uid, f"❌ Заявка {code} на {amount:.2f} сом отклонена.\n{SUPPORT}")
        except Exception:
            pass
        try:
            await call.message.edit_caption(caption=f"❌ #{dep_id} {code} ОТКЛОНЕНА")
        except Exception:
            pass

# ================= WITHDRAW =================
@dp.message(F.text.in_({"📤 Вывести", "Вывести"}))
async def wd_start(message: types.Message, state: FSMContext):
    if not await require_sub(message):
        return
    if not bot_on() and not is_admin(message.from_user.id):
        await message.answer("Бот на обслуживании.")
        return
    await state.set_state(Wd.account)
    await state.update_data(action="withdraw")
    saved = get_account(message.from_user.id)
    extra = f"\n\nСохранённый ID: <code>{saved}</code>" if saved else ""
    await message.answer(
        f"{E['withdraw']} <b>ВЫВОД СРЕДСТВ ({PLATFORM})</b>\n\n"
        f"{E['fire']} Заходим 👇\n"
        f"{E['star']}1. Настройки!\n"
        f"{E['star']}2. Вывести со счета!\n"
        f"{E['star']}3. Наличные\n"
        f"{E['star']}4. Сумму для Вывода!\n"
        f"Город: <b>Каракол</b>\n"
        f"Улица: <b>Ekassa.KG</b>\n"
        f"{E['star']}5. Подтвердить\n"
        f"{E['star']}6. Получить Код!\n"
        f"📍 7. Отправить его в бота\n\n"
        f"Введите ID игрового счёта:{extra}",
        parse_mode="HTML", reply_markup=kb_back(),
    )

@dp.message(Wd.account)
async def wd_acc(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    acc = (message.text or "").strip()
    if not acc:
        await message.answer("Введите ID!")
        return
    save_account(message.from_user.id, acc)
    await state.update_data(account_id=acc)
    await state.set_state(Wd.amount)
    await message.answer(
        f"{E['check']} ID: <code>{acc}</code>\n\n{E['cash']} Введите сумму вывода или кнопку:",
        reply_markup=kb_amounts_wd(), parse_mode="HTML",
    )

@dp.callback_query(F.data.startswith("amt_"), Wd.amount)
async def wd_amt_btn(call: types.CallbackQuery, state: FSMContext):
    amount = float(call.data.replace("amt_", ""))
    await state.update_data(amount=amount)
    await state.set_state(Wd.qr)
    await call.answer()
    data = await state.get_data()
    await call.message.answer(
        f"{E['wallet']} ID: <code>{data.get('account_id')}</code>\n"
        f"{E['cash']} Сумма: <b>{amount:.2f} сом</b>\n\n"
        f"{E['write']} Отправьте <b>фото QR</b> кошелька:",
        parse_mode="HTML", reply_markup=kb_back(),
    )

@dp.message(Wd.amount)
async def wd_amt_txt(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    try:
        amount = float((message.text or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        await message.answer("⚠️ Введите число!")
        return
    if amount < MIN_WITHDRAW:
        await message.answer(f"⚠️ Минимум {MIN_WITHDRAW} сом")
        return
    await state.update_data(amount=amount)
    await state.set_state(Wd.qr)
    data = await state.get_data()
    await message.answer(
        f"🏷 ID: <code>{data.get('account_id')}</code>\n"
        f"💵 Сумма: <b>{amount:.2f} сом</b>\n\n"
        f"📍 Отправьте <b>фото QR</b> кошелька:",
        parse_mode="HTML", reply_markup=kb_back(),
    )

@dp.message(Wd.qr, F.photo | F.document)
async def wd_qr(message: types.Message, state: FSMContext):
    fid = message.photo[-1].file_id if message.photo else message.document.file_id
    await state.update_data(qr_file_id=fid)
    await state.set_state(Wd.code)
    await message.answer(
        f"{E['write']} <b>Шаг: код</b>\n\nОтправьте <b>код вывода</b> из приложения:",
        parse_mode="HTML", reply_markup=kb_back(),
    )

@dp.message(Wd.qr)
async def wd_qr_bad(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    await message.answer("Нужно фото QR!")

@dp.message(Wd.code)
async def wd_code(message: types.Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await show_main(message)
        return
    code_txt = (message.text or "").strip()
    if not code_txt:
        await message.answer("Отправьте код!")
        return
    data = await state.get_data()
    uid = message.from_user.id
    ensure_user(uid, message.from_user.username or "", message.from_user.full_name or "")
    c = code_gen()
    amount = float(data.get("amount") or 0)
    cur.execute(
        """INSERT INTO withdrawals (code,user_id,account_id,amount,qr_file_id,code_txt,status,created_at)
           VALUES (?,?,?,?,?,?,'pending',?)""",
        (c, uid, data.get("account_id"), amount, data.get("qr_file_id"), code_txt,
         now_kg().strftime("%d.%m.%Y %H:%M")),
    )
    w_id = cur.lastrowid
    conn.commit()
    await state.clear()
    await message.answer(
        f"{E['check']} Заявка <b>{c}</b> на вывод принята!\n\n{E['zap']} Ожидайте выплаты.",
        parse_mode="HTML", reply_markup=kb_main(uid),
    )
    cap = (
        f"🛫 <b>ВЫВОД #{w_id}</b> · <code>{c}</code>\n\n"
        f"👤 {label(uid)}\n"
        f"🆔 {PLATFORM} | <code>{data.get('account_id')}</code>\n"
        f"💵 {amount:.2f} сом\n"
        f"🔑 Код: <code>{code_txt}</code>"
    )
    await notify_admins(text=cap, photo=data.get("qr_file_id"), reply_markup=kb_wd(w_id))

@dp.callback_query(F.data.startswith("wd_ok_") | F.data.startswith("wd_no_"))
async def wd_mod(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет прав", show_alert=True)
        return
    ok = call.data.startswith("wd_ok_")
    w_id = int(call.data.split("_")[-1])
    cur.execute("SELECT user_id, account_id, status, code, amount FROM withdrawals WHERE id=?", (w_id,))
    row = cur.fetchone()
    if not row or row[2] != "pending":
        await call.answer("Уже обработано")
        return
    cur.execute("UPDATE withdrawals SET status=? WHERE id=?", ("completed" if ok else "rejected", w_id))
    conn.commit()
    await call.answer("OK")
    try:
        if ok:
            await bot.send_message(
                row[0],
                f"✅ <b>Вывод выполнен!</b>\n\n"
                f"🆔 <code>{row[1]}</code>\n"
                f"💵 {row[4]:.2f} сом\n"
                f"Спасибо, что пользуетесь {BOT_NAME}.",
                parse_mode="HTML",
            )
            await call.message.edit_caption(caption=f"✅ ВЫВОД #{w_id} ГОТОВ")
        else:
            await bot.send_message(row[0], f"❌ Вывод {row[3]} отклонён.")
            await call.message.edit_caption(caption=f"❌ ВЫВОД #{w_id} ОТКЛОНЁН")
    except Exception:
        pass

# ================= SUPPORT =================
@dp.message(F.text.in_({"💬 Поддержка", "Поддержка"}))
async def support(message: types.Message):
    if not await require_sub(message):
        return
    await message.answer(
        f"{E['support']} <b>Поддержка {BOT_NAME}</b>\n\n"
        f"{E['write']} 👉 {SUPPORT}\n{SUPPORT_URL}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💬 Написать", url=SUPPORT_URL)],
        ]),
    )

# ================= ADMIN =================
@dp.message(F.text.in_({"⚙️ Админ-панель", "Админ-панель"}))
@dp.message(Command("admin"))
async def admin_panel(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    await state.clear()
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    await message.answer(
        f"{E['admin']} <b>Панель {BOT_NAME}</b>\n\n"
        f"Бот: {'🟢 Работает' if bot_on() else '🔴 Отключён'}\n"
        f"Автопополнение: {E['check'] + ' Вкл' if auto_on() else E['cross'] + ' Выкл'}\n"
        f"Пользователей: {users}\n"
        f"{E['stats']} Админ: <code>{MAIN_ADMIN}</code>",
        reply_markup=kb_admin(), parse_mode="HTML",
    )

@dp.callback_query(F.data == "adm_back")
async def adm_back(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.answer()
    await show_main(call.message)

@dp.callback_query(F.data == "adm_toggle_bot")
async def adm_toggle_bot(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    set_bot(not bot_on())
    await call.answer("OK")
    await call.message.edit_text(
        f"👑 <b>Панель {BOT_NAME}</b>\n\nБот: {'🟢 Работает' if bot_on() else '🔴 Отключён'}",
        reply_markup=kb_admin(), parse_mode="HTML",
    )

@dp.callback_query(F.data == "adm_toggle_auto")
async def adm_toggle_auto(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    set_auto(not auto_on())
    await call.answer("OK")
    await call.message.edit_text(
        f"👑 <b>Панель {BOT_NAME}</b>\n\nАвтопополнение: {'✅ Вкл' if auto_on() else '❌ Выкл'}",
        reply_markup=kb_admin(), parse_mode="HTML",
    )

@dp.callback_query(F.data == "adm_deps")
async def adm_deps(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.answer()
    cur.execute(
        "SELECT id, code, user_id, amount, account_id, photo_id FROM deposits "
        "WHERE status='pending' ORDER BY id DESC LIMIT 15"
    )
    rows = cur.fetchall()
    if not rows:
        await call.message.answer("Нет активных заявок.")
        return
    for dep_id, code, uid, amount, acc, photo in rows:
        cap = f"🔥 <b>#{dep_id}</b> · <code>{code}</code>\n👤 {label(uid)}\n💵 {amount:.2f}\n🆔 <code>{acc}</code>"
        try:
            if photo:
                await bot.send_photo(call.message.chat.id, photo, caption=cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
            else:
                await call.message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")
        except Exception:
            await call.message.answer(cap, reply_markup=kb_dep(dep_id), parse_mode="HTML")

@dp.callback_query(F.data == "adm_stats")
async def adm_stats(call: types.CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM deposits WHERE status='pending'")
    pending = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE status='approved'")
    total = cur.fetchone()[0]
    await call.answer()
    await call.message.answer(
        f"📈 <b>СТАТИСТИКА</b>\n\n"
        f"👥 Пользователей: <b>{users}</b>\n"
        f"⏳ В очереди: <b>{pending}</b>\n"
        f"💵 Объём: <b>{total:.2f} сом</b>",
        parse_mode="HTML",
    )

@dp.callback_query(F.data == "adm_broadcast")
async def adm_bc(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(Broadcast.content)
    await call.answer()
    await call.message.answer("📢 Отправьте текст или фото с подписью для рассылки:")

@dp.message(Broadcast.content)
async def bc_send(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    cur.execute("SELECT user_id FROM users")
    users = [r[0] for r in cur.fetchall()]
    ok = 0
    photo = message.photo[-1].file_id if message.photo else None
    text = message.caption or message.text or ""
    status = await message.answer(f"⏳ Рассылка: 0/{len(users)}...")
    for uid in users:
        try:
            if photo:
                await bot.send_photo(uid, photo, caption=text, parse_mode="HTML")
            elif text:
                await bot.send_message(uid, text, parse_mode="HTML")
            ok += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)
    await status.edit_text(f"✅ Рассылка: {ok}/{len(users)}")

@dp.callback_query(F.data == "adm_add")
async def adm_add(call: types.CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AdminAdd.uid)
    await call.answer()
    await call.message.answer("➕ ID нового админа:")

@dp.message(AdminAdd.uid)
async def adm_add_do(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    try:
        new_id = int((message.text or "").strip())
        cur.execute("INSERT OR IGNORE INTO admins (chat_id) VALUES (?)", (new_id,))
        conn.commit()
        await state.clear()
        await message.answer(f"✅ Админ <code>{new_id}</code> добавлен!", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Некорректный ID")

@dp.callback_query(F.data == "adm_del")
async def adm_del(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != MAIN_ADMIN:
        await call.answer("Только главный админ", show_alert=True)
        return
    await state.set_state(AdminDel.uid)
    await call.answer()
    await call.message.answer(f"➖ Админы: {get_admins()}\n\nID для удаления:")

@dp.message(AdminDel.uid)
async def adm_del_do(message: types.Message, state: FSMContext):
    if message.from_user.id != MAIN_ADMIN:
        return
    try:
        del_id = int((message.text or "").strip())
        if del_id == MAIN_ADMIN:
            await message.answer("❌ Нельзя удалить главного")
            return
        cur.execute("DELETE FROM admins WHERE chat_id=?", (del_id,))
        conn.commit()
        await state.clear()
        await message.answer(f"✅ <code>{del_id}</code> удалён", parse_mode="HTML")
    except ValueError:
        await message.answer("❌ Некорректный ID")

# ================= ERRORS =================
@dp.errors()
async def on_error(event: ErrorEvent):
    exc = event.exception
    log.exception("Error: %s", exc)
    if isinstance(exc, TelegramRetryAfter):
        await asyncio.sleep(exc.retry_after)
        return True
    if isinstance(exc, (TelegramForbiddenError, TelegramBadRequest, TelegramNetworkError)):
        return True
    return True

# ================= MAIN =================
async def main():
    while True:
        try:
            try:
                await bot.delete_webhook(drop_pending_updates=True)
                log.info("webhook deleted")
            except Exception as e:
                log.warning("delete_webhook: %s", e)
            log.info("%s start | admins=%s", BOT_NAME, get_admins())
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        except TelegramNetworkError as e:
            log.error("Network: %s — retry 5s", e)
            await asyncio.sleep(5)
        except Exception as e:
            log.exception("Crash: %s — restart 5s", e)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
