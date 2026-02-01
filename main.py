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

START_PRICE, KM_PRICE, WAIT_PRICE = 5000, 3500, 500 # 500 so'm/daqiqasiga

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
# 🚕 MIJOZ VA HAYDOVCHI MANTIQI
# ==========================================

# (Oldingi start va reg qismlari o'zgarishsiz qoladi, asosiysi trip mantiqi)

@driver_dp.callback_query(F.data.startswith("acc_"))
async def acc_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    
    conn = sqlite3.connect(DB_FILE)
    d_info = conn.execute("SELECT name, phone, car, car_num FROM drivers WHERE user_id=?", (did,)).fetchone()
    
    # Mijozga xabar yuborish va xabar ID sini saqlash
    c_msg = await client_bot.send_message(int(cid), f"🚕 Haydovchi qabul qildi!\n\n👤: {d_info[0]}\n🚗: {d_info[2]} ({d_info[3]})\n📞: {d_info[1]}")
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚕 Yetib keldim", callback_data="arrived")]])
    d_msg = await call.message.edit_text(f"✅ Qabul qilindi! 📞 {cph}", reply_markup=ikb)
    
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, s_lat, s_lon, driver_msg_id, client_msg_id) VALUES (?,?,?,?,?,?,?)", 
                 (did, int(cid), cph, float(lat), float(lon), d_msg.message_id, c_msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()

@driver_dp.callback_query(F.data == "arrived")
async def arr_call(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya boshlash", callback_data="wait_on")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="can_pre")]
    ])
    await call.message.edit_text("Mijozga 'Yetib keldim' xabari yuborildi.", reply_markup=ikb)
    
    if trip:
        await client_bot.edit_message_text(chat_id=trip[0], message_id=trip[1], text="🚕 Haydovchi yetib keldi! Chiqishingiz mumkin.", reply_markup=None)

# --- JONLI OJIDANIYA TIZIMI ---

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    now = time.time()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (now, call.from_user.id))
    trip = conn.execute("SELECT client_id, client_msg_id, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    conn.commit()
    conn.close()

    # Haydovchi uchun yangi interfeys
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Davom etish (To'xtatish)", callback_data="wait_off")],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="wait_refresh")]
    ])
    
    wait_minutes = int(trip[2])
    current_bill = START_PRICE + (wait_minutes * WAIT_PRICE)
    
    text = f"⏱ Kutish yoqildi...\n⏳ Umumiy vaqt: {wait_minutes} daq\n💰 Joriy summa: {current_bill} so'm"
    await call.message.edit_text(text, reply_markup=ikb)
    
    if trip:
        await client_bot.edit_message_text(chat_id=trip[0], message_id=trip[1], text=f"⏳ Kutish tartibi yoqildi...\n{text}")

@driver_dp.callback_query(F.data == "wait_refresh")
async def wait_refresh(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start, total_wait, client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if trip and trip[0] > 0:
        session_wait = (time.time() - trip[0]) / 60
        total_m = int(trip[1] + session_wait)
        current_bill = START_PRICE + (total_m * WAIT_PRICE)
        
        text = f"⏱ Kutish davom etmoqda...\n⏳ Umumiy vaqt: {total_m} daq\n💰 Joriy summa: {current_bill} so'm"
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="▶️ Davom etish (To'xtatish)", callback_data="wait_off")],
            [InlineKeyboardButton(text="🔄 Yangilash", callback_data="wait_refresh")]
        ])
        
        try:
            await call.message.edit_text(text, reply_markup=ikb)
            await client_bot.edit_message_text(chat_id=trip[2], message_id=trip[3], text=f"⏳ Haydovchi kutmoqda...\n{text}")
        except: pass # Xabar o'zgarmagan bo'lsa xato bermasligi uchun
    conn.close()

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    trip = conn.execute("SELECT wait_start, total_wait, client_id, client_msg_id FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    if trip and trip[0] > 0:
        added = (time.time() - trip[0]) / 60
        new_total = trip[1] + added
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (new_total, call.from_user.id))
        conn.commit()
        
        total_m = int(new_total)
        current_bill = START_PRICE + (total_m * WAIT_PRICE)
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
            [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="fin_pre")]
        ])
        
        text = f"🚖 Safar davom etmoqda.\n⏳ To'xtash vaqti: {total_m} daq\n💰 Hisob: {current_bill} so'm"
        await call.message.edit_text(text, reply_markup=ikb)
        await client_bot.edit_message_text(chat_id=trip[2], message_id=trip[3], text=f"▶️ Safar davom etmoqda...\n{text}")
    conn.close()

# (Qolgan fin_pre va can_yes qismlari o'zgarishsiz qoladi)
# ... [Kodni qolgan qismi yuqoridagi javoblar bilan bir xil] ...

