import os
import asyncio
import logging
import json
from typing import Union, Optional
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
    ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramBadRequest

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "7337873747"))
SHEET_JSON_CONTENT = os.getenv("SHEET_JSON_CONTENT", "")
REQUIRED_CHANNELS = [channel.strip() for channel in os.getenv("REQUIRED_CHANNELS", "@M24SHaxa_youtube").split(',')]
RATING_SHEET_LINK = "https://docs.google.com/spreadsheets/d/1T0JuaRetTKusLkR8Kb21Ie87kA2Z4nv3fDJ2ziyuAh4/edit?gid=0#gid=0"

# Validate required environment variables
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Please add it to the .env file as BOT_TOKEN=your_token")
if not SHEET_JSON_CONTENT:
    raise RuntimeError("SHEET_JSON_CONTENT is not set. Please add the JSON content to the .env file as SHEET_JSON_CONTENT=your_json")

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")  # Added file handler for persistent logs
    ]
)
logger = logging.getLogger(__name__)

# Bot and Dispatcher initialization
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

def connect_to_sheet(spreadsheet_name: str = "Pubg Reyting", worksheet_name: str = "Reyting-bot") -> gspread.Worksheet:
    """
    Connect to Google Sheets using service account credentials.

    Args:
        spreadsheet_name (str): Name of the spreadsheet.
        worksheet_name (str): Name of the worksheet.

    Returns:
        gspread.Worksheet: The connected worksheet.

    Raises:
        RuntimeError: If connection fails.
    """
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SHEET_JSON_CONTENT), scope)
        client = gspread.authorize(creds)
        sheet = client.open(spreadsheet_name).worksheet(worksheet_name)
        logger.info("Successfully connected to Google Sheet: %s - %s", spreadsheet_name, worksheet_name)
        return sheet
    except Exception as e:
        logger.exception("Error connecting to Google Sheets: %s", e)
        raise RuntimeError("Failed to connect to Google Sheets") from e

def append_to_sheet(nickname: str, pubg_id: str) -> bool:
    """
    Append a new row to the Google Sheet with nickname and PUBG ID.

    Args:
        nickname (str): User's PUBG nickname.
        pubg_id (str): User's PUBG ID.

    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        sheet = connect_to_sheet()
        sheet.append_row([nickname, pubg_id])
        logger.info("Successfully added row to sheet: Nickname=%s, PUBG_ID=%s", nickname, pubg_id)
        return True
    except Exception as e:
        logger.exception("Error appending to sheet: %s", e)
        return False

class RegistrationState(StatesGroup):
    """
    Finite State Machine states for user registration process.
    """
    waiting_for_payment_check = State()
    waiting_for_admin_approval = State()
    waiting_for_pubg_nick = State()

# Inline keyboard for main menu
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

# Reply keyboard for social menu
reply_social_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📸 Instagram"), KeyboardButton(text="📱 Telegram")],
        [KeyboardButton(text="🎮 Twitch"), KeyboardButton(text="▶️ YouTube")],
        [KeyboardButton(text="📍 ASOSIY MENYU")]
    ],
    resize_keyboard=True
)

def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """
    Generate inline keyboard for channel subscriptions.

    Returns:
        InlineKeyboardMarkup: Keyboard with subscription buttons.
    """
    inline_keyboard = []
    for i, channel in enumerate(REQUIRED_CHANNELS, 1):
        channel_name = channel.lstrip('@')
        text = f"📢 Kanal {i}" if len(REQUIRED_CHANNELS) > 1 else "📢 Kanal"
        inline_keyboard.append([InlineKeyboardButton(text=text, url=f"https://t.me/{channel_name}")])
    inline_keyboard.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def approve_buttons_template(user_id: int) -> InlineKeyboardMarkup:
    """
    Generate approval buttons for admin to approve or reject payment.

    Args:
        user_id (int): The user's Telegram ID.

    Returns:
        InlineKeyboardMarkup: Keyboard with approve/reject buttons.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ To‘g‘ri", callback_data=f"approve:{user_id}"),
                InlineKeyboardButton(text="❌ Noto‘g‘ri", callback_data=f"reject:{user_id}")
            ]
        ]
    )

async def check_subscription(user_id: int) -> bool:
    """
    Check if the user is subscribed to all required channels.

    Args:
        user_id (int): The user's Telegram ID.

    Returns:
        bool: True if subscribed to all, False otherwise.
    """
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "creator", "administrator"):
                return False
        except Exception as e:
            logger.warning("Subscription check error for channel %s and user %s: %s", channel, user_id, e)
            return False
    return True

async def ask_for_payment(target: Union[Message, CallbackQuery], state: FSMContext) -> None:
    """
    Prompt the user to make a payment and send a check (screenshot).

    Args:
        target (Union[Message, CallbackQuery]): The incoming message or callback.
        state (FSMContext): The FSM context for state management.
    """
    user_id = target.from_user.id if isinstance(target, Message) else target.from_user.id
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

async def show_rating(message: Message) -> None:
    """
    Display the rating sheet link.

    Args:
        message (Message): The incoming message.
    """
    await message.answer(RATING_SHEET_LINK, disable_web_page_preview=True)

class SubscriptionMiddleware:
    """
    Middleware to check if user is subscribed before processing updates.
    """
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
        if user_id == ADMIN_ID:
            return await handler(event, data)
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
async def start_handler(message: Message) -> None:
    """
    Handle the /start command, check subscription, and send welcome message or subscription prompt.

    Args:
        message (Message): The incoming message.
    """
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
async def universal_commands(message: Message, state: FSMContext) -> None:
    """
    Handle various commands like /register, /reyting, etc.

    Args:
        message (Message): The incoming message.
        state (FSMContext): The FSM context.
    """
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
async def subscription_callback(call: CallbackQuery) -> None:
    """
    Handle subscription check callback.

    Args:
        call (CallbackQuery): The callback query.
    """
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
async def register_callback(call: CallbackQuery, state: FSMContext) -> None:
    """
    Handle registration callback.

    Args:
        call (CallbackQuery): The callback query.
        state (FSMContext): The FSM context.
    """
    await ask_for_payment(call, state)
    await call.answer()

@dp.callback_query(F.data == "results")
async def results_callback(call: CallbackQuery) -> None:
    """
    Handle results callback to show rating.

    Args:
        call (CallbackQuery): The callback query.
    """
    await show_rating(call.message)
    await call.answer()

@dp.callback_query(F.data == "my_games")
async def my_games_callback(call: CallbackQuery) -> None:
    """
    Handle my games callback.

    Args:
        call (CallbackQuery): The callback query.
    """
    await call.message.answer("🎮 Sizda hozircha o‘yin yo‘q.")
    await call.answer()

@dp.callback_query(F.data == "contact_admin")
async def contact_admin_callback(call: CallbackQuery) -> None:
    """
    Handle contact admin callback.

    Args:
        call (CallbackQuery): The callback query.
    """
    await call.message.answer("📩 Admin bilan bog‘lanish: @m24_shaxa_yt")
    await call.answer()

@dp.message(F.text == "📸 Instagram")
async def instagram_handler(message: Message) -> None:
    """
    Handle Instagram button press.

    Args:
        message (Message): The incoming message.
    """
    await message.answer("https://www.instagram.com/m24_shaxa_/")

@dp.message(F.text == "📱 Telegram")
async def telegram_handler(message: Message) -> None:
    """
    Handle Telegram button press.

    Args:
        message (Message): The incoming message.
    """
    await message.answer("https://t.me/M24SHaxa_youtube")

@dp.message(F.text == "🎮 Twitch")
async def twitch_handler(message: Message) -> None:
    """
    Handle Twitch button press.

    Args:
        message (Message): The incoming message.
    """
    await message.answer("https://www.twitch.tv/m24_shaxa")

@dp.message(F.text == "▶️ YouTube")
async def youtube_handler(message: Message) -> None:
    """
    Handle YouTube button press.

    Args:
        message (Message): The incoming message.
    """
    await message.answer("https://www.youtube.com/@SHAXA_GAMEPLAY")

@dp.message(F.text == "📍 ASOSIY MENYU")
async def main_menu_handler(message: Message) -> None:
    """
    Handle main menu button press, sending the initial greeting message.

    Args:
        message (Message): The incoming message.
    """
    await message.answer(
        "👋 <b>ASSALOMU ALAYKUM</b>\nTDM TOURNAMENT BOTGA🎮 Xush kelibsiz!\n\n"
        "Bu bot orqali turnirda qatnashishingiz mumkin.\n⚠️ Turnir <b>pullik</b>.\n\n"
        "<b>💸 TURNIR NARXI – 10 000 SO'M 💸</b>",
        reply_markup=inline_main_buttons
    )

@dp.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_check(message: Message, state: FSMContext) -> None:
    """
    Handle payment check (photo or document) and forward to admin.

    Args:
        message (Message): The incoming message.
        state (FSMContext): The FSM context.
    """
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
async def approve_callback(call: CallbackQuery) -> None:
    """
    Handle approve callback from admin.

    Args:
        call (CallbackQuery): The callback query.
    """
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
async def reject_callback(call: CallbackQuery) -> None:
    """
    Handle reject callback from admin.

    Args:
        call (CallbackQuery): The callback query.
    """
    if call.from_user.id != ADMIN_ID:
        await call.answer("Siz admin emassiz.", show_alert=True)
        return
    user_id = int(call.data.split(":")[1])
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, None)
    await bot.send_message(user_id, "❌ Chekingiz rad etildi. Qayta urinib ko‘ring.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("❌ Rad etildi")

@dp.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_info(message: Message, state: FSMContext) -> None:
    """
    Handle PUBG nickname and ID input after approval.

    Args:
        message (Message): The incoming message.
        state (FSMContext): The FSM context.
    """
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

async def main() -> None:
    """
    Main function to start the bot polling.
    """
    logger.info("Bot ishga tushmoqda...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
    
def utility_function_example() -> None:
    """
    Example utility function for future use.
    """
    pass
