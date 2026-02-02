from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from helpers import find_nearest_station
from database import Database
from config import STATIONS, CLIENT_TOKEN

driver_router = Router()
db = Database("taxi.db")
client_bot_sender = Bot(token=CLIENT_TOKEN)

class DriverReg(StatesGroup):
    name = State()

@driver_router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await message.answer("Xush kelibsiz! Ismingizni kiriting:")
    await state.set_state(DriverReg.name)

@driver_router.message(DriverReg.name)
async def process_name(message: types.Message, state: FSMContext):
    await message.answer(f"Rahmat! Endi navbatga turish uchun 'Live Location' yuboring.")
    await state.clear()

@driver_router.edited_message(F.location)
async def handle_driver_live(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    station, dist = find_nearest_station(lat, lon, STATIONS)
    
    data = await state.get_data()
    if not data.get("on_trip"):
        status = "idle" if dist <= 0.5 else "off_duty"
        db.update_driver_status(message.from_user.id, lat, lon, station if dist <= 0.5 else "Yo'lda", status)

# BUYURTMANI QABUL QILISH
@driver_router.callback_query(F.data.startswith("accept_"))
async def accept_order(callback: types.CallbackQuery, state: FSMContext):
    client_id = callback.data.split("_")[1]
    await state.update_data(on_trip=True, current_client=client_id)
    
    # Statusni band qilish
    db.update_driver_status(callback.from_user.id, 0, 0, "Safarda", status="busy")
    
    # Mijozga xabar
    await client_bot_sender.send_message(client_id, f"✅ Haydovchi buyurtmani qabul qildi!\n👨‍✈️: {callback.from_user.full_name}\n🚖 Tez orada yetib boradi.")
    
    await callback.message.edit_text("✅ Buyurtma qabul qilindi. Safar tugagach /finish bosing.")
    await callback.answer()

@driver_router.callback_query(F.data.startswith("reject_"))
async def reject_order(callback: types.CallbackQuery):
    await callback.message.edit_text("❌ Siz buyurtmani rad etdingiz.")
    await callback.answer()
