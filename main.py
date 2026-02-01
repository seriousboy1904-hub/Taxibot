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

# Tariflar
START_PRICE = 5000  # Start
KM_PRICE = 3500     # 1 km uchun
WAIT_PRICE = 500    # 1 minut kutish uchun

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
dp = Dispatcher()

# --- DATABASE VA LOGIKA ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Haydovchilar (navbat va info)
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, 
         station TEXT, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    # Faol safarlar
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_name TEXT, 
         start_time REAL, start_lat REAL, start_lon REAL, wait_start REAL DEFAULT 0)''')
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
    except: return "Nukus"

# ==========================================
# 🚕 MIJOZ BOTI (CLIENT BOT)
# ==========================================

@dp.message(Command("start"), F.bot.id == client_bot.id)
async def client_start(message: types.Message):
    await message.answer("Xush kelibsiz! Ismingiz va manzilingizni bilishimiz uchun lokatsiya yuboring.", 
                         reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]], resize_keyboard=True))

@dp.message(F.location, F.bot.id == client_bot.id)
async def client_loc(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)
    
    # Bekatdagi birinchi haydovchini topish
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM drivers WHERE station = ? AND status = 'online' ORDER BY joined_at ASC LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        # Haydovchining shaxsiy botiga buyurtma yuborish
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_query_id=f"acc_{message.from_user.id}"),
             InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{message.from_user.id}")]
        ])
        try:
            await driver_bot.send_message(driver[0], f"🚕 YANGI BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n\nQabul qilasizmi?", reply_markup=ikb)
            await message.answer(f"⏳ Buyurtmangiz bekatdagi navbatda turgan haydovchiga yuborildi. Kuting...")
        except:
            await send_to_group(message, station)
    else:
        await send_to_group(message, station)

async def send_to_group(message, station):
    link = f"https://t.me/{(await driver_bot.get_me()).username}?start=groupacc_{message.from_user.id}"
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]])
    await client_bot.send_location(GROUP_ID, message.location.latitude, message.location.longitude)
    await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n\nHozircha navbatda haydovchi yo'q yoki rad etildi.", reply_markup=ikb)
    await message.answer("🚕 Hozircha navbatda haydovchi yo'q, buyurtma umumiy guruhga yuborildi.")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (DRIVER BOT)
# ==========================================

@dp.message(Command("start"), F.bot.id == driver_bot.id)
async def driver_start(message: types.Message, command: CommandObject):
    # Guruhdan qabul qilish logikasi
    if command.args and "groupacc" in command.args:
        cid = int(command.args.split("_")[1])
        await start_trip(message, cid)
        return

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)],
        [KeyboardButton(text="🏁 Safarni yakunlash"), KeyboardButton(text="⏳ Kutishni boshlash")],
        [KeyboardButton(text="📴 Offline")]
    ], resize_keyboard=True)
    await message.answer("👨‍✈️ Haydovchi paneli. Ma'lumotlaringizni to'ldiring va liniyaga chiqing.", reply_markup=kb)

@dp.callback_query(F.data.startswith("skip_"), F.bot.id == driver_bot.id)
async def skip_order(call: CallbackQuery):
    cid = int(call.data.split("_")[1])
    await call.message.edit_text("🔄 Buyurtma o'tkazib yuborildi.")
    # Guruhga yuborish funksiyasini chaqirish (bu yerda mantiqiy bog'liqlik)
    await call.answer("O'tkazib yuborildi")

@dp.message(F.text == "⏳ Kutishni boshlash", F.bot.id == driver_bot.id)
async def start_wait(message: types.Message):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("UPDATE trips SET wait_start = ? WHERE driver_id = ?", (time.time(), message.from_user.id))
    conn.commit(); conn.close()
    await message.answer("⏱ Kutish vaqti hisoblanmoqda...")

async def start_trip(message, cid):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, start_time) VALUES (?, ?, ?)", 
                   (message.from_user.id, cid, time.time()))
    cursor.execute("UPDATE drivers SET status = 'busy' WHERE user_id = ?", (message.from_user.id,))
    conn.commit(); conn.close()
    await message.answer("🚖 Safar boshlandi!")
    await client_bot.send_message(cid, "🚕 Haydovchi buyurtmangizni qabul qildi!")

@dp.message(F.text == "🏁 Safarni yakunlash", F.bot.id == driver_bot.id)
async def end_trip(message: types.Message):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("SELECT * FROM trips WHERE driver_id = ?", (message.from_user.id,))
    trip = cursor.fetchone()
    if not trip: return
    
    # Hisob-kitob (Taksometr)
    duration = (time.time() - trip[3]) / 60 # minut
    wait_time = (time.time() - trip[6]) / 60 if trip[6] > 0 else 0
    total_sum = START_PRICE + (wait_time * WAIT_PRICE) # Masofani ham qo'shish mumkin
    
    await message.answer(f"🏁 Safar yakunlandi!\n⏱ Umumiy vaqt: {int(duration)} daqiqa\n⏳ Kutish: {int(wait_time)} daqiqa\n💰 Jami: {int(total_sum)} so'm")
    await client_bot.send_message(trip[1], f"🏁 Safar yakunlandi. To'lov: {int(total_sum)} so'm. Rahmat!")
    
    cursor.execute("DELETE FROM trips WHERE driver_id = ?", (message.from_user.id,))
    cursor.execute("UPDATE drivers SET status = 'online', joined_at = ? WHERE user_id = ?", (datetime.now().isoformat(), message.from_user.id))
    conn.commit(); conn.close()

# --- ISHGA TUSHIRISH ---
async def main():
    init_db()
    await asyncio.gather(dp.start_polling(client_bot), dp.start_polling(driver_bot))

if __name__ == '__main__':
    asyncio.run(main())
