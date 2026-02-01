import os
import json
import math
import sqlite3
import asyncio
import time
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
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

START_PRICE = 5000
KM_PRICE = 3500
WAIT_PRICE = 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)

client_dp = Dispatcher()
driver_dp = Dispatcher()

# --- BAZA VA GEOLOKATSIYA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, station TEXT, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, 
         start_time REAL, wait_start REAL DEFAULT 0, 
         start_lat REAL, start_lon REAL)''')
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
            if d < min_dist:
                min_dist, closest = d, feat['properties']['name']
        return closest.strip() # Bo'sh joylarni tozalash
    except Exception as e:
        print(f"Geojson xatosi: {e}")
        return "Markaz"

# ==========================================
# 🚕 MIJOZ BOTI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiyangizni yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)
    
    print(f"\n🔍 QIDIRUV: Mijoz bekati: {station}")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Bazadan online haydovchini qidirish
    cursor.execute("SELECT user_id, name FROM drivers WHERE status = 'online' AND station = ? ORDER BY joined_at ASC LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        d_id, d_name = driver
        print(f"✅ TOPILDI: Haydovchi {d_name} (ID: {d_id})")
        
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{message.from_user.id}_{lat}_{lon}"),
                InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{message.from_user.id}_{station}_{lat}_{lon}")
            ]
        ])
        
        try:
            await driver_bot.send_message(
                d_id,
                f"🚕 YANGI BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n\nQabul qilasizmi?",
                reply_markup=ikb
            )
            await message.answer(f"⏳ Buyurtma {station} bekatidagi haydovchiga ({d_name}) yuborildi.")
        except Exception as e:
            print(f"❌ XATOLIK: Haydovchiga xabar ketmadi: {e}")
            await send_to_group(message, station, lat, lon)
    else:
        print("ℹ️ STATUS: Bo'sh haydovchi yo'q, guruhga yuborilmoqda.")
        await send_to_group(message, station, lat, lon)

async def send_to_group(message, station, lat, lon):
    bot_me = await driver_bot.get_me()
    link = f"https://t.me/{bot_me.username}?start=gr_{message.from_user.id}_{lat}_{lon}"
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]])
    
    await client_bot.send_location(GROUP_ID, lat, lon)
    await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}", reply_markup=ikb)
    await message.answer("🚕 Hozircha bo'sh haydovchi yo'q, buyurtma guruhga yuborildi.")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message, command: CommandObject):
    if command.args and command.args.startswith("gr_"):
        parts = command.args.split("_")
        client_id, c_lat, c_lon = int(parts[1]), float(parts[2]), float(parts[3])
        await start_trip_engine(message.from_user.id, client_id, c_lat, c_lon)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)],
            [KeyboardButton(text="🏁 Yakunlash", request_location=True), KeyboardButton(text="⏳ Kutish")],
            [KeyboardButton(text="📴 Offline")]
        ], resize_keyboard=True
    )
    await message.answer("👨‍✈️ Haydovchi paneli. Ishni boshlash uchun lokatsiya yuboring.", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_status_online(message: types.Message):
    # Safar yakunlanayotgan bo'lsa, bu yerda to'xtatamiz
    if message.reply_to_message or "Yakunlash" in (message.text or ""):
        return 

    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO drivers (user_id, name, station, status, joined_at) VALUES (?, ?, ?, 'online', ?)",
                   (message.from_user.id, message.from_user.full_name, station, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    
    print(f"🆕 HAYDOVCHI ONLINE: {message.from_user.full_name} | Bekat: {station}")
    await message.answer(f"✅ Siz online holatdasiz!\n📍 Bekat: {station}\n\nBuyurtmalar tushsa sizga xabar beramiz.")

@driver_dp.callback_query(F.data.startswith("acc_"))
async def driver_accept_call(call: CallbackQuery):
    _, c_id, lat, lon = call.data.split("_")
    await call.message.edit_text("✅ Buyurtma qabul qilindi!")
    await start_trip_engine(call.from_user.id, int(c_id), float(lat), float(lon))

async def start_trip_engine(driver_id, client_id, c_lat, c_lon):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, start_time, start_lat, start_lon) VALUES (?, ?, ?, ?, ?)",
                   (driver_id, client_id, time.time(), c_lat, c_lon))
    cursor.execute("UPDATE drivers SET status = 'busy' WHERE user_id = ?", (driver_id,))
    conn.commit()
    conn.close()

    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏳ Kutish")], [KeyboardButton(text="🏁 Yakunlash", request_location=True)]], resize_keyboard=True)
    await driver_bot.send_message(driver_id, "🚖 Safar boshlandi!", reply_markup=kb)
    await client_bot.send_message(client_id, "🚕 Haydovchi buyurtmani qabul qildi!")

@driver_dp.message(F.text == "⏳ Kutish")
async def driver_wait_start(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE trips SET wait_start = ? WHERE driver_id = ?", (time.time(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer("⏱ Kutish vaqti hisoblanmoqda...")

@driver_dp.message(F.location)
async def driver_end_trip(message: types.Message):
    # Bu faqat "Yakunlash" bosilganda ishlaydi
    e_lat, e_lon = message.location.latitude, message.location.longitude
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, start_time, wait_start, start_lat, start_lon FROM trips WHERE driver_id = ?", (message.from_user.id,))
    trip = cursor.fetchone()
    
    if trip:
        cid, s_time, w_start, s_lat, s_lon = trip
        
        distance = get_dist(s_lat, s_lon, e_lat, e_lon) * 1.2
        if distance < 0.5: distance = 0.0 # Juda yaqin bo'lsa 0 km
        
        wait_time = (time.time() - w_start) / 60 if w_start > 0 else 0
        total_price = START_PRICE + (distance * KM_PRICE) + (wait_time * WAIT_PRICE)
        
        chek = (f"🏁 SAFAR YAKUNLANDI\n\n🛣 Masofa: {distance:.1f} km\n"
                f"⏳ Kutish: {int(wait_time)} daq\n💰 To'lov: {int(total_price)} so'm")
        
        await message.answer(chek, reply_markup=ReplyKeyboardRemove())
        await client_bot.send_message(cid, chek + "\n\nRahmat!")
        
        cursor.execute("DELETE FROM trips WHERE driver_id = ?", (message.from_user.id,))
        cursor.execute("UPDATE drivers SET status = 'online' WHERE user_id = ?", (message.from_user.id,))
        conn.commit()
    conn.close()

async def main():
    init_db()
    # Botlarni parallel ishga tushirish
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
