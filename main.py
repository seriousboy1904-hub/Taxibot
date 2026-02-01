import os, json, math, sqlite3, asyncio, time
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

load_dotenv()

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

START_PRICE, KM_PRICE, WAIT_PRICE = 5000, 3500, 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

# --- HOLATLAR (FSM) ---
class DriverReg(StatesGroup):
    phone = State()
    car_model = State()
    car_number = State()

class OrderState(StatesGroup):
    waiting_phone = State()

# --- BAZA BILAN ISHLASH ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline')''')
    c.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         start_time REAL, wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         s_lat REAL, s_lon REAL)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_station(lat, lon):
    try:
        with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        closest, min_dist = "Markaz", float('inf')
        for feat in data['features']:
            c = feat['geometry']['coordinates']
            d = get_dist(lat, lon, c[1], c[0])
            if d < min_dist: min_dist, closest = d, feat['properties']['name']
        return closest
    except: return "Noma'lum"

# ==========================================
# 🚕 MIJOZ BOTI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiyangizni yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(OrderState.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("📱 Telefon raqamingizni yuboring:", reply_markup=kb)

@client_dp.message(OrderState.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data['lat'], data['lon']
    c_phone = message.contact.phone_number
    station = find_station(c_lat, c_lon)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name, lat, lon FROM drivers WHERE status = 'online' AND station = ? LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        d_id, d_name, d_lat, d_lon = driver
        dist = get_dist(d_lat, d_lon, c_lat, c_lon)
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{message.from_user.id}_{c_phone}")]
        ])
        
        await driver_bot.send_location(d_id, c_lat, c_lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n📞: {c_phone}\n📏 Masofa: {dist:.1f} km", reply_markup=ikb)
        await message.answer(f"⏳ Buyurtma haydovchiga ({d_name}) yuborildi.", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("🚕 Hozircha bo'sh haydovchi yo'q, operatorga ulaning.")
    await state.clear()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (REGISTRATSIYA)
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT * FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()

    if not user:
        await state.set_state(DriverReg.phone)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
        await message.answer("Ro'yxatdan o'tish uchun raqamingizni yuboring:", reply_markup=kb)
    else:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True)
        await message.answer("Siz ro'yxatdan o'tgansiz. Ishni boshlash uchun lokatsiya yuboring.", reply_markup=kb)

@driver_dp.message(DriverReg.phone, F.contact)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    cars = [["Nexia 3", "Cobalt"], ["Gentra", "Spark"], ["Damas"]]
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c) for c in row] for row in cars], resize_keyboard=True)
    await state.set_state(DriverReg.car_model)
    await message.answer("Moshina turini tanlang:", reply_markup=kb)

@driver_dp.message(DriverReg.car_model)
async def reg_car(message: types.Message, state: FSMContext):
    await state.update_data(car=message.text)
    await state.set_state(DriverReg.car_number)
    await message.answer("Moshina raqamini kiriting (masalan: 01A777AA):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_number)
async def reg_done(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num, status) VALUES (?,?,?,?,?,?)",
                 (message.from_user.id, message.from_user.full_name, data['phone'], data['car'], message.text, 'offline'))
    conn.commit()
    conn.close()
    await message.answer("✅ Tabriklaymiz! Endi 'Ishni boshlash' tugmasini bosing.", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True))
    await state.clear()

# ==========================================
# 🚖 SAFAR VA BOSHQARUV
# ==========================================

@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=? WHERE user_id=?", (station, lat, lon, message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Siz onlinesiz!\n📍 Bekat: {station}")

@driver_dp.callback_query(F.data.startswith("acc_"))
async def accept_order(call: CallbackQuery):
    _, c_id, c_phone = call.data.split("_")
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone) VALUES (?,?,?)", (call.from_user.id, c_id, c_phone))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()

    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    await call.message.edit_text(f"✅ Qabul qilindi!\n📞 Mijoz: {c_phone}", reply_markup=ikb)
    await client_bot.send_message(c_id, "🚕 Haydovchi yo'lga chiqdi!")

@driver_dp.callback_query(F.data == "arrived")
async def driver_arrived(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Kutish (Ojidaniya)", callback_data="wait_start")],
        [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="finish_pre")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_pre")]
    ])
    await call.message.edit_text("Mijozga 'Yetib keldim' xabari yuborildi. Tanlang:", reply_markup=ikb)
    
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip: await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi! Chiqishingiz mumkin.")

@driver_dp.callback_query(F.data == "wait_start")
async def wait_start(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish (Safar boshlandi)", callback_data="wait_stop")]])
    await call.message.edit_text("⏱ Kutish vaqti hisoblanmoqda...", reply_markup=ikb)

@driver_dp.callback_query(F.data == "wait_stop")
async def wait_stop(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip:
        added_wait = (time.time() - trip[0]) / 60
        new_total = trip[1] + added_wait
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (new_total, call.from_user.id))
        conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="finish_pre")]])
    await call.message.edit_text("🚖 Safar davom etmoqda...", reply_markup=ikb)

@driver_dp.callback_query(F.data == "cancel_pre")
async def cancel_pre(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ha", callback_data="cancel_yes"), InlineKeyboardButton(text="❌ Yo'q", callback_data="arrived")]
    ])
    await call.message.edit_text("⚠️ Niyatingiz qat'iymi? Bekor qilinsinmi?", reply_markup=ikb)

@driver_dp.callback_query(F.data == "cancel_yes")
async def cancel_yes(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
    conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()
    await call.message.edit_text("❌ Buyurtma bekor qilindi.")

@driver_dp.callback_query(F.data == "finish_pre")
async def finish_trip(call: CallbackQuery):
    # Bu yerda oddiy yakunlash (aslida masofa uchun lokatsiya olinishi kerak)
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip:
        price = START_PRICE + (trip[1] * WAIT_PRICE)
        text = f"🏁 Safar yakunlandi!\n💰 To'lov: {int(price)} so'm\n⏳ Kutish: {int(trip[1])} daq"
        await call.message.edit_text(text)
        await client_bot.send_message(trip[0], text)
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
