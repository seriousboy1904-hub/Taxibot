from aiogram import Router, F, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
# ... (kerakli importlar)

class DriverReg(StatesGroup):
    name = State()
    phone = State()
    car_info = State()
    live_loc = State()

@driver_router.message(Command("start"))
async def start_driver(message: types.Message, state: FSMContext):
    await message.answer("Xush kelibsiz haydovchi! Ismingizni kiriting:")
    await state.set_state(DriverReg.name)

# ... (Ism, telefon va moshina raqamini yig'ish funksiyalari)

@driver_router.edited_message(F.location)
async def handle_live_location(message: types.Message):
    # Haydovchi joylashuvini yangilash va navbatni ko'rsatish
    lat, lon = message.location.latitude, message.location.longitude
    [span_5](start_span)station, dist = find_nearest_station(lat, lon, STATIONS)[span_5](end_span)
    
    if dist <= 0.5: # 500 metr ichida bo'lsa
        db.update_driver_status(message.from_user.id, lat, lon, station, status="idle")
        count = db.get_queue_info(station)
        await message.answer(f"Siz {station} bekatidasiz. Navbatda: {count}-chi haydovchisiz.")
