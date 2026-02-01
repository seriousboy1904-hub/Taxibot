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

# --- KONFIGURATSIYA (TOKENLARNI .env FAYLIDAN OLADI) ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# TARIFLAR
MIN_PRICE = 5000       
KM_PRICE = 1000          
WAIT_PRICE = 500         

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    name, phone, car_model, car_number = State(), State(), State(), State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA FUNKSIYALARI ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL DEFAULT 0, lon REAL DEFAULT 0, 
         status TEXT DEFAULT 'offline', last_seen REAL DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL DEFAULT 0, last_lon REAL DEFAULT 0,
         total_dist REAL DEFAULT 0, is_riding INTEGER DEFAULT 0,
         driver_msg_id INTEGER, client_msg_id INTEGER)''')
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
# 🔄 MONITORING LOOP (TUGMALARNI QAYTA CHIZISH)
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

        curr_wait = total_wait_min + ((time.time() - wait_start) / 60 if wait_start > 0 else 0)
        dist_cost = (total_dist - 1.0) * KM_PRICE if total_dist > 1.0 else 0
        summa = int(MIN_PRICE + dist_cost + (int(curr_wait) * WAIT_PRICE))
        
        # TUGMALARNI QAT'IY YIG'ISH
        kb = []
        # Ojidaniye holati
        if wait_start > 0:
            kb.append([InlineKeyboardButton(text="⏸ Pauza (Kutish)", callback_data="wait_pause")])
        else:
            kb.append([InlineKeyboardButton(text="▶️ Ojidaniye", callback_data="wait_play")])
        
        # Safar holati
        if is_riding == 0:
            kb.append([InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")])
        else:
            kb.append([InlineKeyboardButton(text="🏁 YAKUNLASH", callback_data="fin_pre")])

        txt = f"{'🚖 SAFARDA' if is_riding else '⏳ KUTISHDA'}\n\n🛣 Masofa: {total_dist:.2f} km\n⏱ Kutish: {int(curr_wait)} daq\n💰 Hisob: {summa} so'm"
        
        try:
            await driver_bot.edit_message_text(txt, did, d_msg_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
            await client_bot.edit_message_text(txt, cid, c_msg_id)
        except: pass
        conn.close()

# ==========================================
# 👨‍✈️ DRIVER HANDLERS
# ==========================================

@driver_dp.message(F.location)
async def dr_loc_receiver(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    
    # 1. Navbat (Faqat Live Location uchun)
    if message.location.live_period:
        st = find_station(lat, lon)
        curr = conn.execute("SELECT status FROM drivers WHERE user_id=?", (did,)).fetchone()
        if curr and curr[0] != 'busy':
            conn.execute("UPDATE drivers SET status='online', last_seen=?, station=?, lat=?, lon=? WHERE user_id=?", (time.time(), st, lat, lon, did))
            drivers = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? ORDER BY last_seen ASC", (st,)).fetchall()
            pos = next((i for i, (uid,) in enumerate(drivers, 1) if uid == did), 0)
            await message.answer(f"📍 {st}\n👥 Navbat: {pos}-chi ({len(drivers)} tadan)")

    # 2. GPS Masofa hisobi
    tr = conn.execute("SELECT is_riding, last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    if tr and tr[0] == 1:
        l_lat, l_lon, t_dist = tr[1], tr[2], tr[3]
        if l_lat > 0:
            step = get_dist(l_lat, l_lon, lat, lon)
            if 0.005 < step < 0.5: # 5 metr va 500 metr oralig'idagi harakat
                conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (t_dist + step, lat, lon, did))
        else:
            conn.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, did))
    
    conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "arrived")
async def arrived_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit(); conn.close()
    await call.message.edit_text("Yetib keldingiz. Ojidaniye boshlandi.")
    asyncio.create_task(taximeter_loop(call.from_user.id))

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    new_wait = tr[1] + ((time.time() - tr[0])/60 if tr[0] > 0 else 0)
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=?, last_lat=?, last_lon=? WHERE driver_id=?", (new_wait, dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close(); await call.answer("Oq yo'l!")

@driver_dp.callback_query(F.data == "wait_pause")
async def pause_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0: conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[1] + (time.time()-tr[0])/60, call.from_user.id)); conn.commit()
    conn.close(); await call.answer("Pauza")

@driver_dp.callback_query(F.data == "wait_play")
async def play_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id)); conn.commit(); conn.close(); await call.answer("Davom...")

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        w_min = tr[4] + ((time.time() - tr[3])/60 if tr[3] > 0 else 0)
        dist_cost = (tr[7] - 1.0) * KM_PRICE if tr[7] > 1.0 else 0
        total = int(MIN_PRICE + dist_cost + (int(w_min) * WAIT_PRICE))
        res = f"🏁 YAKUNLANDI\n🛣 Masofa: {tr[7]:.2f} km\n⏱ Kutish: {int(w_min)} daq\n💰 Jami: {total} so'm"
        await call.message.edit_text(res); await client_bot.send_message(tr[1], res)
        conn.execute("UPDATE drivers SET status='offline' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

# ==========================================
# 🚕 LOGIKA: QABUL QILISH VA REGISTRATSIYA
# ==========================================

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE); d = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    c_msg = await client_bot.send_message(cid, f"🚕 Haydovchi: {d[0]} ({d[3]})\n📞 {d[1]}")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await msg.edit_text(f"✅ Mijoz: {cph}", reply_markup=ikb) if msg else await driver_bot.send_message(did, f"✅ Mijoz: {cph}", reply_markup=ikb)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?)", (did, cid, cph, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,)); conn.commit(); conn.close()

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_cb(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_"); await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

@driver_dp.message(Command("start"))
async def dr_start(message: types.Message, command: CommandObject, state: FSMContext):
    if command.args and command.args.startswith("gr_"):
        p = command.args.split("_"); return await start_trip_logic(message.from_user.id, int(p[1]), p[4], float(p[2]), float(p[3]))
    conn = sqlite3.connect(DB_FILE); u = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone(); conn.close()
    if not u: await state.set_state(DriverReg.name); await message.answer("Ism:")
    else: await message.answer("Ishni boshlash (Live Location yuboring)", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Online", request_location=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.name)
async def dr_n(message: types.Message, state: FSMContext):
    await state.update_data(n=message.text); await state.set_state(DriverReg.phone); await message.answer("Raqam:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def dr_p(message: types.Message, state: FSMContext):
    await state.update_data(p=message.contact.phone_number); await state.set_state(DriverReg.car_model); await message.answer("Moshina:", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def dr_m(message: types.Message, state: FSMContext):
    await state.update_data(m=message.text); await state.set_state(DriverReg.car_number); await message.answer("Raqami:")

@driver_dp.message(DriverReg.car_number)
async def dr_f(message: types.Message, state: FSMContext):
    d = await state.get_data(); conn = sqlite3.connect(DB_FILE); conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num) VALUES (?,?,?,?,?)", (message.from_user.id, d['n'], d['p'], d['m'], message.text)); conn.commit(); conn.close(); await state.clear(); await message.answer("✅ Tayyor! /start")

# --- MIJOZ ---
@client_dp.message(Command("start"))
async def c_start(message: types.Message):
    await message.answer("📍 Lokatsiya yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya", request_location=True)]], resize_keyboard=True))

@client_dp.message(F.location)
async def c_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude); await state.set_state(ClientOrder.waiting_phone); await message.answer("📱 Raqam:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def c_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); station = find_station(d['lat'], d['lon']); conn = sqlite3.connect(DB_FILE)
    dr = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? ORDER BY last_seen ASC LIMIT 1", (station,)).fetchone(); conn.close()
    if dr:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul", callback_data=f"acc_{message.from_user.id}_{message.contact.phone_number}_{d['lat']}_{d['lon']}"), InlineKeyboardButton(text="🔄 Skip", callback_data="skip")]])
        await driver_bot.send_message(dr[0], f"🚕 Buyurtma!\n📞 {message.contact.phone_number}", reply_markup=ikb)
    else: await client_bot.send_message(GROUP_ID, f"📢 Bo'sh haydovchi yo'q! Bekat: {station}")
    await message.answer("⏳ Qidirilmoqda...", reply_markup=ReplyKeyboardRemove()); await state.clear()

async def main():
    init_db(); await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
