import os, asyncio, math, json, aiosqlite, time
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

load_dotenv()

# --- TARIFLAR (So'mda) ---
START_PRICE = 10000      # Shahar ichi ochilish
NEXT_KM_PRICE = 2000     # Har bir km uchun
WAIT_PER_MINUTE = 500    # Har bir daqiqa kutish uchun
MIN_DISTANCE = 3.0       # Minimal masofa (km)

# --- BOT VA BAZA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
DB_FILE = 'taxi_pro.db'
GEOJSON_FILE = 'locations.json'

client_bot, driver_bot = Bot(token=CLIENT_TOKEN), Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class TripState(StatesGroup):
    on_trip = State()

# --- GEODEZIYA FUNKSIYALARI ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 # km
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2) * math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- BAZA STRUKTURASI ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        # Haydovchilar jadvali
        await db.execute('''CREATE TABLE IF NOT EXISTS drivers 
            (id INTEGER PRIMARY KEY, status TEXT, station TEXT, lat REAL, lon REAL)''')
        # Safarlar jadvali (Taksometr ma'lumotlari bilan)
        await db.execute('''CREATE TABLE IF NOT EXISTS trips 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, driver_id INTEGER, client_id INTEGER,
             start_time REAL, end_time REAL, wait_seconds REAL DEFAULT 0,
             total_km REAL DEFAULT 0, total_price INTEGER DEFAULT 0, status TEXT)''')
        await db.commit()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI & TAKSOMETR
# ==========================================

@driver_dp.message(F.location)
async def update_driver_status(message: types.Message):
    # Bu yerda JSON bekat mantiqini find_closest_station bilan ulasangiz bo'ladi
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO drivers (id, status, lat, lon) VALUES (?, 'online', ?, ?)",
                         (message.from_user.id, message.location.latitude, message.location.longitude))
        await db.commit()
    await message.answer("✅ Siz onlaynsiz. Buyurtmalar kutilmoqda...")

@driver_dp.callback_query(F.data.startswith("start_trip_"))
async def start_trip(callback: types.CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    start_ts = time.time()
    
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE trips SET start_time = ?, status = 'running' WHERE id = ?", (start_ts, order_id))
        await db.commit()
    
    await state.set_state(TripState.on_trip)
    await state.update_data(order_id=order_id, last_lat=None, last_lon=None, total_km=0.0)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏹ Safarni tugatish")]], resize_keyboard=True)
    await callback.message.answer("🚀 Safar boshlandi. Taksometr yoqildi.", reply_markup=kb)

# --- TAKSOMETR: JONLI LOKATSIYA ORQALI MASOFA O'LCHASH ---
@driver_dp.edited_message(TripState.on_trip, F.location)
async def track_trip(message: types.Message, state: FSMContext):
    data = await state.get_data()
    curr_lat, curr_lon = message.location.latitude, message.location.longitude
    
    if data.get('last_lat'):
        dist = calculate_distance(data['last_lat'], data['last_lon'], curr_lat, curr_lon)
        new_total_km = data['total_km'] + dist
        await state.update_data(last_lat=curr_lat, last_lon=curr_lon, total_km=new_total_km)
        
        # Mijozga real vaqtda masofani bildirish (ixtiyoriy)
        print(f"Yurilgan masofa: {new_total_km:.2f} km")
    else:
        await state.update_data(last_lat=curr_lat, last_lon=curr_lon)

@driver_dp.message(TripState.on_trip, F.text == "⏹ Safarni tugatish")
async def finish_trip(message: types.Message, state: FSMContext):
    data = await state.get_data()
    end_ts = time.time()
    
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT start_time, client_id FROM trips WHERE id = ?", (data['order_id'],))
        row = await cursor.fetchone()
        
        duration_mins = (end_ts - row[0]) / 60
        # Hisoblash mantiqi
        km_cost = max(0, data['total_km'] - MIN_DISTANCE) * NEXT_KM_PRICE
        total_price = START_PRICE + km_cost
        
        await db.execute("UPDATE trips SET end_time = ?, total_km = ?, total_price = ?, status = 'finished' WHERE id = ?",
                         (end_ts, data['total_km'], total_price, data['order_id']))
        await db.execute("UPDATE drivers SET status = 'online' WHERE id = ?", (message.from_user.id,))
        await db.commit()
        
        # Mijozga chek yuborish
        receipt = (f"🏁 Safar yakunlandi\n\n"
                   f"🛣 Masofa: {data['total_km']:.2f} km\n"
                   f"⏱ Vaqt: {int(duration_mins)} daqiqa\n"
                   f"💰 Jami: {int(total_price)} so'm")
        
        await message.answer(receipt, reply_markup=ReplyKeyboardRemove())
        await client_bot.send_message(row[1], receipt)
    
    await state.clear()

# ==========================================
# 🚕 MIJOZ BOTI & BUYURTMA
# ==========================================

@client_dp.message(F.location)
async def create_order(message: types.Message):
    c_lat, c_lon = message.location.latitude, message.location.longitude
    
    async with aiosqlite.connect(DB_FILE) as db:
        # Eng yaqin online haydovchini qidirish
        cursor = await db.execute("SELECT id FROM drivers WHERE status = 'online' LIMIT 1")
        driver = await cursor.fetchone()
        
        if driver:
            # Safar yaratish
            cursor = await db.execute("INSERT INTO trips (client_id, driver_id, status) VALUES (?, ?, 'pending')", 
                                      (message.from_user.id, driver[0]))
            trip_id = cursor.lastrowid
            await db.commit()
            
            ikb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"start_trip_{trip_id}")
            ]])
            await driver_bot.send_location(driver[0], c_lat, c_lon)
            await driver_bot.send_message(driver[0], "🚕 Yangi buyurtma!", reply_markup=ikb)
            await message.answer("Haydovchi topildi, yo'lga chiqmoqda...")
        else:
            await message.answer("Hozircha bo'sh haydovchilar yo'q.")

# ==========================================
# ISHGA TUSHIRISH
# ==========================================
async def main():
    await init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
