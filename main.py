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
         start_time REAL, wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         total_dist REAL DEFAULT 0, last_lat REAL, last_lon REAL, s_lat REAL, s_lon REAL)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371 # Yer radiusi
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
# 👨‍✈️ HAYDOVCHI LOKATSIYASINI KUZATISH (MASOFA UCHUN)
# ==========================================

async def update_trip_distance(d_id, lat, lon):
    """Haydovchi harakatlanganda masofani hisoblash"""
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT total_dist, last_lat, last_lon FROM trips WHERE driver_id=?", (d_id,)).fetchone()
    
    if trip:
        total_dist, last_lat, last_lon = trip
        if last_lat and last_lon:
            step_dist = get_dist(last_lat, last_lon, lat, lon)
            # Agar haydovchi kamida 20 metr yursa, masofani qo'shamiz (GPS xatoligi uchun)
            if step_dist > 0.02:
                total_dist += step_dist
                conn.execute("UPDATE trips SET total_dist=?, last_lat=?, last_lon=? WHERE driver_id=?", 
                             (total_dist, lat, lon, d_id))
                conn.commit()
        else:
            conn.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, d_id))
            conn.commit()
    conn.close()

@driver_dp.message(F.location)
async def driver_loc_msg(message: types.Message):
    # Oddiy lokatsiya yuborilganda (ishni boshlashda)
    lat, lon = message.location.latitude, message.location.longitude
    st = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', station=?, lat=?, lon=?, joined_at=? WHERE user_id=?", 
                 (st, lat, lon, datetime.now().isoformat(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Onlinesiz! Bekat: {st}\nSafar boshlangach, masofa hisoblanishi uchun 'Live Location' ulashing.")

@driver_dp.edited_message(F.location)
async def driver_live_loc(message: types.Message):
    # Jonli lokatsiya tahrirlanganda (safar davomida)
    await update_trip_distance(message.from_user.id, message.location.latitude, message.location.longitude)

# ==========================================
# 🚕 MIJOZ BOTI MANTIQI
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
    await message.answer("⏳ Buyurtma haydovchilarga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

async def find_and_send_driver(c_id, c_name, c_phone, lat, lon, exclude_id=None):
    station = find_station(lat, lon)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    sql = "SELECT user_id FROM drivers WHERE status = 'online' AND station = ?"
    params = [station]
    if exclude_id:
        sql += " AND user_id != ?"
        params.append(exclude_id)
    sql += " ORDER BY joined_at ASC LIMIT 1"
    driver = cursor.execute(sql, params).fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{lat}_{lon}")],
            [InlineKeyboardButton(text="🔄 Skip", callback_data=f"skip_{c_id}_{c_phone}_{lat}_{lon}")]
        ])
        await driver_bot.send_location(d_id, lat, lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
    else:
        # Guruhga yuborish
        link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{c_id}_{lat}_{lon}_{c_phone}"
        await client_bot.send_location(GROUP_ID, lat, lon)
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}", 
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚖 Olish", url=link)]]))

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (SAFAR BOSHQARUVI)
# ==========================================

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, last_lat, last_lon) VALUES (?,?,?,?,?,?,?)", 
                 (call.from_user.id, cid, cph, lat, lon, lat, lon))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (call.from_user.id,))
    conn.commit()
    conn.close()
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    await call.message.edit_text(f"✅ Qabul qilindi! 📞 {cph}\nManzilga yetgach tugmani bosing.", reply_markup=ikb)

@driver_dp.callback_query(F.data == "fin_pre")
async def fin_pre(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, total_dist FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        c_id, wait_min, dist_km = tr
        wait_price = int(wait_min) * WAIT_PRICE
        dist_price = dist_km * KM_PRICE
        total = round((START_PRICE + wait_price + dist_price) / 100) * 100

        res = (f"🏁 **Safar yakunlandi!**\n"
               f"🛣 Masofa: {dist_km:.1f} km ({dist_price:,.0f} so'm)\n"
               f"⏳ Kutish: {int(wait_min)} daq ({wait_price:,.0f} so'm)\n"
               f"💵 **JAMI: {total:,.0f} so'm**")
        
        await call.message.edit_text(res, parse_mode="Markdown")
        try: await client_bot.send_message(c_id, res, parse_mode="Markdown")
        except: pass
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# ... (Boshqa yordamchi callbacklar: arrived, wait_on, wait_off kodingizdagi kabi qoladi)

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
