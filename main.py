import os, json, math, sqlite3, asyncio, time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from dotenv import load_dotenv

load_dotenv()

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

MIN_PRICE, KM_PRICE, WAIT_PRICE = 5000, 1000, 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    name, phone, car_model, car_number = State(), State(), State(), State()

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL DEFAULT 0, lon REAL DEFAULT 0, 
         status TEXT DEFAULT 'offline', last_seen REAL DEFAULT 0)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL DEFAULT 0, last_lon REAL DEFAULT 0,
         total_dist REAL DEFAULT 0, is_riding INTEGER DEFAULT 0,
         driver_msg_id INTEGER, client_msg_id INTEGER)''')
    conn.commit(); conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371 
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ==========================================
# 🔄 MONITORING (RUCHOY BOSHQARUV BILAN)
# ==========================================

async def taximeter_loop(did):
    while True:
        await asyncio.sleep(4)
        conn = sqlite3.connect(DB_FILE)
        tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (did,)).fetchone()
        if not tr: conn.close(); break
        
        cid, wait_start, total_wait_min = tr[1], tr[3], tr[4]
        total_dist, is_riding = tr[7], tr[8]
        d_msg_id, c_msg_id = tr[9], tr[10]

        # Ojidaniye faqat wait_start > 0 bo'lsa hisoblanadi
        curr_wait = total_wait_min + ((time.time() - wait_start) / 60 if wait_start > 0 else 0)
        dist_cost = (total_dist - 1.0) * KM_PRICE if total_dist > 1.0 else 0
        summa = int(MIN_PRICE + dist_cost + (int(curr_wait) * WAIT_PRICE))
        
        kb = []
        # 1. Ojidaniye tugmasi (Ruchnoy)
        if wait_start > 0:
            kb.append([InlineKeyboardButton(text="⏸ Kutishni to'xtatish", callback_data="wait_pause")])
        else:
            kb.append([InlineKeyboardButton(text="▶️ Ojidaniye boshlash", callback_data="wait_play")])
        
        # 2. Safar tugmasi
        if is_riding == 0:
            kb.append([InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")])
        else:
            kb.append([InlineKeyboardButton(text="🏁 SAFARNI YAKUNLASH", callback_data="fin_pre")])

        st_txt = "🚖 Safarda" if is_riding else "⌛️ To'xtab turibdi"
        txt = f"{st_txt}\n\n🛣 Masofa: {total_dist:.2f} km\n⏱ Kutish: {int(curr_wait)} daq\n💰 Summa: {summa} so'm"
        
        try:
            await driver_bot.edit_message_text(txt, did, d_msg_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            await client_bot.edit_message_text(txt, cid, c_msg_id)
        except: pass
        conn.close()

# ==========================================
# 🚕 RUCHOY LOGIKA
# ==========================================

@driver_dp.callback_query(F.data == "arrived")
async def arrived_cb(call: CallbackQuery):
    # Bu yerda ojidaniye avtomatik BOSHLANMAYDI
    await call.message.edit_text("Siz manzildasiz. Kerakli tugmani bosing:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Ojidaniye boshlash", callback_data="wait_play")],
            [InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")]
        ]))
    asyncio.create_task(taximeter_loop(call.from_user.id))

@driver_dp.callback_query(F.data == "wait_play")
async def wait_play_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Kutish vaqti yoqildi")

@driver_dp.callback_query(F.data == "wait_pause")
async def wait_pause_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        added = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[1] + added, call.from_user.id))
        conn.commit()
    conn.close(); await call.answer("Kutish to'xtatildi")

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    # Safar boshlanganda ojidaniye bo'lsa uni to'xtatib total_wait'ga o'tkazadi
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    new_wait = tr[1] + ((time.time() - tr[0])/60 if tr[0] > 0 else 0)
    
    # Safarni boshlash (is_riding=1) va masofa uchun oxirgi nuqtani belgilash
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                 (new_wait, dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Oq yo'l! Masofa hisobi boshlandi.")

# --- FINISH VA LOKATSIYA (O'ZGARISHSIZ) ---

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        w_min = tr[4] + ((time.time() - tr[3])/60 if tr[3] > 0 else 0)
        total = int(MIN_PRICE + ((tr[7]-1)*KM_PRICE if tr[7]>1 else 0) + (int(w_min)*WAIT_PRICE))
        res = f"🏁 YAKUNLANDI\n🛣 Masofa: {tr[7]:.2f} km\n💰 Jami: {total} so'm"
        await call.message.edit_text(res); await client_bot.send_message(tr[1], res)
        conn.execute("UPDATE drivers SET status='offline' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

@driver_dp.message(F.location)
async def loc_handler(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    # Masofa faqat is_riding=1 bo'lganda hisoblanadi
    tr = conn.execute("SELECT is_riding, last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    if tr and tr[0] == 1:
        step = get_dist(tr[1], tr[2], lat, lon)
        if 0.005 < step < 0.5:
            conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (tr[3]+step, lat, lon, did))
    # Navbatni yangilash... (qolgan mantiq)
    conn.commit(); conn.close()

# (Boshqa hamma funksiyalar: Registration, Client Start, find_station... oldingi koddagi kabi qoladi)

async def main():
    init_db(); await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
