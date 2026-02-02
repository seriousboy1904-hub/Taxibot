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
    await message.answer("Salom haydovchi! Navbatga turish uchun 'Share Live Location' yuboring.")

@driver_router.message(F.location)
@driver_router.edited_message(F.location)
async def handle_driver_loc(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    station_name, dist = find_nearest_station(lat, lon, STATIONS)
    status_label = station_name if dist <= 0.6 else "Yo'lda"
    
    data = await state.get_data()
    if data.get("on_trip"):
        # Taksometr hisobi
        total = data.get("total_dist", 0)
        last_l = data.get("last_l")
        if last_l:
            total += get_distance(last_l[0], last_l[1], lat, lon)
        await state.update_data(total_dist=total, last_l=(lat, lon))
        db.update_driver_status(message.from_user.id, lat, lon, "Safarda", "busy")
    else:
        db.update_driver_status(message.from_user.id, lat, lon, status_label, "idle")

@driver_router.callback_query(F.data.startswith("accept_"))
async def accept_order(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(on_trip=True, total_dist=0, last_l=None)
    db.update_driver_status(call.from_user.id, 0, 0, "Safarda", "busy")
    await call.message.answer("Safar boshlandi! Masofa o'lchanmoqda. Tugatish: /finish")
    await call.answer()

@driver_router.message(Command("finish"))
async def finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if data.get("on_trip"):
        await message.answer(f"🏁 Safar tugadi. Masofa: {data.get('total_dist', 0):.2f} km")
        await state.clear()
        # Statusni yangilash uchun qaytadan location yuborishi kerak
    else:
        await message.answer("Siz safarda emassiz.")
