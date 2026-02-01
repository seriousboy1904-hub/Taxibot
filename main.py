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

load_dotenv()

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# TARIFLAR
START_PRICE = 10000  # 1 km gacha
NEXT_KM_PRICE = 1000 # 1 km dan keyin har bir km uchun
WAIT_PRICE = 1000    # 1 daqiqa kutish uchun

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    phone, car_model, car_number = State(), State(), State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# ==========================================
# 🗺 JSON NUQTALAR BILAN ISHLASH (Namuna asosida)
# ==========================================
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000 # metrda
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest_station(u_lat, u_lon):
    if not os.path.exists(GEOJSON_FILE): 
        return "Noma'lum", 0
    try:
        with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        closest_name, min_dist = "Noma'lum", float('inf')
        for feat in data.get('features', []):
            coords = feat.get('geometry', {}).get('coordinates') # [lon, lat]
            name = feat.get('properties', {}).get('name', "Bekat")
            dist = calculate_distance(u_lat, u_lon, coords[1], coords[0])
            if dist < min_dist:
                min_dist, closest_name = dist, name
        return closest_name, min_dist
    except:
        return "Xato", 0

# ==========================================
# 📊 BAZA VA MANTIQ
# ==========================================
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

def calculate_trip_price(dist_km, wait_min):
    price = START_PRICE
    if dist_km > 1:
        price += (dist_km - 1) * NEXT_KM_PRICE
    price += (wait_min * WAIT_PRICE)
    return price

# ==========================================
# 🚕 MIJOZ BOTI
# ==========================================
@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Taksi chaqirish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiya yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    st_name, _ = find_closest_station(message.location.latitude, message.location.longitude)
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude, station=st_name)
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer(f"📍 Sizga eng yaqin bekat: **{st_name}**\n📱 Telefon raqamingizni yuboring:", reply_markup=kb, parse_mode="Markdown")

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon, c_st = data['lat'], data['lon'], data['station']
    c_phone, c_id, c_name = message.contact.phone_number, message.from_user.id, message.from_user.full_name

    conn = sqlite3.connect(DB_FILE)
    # Bekatdagi birinchi haydovchini olish
    driver = conn.execute("SELECT user_id FROM drivers WHERE status = 'online' AND station = ? ORDER BY joined_at ASC LIMIT 1", (c_st,)).fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{c_lat}_{c_lon}")]])
        await driver_bot.send_location(d_id, c_lat, c_lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n📍 Bekat: {c_st}\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
        await message.answer(f"⏳ Buyurtma **{c_st}** bekatidagi haydovchiga yuborildi.", reply_markup=ReplyKeyboardRemove())
    else:
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {c_st}\n👤 Mijoz: {c_name}\n📞 {c_phone}")
        await message.answer(f"Hozircha yaqin atrofda bo'sh haydovchi yo'q, buyurtma guruhga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================
@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    st_name, _ = find_closest_station(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""UPDATE drivers SET status='online', lat=?, lon=?, station=?, joined_at=? WHERE user_id=?""", 
                 (lat, lon, st_name, datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Onlinesiz.\n📍 Bekat: **{st_name}**\n🔄 Navbatga qo'shildingiz.", parse_mode="Markdown")

@driver_dp.callback_query(F.data.startswith("acc_"))
async def accept_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    # Taksometr monitorini yaratish
    res = await call.message.answer(f"🚖 **Safar boshlandi**\n\n📏 0.00 km | 💰 {START_PRICE:,.0f} so'm")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, last_lat, last_lon, distance, total_wait, msg_id) VALUES (?,?,?,?,?,?,?,0,0,?)",
                 (did, cid, cph, lat, lon, lat, lon, res.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
    await res.edit_reply_markup(reply_markup=ikb)
    await call.message.delete()

@driver_dp.edited_message(F.location)
async def taxi_meter(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance, total_wait, msg_id, wait_start FROM trips WHERE driver_id=?", (did,)).fetchone()
    if trip:
        l_lat, l_lon, dist, twait, msg_id, w_s = trip
        new_dist = dist
        if w_s == 0 and l_lat:
            # Nuqtalar orasidagi masofani KM ga o'tkazamiz (/1000)
            step = calculate_distance(l_lat, l_lon, lat, lon) / 1000
            if step > 0.02: new_dist += step
        cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        conn.commit()
        p = calculate_trip_price(new_dist, twait)
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya" if w_s==0 else "▶️ Davom etish", callback_data="wait_on" if w_s==0 else "wait_off")],[InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
        try: await driver_bot.edit_message_text(f"🚖 **TAKSOMETR**\n\n📏 {new_dist:.2f} km\n⏳ {int(twait)} daq\n💰 **{p:,.0f} so'm**", did, msg_id, parse_mode="Markdown", reply_markup=ikb)
        except: pass
    conn.close()

# --- OJIDANIYA VA YAKUNLASH ---
@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id)); conn.commit(); conn.close()
    await call.answer("Kutish rejimi yoqildi")

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        d = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (d, call.from_user.id)); conn.commit()
    conn.close(); await call.answer("Safar davom etadi")

@driver_dp.callback_query(F.data == "fin_pre")
async def fin(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT client_id, total_wait, distance, s_lat, s_lon, last_lat, last_lon FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, tw, dist, slat, slon, flat, flon = tr
        total = calculate_trip_price(dist, tw)
        url = f"https://www.google.com/maps/dir/{slat},{slon}/{flat},{flon}"
        txt = f"🏁 **Safar yakunlandi**\n\n📏 {dist:.2f} km\n⏳ {int(tw)} daq\n💰 **{total:,.0f} so'm**\n📍 [Yo'nalishni ko'rish]({url})"
        await call.message.edit_text(txt, parse_mode="Markdown", disable_web_page_preview=False)
        if cid: await client_bot.send_message(cid, txt, parse_mode="Markdown")
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot, skip_updates=True), driver_dp.start_polling(driver_bot, skip_updates=True))

if __name__ == '__main__':
    asyncio.run(main())
