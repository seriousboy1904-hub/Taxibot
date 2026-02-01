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

START_PRICE, WAIT_PRICE = 5000, 500 

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
# 🚕 MIJOZ BOTI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiyangizni yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("📱 Telefon raqamingizni yuboring:", reply_markup=kb)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await find_and_send_driver(message.from_user.id, message.from_user.full_name, message.contact.phone_number, data['lat'], data['lon'])
    await message.answer("⏳ Buyurtma haydovchilarga yuborildi. Iltimos kuting...", reply_markup=ReplyKeyboardRemove())
    await state.clear()

async def find_and_send_driver(c_id, c_name, c_phone, lat, lon, exclude_id=None):
    station = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    query = "SELECT user_id, name, lat, lon FROM drivers WHERE status = 'online' AND station = ?"
    params = [station]
    if exclude_id:
        query += " AND user_id != ?"
        params.append(exclude_id)
    query += " ORDER BY joined_at ASC LIMIT 1"
    
    cursor.execute(query, params)
    driver = cursor.fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        dist = get_dist(driver[2], driver[3], lat, lon)
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}")],
            [InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{c_id}_{c_phone}_{lat}_{lon}")]
        ])
        await driver_bot.send_location(d_id, lat, lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}\n📏 Masofa: {dist:.1f} km", reply_markup=ikb)
    else:
        link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{c_id}_{lat}_{lon}_{c_phone}"
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]])
        await client_bot.send_location(GROUP_ID, lat, lon)
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {c_name}", reply_markup=ikb)

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start_cmd(message: types.Message, command: CommandObject, state: FSMContext):
    if command.args and command.args.startswith("gr_"):
        parts = command.args.split("_")
        return await start_trip_logic(message.from_user.id, int(parts[1]), parts[4], float(parts[2]), float(parts[3]))

    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()

    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)]], resize_keyboard=True)
        await message.answer("Xush kelibsiz! Ishni boshlash uchun **Live Location** yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
        await message.answer("Ro'yxatdan o'tish:\n1. Telefon raqamingizni yuboring:", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_location_handler(message: types.Message):
    if message.location.live_period is None:
        await message.answer("⚠️ Faqat **Live Location** (Jonli joylashuv) qabul qilinadi!\n\nLocation -> Share My Live Location (8 soat).")
        return

    lat, lon = message.location.latitude, message.location.longitude
    st = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                 (st, lat, lon, datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Onlinesiz! Bekat: {st}")

# --- CALLBACKS & MANTIQ ---

@driver_dp.callback_query(F.data.startswith("skip_"))
async def skip_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await call.message.edit_text("🔄 Buyurtma keyingi haydovchiga yo'naltirildi.")
    await find_and_send_driver(int(cid), "Mijoz", cph, float(lat), float(lon), exclude_id=call.from_user.id)

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE)
    d_info = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    
    # Mijozga xabar
    c_msg = await client_bot.send_message(cid, f"🚕 Haydovchi qabul qildi!\n👤: {d_info[0]}\n🚗: {d_info[2]} ({d_info[3]})\n📞: {d_info[1]}")
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    if msg: d_msg = await msg.edit_text(f"✅ Qabul qilindi! 📞 {cph}", reply_markup=ikb)
    else: d_msg = await driver_bot.send_message(did, f"✅ Qabul qilindi! 📞 {cph}", reply_markup=ikb)
    
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?,?,?)", 
                 (did, cid, cph, lat, lon, d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "arrived")
async def arr_call(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya boshlash", callback_data="wait_on")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="can_pre")]
    ])
    await call.message.edit_text("Mijozga xabar yuborildi.", reply_markup=ikb)
    if trip: await client_bot.edit_message_text(chat_id=trip[0], message_id=trip[1], text="🚕 Haydovchi yetib keldi! Chiqishingiz mumkin.")

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    trip = conn.execute("SELECT client_id, client_msg_id, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    conn.commit()
    conn.close()

    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")], [InlineKeyboardButton(text="🔄 Yangilash", callback_data="wait_on")]])
    txt = f"⏱ Kutish yoqildi...\n⏳ Umumiy: {int(trip[2])} daq\n💰 Summa: {START_PRICE + (int(trip[2])*WAIT_PRICE)} so'm"
    await call.message.edit_text(txt, reply_markup=ikb)
    await client_bot.edit_message_text(chat_id=trip[0], message_id=trip[1], text=f"⏳ Haydovchi kutmoqda...\n{txt}")

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start, total_wait, client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip and trip[0] > 0:
        new_total = trip[1] + ((time.time() - trip[0]) / 60)
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (new_total, call.from_user.id))
        conn.commit()
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")], [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]])
        txt = f"🚖 Safar davom etmoqda.\n⏳ Kutish: {int(new_total)} daq\n💰 Hisob: {START_PRICE + (int(new_total)*WAIT_PRICE)} so'm"
        await call.message.edit_text(txt, reply_markup=ikb)
        await client_bot.edit_message_text(chat_id=trip[2], message_id=trip[3], text=f"▶️ Safar davom etmoqda...\n{txt}")
    conn.close()

@driver_dp.callback_query(F.data == "can_pre")
async def can_pre(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ha", callback_data="can_yes"), InlineKeyboardButton(text="❌ Yo'q", callback_data="arrived")]])
    await call.message.edit_text("⚠️ Rostdan bekor qilasizmi?", reply_markup=ikb)

@driver_dp.callback_query(F.data == "can_yes")
async def can_yes(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
    conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()
    await call.message.edit_text("❌ Bekor qilindi.")
    if trip: await client_bot.send_message(trip[0], "❌ Haydovchi buyurtmani bekor qildi.")

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_pre(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        res = f"🏁 Safar yakunlandi!\n💰 To'lov: {START_PRICE + (int(tr[1])*WAIT_PRICE)} so'm"
        await call.message.edit_text(res)
        await client_bot.send_message(tr[0], res)
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# --- REGISTRATION ---
@driver_dp.message(DriverReg.phone, F.contact)
async def dr_p(m: types.Message, s: FSMContext):
    await s.update_data(p=m.contact.phone_number)
    await s.set_state(DriverReg.car_model)
    await m.answer("2. Mashina rusumi (Nexia 3, Cobalt...):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def dr_c(m: types.Message, s: FSMContext):
    await s.update_data(c=m.text)
    await s.set_state(DriverReg.car_number)
    await m.answer("3. Mashina raqami (01A777AA):")

@driver_dp.message(DriverReg.car_number)
async def dr_n(m: types.Message, s: FSMContext):
    d = await s.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num) VALUES (?,?,?,?,?)", 
                 (m.from_user.id, m.from_user.full_name, d['p'], d['c'], m.text))
    conn.commit()
    conn.close()
    await s.clear()
    await m.answer("✅ Ro'yxatdan o'tdingiz! /start bosing.")

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
