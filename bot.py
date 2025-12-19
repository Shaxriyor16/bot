import os
import asyncio
import logging
from typing import Union
from dotenv import load_dotenv
load_dotenv()
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    Reply estatesKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramBadRequest

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7337873747"))
SHEET_JSON = os.getenv("SHEET_JSON", "Reyting-bot.json")
REQUIRED_CHANNELS = [channel.strip() for channel in os.getenv("REQUIRED_CHANNELS", "@M24SHaxa_youtube").split(',')]
RATING_SHEET_LINK = "https://docs.google.com/spreadsheets/d/1T0JuaRetTKusLkR8Kb21Ie87kA2Z4nv3fDJ2ziyuAh4/edit?gid=0#gid=0"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Put it into .env as BOT_TOKEN=your_token")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

def connect_to_sheet(spreadsheet_name: str = "Pubg Reyting", worksheet_name: str = "Reyting-bot"):
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(SHEET_JSON, scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).worksheet(worksheet_name)
        return sheet
    except Exception as e:
        logger.exception("Google Sheetsga ulanishda xatolik:")
        raise

def append_to_sheet(nickname: str, pubg_id: str):
    try:
        sheet = connect_to_sheet()
        sheet.append_row([nickname, pubg_id])
        logger.info("Row added to sheet: %s | %s", nickname, pubg_id)
        return True
    except Exception as e:
        logger.exception("sheet append error")
        return False

class RegistrationState(StatesGroup):
    waiting_for_payment_check = State()
    waiting_for_admin_approval = State()
    waiting_for_pubg_nick = State()

inline_main_buttons = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Ro'yxatdan o'tish", callback_data="register"),
            InlineKeyboardButton(text="📊 Natijalar", callback_data="results")
        ],
        [
            InlineKeyboardButton(text="🎮 Mening o‘yinlarim", callback_data="my_games"),
            InlineKeyboardButton(text="📮 Admin bilan bog'lanish", callback_data="contact_admin")
        ]
    ]
)

reply_social_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📸 Instagram"), KeyboardButton(text="📱 Telegram")],
        [KeyboardButton(text="🎮 Twitch"), KeyboardButton(text="▶️ YouTube")],
        [KeyboardButton(text="📍 ASOSIY MENYU")]
    ],
    resize_keyboard=True
)

def get_subscription_keyboard():
    inline_keyboard = []
    for i, channel in enumerate(REQUIRED_CHANNELS, 1):
        channel_name = channel.lstrip('@')
        text = f"📢 Kanal {i}" if len(REQUIRED_CHANNELS) > 1 else "📢 Kanal"
        inline_keyboard.append([InlineKeyboardButton(text=text, url=f"https://t.me/{channel_name}")])
    inline_keyboard.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def approve_buttons_template(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ To‘g‘ri", callback_data=f"approve:{user_id}"),
                InlineKeyboardButton(text="❌ Noto‘g‘ri", callback_data=f"reject:{user_id}")
            ]
        ]
    )

async def check_subscription(user_id: int) -> bool:
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "creator", "administrator"):
                return False
        except Exception as e:
            logger.warning("check_subscription error for channel %s user %s: %s", channel, user_id, e)
            return False
    return True

async def ask_for_payment(target: Union[Message, CallbackQuery], state: FSMContext):
    user_id = target.from_user.id
    text = (
        "💳 <b>Karta turi:</b> HUMO\n"
        "💳 <b>Karta raqami:</b> <code>9860 6004 1512 3691</code>\n\n"
        "📌 Toʻlovni amalga oshirib, CHECK (skrinshot) yuboring."
    )
    msg = await bot.send_message(user_id, text)
    await asyncio.sleep(5)
    try:
        await bot.delete_message(user_id, msg.message_id)
    except TelegramBadRequest:
        pass
    await bot.send_message(user_id, "✅ Endi to‘lovni amalga oshirgach, <b>chekni yuboring</b> (rasm yoki fayl):")
    await state.set_state(RegistrationState.waiting_for_payment_check)

async def show_rating(message: Message):
    try:
        sheet = connect_to_sheet()
        data = sheet.get_all_values()
    except Exception:
        await message.answer("⚠️ Reytingni olishda xatolik yuz berdi.")
        return

    if len(data) <= 1:
        text = "📊 Reytinglar hali mavjud emas.\n\n"
    else:
        lines = ["🏆 <b>Reyting jadvali (Top 20):</b>\n"]
        for idx, row in enumerate(data[1:21], start=1):
            nickname = row[0] if len(row) > 0 else "-"
            pubg_id = row[1] if len(row) > 1 else "-"
            lines.append(f"{idx}. <b>{nickname}</b> (ID: {pubg_id})")
        text = "\n".join(lines) + "\n\n"

    text += f"📋 To'liq reyting jadvali:\n{RATING_SHEET_LINK}"
    await message.answer(text, disable_web_page_preview=True)

class SubscriptionMiddleware:
    async def __call__(self, handler, event, data):
        allow = False
        if isinstance(event, Message):
            if event.text and event.text.startswith(("/start", "/help", "/register", "/mygames", "/contactwithadmin", "/about", "/reyting")):
                allow = True
        elif isinstance(event, CallbackQuery):
            if event.data == "check_subscription":
                allow = True
        if allow:
            return await handler(event, data)

        user_id = event.from_user.id
        if not await check_subscription(user_id):
            kanal_text = "kanallarga" if len(REQUIRED_CHANNELS) > 1 else "kanalga"
            text = f"❌ Botdan foydalanish uchun {kanal_text} obuna bo‘lishingiz kerak."
            markup = get_subscription_keyboard()
            if isinstance(event, Message):
                await event.answer(text, reply_markup=markup)
            elif isinstance(event, CallbackQuery):
                try:
                    await event.message.edit_text(text, reply_markup=markup)
                except TelegramBadRequest:
                    await bot.send_message(event.message.chat.id, text, reply_markup=markup)
                await event.answer()
            return
        return await handler(event, data)

dp.message.middleware(SubscriptionMiddleware())
dp.callback_query.middleware(SubscriptionMiddleware())

@dp.message(Command("start"))
async def start_handler(message: Message):
    user_id = message.from_user.id
    if await check_subscription(user_id):
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM</b>\nTDM TOURNAMENT BOTGA🎮 Xush kelibsiz!\n\n"
            "Bu bot orqali turnirda qatnashishingiz mumkin.\n⚠️ Turnir <b>pullik</b>.\n\n"
            "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )
    else:
        kanal_text = "kanallarga" if len(REQUIRED_CHANNELS) > 1 else "kanalga"
        await message.answer(
            f"👋 Assalomu alaykum!\n\nBotdan foydalanish uchun quyidagi {kanal_text} obuna bo‘ling va ✅ Tekshirish tugmasini bosing 👇",
            reply_markup=get_subscription_keyboard()
        )

@dp.message(Command(commands=["register", "reyting", "mygames", "contactwithadmin", "about", "help"]))
async def universal_commands(message: Message, state: FSMContext):
    cmd = message.text.lower()
    if "/register" in cmd:
        await ask_for_payment(message, state)
    elif "/reyting" in cmd:
        await show_rating(message)
    elif "/mygames" in cmd:
        await message.answer("🎮 Sizda hozircha o‘yin yo‘q.")
    elif "/contactwithadmin" in cmd:
        await message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")
    elif "/about" in cmd:
        await message.answer(
            "🎮 PUBG MOBILE TURNIR BOT 🎮\n\n"
            "Bu bot orqali siz pullik PUBG Mobile turnirlarida qatnashishingiz,\n"
            "to‘lov qilgan holda ishtirok etishingiz va sovrinli o‘rinlar uchun kurashishingiz mumkin! 🏆"
        )
    elif "/help" in cmd:
        await message.answer(
            "/start — Botni qayta ishga tushirish\n"
            "/register — Ro'yxatdan o'tish\n"
            "/reyting — Reytingni ko'rish\n"
            "/mygames — Mening o'yinlarim\n"
            "/contactwithadmin — Admin bilan bog'lanish\n"
            "/about — Bot haqida\n"
            "/help — Yordam"
        )

@dp.callback_query(F.data == "check_subscription")
async def subscription_callback(call: CallbackQuery):
    user_id = call.from_user.id
    if await check_subscription(user_id):
        await call.message.edit_text(
            "✅ Obunangiz tasdiqlandi. Endi botdan to‘liq foydalanishingiz mumkin.",
            reply_markup=inline_main_buttons
        )
    else:
        kanal_text = "kanallarga" if len(REQUIRED_CHANNELS) > 1 else "kanalga"
        await call.message.edit_text(
            f"❌ Siz hali {kanal_text} obuna bo‘lmagansiz.\nIltimos, obuna bo‘ling va ✅ Tekshirish tugmasini yana bosing 👇",
            reply_markup=get_subscription_keyboard()
        )
    await call.answer()

@dp.callback_query(F.data == "register")
async def register_callback(call: CallbackQuery, state: FSMContext):
    await ask_for_payment(call, state)
    await call.answer()

@dp.callback_query(F.data == "results")
async def results_callback(call: CallbackQuery):
    await show_rating(call.message)
    await call.answer()

@dp.callback_query(F.data == "my_games")
async def my_games_callback(call: CallbackQuery):
    await call.message.answer("🎮 Sizda hozircha o‘yin yo‘q.")
    await call.answer()

@dp.callback_query(F.data == "contact_admin")
async def contact_admin_callback(call: CallbackQuery):
    await call.message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")
    await call.answer()

@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext):
    await message.answer("🕔 Chekingiz admin tomonidan tekshirilmoqda.")
    approve_buttons = approve_buttons_template(message.from_user.id)
    try:
        if message.photo:
            file_id = message.photo[-1].file_id
            await bot.send_photo(
                ADMIN_ID, file_id,
                caption=(f"🥾 Yangi chek:\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yo‘q'}"),
                reply_markup=approve_buttons
            )
        elif message.document:
            file_id = message.document.file_id
            await bot.send_document(
                ADMIN_ID, file_id,
                caption=(f"🥾 Yangi chek (fayl):\n👤 <b>{message.from_user.full_name}</b>\n"
                         f"🆔 <code>{message.from_user.id}</code>\n"
                         f"📌 @{message.from_user.username or 'username yo‘q'}"),
                reply_markup=approve_buttons
            )
    except Exception as e:
        logger.exception("Failed to send check to admin: %s", e)
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi.")
        await state.clear()
        return
    await state.set_state(RegistrationState.waiting_for_admin_approval)

@dp.callback_query(F.data.startswith("approve:"))
async def approve_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    await bot.send_message(user_id, "✅ Chekingiz tasdiqlandi. Endi PUBG nickname va ID'ingizni yuboring.\nMasalan: Nickname 123456789")
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("✅ Tasdiqlandi")

@dp.callback_query(F.data.startswith("reject:"))
async def reject_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.clear_state(key)
    await bot.send_message(user_id, "❌ Chekingiz rad etildi. Qayta urinib ko‘ring.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("❌ Rad etildi")

@dp.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_info(message: Message, state: FSMContext):
    text = message.text or ""
    tokens = text.replace(",", " ").split()
    pubg_nick = " ".join(tokens[:-1]) if len(tokens) >= 2 else text.strip()
    pubg_id = tokens[-1] if len(tokens) >= 2 else "ID not provided"
    nickname = pubg_nick or message.from_user.full_name

    ok = append_to_sheet(nickname, pubg_id)
    if ok:
        await message.answer("📋 Ma'lumot qabul qilindi. Reytingga qoʻshildi. Rahmat!", reply_markup=reply_social_menu)
    else:
        await message.answer("⚠️ Reytingga qoʻshishda xatolik yuz berdi. Admin bilan bog‘laning.", reply_markup=reply_social_menu)
    
    try:
        await bot.send_message(ADMIN_ID, f"🆕 Yangi qatnashchi:\n👤 {message.from_user.full_name}\n🎮 Nick: {nickname}\n🆔 ID: {pubg_id}\n🆔 User ID: {message.from_user.id}")
    except Exception:
        pass
    await state.clear()

async def main():
    logger.info("Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
