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

# --- SOZLAMALAR ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# Tariflar
MIN_PRICE, KM_PRICE, WAIT_PRICE = 5000, 1000, 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    name = State()
    phone = State()
    car_model = State()
    car_number = State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- BAZA BILAN ISHLASH ---
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
# 🔄 TAXIMETER LOOP (TUGMALARNI YANGILASH)
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
        
        kb = []
        # Ojidaniye tugmasi
        if wait_start > 0:
            kb.append([InlineKeyboardButton(text="⏸ Kutishni to'xtatish", callback_data="wait_pause")])
        else:
            kb.append([InlineKeyboardButton(text="▶️ Ojidaniye boshlash", callback_data="wait_play")])
        
        # Safar holati tugmasi
        if is_riding == 0:
            kb.append([InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")])
        else:
            kb.append([InlineKeyboardButton(text="🏁 YAKUNLASH", callback_data="fin_pre")])

        txt = f"{'🚖 Safarda' if is_riding else '⏳ To`xtab turibdi'}\n\n🛣 Masofa: {total_dist:.2f} km\n⏱ Kutish: {int(curr_wait)} daq\n💰 Summa: {summa} so'm"
        
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
    await call.message.edit_text("Siz manzildasiz. Kerakli amalni tanlang:", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Ojidaniye boshlash", callback_data="wait_play")],
            [InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")]
        ]))
    asyncio.create_task(taximeter_loop(call.from_user.id))

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    new_wait = tr[1] + ((time.time() - tr[0])/60 if tr[0] > 0 else 0)
    
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                 (new_wait, dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Safar boshlandi, masofa hisoblanmoqda!")

@driver_dp.callback_query(F.data == "wait_play")
async def wait_play_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "wait_pause")
async def wait_pause_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        added = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[1] + added, call.from_user.id))
        conn.commit()
    conn.close()

@driver_dp.message(F.location)
async def loc_receiver(message: types.Message):
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    conn = sqlite3.connect(DB_FILE)
    
    # Live location orqali online bo'lish
    if message.location.live_period:
        st = find_station(lat, lon)
        conn.execute("UPDATE drivers SET status='online', last_seen=?, station=?, lat=?, lon=? WHERE user_id=?", (time.time(), st, lat, lon, did))
    
    # Masofa hisoblash
    tr = conn.execute("SELECT is_riding, last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    if tr and tr[0] == 1:
        step = get_dist(tr[1], tr[2], lat, lon)
        if 0.005 < step < 0.6:
            conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (tr[3]+step, lat, lon, did))
    conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_cb(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        w_min = tr[4] + ((time.time() - tr[3])/60 if tr[3] > 0 else 0)
        total = int(MIN_PRICE + ((tr[7]-1)*KM_PRICE if tr[7]>1 else 0) + (int(w_min)*WAIT_PRICE))
        res = f"🏁 Safar yakunlandi!\n🛣 Masofa: {tr[7]:.2f} km\n💰 Jami: {total} so'm"
        await call.message.edit_text(res); await client_bot.send_message(tr[1], res)
        conn.execute("UPDATE drivers SET status='offline' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

# ==========================================
# 🚕 BUYURTMA VA RO'YXATDAN O'TISH
# ==========================================

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE); d = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    # Mijozga haydovchi xabari
    await client_bot.send_message(cid, f"🚕 Haydovchi topildi!\n👤 {d[0]}\n🚗 {d[2]} ({d[3]})\n📞 {d[1]}")
    c_msg = await client_bot.send_message(cid, "Safar boshlanishini kuting...")
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await msg.edit_text(f"✅ Buyurtma qabul qilindi\n📞 Mijoz: {cph}", reply_markup=ikb) if msg else await driver_bot.send_message(did, f"✅ Buyurtma: {cph}", reply_markup=ikb)
    
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?)", (did, cid, cph, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,)); conn.commit(); conn.close()

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_"); await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

@driver_dp.message(Command("start"))
async def dr_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE); u = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone(); conn.close()
    if not u: await state.set_state(DriverReg.name); await message.answer("Ismingiz:")
    else: await message.answer("Online bo'lish uchun Live Location yuboring.", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Online", request_location=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.name)
async def dr_n(m, s): await s.update_data(n=m.text); await s.set_state(DriverReg.phone); await m.answer("Raqam:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Yuborish", request_contact=True)]], resize_keyboard=True))
@driver_dp.message(DriverReg.phone, F.contact)
async def dr_p(m, s): await s.update_data(p=m.contact.phone_number); await s.set_state(DriverReg.car_model); await m.answer("Mashina rusumi:", reply_markup=ReplyKeyboardRemove())
@driver_dp.message(DriverReg.car_model)
async def dr_m(m, s): await s.update_data(m=m.text); await s.set_state(DriverReg.car_number); await m.answer("Mashina raqami:")
@driver_dp.message(DriverReg.car_number)
async def dr_f(m, s):
    d = await s.get_data(); conn = sqlite3.connect(DB_FILE); conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num) VALUES (?,?,?,?,?)", (m.from_user.id, d['n'], d['p'], d['m'], m.text)); conn.commit(); conn.close(); await s.clear(); await m.answer("✅ Ro'yxatdan o'tdingiz! /start")

# --- MIJOZ BOTI ---
@client_dp.message(Command("start"))
async def c_start(m): await m.answer("📍 Taxi uchun lokatsiya yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya", request_location=True)]], resize_keyboard=True))
@client_dp.message(F.location)
async def c_loc(m, s): await s.update_data(lat=m.location.latitude, lon=m.location.longitude); await s.set_state(ClientOrder.waiting_phone); await m.answer("📞 Raqamingiz:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))
@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def c_final(m, s):
    d = await s.get_data(); st = find_station(d['lat'], d['lon']); conn = sqlite3.connect(DB_FILE)
    dr = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? ORDER BY last_seen ASC LIMIT 1", (st,)).fetchone(); conn.close()
    if dr:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul", callback_data=f"acc_{m.from_user.id}_{m.contact.phone_number}_{d['lat']}_{d['lon']}")]])
        await driver_bot.send_message(dr[0], f"🚕 Yangi buyurtma!\n📞 {m.contact.phone_number}", reply_markup=ikb)
        await m.answer("⏳ Haydovchi topildi, xabar yuborildi.", reply_markup=ReplyKeyboardRemove())
    else: await m.answer("⚠️ Hozircha bo'sh haydovchi yo'q."); await s.clear()

async def main():
    init_db(); await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
