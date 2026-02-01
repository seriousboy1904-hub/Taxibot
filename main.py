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
START_PRICE = 5000  # Boshlang'ich narx
KM_PRICE = 3500     # 1 km uchun
WAIT_PRICE = 500    # 1 daqiqa kutish uchun

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
         start_time REAL, wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL, last_lon REAL, distance REAL DEFAULT 0)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371 # Yer radiusi
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
# 👨‍✈️ HAYDOVCHI BOTI (TAKSOMETR QISMI)
# ==========================================

@driver_dp.edited_message(F.location)
async def track_taxi_meter(message: types.Message):
    """Haydovchi harakatlanganda masofani hisoblaydi"""
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        last_lat, last_lon, current_dist = trip
        if last_lat and last_lon:
            # Ikki nuqta orasidagi masofani hisoblaymiz
            step = get_dist(last_lat, last_lon, lat, lon)
            if step > 0.03: # 30 metrdan ortiq harakat bo'lsagina hisobga olamiz (GPS xatoligi uchun)
                new_dist = current_dist + step
                cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        else:
            cursor.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, did))
        conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_pre(call: CallbackQuery):
    """Safarni yakunlash va hisob-kitob"""
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if tr:
        c_id, t_wait, dist = tr
        wait_cost = int(t_wait) * WAIT_PRICE
        dist_cost = dist * KM_PRICE
        total = START_PRICE + wait_cost + dist_cost
        
        res = (f"🏁 **Safar yakunlandi**\n\n"
               f"📏 Masofa: {dist:.2f} km\n"
               f"⏳ Kutish: {int(t_wait)} daq\n"
               f"💰 **Jami to'lov: {total:,.0f} so'm**\n"
               f"_(Start: {START_PRICE} + Yo'l: {dist_cost:,.0f})_")
        
        await call.message.edit_text(res, parse_mode="Markdown")
        await client_bot.send_message(c_id, res, parse_mode="Markdown")
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# ==========================================
# 🚕 LOGIKA DAVOMI (Oldingi funksiyalarni saqlagan holda)
# ==========================================

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE)
    # last_lat va last_lon boshlang'ich nuqta sifatida olinadi
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, last_lat, last_lon, distance) VALUES (?,?,?,?,?,?)", 
                 (did, cid, cph, lat, lon, 0.0))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    t = f"✅ Qabul qilindi! Haydashni boshlashdan oldin 'Live Location' yuboring.\n📞 {cph}"
    if msg: await msg.edit_text(t, reply_markup=ikb)
    else: await driver_bot.send_message(did, t, reply_markup=ikb)

# --- Qolgan barcha handlerlar (start, reg, arrived, wait) o'zgarishsiz qoladi ---
# (Siz yuborgan oldingi kodning qolgan qismlarini shu yerga qo'shasiz)

@driver_dp.callback_query(F.data == "arrived")
async def arr_call(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("Mijozga xabar yuborildi. Safar boshlanganda masofa o'lchash avtomatik boshlanadi.", reply_markup=ikb)
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip: await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi!")

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish (Kutish tugadi)", callback_data="wait_off")]])
    await call.message.edit_text("⏱ Kutish vaqti hisoblanmoqda...", reply_markup=ikb)

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip and trip[0] > 0:
        added = (time.time() - trip[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (added, call.from_user.id))
        conn.commit()
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("🚖 Harakat davom etmoqda...", reply_markup=ikb)

# --- ASOSIY ISHGA TUSHIRISH ---
async def main():
    init_db()
    # Har ikkala botni bir vaqtda ishga tushirish
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
