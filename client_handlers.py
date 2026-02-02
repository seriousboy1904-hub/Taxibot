from aiogram import Router, F, types
from database import Database
from helpers import find_nearest_station
from config import DRIVER_TOKEN
from aiogram import Bot

client_router = Router()
db = Database("taxi.db")
# Haydovchiga xabar yuborish uchun Driver Bot obyektini yaratamiz
driver_bot_sender = Bot(token=DRIVER_TOKEN)

@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat = message.location.latitude
    c_lon = message.location.longitude
    
    # 1. Mijozga eng yaqin bekatni topamiz
    from config import STATIONS
    station_name, _ = find_nearest_station(c_lat, c_lon, STATIONS)
    
    # 2. Bazadan shu bekatdagi navbatdagi bo'sh haydovchini olamiz
    next_driver = db.get_first_driver_in_queue(station_name)
    
    if next_driver:
        # Haydovchi botiga xabar yuboramiz
        await driver_bot_sender.send_message(
            next_driver['user_id'],
            f"🚕 Navbat bo'yicha buyurtma!\n📍 Bekat: {station_name}\n👤 Mijoz: {message.from_user.full_name}"
        )
        await message.answer(f"Sizga eng yaqin bekat: {station_name}. Haydovchi yo'lga chiqdi!")
    else:
        await message.answer("Hozircha bu bekatda bo'sh haydovchilar yo'q.")
