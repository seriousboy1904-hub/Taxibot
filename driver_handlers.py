from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from helpers import find_nearest_station, get_distance
from database import Database
from config import STATIONS

driver_router = Router()
db = Database("taxi.db")

@driver_router.message(Command("start"))
async def start_driver(message: types.Message):
    await message.answer("Salom haydovchi! Navbatga turish uchun **Live Location** yuboring.")

# Ham yangi (message), ham o'zgargan (edited_message) locationni eshitamiz
@driver_router.message(F.location)
@driver_router.edited_message(F.location)
async def handle_driver_loc(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    driver_id = message.from_user.id
    
    station_name, dist = find_nearest_station(lat, lon, STATIONS)
    # 600 metrdan yaqin bo'lsa bekatda, aks holda "Yo'lda"
    current_station = station_name if dist <= 0.6 else "Yo'lda"
    
    data = await state.get_data()
    if data.get("on_trip"):
        # Taksometr mantiqi (Sizning kodingizdan)
        total_dist = data.get("total_distance", 0)
        last_lat = data.get("last_lat", lat)
        last_lon = data.get("last_lon", lon)
        step = get_distance(last_lat, last_lon, lat, lon)
        
        if step > 0.01:
            total_dist += step
            await state.update_data(total_distance=total_dist, last_lat=lat, last_lon=lon)
        db.update_driver_status(driver_id, lat, lon, "Safarda", status="busy")
    else:
        # Navbatga qo'shish
        db.update_driver_status(driver_id, lat, lon, current_station, status="idle")

@driver_router.callback_query(F.data.startswith("accept_"))
async def accept_order(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(on_trip=True, total_distance=0, last_lat=None, last_lon=None)
    db.update_driver_status(call.from_user.id, 0, 0, "Safarda", status="busy")
    await call.message.edit_text(call.message.text + "\n\n✅ Qabul qilindi. Safar boshlandi.")
    await call.answer()

@driver_router.message(Command("finish"))
async def finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("on_trip"):
        await message.answer(f"🏁 Safar tugadi. Masofa: {data.get('total_distance', 0):.2f} km")
        await state.clear()
        # Keyin haydovchi yana location yuborsa navbatga qaytadi
    else:
        await message.answer("Siz hozir safarda emassiz.")
