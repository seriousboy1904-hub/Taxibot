import os, json, math, sqlite3, asyncio, time
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

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# YANGI TARIFLAR
START_PRICE = 10000  # 1 km gacha 10 000 so'm
NEXT_KM_PRICE = 1000 # 1 km dan keyin har bir km uchun
WAIT_PRICE = 1000    # 1 daqiqa kutish uchun

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    phone = State()
    car_model = State()
    car_number = State()

# --- BAZA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         status TEXT DEFAULT 'offline', lat REAL, lon REAL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, 
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL, last_lon REAL, distance REAL DEFAULT 0, msg_id INTEGER)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def calculate_price(dist, wait_time):
    # 1 km gacha bo'lgan masofa uchun start price, keyingisi uchun qo'shiladi
    if dist <= 1:
        total = START_PRICE
    else:
        total = START_PRICE + ((dist - 1) * NEXT_KM_PRICE)
    
    total += (wait_time * WAIT_PRICE)
    return total

# --- HAYDOVCHI BOTI ---

@driver_dp.message(Command("start"))
async def d_start(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash", request_location=True)]], resize_keyboard=True)
        await message.answer("Xush kelibsiz! Ishni boshlash uchun lokatsiya yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        await message.answer("Ro'yxatdan o'tish uchun raqam yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(F.location)
async def driver_active(message: types.Message):
    # Haydovchini online qilish
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, status) VALUES (?,?,?)", (message.from_user.id, message.from_user.full_name, 'online'))
    conn.commit()
    await message.answer("✅ Siz onlinesiz. Buyurtma kutishingiz mumkin.")

@driver_dp.edited_message(F.location)
async def taxi_meter_live(message: types.Message):
    """Real vaqt rejimida masofa va pulni hisoblab xabarni yangilaydi"""
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance, total_wait, msg_id, client_id FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        l_lat, l_lon, dist, twait, msg_id, cid = trip
        new_dist = dist
        if l_lat and l_lon:
            step = get_dist(l_lat, l_lon, lat, lon)
            if step > 0.02: # 20 metr siljish bo'lsa
                new_dist += step
        
        cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        conn.commit()
        
        # Narxni hisoblash
        current_price = calculate_price(new_dist, twait)
        
        # Haydovchi ekranidagi xabarni yangilash
        text = (f"🚖 **Safar jarayoni:**\n\n"
                f"📏 Masofa: {new_dist:.2f} km\n"
                f"⏳ Kutish: {int(twait)} daq\n"
                f"💰 Joriy summa: {current_price:,.0f} so'm\n\n"
                f"ℹ️ _Masofa o'zgarganda hisob yangilanadi_")
        
        try:
            await driver_bot.edit_message_text(text, did, msg_id, parse_mode="Markdown", 
                                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                                 [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
                                                 [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
                                             ]))
        except: pass
    conn.close()

@driver_dp.callback_query(F.data == "acc_order") # Bu yerda buyurtmani qabul qilish logikasi
async def accept(call: CallbackQuery):
    did = call.from_user.id
    # Test uchun buyurtma ochish
    conn = sqlite3.connect(DB_FILE)
    # msg_id ni saqlab qolamizki keyin uni yangilab turaylik
    res = await call.message.answer("Safar boshlandi. Live Location (8 soat) yuboring!")
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, distance, msg_id) VALUES (?,?,?)", (did, 0.0, res.message_id))
    conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    await call.answer("Kutish vaqti boshlandi...")
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")]]))

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        diff = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (diff, call.from_user.id))
        conn.commit()
    await call.answer("Kutish to'xtatildi.")
    # Bu yerda tahrirlangan xabar Live Location orqali avtomatik yangilanadi

@driver_dp.callback_query(F.data == "fin_pre")
async def finish(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, twait, dist = tr
        total = calculate_price(dist, twait)
        res_text = (f"🏁 **Safar yakunlandi**\n\n"
                    f"📏 Jami masofa: {dist:.2f} km\n"
                    f"⏳ Jami kutish: {int(twait)} daq\n"
                    f"💰 **To'lov: {total:,.0f} so'm**")
        
        await call.message.edit_text(res_text, parse_mode="Markdown")
        if cid: await client_bot.send_message(cid, res_text, parse_mode="Markdown")
        
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

async def main():
    init_db()
    print("Botlar tayyor! Ishga tushirildi.")
    await asyncio.gather(
        client_dp.start_polling(client_bot, skip_updates=True),
        driver_dp.start_polling(driver_bot, skip_updates=True)
    )

if __name__ == '__main__':
    asyncio.run(main())
