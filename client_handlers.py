from aiogram import Router, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import Database
from helpers import find_nearest_station
from config import DRIVER_TOKEN, STATIONS
from aiogram import Bot

client_router = Router()
db = Database("taxi.db")
# Haydovchi bot orqali xabar yuborish uchun bot obyekti
driver_bot_sender = Bot(token=DRIVER_TOKEN)

@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat = message.location.latitude
    c_lon = message.location.longitude
    
    # Mijozga eng yaqin bekatni aniqlash
    station_name, _ = find_nearest_station(c_lat, c_lon, STATIONS)
    
    # Bazadan ushbu bekatdagi navbatda turgan bo'sh haydovchini olish
    next_driver = db.get_first_driver_in_queue(station_name)
    
    if next_driver:
        # Haydovchiga yuboriladigan tugma
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{message.from_user.id}")]
        ])
        
        try:
            await driver_bot_sender.send_message(
                next_driver['user_id'],
                f"🚕 Yangi buyurtma!\n📍 Bekat: {station_name}\n👤 Mijoz: {message.from_user.full_name}",
                reply_markup=kb
            )
            await message.answer(f"Sizga eng yaqin bekat: {station_name}. Haydovchiga so'rov yuborildi!")
        except Exception:
            await message.answer("Haydovchi bilan bog'lanishda texnik xatolik yuz berdi.")
    else:
        await message.answer(f"Hozircha {station_name} bekatida bo'sh haydovchilar yo'q.")
