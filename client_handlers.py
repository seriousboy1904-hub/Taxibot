from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from helpers import find_nearest_station
from config import DRIVER_TOKEN, STATIONS
from aiogram import Bot

client_router = Router()
db = Database("taxi.db")
driver_bot_sender = Bot(token=DRIVER_TOKEN)

# 1. Start bosganda telefon so'rash
@client_router.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]
        ],
        resize_keyboard=True
    )
    await message.answer("Xush kelibsiz! Botdan foydalanish uchun telefon raqamingizni yuboring:", reply_markup=kb)

# 2. Kontakt yuborgandan keyin Location so'rash
@client_router.message(F.contact)
async def handle_contact(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Joylashuvni yuborish", request_location=True)]
        ],
        resize_keyboard=True
    )
    await message.answer("Rahmat! Endi taksi chaqirish uchun joylashuvingizni yuboring:", reply_markup=kb)

# 3. Location kelganda haydovchini topish
@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat = message.location.latitude
    c_lon = message.location.longitude
    
    station_name, _ = find_nearest_station(c_lat, c_lon, STATIONS)
    next_driver = db.get_first_driver_in_queue(station_name)
    
    if next_driver:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{message.from_user.id}")]
        ])
        
        await driver_bot_sender.send_message(
            next_driver['user_id'],
            f"🚕 Yangi buyurtma!\n📍 Bekat: {station_name}\n👤 Mijoz: {message.from_user.full_name}",
            reply_markup=kb
        )
        await message.answer(f"Sizga eng yaqin bekat: {station_name}. Haydovchiga xabar yuborildi, kuting...")
    else:
        await message.answer(f"Hozircha {station_name} bekatida bo'sh haydovchilar yo'q. Ozroq kutib qayta urinib ko'ring.")
