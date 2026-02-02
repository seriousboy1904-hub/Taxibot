from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from helpers import find_nearest_station
from config import STATIONS, DRIVER_TOKEN
from aiogram import Bot

client_router = Router()
db = Database("taxi.db")
driver_bot = Bot(token=DRIVER_TOKEN)

@client_router.message(Command("start"))
async def start_client(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📱 Kontaktni yuborish", request_contact=True)],
        [KeyboardButton(text="📍 Taksi chaqirish", request_location=True)]
    ], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Avval kontaktni, so'ngra joylashuvni yuboring.", reply_markup=kb)

@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat, c_lon = message.location.latitude, message.location.longitude
    station_name, _ = find_nearest_station(c_lat, c_lon, STATIONS)
    next_driver = db.get_first_driver_in_queue(station_name)
    
    if next_driver:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{message.from_user.id}")]
        ])
        try:
            await driver_bot.send_message(
                next_driver['user_id'],
                f"🚕 Yangi buyurtma!\n📍 Bekat: {station_name}\n👤 Mijoz: {message.from_user.full_name}",
                reply_markup=kb
            )
            await message.answer(f"Sizga eng yaqin bekat: {station_name}. Haydovchiga xabar yuborildi!")
        except:
            await message.answer("Haydovchi bilan bog'lanishda xato.")
    else:
        await message.answer(f"Hozircha {station_name} bekatida bo'sh haydovchi yo'q.")
