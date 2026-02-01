import os, sqlite3, asyncio, time, math, json
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
from shapely.geometry import shape, Point

load_dotenv()

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# TARIFLAR
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

# --- GEOJSON HUDUDNI ANIQLASH ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000 
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest(u_lat, u_lon):
    if not os.path.exists(GEOJSON_FILE): return "Noma'lum", 0
    with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    closest, min_dist = None, float('inf')
    for feat in data.get('features', []):
        coords = feat.get('geometry', {}).get('coordinates')
        name = feat.get('properties', {}).get('name', "Bekat")
        dist = calculate_distance(u_lat, u_lon, coords[1], coords[0])
        if dist < min_dist:
            min_dist, closest = dist, name
    return closest, min_dist

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         status TEXT DEFAULT 'offline', station TEXT, lat REAL, lon REAL, joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         s_lat REAL, s_lon REAL, last_lat REAL, last_lon REAL, 
         distance REAL DEFAULT 0, msg_id INTEGER)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def calculate_price(dist, wait_time):
    price = START_PRICE
    if dist > 1: price += (dist - 1) * NEXT_KM_PRICE
    price += (wait_time * WAIT_PRICE)
    return price

# ==========================================
# 🚕 MIJOZ BOTI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Taksi chaqirish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiyangizni yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    lat, lon = message.location.latitude, message.location.longitude
    station = get_station_name(lat, lon)
    await state.update_data(lat=lat, lon=lon, station=station)
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer(f"📍 Sizning hududingiz: **{station}**\n📱 Telefon raqamingizni yuboring:", reply_markup=kb, parse_mode="Markdown")

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon, c_station = data['lat'], data['lon'], data['station']
    c_phone, c_id, c_name = message.contact.phone_number, message.from_user.id, message.from_user.full_name

    conn = sqlite3.connect(DB_FILE)
    # Aynan shu bekatda online turgan, birinchi bo'lib navbatga kelgan haydovchini topamiz
    driver = conn.execute("SELECT user_id FROM drivers WHERE status = 'online' AND station = ? ORDER BY joined_at ASC LIMIT 1", (c_station,)).fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{c_lat}_{c_lon}")]])
        await driver_bot.send_location(d_id, c_lat, c_lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n📍 Bekat: {c_station}\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
        await message.answer(f"⏳ Buyurtmangiz **{c_station}** bekatidagi haydovchiga yuborildi.", reply_markup=ReplyKeyboardRemove())
    else:
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {c_station}\n👤 Mijoz: {c_name}\n📞 {c_phone}")
        await message.answer(f"Hozircha **{c_station}** bekatida bo'sh haydovchi yo'q, buyurtma guruhga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start_cmd(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True)
        await message.answer("Tayyormisiz? Bekat navbatiga kirish uchun lokatsiya yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        await message.answer("Ro'yxatdan o'tish: Raqam yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = get_station_name(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""UPDATE drivers SET status='online', lat=?, lon=?, station=?, joined_at=? WHERE user_id=?""", 
                 (lat, lon, station, datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Siz onlinesiz.\n📍 Bekat: **{station}**\n🔄 Navbatga qo'shildingiz.", parse_mode="Markdown")

# --- TAKSOMETR VA SAFAR (Oldingi kodlar bilan bir xil, faqat acc_ da joined_at o'zgarmaydi) ---

@driver_dp.callback_query(F.data.startswith("acc_"))
async def accept_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    
    initial_text = f"🚖 **Safar boshlandi**\n\n📏 Masofa: 0.00 km\n⏳ Kutish: 0 daq\n💰 Summa: {START_PRICE:,.0f} so'm"
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
    msg = await call.message.answer(initial_text, reply_markup=ikb, parse_mode="Markdown")
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, last_lat, last_lon, distance, total_wait, msg_id) VALUES (?,?,?,?,?,?,?,0,0,?)",
                 (did, cid, cph, lat, lon, lat, lon, msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    await call.message.delete()
    await client_bot.send_message(cid, "🚕 Haydovchi yo'lga chiqdi.")

@driver_dp.edited_message(F.location)
async def taxi_meter_logic(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance, total_wait, msg_id, wait_start FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        l_lat, l_lon, dist, twait, msg_id, w_start = trip
        new_dist = dist
        if w_start == 0 and l_lat and l_lon:
            step = get_dist(l_lat, l_lon, lat, lon)
            if step > 0.02: new_dist += step
        
        cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        conn.commit()
        
        price = calculate_price(new_dist, twait)
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya" if w_start == 0 else "▶️ Davom etish", callback_data="wait_on" if w_start == 0 else "wait_off")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
        text = (f"🚖 **TAKSOMETR (LIVE)**\n\n📏 Masofa: {new_dist:.2f} km\n⏳ Kutish: {int(twait)} daq\n💰 **Summa: {price:,.0f} so'm**")
        try: await driver_bot.edit_message_text(text, did, msg_id, parse_mode="Markdown", reply_markup=ikb)
        except: pass
    conn.close()

# wait_on, wait_off va fin_pre funksiyalari oldingi koddagidek qoladi...
# (Joy tejash uchun qisqartirildi, lekin mantiq o'zgarmas)

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    await call.answer("Kutish yoqildi")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
    await call.message.edit_reply_markup(reply_markup=ikb)

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        diff = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (diff, call.from_user.id))
        conn.commit()
    conn.close()
    await call.answer("Safar davom etmoqda")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
    await call.message.edit_reply_markup(reply_markup=ikb)

@driver_dp.callback_query(F.data == "fin_pre")
async def finish_trip(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance, s_lat, s_lon, last_lat, last_lon FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, twait, dist, s_lat, s_lon, f_lat, f_lon = tr
        total = calculate_price(dist, twait)
        route_url = f"https://www.google.com/maps/dir/{s_lat},{s_lon}/{f_lat},{f_lon}"
        final_text = f"🏁 **Safar yakunlandi**\n\n📏 Masofa: {dist:.2f} km\n⏳ Kutish: {int(twait)} daq\n💰 **Jami: {total:,.0f} so'm**\n📍 [Yo'nalish]({route_url})"
        await call.message.edit_text(final_text, parse_mode="Markdown", disable_web_page_preview=False)
        if cid: await client_bot.send_message(cid, final_text, parse_mode="Markdown")
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot, skip_updates=True), driver_dp.start_polling(driver_bot, skip_updates=True))

if __name__ == '__main__':
    asyncio.run(main())
