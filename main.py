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

# NARXLAR
START_PRICE = 5000       # Shahar ichi boshlanishi
WAIT_PRICE = 500         # 1 daqiqa kutish
KM_PRICE = 1500          # 1 km yurish uchun

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
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         ride_start_lat REAL DEFAULT 0, ride_start_lon REAL DEFAULT 0,
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
# 🔄 LIVE TAXIMETER (OJIDANIYA VA MASOFA)
# ==========================================

async def taximeter_loop(did):
    """Ojidaniya yoki Safar vaqtida har 10 soniyada ma'lumotni yangilaydi"""
    while True:
        await asyncio.sleep(10)
        conn = sqlite3.connect(DB_FILE)
        tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (did,)).fetchone()
        
        if not tr: conn.close(); break
        
        # Ma'lumotlarni indeks bo'yicha olish (init_db dagi tartibda)
        cid, wait_start, total_wait_min = tr[1], tr[3], tr[4]
        last_lat, last_lon, total_dist, is_riding = tr[7], tr[8], tr[9], tr[10]
        d_msg_id, c_msg_id = tr[11], tr[12]

        # Haydovchining oxirgi onlayn koordinatasini olish
        dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (did,)).fetchone()
        
        current_wait_min = total_wait_min
        if wait_start > 0:
            current_wait_min += (time.time() - wait_start) / 60

        ride_dist = total_dist
        if is_riding == 1 and dr:
            d = get_dist(last_lat, last_lon, dr[0], dr[1])
            if d < 0.5: # Sakrashlarni oldini olish (max 0.5km 10 sekunda)
                ride_dist += d
                conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", (ride_dist, dr[0], dr[1], did))
                conn.commit()

        summa = START_PRICE + (int(current_wait_min) * WAIT_PRICE) + (ride_dist * KM_PRICE)
        
        status_txt = "🚕 Safar davom etmoqda..." if is_riding else "⏳ Kutish rejimi..."
        txt = f"{status_txt}\n⏱ Kutish: {int(current_wait_min)} daq\n🛣 Masofa: {ride_dist:.2f} km\n💰 Hisob: {int(summa)} so'm"
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[])
        if is_riding == 0:
            ikb.inline_keyboard.append([InlineKeyboardButton(text="▶️ Safarni boshlash", callback_data="ride_start")])
        ikb.inline_keyboard.append([InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")])

        try:
            await driver_bot.edit_message_text(chat_id=did, message_id=d_msg_id, text=txt, reply_markup=ikb)
            await client_bot.edit_message_text(chat_id=cid, message_id=c_msg_id, text=txt)
        except: pass
        conn.close()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def dr_start(message: types.Message, command: CommandObject, state: FSMContext):
    if command.args and command.args.startswith("gr_"):
        p = command.args.split("_")
        return await start_trip_logic(message.from_user.id, int(p[1]), p[4], float(p[2]), float(p[3]))
    
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if not user:
        await state.set_state(DriverReg.name); await message.answer("Ismingizni kiriting:")
    else:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)]], resize_keyboard=True)
        await message.answer("Xizmatga tayyormisiz?", reply_markup=kb)

# --- REGISTRATION ---
@driver_dp.message(DriverReg.name)
async def dr_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text); await state.set_state(DriverReg.phone)
    await message.answer("Raqamingiz:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def dr_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number); await state.set_state(DriverReg.car_model)
    await message.answer("Moshina rusumi:", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def dr_model(message: types.Message, state: FSMContext):
    await state.update_data(model=message.text); await state.set_state(DriverReg.car_number)
    await message.answer("Moshina raqami:")

@driver_dp.message(DriverReg.car_number)
async def dr_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num) VALUES (?,?,?,?,?)", (message.from_user.id, d['name'], d['phone'], d['model'], message.text))
    conn.commit(); conn.close(); await state.clear(); await message.answer("✅ Ro'yxatdan o'tdingiz! /start")

@driver_dp.message(F.location)
async def dr_loc(message: types.Message):
    if message.location.live_period is None:
        await message.answer("⚠️ Faqat 'Live Location' yuboring!"); return
    st = find_station(message.location.latitude, message.location.longitude)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=? WHERE user_id=?", (st, message.location.latitude, message.location.longitude, message.from_user.id))
    conn.commit(); conn.close(); await message.answer(f"✅ Onlinesiz! Bekat: {st}")

# --- SAFAR BOSHQARUVI ---

@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit(); conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Safarni boshlash", callback_data="ride_start")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("Yetib keldingiz. Mijoz chiqishi bilan 'Safarni boshlash'ni bosing.", reply_markup=ikb)
    asyncio.create_task(taximeter_loop(call.from_user.id))

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    dr = conn.execute("SELECT lat, lon FROM drivers WHERE user_id=?", (call.from_user.id,)).fetchone()
    
    new_wait = tr[1] + ((time.time() - tr[0]) / 60)
    conn.execute("UPDATE trips SET wait_start=0, total_wait=?, is_riding=1, ride_start_lat=?, ride_start_lon=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                 (new_wait, dr[0], dr[1], dr[0], dr[1], call.from_user.id))
    conn.commit(); conn.close()
    await call.answer("Safar boshlandi!")

@driver_dp.callback_query(F.data == "fin_pre")
async def finish_trip(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        # Yakuniy hisob
        w_min = tr[4] + ((time.time() - tr[3])/60 if tr[3] > 0 else 0)
        dist = tr[9]
        total = START_PRICE + (int(w_min) * WAIT_PRICE) + (dist * KM_PRICE)
        
        res = f"🏁 Safar yakunlandi!\n\n⏱ Kutish: {int(w_min)} daq\n🛣 Masofa: {dist:.2f} km\n💰 Jami: {int(total)} so'm"
        await call.message.edit_text(res)
        await client_bot.send_message(tr[1], res)
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# --- QABUL VA SKIP ---
@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE); d = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    c_msg = await client_bot.send_message(cid, f"🚕 Haydovchi topildi!\n👤: {d[0]}\n🚗: {d[2]} ({d[3]})\n📞: {d[1]}")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await msg.edit_text(f"✅ Qabul qilindi. 📞 {cph}", reply_markup=ikb) if msg else await driver_bot.send_message(did, f"✅ Qabul qilindi. 📞 {cph}", reply_markup=ikb)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?)", (did, cid, cph, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,)); conn.commit(); conn.close()

# --- MIJOZ BOTI ---
@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    await message.answer("Lokatsiya yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya", request_location=True)]], resize_keyboard=True))

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude); await state.set_state(ClientOrder.waiting_phone)
    await message.answer("Raqamingiz:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); station = find_station(d['lat'], d['lon'])
    conn = sqlite3.connect(DB_FILE); dr = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? LIMIT 1", (station,)).fetchone(); conn.close()
    if dr:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul", callback_data=f"acc_{message.from_user.id}_{message.contact.phone_number}_{d['lat']}_{d['lon']}")]])
        await driver_bot.send_message(dr[0], f"🚕 Buyurtma!\n📞: {message.contact.phone_number}", reply_markup=ikb)
    else:
        link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{message.from_user.id}_{d['lat']}_{d['lon']}_{message.contact.phone_number}"
        await client_bot.send_message(GROUP_ID, f"📢 Bo'sh haydovchi yo'q! Bekat: {station}\n[Olish]({link})", parse_mode="Markdown")
    await message.answer("⏳ Qidirilmoqda..."); await state.clear()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
