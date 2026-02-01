import os, json, math, sqlite3, asyncio, time, logging
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

# Logging xatolarni terminalda ko'rish uchun
logging.basicConfig(level=logging.INFO)
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
         total_dist REAL DEFAULT 0, last_lat REAL, last_lon REAL, s_lat REAL, s_lon REAL)''')
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
# 👨‍✈️ HAYDOVCHI BOTI - LOKATSIYA VA START
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start_cmd(message: types.Message, command: CommandObject, state: FSMContext):
    # Guruhdan kelgan buyurtmani qabul qilish
    if command.args and command.args.startswith("gr_"):
        args = command.args.split("_")
        if len(args) >= 5:
            _, cid, lat, lon, cph = args[:5]
            return await start_trip_logic(message.from_user.id, int(cid), cph, float(lat), float(lon))

    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)]], resize_keyboard=True)
        await message.answer("Xush kelibsiz! Ishni boshlash uchun lokatsiyangizni yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
        await message.answer("Ro'yxatdan o'tish:\n1. Telefon raqamingizni yuboring:", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_loc_handler(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    d_id = message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT total_dist FROM trips WHERE driver_id=?", (d_id,)).fetchone()
    
    if trip:
        # Safar ketayotgan bo'lsa, birinchi nuqtani belgilash
        conn.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, d_id))
        await message.answer("📍 Safar boshlandi. Masofa hisoblanishi uchun 'Live Location' ulashing!")
    else:
        # Shunchaki online bo'lish
        st = find_station(lat, lon)
        conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                     (st, lat, lon, datetime.now().isoformat(), d_id))
        await message.answer(f"✅ Onlinesiz! Bekat: {st}")
    conn.commit()
    conn.close()

@driver_dp.edited_message(F.location)
async def driver_live_update(message: types.Message):
    # JONLI LOKATSIYA tahrirlanganda masofani hisoblash
    lat, lon = message.location.latitude, message.location.longitude
    d_id = message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT total_dist, last_lat, last_lon FROM trips WHERE driver_id=?", (d_id,)).fetchone()
    
    if trip and trip[1] is not None:
        total_dist, last_lat, last_lon = trip
        step = get_dist(last_lat, last_lon, lat, lon)
        if step > 0.02: # 20 metrdan ortiq harakat
            new_dist = total_dist + step
            conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (new_dist, lat, lon, d_id))
            conn.commit()
    conn.close()

# ==========================================
# 🚕 MIJOZ VA SAFAR LOGIKASI
# ==========================================

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, total_dist) VALUES (?,?,?,?,?,0)", 
                 (did, cid, cph, lat, lon))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    text = f"✅ Buyurtma qabul qilindi!\n📞 Mijoz: {cph}\n\nManzilga yetgach tugmani bosing."
    if msg: await msg.edit_text(text, reply_markup=ikb)
    else: await driver_bot.send_message(did, text, reply_markup=ikb)

@driver_dp.callback_query(F.data == "fin_pre")
async def finish_trip(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, total_dist FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        c_id, wait_m, dist_k = tr
        dist_cost = dist_k * KM_PRICE
        wait_cost = int(wait_m) * WAIT_PRICE
        total = round((START_PRICE + dist_cost + wait_cost) / 100) * 100
        
        res = (f"🏁 **Safar yakunlandi**\n\n"
               f"🛣 Masofa: {dist_k:.1f} km ({dist_cost:,.0f} so'm)\n"
               f"⏳ Kutish: {int(wait_m)} daq ({wait_cost:,.0f} so'm)\n"
               f"💰 **Jami: {total:,.0f} so'm**")
        
        await call.message.edit_text(res, parse_mode="Markdown")
        try: await client_bot.send_message(c_id, res, parse_mode="Markdown")
        except: pass
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# --- QOLGAN RO'YXATDAN O'TISH VA MIJOZ QISMLARI ---
# (Kodingizdagi reg_p, reg_c, client_start kabilar o'zgarishsiz qoladi)
# ... [Bu yerga kodingizning qolgan qismlari keladi] ...

@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("Mijozga xabar yuborildi. Safar boshlanganda ojidaniyani to'xtating.", reply_markup=ikb)
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip: 
        try: await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi!")
        except: pass
    conn.close()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
