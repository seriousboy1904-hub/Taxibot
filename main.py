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

# Tariflar
START_PRICE = 5000
KM_PRICE = 3500
WAIT_PRICE = 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         station TEXT, lat REAL, lon REAL, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    # total_dist - bosib o'tilgan masofa, last_lat/lon - hisoblash uchun oxirgi nuqta
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         start_time REAL, wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         total_dist REAL DEFAULT 0, last_lat REAL, last_lon REAL)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ==========================================
# 👨‍✈️ HAYDOVCHI LIVE LOKATSIYA MANTIQI
# ==========================================

# Haydovchi Live Location yuborganida yoki u yangilanganida ishlaydi
@driver_dp.edited_message(F.location)
@driver_dp.message(F.location)
async def handle_live_location(message: types.Message):
    did = message.from_user.id
    lat = message.location.latitude
    lon = message.location.longitude

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Haydovchi hozir faol safardami?
    trip = cursor.execute("SELECT last_lat, last_lon, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        last_lat, last_lon, total_dist = trip
        
        if last_lat and last_lon:
            # Ikki nuqta orasidagi masofani hisoblaymiz (metrlarda aniqroq chiqadi)
            step = get_dist(last_lat, last_lon, lat, lon)
            
            # GPS xatoligini oldini olish uchun: agar 10 metrdan ko'p yurgan bo'lsa qo'shamiz
            if step > 0.01:
                new_dist = total_dist + step
                cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, total_dist=? WHERE driver_id=?", 
                               (lat, lon, new_dist, did))
                conn.commit()
        else:
            # Birinchi marta lokatsiya kelsa, faqat nuqtani saqlaymiz
            cursor.execute("UPDATE trips SET last_lat=?, last_lon=? WHERE driver_id=?", (lat, lon, did))
            conn.commit()
    
    conn.close()

# ==========================================
# 🏁 SAFARNI YAKUNLASH (HISOB-KITOB)
# ==========================================

@driver_dp.callback_query(F.data == "fin_pre")
async def finalize_trip(call: CallbackQuery):
    did = call.from_user.id
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, total_dist FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if tr:
        cid, wait_min, distance = tr
        
        # Hisob-kitob
        dist_cost = distance * KM_PRICE
        wait_cost = wait_min * WAIT_PRICE
        total_price = START_PRICE + dist_cost + wait_cost
        
        res_text = (
            f"🏁 Safar yakunlandi!\n\n"
            f"📏 Bosib o'tilgan yo'l: {distance:.2f} km\n"
            f"⏳ Kutish vaqti: {int(wait_min)} daq\n"
            f"💰 To'lov: {int(total_price):,} so'm\n\n"
            f"Tarif: Start {START_PRICE} + KM {KM_PRICE}"
        )
        
        await call.message.edit_text(res_text)
        
        # Mijozga yuborish
        try:
            await client_bot.send_message(cid, res_text)
        except:
            pass
            
        # Bazadan tripni o'chirish va haydovchini bo'shatish
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (did,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (did,))
        conn.commit()
    
    conn.close()
    await call.answer()

# Qolgan barcha funksiyalar (Reg, Order, Arrived) sizning eski kodingiz bilan bir xil qoladi...
# Faqat 'acc_order' ichida 'last_lat' va 'last_lon' ni null qilib trip ochishingiz kerak.

async def main():
    init_db()
    await asyncio.gather(client_dp.start_polling(client_bot), driver_dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
