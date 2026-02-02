from aiogram import Router, F, types
from aiogram import Bot
from database import Database
from helpers import find_nearest_station
from config import DRIVER_TOKEN, STATIONS

client_router = Router()
db = Database("taxi.db")

driver_bot = Bot(token=DRIVER_TOKEN)

@client_router.message(F.location)
async def handle_client_order(message: types.Message):
    c_lat = message.location.latitude
    c_lon = message.location.longitude

    station_name, distance = find_nearest_station(c_lat, c_lon, STATIONS)
    driver = db.get_first_driver_in_queue(station_name)

    if driver:
        await driver_bot.send_message(
            driver["user_id"],
            (
                "🚕 YANGI BUYURTMA\n"
                f"📍 Bekat: {station_name}\n"
                f"📏 Masofa: {round(distance, 2)}\n"
                f"👤 Mijoz: {message.from_user.full_name}\n"
                f"📌 Lokatsiya: {c_lat}, {c_lon}"
            )
        )

        await message.answer(
            f"✅ Buyurtma qabul qilindi\n"
            f"📍 Bekat: {station_name}\n"
            "🚗 Haydovchi yo‘lda"
        )
    else:
        await message.answer(
            "⛔ Hozircha bo‘sh haydovchi yo‘q\n"
            "⏳ Iltimos kuting"
        )