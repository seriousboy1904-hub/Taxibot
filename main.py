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

START_PRICE, WAIT_PRICE = 5000, 500 # 500 so'm/daq

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

# --- HOLATLAR ---
class DriverReg(StatesGroup):
    name = State()
    phone = State()
    car_model = State()
    car_number = State()

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
         start_time REAL, wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         s_lat REAL, s_lon REAL, driver_msg_id INTEGER, client_msg_id INTEGER)''')
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
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start_cmd(message: types.Message, command: CommandObject, state: FSMContext):
    if command.args and command.args.startswith("gr_"):
        p = command.args.split("_")
        return await start_trip_logic(message.from_user.id, int(p[1]), p[4], float(p[2]), float(p[3]))

    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)]], resize_keyboard=True)
        await message.answer("Ishni boshlash uchun **Live Location** yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.name)
        await message.answer("Ismingizni kiriting:")

@driver_dp.message(DriverReg.name)
async def reg_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text); await state.set_state(DriverReg.phone)
    await message.answer("Telefon raqamni yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def reg_phone(message: types.Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number); await state.set_state(DriverReg.car_model)
    await message.answer("Mashina rusumi (Cobalt, Nexia...):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def reg_model(message: types.Message, state: FSMContext):
    await state.update_data(model=message.text); await state.set_state(DriverReg.car_number)
    await message.answer("Mashina raqami (01A777AA):")

@driver_dp.message(DriverReg.car_number)
async def reg_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num) VALUES (?,?,?,?,?)", (message.from_user.id, data['name'], data['phone'], data['model'], message.text))
    conn.commit(); conn.close(); await state.clear()
    await message.answer("✅ Ro'yxatdan o'tdingiz! /start bosing.")

@driver_dp.message(F.location)
async def driver_loc(message: types.Message):
    if message.location.live_period is None:
        await message.answer("⚠️ Faqat **Live Location** yuboring!"); return
    st = find_station(message.location.latitude, message.location.longitude)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", (st, message.location.latitude, message.location.longitude, datetime.now().isoformat(), message.from_user.id))
    conn.commit(); conn.close()
    await message.answer(f"✅ Onlinesiz! Bekat: {st}")

# --- TRIP LOGIC & OJIDANIYA ---

@driver_dp.callback_query(F.data == "wait_on" or F.data == "wait_refresh")
async def wait_logic(call: CallbackQuery):
    now = time.time()
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, client_msg_id, wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if not tr: return
    
    # Agar birinchi marta yoqilayotgan bo'lsa (wait_start == 0)
    w_start = tr[2] if tr[2] > 0 else now
    if tr[2] == 0:
        conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (now, call.from_user.id))
        conn.commit()

    # Hisoblash
    current_session = (now - w_start) / 60
    total_m = int(tr[3] + current_session)
    summa = START_PRICE + (total_m * WAIT_PRICE)
    
    txt = f"⏳ Kutish vaqti: {total_m} daq\n💰 Joriy summa: {summa} so'm"
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Safarni davom ettirish", callback_data="wait_off")],
        [InlineKeyboardButton(text="🔄 Vaqtni yangilash", callback_data="wait_refresh")]
    ])
    
    try:
        await call.message.edit_text(txt, reply_markup=ikb)
        await client_bot.edit_message_text(chat_id=tr[0], message_id=tr[1], text=f"⏳ Haydovchi kutmoqda...\n{txt}")
    except: pass
    conn.close()

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    now = time.time()
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait, client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if tr and tr[0] > 0:
        new_total = tr[1] + ((now - tr[0]) / 60)
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (new_total, call.from_user.id))
        conn.commit()
        
        total_m = int(new_total)
        summa = START_PRICE + (total_m * WAIT_PRICE)
        txt = f"🚖 Safar davom etmoqda.\n⏳ Umumiy ojidaniya: {total_m} daq\n💰 Hisob: {summa} so'm"
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")], [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
        await call.message.edit_text(txt, reply_markup=ikb)
        await client_bot.edit_message_text(chat_id=tr[2], message_id=tr[3], text=f"▶️ Safar davom etmoqda...\n{txt}")
    conn.close()

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    conn = sqlite3.connect(DB_FILE)
    d = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    c_msg = await client_bot.send_message(cid, f"🚕 Haydovchi topildi!\n👤: {d[0]}\n🚗: {d[2]} ({d[3]})\n📞: {d[1]}")
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await call.message.edit_text(f"✅ Qabul qilindi! 📞 {cph}", reply_markup=ikb)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?,?,?)", (did, cid, cph, lat, lon, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,)); conn.commit(); conn.close()

@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone(); conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya boshlash", callback_data="wait_on")], [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="can_pre")]])
    await call.message.edit_text("Mijozga 'Yetib keldim' xabari yuborildi.", reply_markup=ikb)
    if tr: await client_bot.edit_message_text(chat_id=tr[0], message_id=tr[1], text="🚕 Haydovchi yetib keldi! Chiqishingiz mumkin.")

# ==========================================
# 🚕 MIJOZ BOTI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    await message.answer("Taksi chaqirish uchun lokatsiya yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya", request_location=True)]], resize_keyboard=True))

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude); await state.set_state(ClientOrder.waiting_phone)
    await message.answer("Telefoningizni yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_final(message: types.Message, state: FSMContext):
    d = await state.get_data(); station = find_station(d['lat'], d['lon'])
    conn = sqlite3.connect(DB_FILE); dr = conn.execute("SELECT user_id FROM drivers WHERE status='online' AND station=? LIMIT 1", (station,)).fetchone(); conn.close()
    if dr:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul", callback_data=f"acc_{message.from_user.id}_{message.contact.phone_number}_{d['lat']}_{d['lon']}")]])
        await driver_bot.send_message(dr[0], f"🚕 Buyurtma!\n📞: {message.contact.phone_number}", reply_markup=ikb)
    else:
        link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{message.from_user.id}_{d['lat']}_{d['lon']}_{message.contact.phone_number}"
        await client_bot.send_message(GROUP_ID, f"📢 Bo'sh haydovchi yo'q! Bekat: {station}\n[Buyurtmani olish]({link})", parse_mode="Markdown")
    await message.answer("⏳ Haydovchi qidirilmoqda...", reply_markup=ReplyKeyboardRemove()); await state.clear()

# --- FINISH & CANCEL ---
@driver_dp.callback_query(F.data == "fin_pre")
async def finish(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE); tr = conn.execute("SELECT client_id, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        res = f"🏁 Safar yakunlandi!\n💰 Jami: {START_PRICE + (int(tr[1])*WAIT_PRICE)} so'm"
        await call.message.edit_text(res); await client_bot.send_message(tr[0], res)
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,)); conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,)); conn.commit()
    conn.close()

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
