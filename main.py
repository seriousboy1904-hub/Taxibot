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

# NARXLAR (O'zingizga moslang)
START_PRICE, KM_PRICE, WAIT_PRICE = 5000, 3500, 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    phone, car_model, car_number = State(), State(), State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL DEFAULT 0, last_lon REAL DEFAULT 0,
         total_dist REAL DEFAULT 0, is_riding INTEGER DEFAULT 0,
         d_msg_id INTEGER, c_msg_id INTEGER)''')
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
# 🔄 MONITORING (TUGMALARNI YANGILASH)
# ==========================================

async def taximeter_loop(did):
    while True:
        await asyncio.sleep(4)
        conn = sqlite3.connect(DB_FILE)
        tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (did,)).fetchone()
        if not tr: conn.close(); break
        
        cid, wait_start, total_wait, t_dist, is_riding, d_msg_id, c_msg_id = tr[1], tr[4], tr[5], tr[7], tr[8], tr[9], tr[10]

        # Kutish vaqtini hisoblash
        curr_wait = total_wait + ((time.time() - wait_start) / 60 if wait_start > 0 else 0)
        
        # Narxni hisoblash
        dist_cost = (t_dist - 1.0) * KM_PRICE if t_dist > 1.0 else 0
        summa = int(START_PRICE + dist_cost + (int(curr_wait) * WAIT_PRICE))
        
        # TUGMALARNI CHIZISH
        kb = []
        # 1. Ojidaniye qatori
        if wait_start > 0:
            kb.append([InlineKeyboardButton(text="⏸ Kutishni to'xtatish", callback_data="wait_off")])
        else:
            kb.append([InlineKeyboardButton(text="▶️ Ojidaniye boshlash", callback_data="wait_on")])
        
        # 2. Safar qatori
        if is_riding == 0:
            kb.append([InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")])
        else:
            kb.append([InlineKeyboardButton(text="🏁 SAFARNI YAKUNLASH", callback_data="fin_pre")])

        txt = f"{'🚖 Safarda' if is_riding else '⏳ To`xtab turibdi'}\n\n🛣 Masofa: {t_dist:.2f} km\n⏱ Kutish: {int(curr_wait)} daq\n💰 Summa: {summa} so'm"
        
        try:
            await driver_bot.edit_message_text(txt, did, d_msg_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            await client_bot.edit_message_text(txt, cid, c_msg_id)
        except: pass
        conn.close()

# ==========================================
# 👨‍✈️ HAYDOVCHI HANDLERLARI
# ==========================================

@driver_dp.callback_query(F.data == "arrived")
async def arrived_cb(call: CallbackQuery):
    did = call.from_user.id
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    # Haydovchida boshqaruv panelini yaratish
    d_msg = await call.message.edit_text("Yetib keldingiz. Safarni boshlang yoki ojidaniye yoqing.", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Ojidaniye", callback_data="wait_on")],
            [InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")]
        ]))
    
    # Mijozda yangilanib turadigan xabarni yaratish
    c_msg = await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi!")
    
    conn.execute("UPDATE trips SET d_msg_id=?, c_msg_id=? WHERE driver_id=?", (d_msg.message_id, c_msg.message_id, did))
    conn.commit(); conn.close()
    
    asyncio.create_task(taximeter_loop(did))

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Ojidaniye yoqildi")

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        added = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[5] + added, call.from_user.id))
        conn.commit()
    conn.close(); await call.answer("Ojidaniye to'xtatildi")

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    # Safar boshlanganda ojidaniyani o'chirish va masofa hisobini yoqish
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    new_wait = tr[1] + ((time.time() - tr[0])/60 if tr[0] > 0 else 0)
    
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                 (new_wait, dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Oq yo'l!")

@driver_dp.message(F.location)
async def location_handler(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    
    # 1. Navbat (Online)
    st = find_station(lat, lon)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                 (st, lat, lon, datetime.now().isoformat(), did))
    
    # 2. Masofa hisoblash (Agar safarda bo'lsa)
    tr = conn.execute("SELECT is_riding, last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    if tr and tr[0] == 1:
        step = get_dist(tr[1], tr[2], lat, lon)
        if 0.005 < step < 0.6: # 5 metr va 600 metr orasidagi harakat
            conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                         (tr[3] + step, lat, lon, did))
    
    conn.commit(); conn.close()

# Qolgan funksiyalar (Registration, Client Start, find_and_send_driver, fin_pre) oldingidek qoladi...
# Faqat fin_pre qismida 'total_dist' ni ham narxga qo'shib yuborasiz.

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
