"""
PUBG Tournament Bot - Professional Edition
Minimal va kuchli yechim - Flask API bilan birlashgan
Kuchaytirilgan: Ro'yxatdan o'tishdan keyin avtomatik qo'shish va turnir vaqti haqida bildirishnoma
"""

import os
import asyncio
import logging
import json
import random
import re
import csv
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.exceptions import TelegramBadRequest

from flask import Flask, request, jsonify
from flask_cors import CORS
import threading

BOT_TOKEN = "8159939407:AAEBDrIJMUmda8iStU3VYkxEvYiNGiL7PaE"
ADMIN_ID = int(os.getenv("ADMIN_ID", "7337873747"))
SHEET_JSON_CONTENT = os.getenv("SHEET_JSON_CONTENT", "")
REQUIRED_CHANNELS = [ch.strip() for ch in os.getenv("REQUIRED_CHANNELS", "@M24SHaxa_youtube").split(',')]

SHEET_SPREADSHEET_NAME = "Pubg Reyting"
SHEET_WORKSHEET_NAME = "Reyting-bot"
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vS1yzcrcxk4JV6_mymIHCIMB6KLuABaEuu5LvBCc2VuiAxaNa-KtBG-oB5s-AHeACrePlqpJrT4SXJj/pub?output=csv"
RATING_SHEET_LINK = "https://docs.google.com/spreadsheets/d/1T0JuaRetTKusLkR8Kb21Ie87kA2Z4nv3fDJ2ziyuAh4/edit?gid=0#gid=0"

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN bo'lishi kerak!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
MAIN_LOOP = None

tournament_data = {
    'active': False,
    'start_time': None,
    'end_time': None,  # Yangi: Turnir tugash vaqti
    'scheduled_time': None,  # Yangi: Rejalashtirilgan boshlanish vaqti
    'cleanup_task': None,
    'players': [],
    'lobby_id': None,
    'password': None,
    'total_registrations': 0,  # Yangi: Jami ro'yxatdan o'tganlar soni
    'waiting_list': []  # Yangi: Kutish ro'yxati (agar turnir to'la bo'lsa)
}

app = Flask(__name__)
CORS(app)

def connect_to_sheet():
    """Google Sheets API orqali ulanish (agar JSON mavjud bo'lsa)"""
    try:
        if not SHEET_JSON_CONTENT:
            logger.warning("⚠️ SHEET_JSON_CONTENT yo'q, CSV mode ishlatilmoqda")
            return None
            
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(SHEET_JSON_CONTENT), scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_SPREADSHEET_NAME).worksheet(SHEET_WORKSHEET_NAME)
        logger.info("✅ Google Sheets API bilan ulanildi")
        return sheet
    except Exception as e:
        logger.warning(f"⚠️ Google Sheets API xatosi: {e}, CSV mode'ga o'tilmoqda")
        return None

def get_sheet_data_from_csv() -> List[List[str]]:
    """CSV link orqali ma'lumotlarni olish (fallback method)"""
    try:
        logger.info(f"📥 CSV yuklanmoqda: {SHEET_CSV_URL}")
        response = requests.get(SHEET_CSV_URL, timeout=10)
        response.raise_for_status()
        
        lines = response.text.strip().split('\n')
        reader = csv.reader(lines)
        data = list(reader)
        
        logger.info(f"✅ CSV dan {len(data)} qator o'qildi")
        return data
    except Exception as e:
        logger.exception(f"❌ CSV yuklanmadi: {e}")
        return []

def append_to_sheet(nickname: str, pubg_id: str, telegram_id: int) -> bool:
    """O'yinchini sheet'ga qo'shish (Google API yoki CSV)"""
    try:
        sheet = connect_to_sheet()
        
        if sheet:
            sheet.append_row([nickname, pubg_id, telegram_id, datetime.now().isoformat()])  # Yangi: Ro'yxatdan o'tish vaqtini qo'shish
            logger.info(f"✅ Sheet'ga qo'shildi (API): {nickname} | {pubg_id} | {telegram_id}")
            return True
        else:
            logger.warning(f"⚠️ CSV mode - ma'lumot faqat log'da: {nickname} | {pubg_id} | {telegram_id}")
            logger.info("💡 To'liq funksiyani ishlatish uchun SHEET_JSON_CONTENT .env ga qo'shing")
            if not hasattr(append_to_sheet, 'temp_storage'):
                append_to_sheet.temp_storage = []
            append_to_sheet.temp_storage.append([nickname, pubg_id, telegram_id, datetime.now().isoformat()])
            return True
            
    except Exception as e:
        logger.exception("Sheet append xatosi")
        return False

def _get_registered_users_sync() -> List[Dict]:
    """Ro'yxatdagi barcha o'yinchilarni olish"""
    try:
        sheet = connect_to_sheet()
        
        if sheet:
            data = sheet.get_all_values()
            logger.info(f"✅ Google Sheets API dan {len(data)} qator olindi")
        else:
            data = get_sheet_data_from_csv()
            
            if hasattr(append_to_sheet, 'temp_storage'):
                data.extend(append_to_sheet.temp_storage)
                logger.info(f"✅ CSV + temp: {len(data)} qator")
        
        users = []
        for row in data[1:]:  # Skip header
            if len(row) >= 3 and str(row[2]).isdigit():
                users.append({
                    'nickname': row[0],
                    'pubg_id': row[1],
                    'telegram_id': int(row[2]),
                    'registration_time': row[3] if len(row) > 3 else None  # Yangi: Ro'yxat vaqti
                })
        
        logger.info(f"✅ Jami {len(users)} o'yinchi topildi")
        return users
    except Exception as e:
        logger.exception("get_registered_users xatosi")
        return []

async def get_registered_users() -> List[Dict]:
    """Async wrapper for getting users"""
    return await asyncio.to_thread(_get_registered_users_sync)

def _clear_sheet_data_sync():
    """Sheet ma'lumotlarini tozalash"""
    try:
        sheet = connect_to_sheet()
        
        if sheet:
            all_rows = sheet.get_all_values()
            if len(all_rows) > 1:
                sheet.delete_rows(2, len(all_rows))
            logger.info("✅ Sheet tozalandi (API)")
        else:
            if hasattr(append_to_sheet, 'temp_storage'):
                append_to_sheet.temp_storage.clear()
            logger.info("✅ Temp storage tozalandi (CSV mode)")
        
        return True
    except Exception as e:
        logger.exception("clear_sheet_data xatosi")
        return False

async def clear_sheet_data():
    """Async wrapper for clearing data"""
    return await asyncio.to_thread(_clear_sheet_data_sync)

def parse_player_info(text: str) -> Dict[str, str]:
    """
    Smart parser - har qanday formatda nickname va ID ajratadi
    
    Qabul qilinadigan formatlar:
    - "ShadowKiller 5123456789"
    - "Pro Gamer, 5987654321"
    - "Nickname: ProPlayer, ID: 5456789123"
    - "ProGamer\n5789123456"
    """
    text = text.strip()
    
    pattern1 = r'^(.+?)\s+([5]\d{9})$'
    match = re.match(pattern1, text)
    if match:
        return {
            'nickname': match.group(1).strip(),
            'pubg_id': match.group(2)
        }
    
    id_pattern = r'[5]\d{9}'
    id_match = re.search(id_pattern, text)
    if id_match:
        pubg_id = id_match.group()
        nickname = text.replace(pubg_id, '').strip()
        nickname = re.sub(r'[,:\n\t]+', ' ', nickname).strip()
        if nickname:
            return {'nickname': nickname, 'pubg_id': pubg_id}
    
    for sep in [',', '\n', ':']:
        if sep in text:
            parts = [p.strip() for p in text.split(sep) if p.strip()]
            if len(parts) >= 2:
                for i, part in enumerate(parts):
                    if re.match(r'^[5]\d{9}$', part):
                        other_parts = [p for j, p in enumerate(parts) if j != i]
                        return {'nickname': ' '.join(other_parts), 'pubg_id': part}
    
    parts = text.split()
    if len(parts) >= 2:
        return {'nickname': ' '.join(parts[:-1]), 'pubg_id': parts[-1]}
    
    return {'nickname': text, 'pubg_id': 'NOT_PROVIDED'}

async def start_tournament(scheduled_time: Optional[datetime] = None):
    """Turnirni boshlash va 24h timer o'rnatish, rejalashtirilgan vaqt bilan"""
    tournament_data['active'] = True
    tournament_data['start_time'] = datetime.now()
    tournament_data['scheduled_time'] = scheduled_time or (datetime.now() + timedelta(hours=1))  # Default 1 soat keyin
    
    tournament_data['end_time'] = tournament_data['scheduled_time'] + timedelta(hours=24)
    
    if tournament_data['cleanup_task']:
        tournament_data['cleanup_task'].cancel()
    
    tournament_data['cleanup_task'] = asyncio.create_task(auto_cleanup_tournament())
    logger.info(f"🏁 Turnir boshlandi, boshlanish vaqti: {tournament_data['scheduled_time']}, 24 soatlik timer o'rnatildi")

async def auto_cleanup_tournament():
    """Turnir tugash vaqtiga qadar kutish va avtomatik tozalash"""
    if tournament_data['end_time']:
        wait_seconds = (tournament_data['end_time'] - datetime.now()).total_seconds()
        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)
    else:
        await asyncio.sleep(24 * 60 * 60)  # Fallback 24 hours
    
    logger.info("⏰ Turnir vaqti tugadi, avtomatik tozalash...")
    await end_tournament(auto=True)

async def end_tournament(auto=False):
    """Turnirni yakunlash va ma'lumotlarni tozalash"""
    await clear_sheet_data()
    
    tournament_data['active'] = False
    tournament_data['start_time'] = None
    tournament_data['end_time'] = None
    tournament_data['scheduled_time'] = None
    tournament_data['lobby_id'] = None
    tournament_data['password'] = None
    tournament_data['players'] = []
    tournament_data['total_registrations'] = 0
    tournament_data['waiting_list'] = []
    
    if tournament_data['cleanup_task']:
        tournament_data['cleanup_task'].cancel()
        tournament_data['cleanup_task'] = None
    
    message = "⏰ Turnir avtomatik yakunlandi (vaqt tugadi)" if auto else "✅ Turnir yakunlandi"
    try:
        await bot.send_message(ADMIN_ID, message)
    except:
        pass
    
    logger.info(f"🏁 Turnir yakunlandi (auto={auto})")

def execute_on_main_loop(coro):
    """Async funktsiyani asosiy loopda ishlatish"""
    if MAIN_LOOP and MAIN_LOOP.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, MAIN_LOOP)
        return future.result()
    else:
        logger.error("Main loop is not running!")
        raise RuntimeError("Main loop is not running")

@app.route('/api/get_players', methods=['GET'])
def api_get_players():
    """O'yinchilar ro'yxatini olish"""
    try:
        users = execute_on_main_loop(get_registered_users())
        return jsonify({
            'success': True,
            'players': users,
            'tournament_active': tournament_data['active'],
            'tournament_start': tournament_data['start_time'].isoformat() if tournament_data['start_time'] else None,
            'tournament_scheduled': tournament_data['scheduled_time'].isoformat() if tournament_data['scheduled_time'] else None,
            'tournament_end': tournament_data['end_time'].isoformat() if tournament_data['end_time'] else None,
            'total_registrations': tournament_data['total_registrations'],
            'waiting_list_count': len(tournament_data['waiting_list']),
            'data_source': 'Google Sheets API' if connect_to_sheet() else 'CSV + Temp Storage'
        })
    except Exception as e:
        logger.exception("api_get_players xatosi")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/send_lobby', methods=['POST'])
def api_send_lobby():
    """Tanlangan o'yinchilarga lobby yuborish"""
    try:
        data = request.json
        lobby_id = data.get('lobby_id', '').strip()
        password = data.get('password', '').strip()
        players = data.get('players', [])
        
        if not re.match(r'^\d{7}$', lobby_id):
            return jsonify({'success': False, 'error': 'Lobby ID 7 ta raqamdan iborat bo\'lishi kerak'}), 400
        
        if len(password) < 4:
            return jsonify({'success': False, 'error': 'Parol kamida 4 ta belgidan iborat bo\'lishi kerak'}), 400
        
        if len(players) < 2:
            return jsonify({'success': False, 'error': 'Kamida 2 ta o\'yinchi kerak'}), 400
        
        execute_on_main_loop(start_tournament())
        
        tournament_data['lobby_id'] = lobby_id
        tournament_data['password'] = password
        tournament_data['players'] = players
        
        sent_count = 0
        failed_users = []
        
        async def send_messages():
            nonlocal sent_count, failed_users
            for player in players:
                try:
                    others = [p for p in players if p['telegram_id'] != player['telegram_id']]
                    opponents = ", ".join([p['nickname'] for p in others])
                    
                    text = (
                        f"🎮 <b>YANGI O'YIN BOSHLANDI!</b>\n\n"
                        f"👥 <b>Raqiblaringiz:</b>\n{opponents}\n\n"
                        f"🆔 <b>Lobby ID:</b> <code>{lobby_id}</code>\n"
                        f"🔐 <b>Parol:</b> <code>{password}</code>\n\n"
                        f"⏰ Tezroq o'yinga kiring!\n"
                        f"🏆 Omad tilaymiz!"
                    )
                    
                    await bot.send_message(player['telegram_id'], text)
                    sent_count += 1
                    await asyncio.sleep(0.1)
                except Exception as e:
                    logger.warning(f"Failed to send to {player['telegram_id']}: {e}")
                    failed_users.append(player['nickname'])
        
        execute_on_main_loop(send_messages())
        
        return jsonify({
            'success': True,
            'sent_count': sent_count,
            'total': len(players),
            'failed': failed_users
        })
        
    except Exception as e:
        logger.exception("api_send_lobby xatosi")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/schedule_tournament', methods=['POST'])
def api_schedule_tournament():
    """Turnirni rejalashtirish (yangi endpoint)"""
    try:
        data = request.json
        scheduled_time_str = data.get('scheduled_time')  # Format: 'YYYY-MM-DD HH:MM'
        
        if not scheduled_time_str:
            return jsonify({'success': False, 'error': 'Rejalashtirilgan vaqt kerak'}), 400
        
        try:
            scheduled_time = datetime.strptime(scheduled_time_str, '%Y-%m-%d %H:%M')
            if scheduled_time < datetime.now():
                return jsonify({'success': False, 'error': 'Vaqt o\'tmishda bo\'lmasligi kerak'}), 400
        except ValueError:
            return jsonify({'success': False, 'error': 'Vaqt formati noto\'g\'ri (YYYY-MM-DD HH:MM)'}), 400
        
        execute_on_main_loop(start_tournament(scheduled_time))
        
        return jsonify({
            'success': True,
            'scheduled_time': scheduled_time.isoformat(),
            'message': 'Turnir rejalashtirildi va barcha foydalanuvchilarga bildirishnoma yuborildi'
        })
    except Exception as e:
        logger.exception("api_schedule_tournament xatosi")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/end_tournament', methods=['POST'])
def api_end_tournament():
    """Turnirni yakunlash"""
    try:
        execute_on_main_loop(end_tournament(auto=False))
        return jsonify({'success': True, 'message': 'Turnir yakunlandi'})
    except Exception as e:
        logger.exception("api_end_tournament xatosi")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def api_health():
    """Health check"""
    return jsonify({
        'status': 'ok',
        'bot_running': True,
        'tournament_active': tournament_data['active'],
        'data_source': 'Google Sheets API' if connect_to_sheet() else 'CSV + Temp Storage'
    })

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
            InlineKeyboardButton(text="🎮 Mening o'yinlarim", callback_data="my_games"),
            InlineKeyboardButton(text="📮 Admin", callback_data="contact_admin")
        ]
    ]
)

def get_subscription_keyboard():
    inline_keyboard = []
    for i, channel in enumerate(REQUIRED_CHANNELS, 1):
        channel_name = channel.lstrip('@')
        text = f"📢 Kanal {i}" if len(REQUIRED_CHANNELS) > 1 else "📢 Kanal"
        inline_keyboard.append([InlineKeyboardButton(text=text, url=f"https://t.me/{channel_name}")])
    inline_keyboard.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="check_subscription")])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def approve_buttons(user_id: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ To'g'ri", callback_data=f"approve:{user_id}"),
            InlineKeyboardButton(text="❌ Noto'g'ri", callback_data=f"reject:{user_id}")
        ]]
    )

async def check_subscription(user_id: int) -> bool:
    """Kanal obunasini tekshirish"""
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "creator", "administrator"):
                return False
        except Exception as e:
            logger.warning(f"Subscription check xatosi {channel}: {e}")
            return False
    return True

class SubscriptionMiddleware:
    async def __call__(self, handler, event, data):
        allowed_commands = ["/start", "/help"]
        allowed_callbacks = ["check_subscription"]
        
        if isinstance(event, Message):
            if event.text and any(event.text.startswith(cmd) for cmd in allowed_commands):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            if event.data in allowed_callbacks:
                return await handler(event, data)
        
        user_id = event.from_user.id
        
        if user_id == ADMIN_ID:
            return await handler(event, data)
        
        if not await check_subscription(user_id):
            text = "❌ Botdan foydalanish uchun kanallarga obuna bo'ling."
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

@router.message(Command("start"))
async def start_handler(message: Message):
    if await check_subscription(message.from_user.id):
        await message.answer(
            "👋 <b>ASSALOMU ALAYKUM</b>\n"
            "🎮 TDM TOURNAMENT BOT'GA Xush kelibsiz!\n\n"
            "⚠️ Turnir <b>pullik</b>\n"
            "<b>💸 NARXI – 10 000 SO'M 💸</b>",
            reply_markup=inline_main_buttons
        )
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\n"
            "Botdan foydalanish uchun kanallarga obuna bo'ling 👇",
            reply_markup=get_subscription_keyboard()
        )

@router.callback_query(F.data == "check_subscription")
async def check_subscription_callback(call: CallbackQuery):
    if await check_subscription(call.from_user.id):
        await call.message.edit_text("✅ Obuna tasdiqlandi!", reply_markup=inline_main_buttons)
    else:
        await call.message.edit_text(
            "❌ Hali obuna bo'lmagansiz.\nObuna bo'ling va qayta tekshiring 👇",
            reply_markup=get_subscription_keyboard()
        )
    await call.answer()

@router.callback_query(F.data == "register")
async def register_callback(call: CallbackQuery, state: FSMContext):
    text = (
        "💳 <b>To'lov ma'lumotlari:</b>\n\n"
        "💳 Karta: HUMO\n"
        "💳 Raqam: <code>9860 6004 1512 3691</code>\n\n"
        "📌 To'lovni amalga oshirib, 5 sekunddan keyin CHECK yuboring."
    )
    await call.message.answer(text)
    await asyncio.sleep(5)  # 5 sekundlik kechikish
    await call.message.answer("🕐 Endi to'lov chekini yuboring (rasm yoki hujjat sifatida).")
    await state.set_state(RegistrationState.waiting_for_payment_check)
    await call.answer()

@router.callback_query(F.data == "results")
async def results_callback(call: CallbackQuery):
    try:
        users = await get_registered_users()
        
        if len(users) == 0:
            text = "📊 Reytinglar hali mavjud emas.\n\n"
        else:
            text = "🏆 <b>Top 20:</b>\n\n"
            for idx, user in enumerate(users[:20], 1):
                text += f"{idx}. <b>{user['nickname']}</b> ({user['pubg_id']})\n"
            text += "\n"
        
        text += f"📋 To'liq reyting:\n{RATING_SHEET_LINK}\n\n"
        text += f"📊 CSV link:\n{SHEET_CSV_URL}"
        await call.message.answer(text, disable_web_page_preview=True)
    except:
        await call.message.answer("⚠️ Xatolik")
    await call.answer()

@router.callback_query(F.data == "my_games")
async def my_games_callback(call: CallbackQuery):
    if tournament_data['active'] and call.from_user.id in [p['telegram_id'] for p in tournament_data['players']]:
        text = (
            f"🎮 <b>Faol O'yin:</b>\n\n"
            f"🆔 Lobby: <code>{tournament_data['lobby_id']}</code>\n"
            f"🔐 Parol: <code>{tournament_data['password']}</code>\n\n"
            f"⏰ Boshlanish: {tournament_data['scheduled_time'].strftime('%Y-%m-%d %H:%M') if tournament_data['scheduled_time'] else 'Tez orada'}\n"
            f"🏁 Tugash: {tournament_data['end_time'].strftime('%Y-%m-%d %H:%M') if tournament_data['end_time'] else '24 soat ichida'}"
        )
    else:
        text = "🎮 Sizda faol o'yin yo'q."
    await call.message.answer(text)
    await call.answer()

@router.callback_query(F.data == "contact_admin")
async def contact_admin_callback(call: CallbackQuery):
    await call.message.answer("📩 Admin: @m24_shaxa_yt")
    await call.answer()

@router.message(RegistrationState.waiting_for_payment_check, F.photo | F.document)
async def handle_payment_check(message: Message, state: FSMContext):
    await message.answer("🕐 Chekingiz tekshirilmoqda...")
    
    caption = (
        f"💳 Yangi to'lov:\n"
        f"👤 {message.from_user.full_name}\n"
        f"🆔 <code>{message.from_user.id}</code>\n"
        f"📌 @{message.from_user.username or 'username yo\'q'}"
    )
    
    try:
        if message.photo:
            await bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption, reply_markup=approve_buttons(message.from_user.id))
        elif message.document:
            await bot.send_document(ADMIN_ID, message.document.file_id, caption=caption, reply_markup=approve_buttons(message.from_user.id))
        
        await state.set_state(RegistrationState.waiting_for_admin_approval)
    except Exception as e:
        logger.exception("Admin'ga yuborishda xato")
        await message.answer("⚠️ Xatolik, qayta urinib ko'ring.")
        await state.clear()

@router.callback_query(F.data.startswith("approve:"))
async def approve_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz", show_alert=True)
        return
    
    user_id = int(call.data.split(":")[1])
    
    await bot.send_message(
        user_id,
        "✅ To'lov tasdiqlandi!\n\n"
        "📝 Endi PUBG nickname va ID yuboring.\n\n"
        "<b>Format:</b>\n"
        "ShadowKiller 5123456789\n\n"
        "⚠️ ID 10 ta raqam (5 bilan boshlanadi)"
    )
    
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, RegistrationState.waiting_for_pubg_nick)
    
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("✅ Tasdiqlandi")

@router.callback_query(F.data.startswith("reject:"))
async def reject_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz", show_alert=True)
        return
    
    user_id = int(call.data.split(":")[1])
    
    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    await dp.storage.set_state(key, None)
    
    await bot.send_message(user_id, "❌ To'lov rad etildi. Qayta urinib ko'ring.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("❌ Rad etildi")

@router.message(RegistrationState.waiting_for_pubg_nick)
async def handle_pubg_info(message: Message, state: FSMContext):
    parsed = parse_player_info(message.text or "")
    nickname = parsed['nickname'] or message.from_user.full_name
    pubg_id = parsed['pubg_id']
    
    if not re.match(r'^[5]\d{9}$', pubg_id):
        await message.answer(
            "⚠️ <b>PUBG ID noto'g'ri!</b>\n\n"
            "ID 10 ta raqam, 5 bilan boshlanishi kerak.\n"
            "Masalan: 5123456789\n\n"
            "Qayta yuboring:"
        )
        return
    
    # Kuchaytirilgan: Avtomatik qo'shish va turnir vaqti haqida bildirishnoma
    success = await asyncio.to_thread(append_to_sheet, nickname, pubg_id, message.from_user.id)
    
    if success:
        tournament_data['total_registrations'] += 1
        
        # Agar turnir faol bo'lsa, o'yinchini players ga qo'shish
        if tournament_data['active']:
            new_player = {
                'nickname': nickname,
                'pubg_id': pubg_id,
                'telegram_id': message.from_user.id,
                'registration_time': datetime.now().isoformat()
            }
            if len(tournament_data['players']) < 100:  # Masalan, maks 100 o'yinchi
                tournament_data['players'].append(new_player)
                logger.info(f"✅ Yangi o'yinchi turnirga qo'shildi: {nickname}")
            else:
                tournament_data['waiting_list'].append(new_player)
                logger.info(f"📋 Yangi o'yinchi kutish ro'yxatiga qo'shildi: {nickname}")
        
        # Turnir vaqti haqida bildirishnoma
        tournament_info = ""
        if tournament_data['active']:
            scheduled_str = tournament_data['scheduled_time'].strftime('%Y-%m-%d %H:%M') if tournament_data['scheduled_time'] else "Tez orada"
            end_str = tournament_data['end_time'].strftime('%Y-%m-%d %H:%M') if tournament_data['end_time'] else "24 soat ichida"
            position = len(tournament_data['players']) if message.from_user.id in [p['telegram_id'] for p in tournament_data['players']] else f"Kutish ro'yxatida: {len(tournament_data['waiting_list'])}"
            
            tournament_info = (
                f"\n\n🎮 <b>Turnir Ma'lumotlari:</b>\n"
                f"⏰ Boshlanish vaqti: {scheduled_str}\n"
                f"🏁 Tugash vaqti: {end_str}\n"
                f"👥 Jami qatnashchilar: {tournament_data['total_registrations']}\n"
                f"📍 Sizning holatingiz: {position}\n\n"
                f"⚠️ Turnir boshlanishidan oldin tayyor bo'ling!\n"
                f"🏆 G'olib bo'lishingizga omad!"
            )
        else:
            tournament_info = "\n\n🎮 Turnir hali boshlanmagan. Admin sizga xabar beradi!"
        
        await message.answer(
            f"✅ <b>Ro'yxatdan o'tdingiz!</b>\n\n"
            f"👤 Nickname: <b>{nickname}</b>\n"
            f"🆔 PUBG ID: <code>{pubg_id}</code>\n"
            f"🆔 Telegram ID: <code>{message.from_user.id}</code>\n"
            f"📅 Ro'yxat vaqti: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"{tournament_info}",
            reply_markup=inline_main_buttons
        )
        
        try:
            await bot.send_message(
                ADMIN_ID,
                f"✅ Yangi qatnashchi:\n"
                f"👤 {message.from_user.full_name}\n"
                f"🎮 {nickname}\n"
                f"🆔 PUBG ID: {pubg_id}\n"
                f"🆔 TG ID: {message.from_user.id}\n"
                f"📅 Vaqt: {datetime.now().isoformat()}\n"
                f"👥 Jami: {tournament_data['total_registrations']}"
            )
        except:
            pass
    else:
        await message.answer("⚠️ Xatolik. Admin bilan bog'laning.")
    
    await state.clear()

@router.message(Command("admin_status"))
async def admin_status(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    users = await get_registered_users()
    
    status = (
        f"📊 <b>Bot Status:</b>\n\n"
        f"👥 O'yinchilar: {len(users)}\n"
        f"🎮 Turnir: {'✅ Faol' if tournament_data['active'] else '❌ Faol emas'}\n"
    )
    
    if tournament_data['active'] and tournament_data['start_time']:
        elapsed = datetime.now() - tournament_data['start_time']
        remaining = timedelta(hours=24) - elapsed
        hours = remaining.seconds // 3600
        minutes = (remaining.seconds % 3600) // 60
        status += f"⏰ Qolgan: {hours}s {minutes}d\n"
    
    await message.answer(status)

@router.message(Command("end_tournament"))
async def admin_end_tournament(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    
    await end_tournament(auto=False)
    await message.answer("✅ Turnir yakunlandi va tozalandi")

@router.message(Command("help"))
async def help_handler(message: Message):
    """Bot haqida yordam"""
    text = (
        "📚 <b>Bot Komandalari:</b>\n\n"
        "/start - Botni ishga tushirish\n"
        "/help - Yordam\n"
        "/admin_status - Admin uchun status (faqat admin)\n"
        "/end_tournament - Turnirni yakunlash (faqat admin)\n"
        "/rules - Turnir qoidalari\n"
        "/faq - Tez-tez so'raladigan savollar\n"
        "/profile - Foydalanuvchi profili\n\n"
        "Inline tugmalar orqali ro'yxatdan o'ting va natijalarni ko'ring!"
    )
    await message.answer(text)

@router.message(Command("rules"))
async def rules_handler(message: Message):
    """Turnir qoidalari"""
    text = (
        "📜 <b>Turnir Qoidalari:</b>\n\n"
        "1. Turnir pullik: 10 000 so'm.\n"
        "2. PUBG ID 5 bilan boshlanadigan 10 raqam bo'lishi kerak.\n"
        "3. Cheating taqiqlangan.\n"
        "4. 24 soat ichida turnir yakunlanadi.\n"
        "5. Admin qarori qaytarilmaydi.\n\n"
        "Qo'shimcha savollar uchun: /faq"
    )
    await message.answer(text)

@router.message(Command("faq"))
async def faq_handler(message: Message):
    """Tez-tez so'raladigan savollar"""
    text = (
        "❓ <b>FAQ:</b>\n\n"
        "Savol: To'lov qanday amalga oshiriladi?\n"
        "Javob: HUMO karta orqali: 9860 6004 1512 3691\n\n"
        "Savol: Qancha vaqt kutish kerak?\n"
        "Javob: Turnir boshlanishi admin tomonidan belgilanadi.\n\n"
        "Savol: Nickname o'zgartirsa bo'ladimi?\n"
        "Javob: Ro'yxatdan o'tganingizdan keyin admin orqali."
    )
    await message.answer(text)

@router.message(Command("profile"))
async def profile_handler(message: Message):
    """Foydalanuvchi profili"""
    users = await get_registered_users()
    user_id = message.from_user.id
    user = next((u for u in users if u['telegram_id'] == user_id), None)
    
    if user:
        text = (
            f"👤 <b>Sizning Profiliz:</b>\n\n"
            f"Nickname: {user['nickname']}\n"
            f"PUBG ID: {user['pubg_id']}\n"
            f"Telegram ID: {user_id}\n"
            f"📅 Ro'yxat vaqti: {user['registration_time'] or 'Aniqlanmagan'}\n\n"
            f"🎮 Faol turnir: {'Ha' if tournament_data['active'] else 'Yo\'q'}"
        )
    else:
        text = "⚠️ Siz hali ro'yxatdan o'tmagansiz. /start orqali boshlang."
    
    await message.answer(text)

def run_flask():
    """Flask server'ni alohida thread'da ishga tushirish"""
    logger.info("🌐 Flask API Server ishga tushmoqda...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False, use_evalex=False)

async def main():
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    dp.include_router(router)
    logger.info("🚀 Bot ishga tushmoqda...")
    
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask API Server ishga tushdi (port 5000)")
    
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())