
import asyncio
import logging
import sys
import os
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

# Configure logging
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

# List of initial admin user IDs (Replace or add your Telegram Admin ID)
ADMIN_IDS = [8992968778] 

# Bot state variables
AUTO_TOPUP_ENABLED = True  # Status for auto-topup
BOT_ENABLED = True         # Global switch to enable/disable bot for users
USER_IDS = set()           # Store users for broadcasting

class TransactionStates(StatesGroup):
    waiting_for_channel_sub = State()
    choosing_action = State()
    entering_id = State()
    entering_amount = State()
    uploading_qr_or_receipt = State()
    admin_broadcast = State()
    admin_add_id = State()
    admin_del_id = State()

def get_sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟠 Подписаться на канал", url="https://t.me/ekassaNews")],
        [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_sub")]
    ])

def get_main_menu(user_id: int):
    keyboard = [
        [KeyboardButton(text="📥 Пополнить"), KeyboardButton(text="📤 Вывести")],
        [KeyboardButton(text="💬 Поддержка")]
    ]
    if user_id in ADMIN_IDS:
        keyboard.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_admin_menu():
    bot_status_text = "🔴 Выключить бота" if BOT_ENABLED else "🟢 Включить бота"
    auto_status_text = "🟢 Автопополнение (Вкл)" if AUTO_TOPUP_ENABLED else "🔴 Автопополнение (Выкл)"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Сделать рассылку (Текст/Фото)", callback_data="adm_broadcast")],
        [InlineKeyboardButton(text=bot_status_text, callback_data="adm_toggle_bot")],
        [InlineKeyboardButton(text=auto_status_text, callback_data="adm_toggle_auto")],
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="adm_add")],
        [InlineKeyboardButton(text="➖ Удалить админа", callback_data="adm_del")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="adm_back")]
    ])

router = Router()

@router.message.middleware()
async def check_bot_enabled(handler, event, data):
    user_id = event.from_user.id if event.from_user else 0
    if not BOT_ENABLED and user_id not in ADMIN_IDS:
        if isinstance(event, Message):
            await event.answer("⚠️ В данный момент бот находится на техническом обслуживании. Попробуйте позже.")
        elif isinstance(event, CallbackQuery):
            await event.answer("⚠️ Бот на техобслуживании.", show_alert=True)
        return
    return await handler(event, data)

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    USER_IDS.add(user_id)
    
    await state.clear()
    await state.set_state(TransactionStates.waiting_for_channel_sub)
    await message.answer(
        "👋 Добро пожаловать в официальный бот **EkassaKG**!\n\n"
        "🔒 Для использования бота подпишитесь на наш канал: https://t.me/ekassaNews\n"
        "После подписки нажмите «Проверить подписку».",
        reply_markup=get_sub_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(F.data == "check_sub")
async def process_check_sub(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TransactionStates.choosing_action)
    user_id = callback.from_user.id
    USER_IDS.add(user_id)
    await callback.message.answer(
        "✅ Подписка подтверждена. Выберите действие ниже:",
        reply_markup=get_main_menu(user_id)
    )
    await callback.answer()

@router.message(F.text == "📥 Пополнить")
async def process_deposit(message: Message, state: FSMContext):
    await state.set_state(TransactionStates.entering_id)
    await state.update_data(bookmaker="1XBET", action_type="deposit")
    await message.answer(
        "🟢 **ПОПОЛНЕНИЕ СЧЕТА (1XBET)**\n\n"
        "📍 Заходим в приложение или на сайт\n"
        "📍 1. Настройки!\n"
        "📍 2. Введите ID Вашего игрового счета:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )

@router.message(F.text == "📤 Вывести")
async def process_withdraw(message: Message, state: FSMContext):
    await state.set_state(TransactionStates.entering_id)
    await state.update_data(bookmaker="1XBET", action_type="withdraw")
    await message.answer(
        "📤 **ВЫВОД СРЕДСТВ (1XBET)**\n\n"
        "📍 Заходим 👇\n"
        "📍 1. Настройки!\n"
        "📍 2. Вывести со счета!\n"
        "📍 3. Наличные\n"
        "📍 4. Сумму для Вывода!\n"
        "Город: Каракол\n"
        "Улица: Ekassa.KG\n"
        "📍 5. Подтвердить\n"
        "📍 6. Получить Код!\n"
        "📍 7. Отправить его в бота\n\n"
        "Введите ID Вашего игрового счета 1XBET:", 
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
        ])
    )

@router.message(F.text == "💬 Поддержка")
async def process_support(message: Message):
    await message.answer(
        "💬 По всем вопросам обращайтесь в поддержку:\n👉 @Ekassahelp_bot",
        parse_mode=ParseMode.MARKDOWN
    )

@router.message(TransactionStates.entering_id)
async def process_id_entered(message: Message, state: FSMContext):
    await state.update_data(account_id=message.text)
    data = await state.get_data()
    action_type = data.get("action_type", "deposit")
    
    await state.set_state(TransactionStates.entering_amount)
    auto_status = "🟢 Активно" if AUTO_TOPUP_ENABLED else "🔴 Отключено"
    
    if action_type == "deposit":
        await message.answer(
            f"💰 **Пополнение счета (1XBET)** (Автопополнение: {auto_status})\n\n"
            "Минимум: 35 сом | Максимум: 100 000 сом\n\n"
            "Введите сумму пополнения или выберите одну из кнопок:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="100 сом", callback_data="amt_100"), InlineKeyboardButton(text="500 сом", callback_data="amt_500")],
                [InlineKeyboardButton(text="1000 сом", callback_data="amt_1000"), InlineKeyboardButton(text="5000 сом", callback_data="amt_5000")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.answer(
            f"💵 **Вывод средств (1XBET)**\n\n"
            "Введите сумму для вывода или выберите одну из кнопок:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="500 сом", callback_data="amt_500"), InlineKeyboardButton(text="1000 сом", callback_data="amt_1000")],
                [InlineKeyboardButton(text="5000 сом", callback_data="amt_5000"), InlineKeyboardButton(text="10000 сом", callback_data="amt_10000")],
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )

@router.callback_query(F.data.startswith("amt_"))
async def process_amount_chosen(callback: CallbackQuery, state: FSMContext):
    amount = callback.data.split("_")[1]
    data = await state.get_data()
    acc_id = data.get("account_id")
    action_type = data.get("action_type", "deposit")
    
    await state.set_state(TransactionStates.uploading_qr_or_receipt)
    
    if action_type == "deposit":
        await callback.message.answer(
            f"🏷 Ваш ID: `{acc_id}`\n💵 Сумма к оплате: **{amount}.00 COM**\n\n"
            "📍 Отсканируйте QR-код или переведите средства.\n"
            "Затем отправьте сюда скриншот чека.\n⏳ Осталось на оплату: **05:00**",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Мбанк", callback_data="pay_mbank"), InlineKeyboardButton(text="О!Деньги", callback_data="pay_odengi")],
                [InlineKeyboardButton(text="MegaPay", callback_data="pay_megapay"), InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await callback.message.answer(
            f"🏷 Ваш ID: `{acc_id}`\n💵 Сумма вывода: **{amount}.00 COM**\n\n"
            "📍 Отправьте фото QR-кода кошелька для получения наличных.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]
            ]),
            parse_mode=ParseMode.MARKDOWN
        )
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def process_cancel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(TransactionStates.choosing_action)
    user_id = callback.from_user.id
    await callback.message.answer("❌ Операция отменена.", reply_markup=get_main_menu(user_id))
    await callback.answer()

@router.message(F.text == "⚙️ Админ-панель")
async def admin_panel_handler(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ У вас нет доступа к административной панели.")
        return
    
    await message.answer(
        f"👑 **Панель Администратора EkassaKG**\n\n"
        f"Статус бота: {'🟢 Работает' if BOT_ENABLED else '🔴 Отключен'}\n"
        f"Статус автопополнения: {'✅ Включено' if AUTO_TOPUP_ENABLED else '❌ Отключено'}\n"
        f"Пользователей в базе: {len(USER_IDS)}\n"
        f"Администраторов: {len(ADMIN_IDS)}",
        reply_markup=get_admin_menu(),
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(F.data == "adm_back")
async def admin_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=get_main_menu(callback.from_user.id))
    await callback.answer()

@router.callback_query(F.data == "adm_toggle_bot")
async def toggle_bot_status(callback: CallbackQuery):
    global BOT_ENABLED
    if callback.from_user.id not in ADMIN_IDS:
        return
    BOT_ENABLED = not BOT_ENABLED
    status_text = "включен 🟢" if BOT_ENABLED else "отключен 🔴"
    await callback.message.edit_text(
        f"👑 **Панель Администратора EkassaKG**\n\nБот теперь {status_text}.",
        reply_markup=get_admin_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@router.callback_query(F.data == "adm_toggle_auto")
async def toggle_auto_topup(callback: CallbackQuery):
    global AUTO_TOPUP_ENABLED
    if callback.from_user.id not in ADMIN_IDS:
        return
    AUTO_TOPUP_ENABLED = not AUTO_TOPUP_ENABLED
    status_text = "включено 🟢" if AUTO_TOPUP_ENABLED else "отключено 🔴"
    await callback.message.edit_text(
        f"👑 **Панель Администратора EkassaKG**\n\nАвтопополнение теперь {status_text}.",
        reply_markup=get_admin_menu(),
        parse_mode=ParseMode.MARKDOWN
    )
    await callback.answer()

@router.callback_query(F.data == "adm_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(TransactionStates.admin_broadcast)
    await callback.message.answer(
        "📢 Отправьте сообщение для рассылки.\n"
        "Вы можете отправить текст, фото с подписью или видео:"
    )
    await callback.answer()

@router.message(TransactionStates.admin_broadcast)
async def send_broadcast_message(message: Message, state: FSMContext, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await state.clear()
    success_count = 0
    fail_count = 0
    
    status_msg = await message.answer(f"⏳ Рассылка началась по {len(USER_IDS)} пользователям...")
    
    for uid in USER_IDS:
        try:
            if message.photo:
                await bot.send_photo(chat_id=uid, photo=message.photo[-1].file_id, caption=message.caption, parse_mode=ParseMode.HTML)
            elif message.video:
                await bot.send_video(chat_id=uid, video=message.video.file_id, caption=message.caption, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(chat_id=uid, text=message.text, parse_mode=ParseMode.HTML)
            success_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail_count += 1
            
    await status_msg.edit_text(
        f"✅ **Рассылка завершена!**\n\n"
        f"📤 Успешно доставлено: {success_count}\n"
        f"❌ Ошибок отправки: {fail_count}",
        parse_mode=ParseMode.MARKDOWN
    )

@router.callback_query(F.data == "adm_add")
async def add_admin_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(TransactionStates.admin_add_id)
    await callback.message.answer("➕ Введите Telegram ID нового администратора (число):")
    await callback.answer()

@router.message(TransactionStates.admin_add_id)
async def save_new_admin(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        new_id = int(message.text.strip())
        if new_id not in ADMIN_IDS:
            ADMIN_IDS.append(new_id)
            await message.answer(f"✅ Пользователь `{new_id}` успешно добавлен в список администраторов!", parse_mode=ParseMode.MARKDOWN)
        else:
            await message.answer("⚠️ Этот пользователь уже является администратором.")
    except ValueError:
        await message.answer("❌ Ошибка. Введите корректный числовой ID.")
    await state.clear()

@router.callback_query(F.data == "adm_del")
async def del_admin_prompt(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.set_state(TransactionStates.admin_del_id)
    await callback.message.answer(f"➖ Текущие админы: `{ADMIN_IDS}`\n\nВведите Telegram ID для удаления:")
    await callback.answer()

@router.message(TransactionStates.admin_del_id)
async def remove_admin(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        del_id = int(message.text.strip())
        if del_id in ADMIN_IDS:
            if len(ADMIN_IDS) > 1:
                ADMIN_IDS.remove(del_id)
                await message.answer(f"✅ Администратор `{del_id}` удален.", parse_mode=ParseMode.MARKDOWN)
            else:
                await message.answer("⚠️ Нельзя удалить единственного администратора.")
        else:
            await message.answer("❌ Такой ID не найден в списке админов.")
    except ValueError:
        await message.answer("❌ Ошибка ввода.")
    await state.clear()

async def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("❌ ОШИБКА: Переменная окружения BOT_TOKEN не задана!")
        return
    
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    
    print("Бот EkassaKG успешно запущен на Render!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
