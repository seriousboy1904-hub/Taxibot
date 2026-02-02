from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from helpers import find_nearest_station, get_distance
from database import Database
from config import STATIONS
import logging

driver_router = Router()
db = Database("taxi.db")

# Anketa uchun holatlar
class DriverReg(StatesGroup):
    waiting_for_name = State()

# --- 1. START VA ANKETA ---
@driver_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    # Haydovchi bazada bormi?
    await message.answer("Xush kelibsiz! Haydovchi botdan foydalanish uchun ismingizni kiriting:")
    await state.set_state(DriverReg.waiting_for_name)

@driver_router.message(DriverReg.waiting_for_name)
async def process_name(message: types.Message, state: FSMContext):
    full_name = message.text
    # Bazada foydalanuvchini yaratish (oddiygina)
    # database.py dagi update_driver_status ni moslashtiramiz
    await message.answer(f"Rahmat, {full_name}! Endi navbatga turish uchun 'Live Location' (Jonli joylashuv) yuboring.")
    await state.clear()

# --- 2. NAVBATGA OLISH (LIVE LOCATION) ---
@driver_router.edited_message(F.location)
async def handle_driver_live_location(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    driver_id = message.from_user.id
    
    # Eng yaqin bekatni aniqlash
    station_name, dist = find_nearest_station(lat, lon, STATIONS)
    
    # 0.5 km (500 metr) ichida bo'lsa bekatga biriktiramiz
    current_station = station_name if dist <= 0.5 else "Yo'lda"
    
    data = await state.get_data()
    on_trip = data.get("on_trip", False)

    if not on_trip:
        if current_station != "Yo'lda":
            # NAVBATGA QO'SHISH (Bazaga yozish)
            db.update_driver_status(driver_id, lat, lon, current_station, status="idle")
            logging.info(f"Haydovchi {driver_id} {current_station} bekatida navbatga turdi.")
        else:
            # Bekatdan uzoqlashsa statusni o'zgartirish (ixtiyoriy)
            db.update_driver_status(driver_id, lat, lon, "Yo'lda", status="off_duty")
