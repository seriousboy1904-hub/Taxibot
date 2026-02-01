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

# Logging sozlash
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
    c_lat, c_lon = data['lat'], data['lon']
    c_phone = message.contact.phone_number
    await find_and_send_driver(message.from_user.id, message.from_user.full_name, c_phone, c_lat, c_lon)
    await message.answer("⏳ Buyurtma haydovchilarga yuborildi. Iltimos, kuting...", reply_markup=ReplyKeyboardRemove())
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
        d_id, d_name, d_lat, d_lon = driver
        dist = get_dist(d_lat, d_lon, lat, lon)
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}")],
            [InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{c_id}_{c_phone}_{lat}_{lon}")]
        ])
        try:
            await driver_bot.send_location(d_id, lat, lon)
            await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}\n📏 Masofa: {dist:.1f} km", reply_markup=ikb)
        except: pass
    else:
        # Hech kim topilmasa guruhga tashlash
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
        _, cid, lat, lon, cph = command.args.split("_")
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

@driver_dp.message(DriverReg.phone, F.contact)
async def reg_p(message: types.Message, state: FSMContext):
    await state.update_data(p=message.contact.phone_number)
    cars = [["Nexia 3", "Cobalt"], ["Gentra", "Spark"], ["Damas"]]
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c) for c in r] for r in cars], resize_keyboard=True)
    await state.set_state(DriverReg.car_model)
    await message.answer("2. Mashina rusumini tanlang:", reply_markup=kb)

@driver_dp.message(DriverReg.car_model)
async def reg_c(message: types.Message, state: FSMContext):
    await state.update_data(c=message.text)
    await state.set_state(DriverReg.car_number)
    await message.answer("3. Mashina raqamini kiriting (Masalan: 01A777AA):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_number)
async def reg_f(message: types.Message, state: FSMContext):
    d = await state.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num, status, joined_at) VALUES (?,?,?,?,?,?,?)",
                 (message.from_user.id, message.from_user.full_name, d['p'], d['c'], message.text, 'offline', datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await state.clear()
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)]], resize_keyboard=True)
    await message.answer("✅ Ro'yxatdan o'tdingiz! Endi ishni boshlashingiz mumkin.", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_loc_upd(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    d_id = message.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT total_dist, last_lat, last_lon FROM trips WHERE driver_id=?", (d_id,)).fetchone()
    
    if trip:
        # Safar davom etmoqda - KM hisoblash
        total_dist, last_lat, last_lon = trip
        if last_lat and last_lon:
            new_dist = get_dist(last_lat, last_lon, lat, lon)
            total_dist += new_dist
        
        conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                     (total_dist, lat, lon, d_id))
        conn.commit()
    else:
        # Online rejim
        st = find_station(lat, lon)
        conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                     (st, lat, lon, datetime.now().isoformat(), d_id))
        conn.commit()
        await message.answer(f"✅ Onlinesiz! Bekat: {st}")
    conn.close()

# --- CALLBACKS ---

@driver_dp.callback_query(F.data.startswith("skip_"))
async def skip_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await call.message.edit_text("🔄 Buyurtma o'tkazib yuborildi.")
    await find_and_send_driver(int(cid), "Mijoz", cph, float(lat), float(lon), exclude_id=call.from_user.id)

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    await start_trip_logic(call.from_user.id, int(cid), cph, float(lat), float(lon), call.message)

async def start_trip_logic(did, cid, cph, lat, lon, msg=None):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, last_lat, last_lon) VALUES (?,?,?,?,?,?,?)", 
                 (did, cid, cph, lat, lon, lat, lon))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    t = f"✅ Qabul qilindi! 📞 {cph}\n\nBorish manzilingiz lokatsiyada ko'rinmoqda. 'Yetib keldim' tugmasini bosing."
    if msg: await msg.edit_text(t, reply_markup=ikb)
    else: await driver_bot.send_message(did, t, reply_markup=ikb)

@driver_dp.callback_query(F.data == "arrived")
async def arr_call(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="can_pre")]
    ])
    await call.message.edit_text("Mijozga 'Yetib keldim' xabari yuborildi. Safar boshlanganda ojidaniyani to'xtating.", reply_markup=ikb)
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    conn.close()
    if trip: 
        try: await client_bot.send_message(trip[0], "🚕 Haydovchi yetib keldi!")
        except: pass

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Ojidaniyani to'xtatish", callback_data="wait_off")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("⏱ Kutish (Ojidaniya) yoqildi...", reply_markup=ikb)

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if trip and trip[0] > 0:
        added = (time.time() - trip[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (added, call.from_user.id))
        conn.commit()
    conn.close()
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
    ])
    await call.message.edit_text("🚖 Safar davom etmoqda. Bosib o'tilgan masofa va kutish hisoblanmoqda.", reply_markup=ikb)

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_pre(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, total_dist FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if tr:
        client_id, wait_min, dist_km = tr
        wait_cost = int(wait_min) * WAIT_PRICE
        dist_cost = round(dist_km, 1) * KM_PRICE
        total_price = round((START_PRICE + wait_cost + dist_cost) / 100) * 100

        res = (f"🏁 **Safar yakunlandi!**\n\n"
               f"💰 Boshlang'ich: {START_PRICE} so'm\n"
               f"🛣 Masofa: {dist_km:.1f} km ({dist_cost:,.0f} so'm)\n"
               f"⏳ Kutish: {int(wait_min)} daq ({wait_cost:,.0f} so'm)\n"
               f"--- --- --- --- ---\n"
               f"💵 **JAMI: {total_price:,.0f} so'm**")
        
        await call.message.edit_text(res, parse_mode="Markdown")
        try: await client_bot.send_message(client_id, res, parse_mode="Markdown")
        except: pass
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "can_pre")
async def can_pre(call: CallbackQuery):
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ha", callback_data="can_yes"), InlineKeyboardButton(text="❌ Yo'q", callback_data="arrived")]])
    await call.message.edit_text("⚠️ Rostdan bekor qilasizmi?", reply_markup=ikb)

@driver_dp.callback_query(F.data == "can_yes")
async def can_yes(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
    conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()
    await call.message.edit_text("❌ Buyurtma bekor qilindi.")

async def main():
    init_db()
    # Har ikki botni birga ishga tushirish
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
