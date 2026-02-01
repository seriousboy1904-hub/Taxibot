import os, json, math, sqlite3, asyncio, time
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
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

# TARIFLAR
START_PRICE = 5000  
KM_PRICE = 3500     
WAIT_PRICE = 500    

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

# --- HOLATLAR ---
class DriverReg(StatesGroup):
    phone = State()
    car_model = State()
    car_number = State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA FUNKSIYALARI ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL, last_lon REAL, distance REAL DEFAULT 0)''')
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
    except: return "Markaz"

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
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("📱 Telefon raqamingizni yuboring:", reply_markup=kb)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data['lat'], data['lon']
    c_phone = message.contact.phone_number
    await find_and_send_driver(message.from_user.id, message.from_user.full_name, c_phone, c_lat, c_lon)
    await message.answer("⏳ Buyurtma haydovchilarga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

async def find_and_send_driver(c_id, c_name, c_phone, lat, lon, exclude_id=None):
    station = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    if exclude_id:
        cursor.execute("SELECT user_id FROM drivers WHERE status = 'online' AND station = ? AND user_id != ? ORDER BY joined_at ASC LIMIT 1", (station, exclude_id))
    else:
        cursor.execute("SELECT user_id FROM drivers WHERE status = 'online' AND station = ? ORDER BY joined_at ASC LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}")],
            [InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{c_id}_{c_phone}_{lat}_{lon}")]
        ])
        await driver_bot.send_location(d_id, lat, lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
    else:
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {c_name}\n📞 {c_phone}")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True)
        await message.answer("Ishni boshlash uchun lokatsiya yuboring (Live Location yoqing!)", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        await message.answer("Ro'yxatdan o'tish uchun raqamingizni yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def reg_p(message: types.Message, state: FSMContext):
    await state.update_data(p=message.contact.phone_number)
    await state.set_state(DriverReg.car_model)
    await message.answer("Mashina rusumi (Nexia, Cobalt...):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def reg_c(message: types.Message, state: FSMContext):
    await state.update_data(c=message.text)
    await state.set_state(DriverReg.car_number)
    await message.answer("Mashina raqami:")

@driver_dp.message(DriverReg.car_number)
async def reg_f(message: types.Message, state: FSMContext):
    d = await state.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num, status, joined_at) VALUES (?,?,?,?,?,?,?)",
                 (message.from_user.id, message.from_user.full_name, d['p'], d['c'], message.text, 'offline', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Tayyor! Endi lokatsiya yuboring.")

@driver_dp.message(F.location)
async def driver_loc_upd(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    st = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                 (st, lat, lon, datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Onlinesiz. Bekat: {st}")

# --- TAKSOMETR VA SAFAR LOGIKASI ---

@driver_dp.edited_message(F.location)
async def track_taxi_meter(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance FROM trips WHERE driver_id=?", (did,)).fetchone()
    if trip:
        l_lat, l_lon, d = trip
        if l_lat and l_lon:
            step = get_dist(l_lat, l_lon, lat, lon)
            if step > 0.02: # 20 metrdan ortiq siljish
                cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=distance+? WHERE driver_id=?", (lat, lon, step, did))
                conn.commit()
    conn.close()

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, last_lat, last_lon, distance) VALUES (?,?,?,?,?,0)", 
                 (did, cid, cph, lat, lon))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    await call.message.edit_text(f"✅ Qabul qilindi. 📞 {cph}\nSafar boshlanganda Live Location yoqilganiga ishonch hosil qiling!", reply_markup=ikb)

@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("Mijozga xabar yuborildi. Safar davomida lokatsiya tahrirlanib boradi.", reply_markup=ikb)
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip: await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi!")

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    await call.message.edit_text("⏱ Kutish hisoblanmoqda...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")]]))

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        diff = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (diff, call.from_user.id))
        conn.commit()
    await call.message.edit_text("🚖 Safar davom etmoqda...", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]]))

@driver_dp.callback_query(F.data == "fin_pre")
async def finish(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, twait, dist = tr
        total = START_PRICE + (twait * WAIT_PRICE) + (dist * KM_PRICE)
        res = f"🏁 Safar yakunlandi\n📏 Masofa: {dist:.2f} km\n⏳ Kutish: {int(twait)} daq\n💰 Jami: {total:,.0f} so'm"
        await call.message.edit_text(res)
        await client_bot.send_message(cid, res)
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# --- ASOSIY ISHGA TUSHIRISH ---
async def main():
    init_db()
    print("Botlar yoqilmoqda... Conflict xatosi bo'lmasligi uchun boshqa nusxalarni o'chiring.")
    # skip_updates=True eski xabarlarni o'tkazib yuboradi va conflict ehtimolini kamaytiradi
    await asyncio.gather(
        client_dp.start_polling(client_bot, skip_updates=True),
        driver_dp.start_polling(driver_bot, skip_updates=True)
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except:
        print("Bot to'xtadi.")
