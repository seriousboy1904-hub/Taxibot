from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command # /finish buyrug'i uchun kerak
from helpers import find_nearest_station, get_distance
from database import Database
from config import STATIONS

driver_router = Router()
db = Database("taxi.db")

# 1. HAYDOVCHI LIVE LOCATION YUBORGANDA (Navbat tizimi)
@driver_router.edited_message(F.location)
async def handle_driver_live_location(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    driver_id = message.from_user.id
    
    # Haydovchining hozirgi holatini (FSM xotirasidan) olamiz
    data = await state.get_data()
    on_trip = data.get("on_trip", False)

    # Eng yaqin bekatni aniqlash
    station_name, dist = find_nearest_station(lat, lon, STATIONS)
    current_station = station_name if dist <= 0.5 else "Yo'lda"
    
    # AGAR HAYDOVCHI SAFARDA BO'LSA (Taksometr qismi)
    if on_trip:
        total_dist = data.get("total_distance", 0)
        last_lat = data.get("last_lat", lat)
        last_lon = data.get("last_lon", lon)
        
        # Masofani hisoblash
        step = get_distance(last_lat, last_lon, lat, lon)
        if step > 0.01: # 10 metrdan ortiq siljish bo'lsa hisobga oladi
            total_dist += step
            
        await state.update_data(total_distance=total_dist, last_lat=lat, last_lon=lon)
        # Bazada faqat joylashuvni yangilaymiz, status 'busy'ligicha qoladi
        db.update_driver_status(driver_id, lat, lon, current_station, status="busy")
    else:
        # AGAR HAYDOVCHI BO'SH BO'LSA
        db.update_driver_status(driver_id, lat, lon, current_station, status="idle")

# 2. HAYDOVCHI BUYURTMANI QABUL QILGANDA
@driver_router.callback_query(F.data.startswith("accept_"))
async def start_taxometer(callback: types.CallbackQuery, state: FSMContext):
    # Safar ma'lumotlarini nolga tushiramiz
    await state.update_data(on_trip=True, total_distance=0, last_lat=None, last_lon=None)
    
    # Statusni 'busy' (band) qilamiz
    db.update_driver_status(callback.from_user.id, 0, 0, "Safarda", status="busy")
    
    await callback.message.answer("🚖 Safar boshlandi. Taksometr masofani o'lchamoqda.")
    await callback.answer()

# 3. SAFAR YAKUNI (Siz so'ragan qism)
@driver_router.message(Command("finish"))
async def finish_trip(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    # Agar haydovchi haqiqatda safarda bo'lsa
    if data.get("on_trip"):
        dist = data.get("total_distance", 0)
        
        # Yakuniy hisobot
        await message.answer(f"🏁 Safar tugadi!\n📏 Masofa: {dist:.2f} km.\n\nSiz yana bo'sh (idle) holatiga qaytdingiz va navbatga qo'shildingiz.")
        
        # Statusni 'idle'ga qaytarib, bazani yangilaymiz
        db.update_driver_status(message.from_user.id, data.get("last_lat"), data.get("last_lon"), "Bekatda", status="idle")
        
        # Xotirani tozalaymiz
        await state.clear()
    else:
        await message.answer("Siz hozir safarda emassiz.")
