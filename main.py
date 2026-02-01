import os, sqlite3, asyncio, time, math, json
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

load_dotenv()

# --- SOZLAMALAR ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

START_PRICE = 10000
NEXT_KM_PRICE = 1000
WAIT_PRICE = 1000

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- GEOGRAFIYA MANTIQI ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000 # metrda
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest_station(u_lat, u_lon):
    if not os.path.exists(GEOJSON_FILE): return "Noma'lum", 0
    with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    closest_name, min_dist = "Noma'lum", float('inf')
    for feat in data.get('features', []):
        coords = feat.get('geometry', {}).get('coordinates')
        name = feat.get('properties', {}).get('name', "Bekat")
        dist = calculate_distance(u_lat, u_lon, coords[1], coords[0])
        if dist < min_dist:
            min_dist, closest_name = dist, name
    return closest_name, min_dist

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, status TEXT DEFAULT 'offline', 
         station TEXT, lat REAL, lon REAL, joined_at TEXT)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         s_lat REAL, s_lon REAL, last_lat REAL, last_lon REAL, 
         distance REAL DEFAULT 0, msg_id INTEGER)''')
    conn.commit()
    conn.close()

# ==========================================
# 🚕 MIJOZ BOTI (BUYURTMA BERISH QISMI TO'G'RILANDI)
# ==========================================

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    st_name, _ = find_closest_station(message.location.latitude, message.location.longitude)
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude, station=st_name)
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer(f"📍 Hudud: {st_name}\nTasdiqlash uchun telefoningizni yuboring:", reply_markup=kb)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon, c_st = data['lat'], data['lon'], data['station']
    c_phone, c_id, c_name = message.contact.phone_number, message.from_user.id, message.from_user.full_name

    conn = sqlite3.connect(DB_FILE)
    # TO'G'IRLASH: Faqat aynan o'sha bekat emas, balki eng yaqin online haydovchini qidiramiz
    cursor = conn.execute("SELECT user_id, lat, lon FROM drivers WHERE status = 'online' ORDER BY joined_at ASC")
    all_drivers = cursor.fetchall()
    
    best_driver = None
    min_d = 5000 # 5 km radius ichida haydovchi qidiramiz

    for d_id, d_lat, d_lon in all_drivers:
        d_dist = calculate_distance(c_lat, c_lon, d_lat, d_lon)
        if d_dist < min_d:
            min_d = d_dist
            best_driver = d_id
            break # Birinchi navbatdagi eng yaqinini topdik

    if best_driver:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{c_lat}_{c_lon}")]])
        try:
            await driver_bot.send_location(best_driver, c_lat, c_lon)
            await driver_bot.send_message(best_driver, f"🚕 YANGI BUYURTMA!\n📍 Mijoz yaqinida: {c_st}\n👤 {c_name}\n📞 {c_phone}", reply_markup=ikb)
            await message.answer("⏳ Buyurtma haydovchiga yuborildi.", reply_markup=ReplyKeyboardRemove())
        except Exception:
            await message.answer("Xatolik: Haydovchiga xabar yetib bormadi.")
    else:
        # Guruhga yuborish
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 {c_st}\n📞 {c_phone}")
        await message.answer("Atrofda bo'sh haydovchilar yo'q, buyurtma guruhga yuborildi.")
    
    conn.close()
    await state.clear()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (ONLINE QILISH)
# ==========================================

@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    st_name, _ = find_closest_station(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    # Bu yerda user_id bazada borligini tekshirish shart emas, INSERT OR REPLACE ishlatamiz
    conn.execute("""INSERT OR REPLACE INTO drivers (user_id, status, lat, lon, station, joined_at) 
                    VALUES (?, 'online', ?, ?, ?, ?)""", 
                 (message.from_user.id, lat, lon, st_name, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Siz onlinesiz.\n📍 Bekat: {st_name}\nNavbatga turdingiz.")

# Safar mantiqlari (Taksometr va yakunlash avvalgi koddagidek ishlaydi)
# ... (Yuqoridagi kodning qolgan qismlari o'zgarishsiz qoladi)

async def main():
    init_db()
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
