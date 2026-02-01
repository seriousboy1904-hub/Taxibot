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

# YANGI TARIFLAR
START_PRICE = 10000  
NEXT_KM_PRICE = 1000 
WAIT_PRICE = 1000    

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    phone, car_model, car_number = State(), State(), State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA VA MASOFA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL, last_lon REAL, distance REAL DEFAULT 0, msg_id INTEGER)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def calculate_price(dist, wait_time):
    total = START_PRICE if dist <= 1 else START_PRICE + ((dist - 1) * NEXT_KM_PRICE)
    return total + (wait_time * WAIT_PRICE)

# ==========================================
# 🚕 MIJOZ BOTI (Tog'irlangan qism)
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

async def find_and_send_driver(c_id, c_name, c_phone, lat, lon):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Eng yaqin online haydovchini qidirish
    cursor.execute("SELECT user_id FROM drivers WHERE status = 'online' LIMIT 1")
    driver = cursor.fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}")]
        ])
        await driver_bot.send_location(d_id, lat, lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
    else:
        # Agar online haydovchi bo'lmasa, guruhga yuborish
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (Taksometr qismi)
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True)
        await message.answer("Xush kelibsiz! Ishni boshlash uchun lokatsiya yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        await message.answer("Ro'yxatdan o'tish uchun raqam yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(F.location)
async def driver_active(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, status) VALUES (?,?,?)", (message.from_user.id, message.from_user.full_name, 'online'))
    conn.commit()
    conn.close()
    await message.answer("✅ Siz onlinesiz. Buyurtma kelganda sizga xabar beramiz.")

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    # Safarni bazaga yozish
    res = await call.message.answer("Safar boshlandi! **Live Location** (Jonli joylashuv) yuboring.")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, last_lat, last_lon, distance, msg_id) VALUES (?,?,?,?,?,0,?)", 
                 (did, cid, cph, lat, lon, res.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
    ])
    await res.edit_reply_markup(reply_markup=ikb)

@driver_dp.edited_message(F.location)
async def track_taxi_meter(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance, total_wait, msg_id FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        l_lat, l_lon, dist, twait, msg_id = trip
        new_dist = dist
        if l_lat and l_lon:
            step = get_dist(l_lat, l_lon, lat, lon)
            if step > 0.02: new_dist += step
        
        cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        conn.commit()
        
        price = calculate_price(new_dist, twait)
        text = (f"🚖 **TAKSOMETR**\n\n📏 Masofa: {new_dist:.2f} km\n⏳ Kutish: {int(twait)} daq\n💰 **Summa: {price:,.0f} so'm**")
        
        try:
            await driver_bot.edit_message_text(text, did, msg_id, parse_mode="Markdown", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
                    [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
                ]))
        except: pass
    conn.close()

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")]]))

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        diff = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (diff, call.from_user.id))
        conn.commit()
    conn.close()
    # Taksometr xabari keyingi location editida avtomatik yangilanadi

@driver_dp.callback_query(F.data == "fin_pre")
async def finish(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, twait, dist = tr
        total = calculate_price(dist, twait)
        res = f"🏁 **Safar yakunlandi**\n\n📏 Masofa: {dist:.2f} km\n⏳ Kutish: {int(twait)} daq\n💰 **Jami: {total:,.0f} so'm**"
        await call.message.edit_text(res, parse_mode="Markdown")
        if cid: await client_bot.send_message(cid, res, parse_mode="Markdown")
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

async def main():
    init_db()
    await asyncio.gather(
        client_dp.start_polling(client_bot, skip_updates=True),
        driver_dp.start_polling(driver_bot, skip_updates=True)
    )

if __name__ == '__main__':
    asyncio.run(main())
