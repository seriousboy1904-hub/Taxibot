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

START_PRICE, WAIT_PRICE, KM_PRICE = 5000, 500, 1500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    name, phone, car_model, car_number = State(), State(), State(), State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA ---
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
# 🔄 NAVBATNI HISOBLASH FUNKSIYASI
# ==========================================

def get_queue_info(did, station):
    conn = sqlite3.connect(DB_FILE)
    drivers = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? ORDER BY last_seen ASC", (station,)).fetchall()
    conn.close()
    
    total = len(drivers)
    pos = 0
    for i, (uid,) in enumerate(drivers, 1):
        if uid == did:
            pos = i
            break
    return pos, total

# ==========================================
# 🔄 TAXIMETER LOOP
# ==========================================

async def taximeter_loop(did):
    while True:
        await asyncio.sleep(5)
        conn = sqlite3.connect(DB_FILE)
        tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (did,)).fetchone()
        if not tr: conn.close(); break
        
        cid, wait_start, total_wait_min = tr[1], tr[3], tr[4]
        total_dist, is_riding = tr[7], tr[8]
        d_msg_id, c_msg_id = tr[9], tr[10]

        curr_wait = total_wait_min + ((time.time() - wait_start) / 60 if wait_start > 0 else 0)
        summa = START_PRICE + (int(curr_wait) * WAIT_PRICE) + (total_dist * KM_PRICE)
        
        btns = [[InlineKeyboardButton(text="⏸ Pauza" if wait_start > 0 else "▶️ Ojidaniye", callback_data="wait_pause" if wait_start > 0 else "wait_play")]]
        if is_riding == 0: btns.append([InlineKeyboardButton(text="🚖 Safarni boshlash", callback_data="ride_start")])
        btns.append([InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")])
        
        txt = f"{'🚖 SAFARDA' if is_riding else '⏳ KUTISHDA'}\n\n⏱ Ojidaniye: {int(curr_wait)} daq\n🛣 Masofa: {total_dist:.2f} km\n💰 Hisob: {int(summa)} so'm"
        try:
            await driver_bot.edit_message_text(chat_id=did, message_id=d_msg_id, text=txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
            await client_bot.edit_message_text(chat_id=cid, message_id=c_msg_id, text=txt)
        except: pass
        conn.close()

# ==========================================
# 👨‍✈️ DRIVER HANDLERS
# ==========================================

@driver_dp.message(F.location)
async def dr_loc_handler(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    did = message.from_user.id
    conn = sqlite3.connect(DB_FILE)
    
    # 1. Navbat va Statusni yangilash
    st = find_station(lat, lon)
    curr_status = conn.execute("SELECT status FROM drivers WHERE user_id=?", (did,)).fetchone()
    
    if curr_status and curr_status[0] != 'busy':
        if curr_status[0] == 'offline':
            conn.execute("UPDATE drivers SET status='online', last_seen=?, station=?, lat=?, lon=? WHERE user_id=?", (time.time(), st, lat, lon, did))
        else:
            conn.execute("UPDATE drivers SET lat=?, lon=?, station=? WHERE user_id=?", (lat, lon, st, did))
        
        pos, total = get_queue_info(did, st)
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔴 Ishni yakunlash (Offline)", callback_data="go_offline")]])
        await message.answer(f"📍 Bekat: {st}\n👥 Navbatingiz: {pos}-chi ({total} tadan)", reply_markup=ikb)
    
    # 2. Safar bo'lsa masofa hisoblash
    tr = conn.execute("SELECT is_riding, last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    if tr and tr[0] == 1:
        last_lat, last_lon, total_dist = tr[1], tr[2], tr[3]
        if last_lat > 0:
            step = get_dist(last_lat, last_lon, lat, lon)
            if 0.01 < step < 1.0:
                conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (total_dist + step, lat, lon, did))
        else: conn.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, did))
    
    conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "go_offline")
async def go_offline(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='offline' WHERE user_id=?", (call.from_user.id,))
    conn.commit(); conn.close()
    await call.message.edit_text("🔴 Siz navbatdan chiqdingiz va offlinesiz.")

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    new_wait = tr[1] + ((time.time() - tr[0])/60 if tr[0] > 0 else 0)
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=?, last_lat=?, last_lon=? WHERE driver_id=?", (new_wait, dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close(); await call.answer("Safar boshlandi!")

@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id)); conn.commit(); conn.close()
    await call.message.edit_text("Ojidaniye yoqildi."); asyncio.create_task(taximeter_loop(call.from_user.id))

@driver_dp.callback_query(F.data == "wait_play")
async def wait_play(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id)); conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "wait_pause")
async def wait_pause(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0: conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[1] + (time.time()-tr[0])/60, call.from_user.id)); conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "fin_pre")
async def finish(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        w_min = tr[4] + ((time.time() - tr[3])/60 if tr[3] > 0 else 0)
        total = START_PRICE + (int(w_min) * WAIT_PRICE) + (tr[7] * KM_PRICE)
        res = f"🏁 Yakunlandi\n💰 Jami: {int(total)} so'm\n🛣 Masofa: {tr[7]:.2f} km"
        await call.message.edit_text(res); await client_bot.send_message(tr[1], res)
        conn.execute("UPDATE drivers SET status='offline' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

# --- QABUL / RAD ETISH ---
@driver_dp.callback_query(F.data.startswith("skip_"))
async def skip_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await call.message.edit_text("🔄 Rad etildi."); await find_and_send_driver(int(cid), "Mijoz", cph, float(lat), float(lon), exclude_id=call.from_user.id)

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_"); await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE); d = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    c_msg = await client_bot.send_message(cid, f"🚕 Haydovchi: {d[0]} ({d[3]})\n📞 {d[1]}")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await msg.edit_text(f"✅ Mijoz raqami: {cph}", reply_markup=ikb) if msg else await driver_bot.send_message(did, f"✅ Mijoz raqami: {cph}", reply_markup=ikb)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?)", (did, cid, cph, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,)); conn.commit(); conn.close()

# --- REGISTRATION ---
@driver_dp.message(Command("start"))
async def dr_start(message: types.Message, command: CommandObject, state: FSMContext):
    if command.args and command.args.startswith("gr_"):
        p = command.args.split("_"); return await start_trip_logic(message.from_user.id, int(p[1]), p[4], float(p[2]), float(p[3]))
    conn = sqlite3.connect(DB_FILE); user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone(); conn.close()
    if not user: await state.set_state(DriverReg.name); await message.answer("Ismingiz:")
    else: await message.answer("Ishni boshlash uchun Live Location yuboring.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.name)
async def dr_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text); await state.set_state(DriverReg.phone); await message.answer("Raqam:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def dr_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number); await state.set_state(DriverReg.car_model); await message.answer("Moshina rusumi:", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def dr_model(message: types.Message, state: FSMContext):
    await state.update_data(model=message.text); await state.set_state(DriverReg.car_number); await message.answer("Moshina raqami:")

@driver_dp.message(DriverReg.car_number)
async def dr_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num, status) VALUES (?,?,?,?,?,'offline')", (message.from_user.id, d['name'], d['phone'], d['model'], message.text))
    conn.commit(); conn.close(); await state.clear(); await message.answer("✅ Tayyor! /start")

# --- MIJOZ BOTI ---
@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    await message.answer("📍 Lokatsiya yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya", request_location=True)]], resize_keyboard=True))

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude); await state.set_state(ClientOrder.waiting_phone)
    await message.answer("📱 Raqamingiz:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); await find_and_send_driver(message.from_user.id, message.from_user.full_name, message.contact.phone_number, d['lat'], d['lon'])
    await message.answer("⏳ Qidirilmoqda...", reply_markup=ReplyKeyboardRemove()); await state.clear()

async def find_and_send_driver(c_id, c_name, c_phone, lat, lon, exclude_id=None):
    station = find_station(lat, lon); conn = sqlite3.connect(DB_FILE)
    q = "SELECT user_id FROM drivers WHERE status='online' AND station=? ORDER BY last_seen ASC"
    drivers = conn.execute(q, (station,)).fetchall()
    conn.close()
    
    target_dr = None
    for (uid,) in drivers:
        if exclude_id and uid == exclude_id: continue
        target_dr = uid; break
    
    if target_dr:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}"), InlineKeyboardButton(text="🔄 Skip", callback_data=f"skip_{c_id}_{c_phone}_{lat}_{lon}")]])
        await driver_bot.send_message(target_dr, f"🚕 Yangi buyurtma!\n📞: {c_phone}", reply_markup=ikb)
    else:
        link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{c_id}_{lat}_{lon}_{c_phone}"
        await client_bot.send_message(GROUP_ID, f"📢 Bo'sh haydovchi yo'q! Bekat: {station}\n[Olish]({link})", parse_mode="Markdown")

async def main():
    init_db(); await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
