from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from helpers import find_nearest_station, get_distance
from database import Database
from config import STATIONS

driver_router = Router()
db = Database("taxi.db")

@driver_router.message(Command("start"))
async def driver_start(message: types.Message):
    await message.answer(
        "Xush kelibsiz! Navbatga turish uchun:\n"
        "1. Joylashuv (Location) tugmasini bosing.\n"
        "2. **'Share My Live Location'** (Jonli joylashuv)ni tanlang.\n"
        "Shundan so'ng siz avtomatik navbatga qo'shilasiz."
    )

@driver_router.edited_message(F.location)
@driver_router.message(F.location)
async def handle_driver_location(message: types.Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    driver_id = message.from_user.id
    
    data = await state.get_data()
    on_trip = data.get("on_trip", False)

    # Bekatni aniqlash
    station_name, dist = find_nearest_station(lat, lon, STATIONS)
    current_station = station_name if dist <= 0.5 else "Yo'lda"
    
    if on_trip:
        # Taksometr qismi: Masofani o'lchash
        total_dist = data.get("total_distance", 0)
        last_lat = data.get("last_lat", lat)
        last_lon = data.get("last_lon", lon)
        
        step = get_distance(last_lat, last_lon, lat, lon)
        if step > 0.01: # 10 metrdan ortiq harakat bo'lsa
            total_dist += step
            await state.update_data(total_distance=total_dist, last_lat=lat, last_lon=lon)
        
        db.update_driver_status(driver_id, lat, lon, current_station, status="busy")
    else:
        # Navbatda turish
        db.update_driver_status(driver_id, lat, lon, current_station, status="idle")

@driver_router.callback_query(F.data.startswith("accept_"))
async def start_taxometer(callback: types.CallbackQuery, state: FSMContext):
    # Safar holatini faollashtirish
    await state.update_data(on_trip=True, total_distance=0, last_lat=None, last_lon=None)
    
    # Bazada statusni 'busy' qilish
    db.update_driver_status(callback.from_user.id, 0, 0, "Safarda", status="busy")
    
    await callback.message.edit_text(callback.message.text + "\n\n✅ **Qabul qilindi. Safar boshlandi.**")
    await callback.answer("Safar boshlandi!")

@driver_router.message(Command("finish"))
async def finish_trip(message: types.Message, state: FSMContext):
    data = await state.get_data()
    
    if data.get("on_trip"):
        dist = data.get("total_distance", 0)
        await message.answer(f"🏁 Safar yakunlandi!\n📏 Umumiy masofa: {dist:.2f} km.\n\nSiz yana bo'sh (idle) holatiga qaytdingiz.")
        
        # Holatni bo'shga qaytarish
        db.update_driver_status(message.from_user.id, 0, 0, "Navbatda", status="idle")
        await state.clear()
    else:
        await message.answer("Siz hozir safarda emassiz.")
