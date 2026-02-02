from aiogram import Router, F, types, Bot
from database import Database
from helpers import find_nearest_station
from config import DRIVER_TOKEN, STATIONS
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

client_router = Router()
db = Database("taxi.db")
driver_bot_sender = Bot(token=DRIVER_TOKEN)

@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat = message.location.latitude
    c_lon = message.location.longitude
    
    station_name, dist = find_nearest_station(c_lat, c_lon, STATIONS)
    
    # Navbatdagi bo'sh haydovchini olish
    next_driver = db.get_first_driver_in_queue(station_name)
    
    if next_driver:
        # Haydovchi uchun tugmalar
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{message.from_user.id}"),
                InlineKeyboardButton(text="❌ Skip (O'tkazish)", callback_data=f"reject_{message.from_user.id}")
            ]
        ])
        
        # Haydovchiga xabar
        await driver_bot_sender.send_message(
            next_driver[0], # user_id
            f"🚕 **Yangi buyurtma!**\n\n📍 Bekat: {station_name}\n👤 Mijoz: {message.from_user.full_name}\n\nQabul qilasizmi?",
            parse_mode="Markdown",
            reply_markup=kb
        )
        await message.answer(f"📍 Sizga eng yaqin bekat: **{station_name}**\n⏳ So'rov haydovchiga yuborildi, javobni kuting...", parse_mode="Markdown")
    else:
        await message.answer(f"📍 Sizga eng yaqin bekat: {station_name}\n😔 Afsuski, hozircha bu bekatda bo'sh haydovchi yo'q.")
