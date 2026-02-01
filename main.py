import os
import json
import math
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

# Konfiguratsiya
GROUP_ID = -1003356995649
GEOJSON_FILE = 'locations.json'
DB_FILE = 'unified_taxi.db'

# Ikkala botni yaratish
client_bot = Bot(token=os.getenv("CLIENT_BOT_TOKEN"))
driver_bot = Bot(token=os.getenv("DRIVER_BOT_TOKEN"))

dp = Dispatcher()

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Haydovchilar navbati
    cursor.execute('''CREATE TABLE IF NOT EXISTS queue 
        (user_id INTEGER PRIMARY KEY, name TEXT, station_name TEXT, 
         status TEXT DEFAULT 'online', joined_at TEXT)''')
    conn.commit()
    conn.close()

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest(lat, lon):
    with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    closest, min_dist = "Noma'lum", float('inf')
    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        dist = calculate_distance(lat, lon, coords[1], coords[0])
        if dist < min_dist: min_dist, closest = dist, feat['properties']['name']
    return closest

# ==========================================
# 🚕 MIJOZ BOTI FUNKSIYALARI (CLIENT BOT)
# ==========================================

@dp.message(Command("start"), F.bot.id == client_bot.id)
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚕 Taxi chaqirish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taxi chaqirish uchun lokatsiyangizni yuboring.", reply_markup=kb)

@dp.message(F.location, F.bot.id == client_bot.id)
async def client_location(message: types.Message):
    st = find_closest(message.location.latitude, message.location.longitude)
    
    # Guruhga buyurtma yuborish
    await client_bot.send_location(GROUP_ID, message.location.latitude, message.location.longitude)
    await client_bot.send_message(GROUP_ID, f"🚕 YANGI BUYURTMA\n📍 Bekat: {st}\n👤 Mijoz: {message.from_user.full_name}")
    
    await message.answer(f"✅ Rahmat! Buyurtmangiz {st} bekatidagi haydovchilarga yuborildi.")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI FUNKSIYALARI (DRIVER BOT)
# ==========================================

@dp.message(Command("start"), F.bot.id == driver_bot.id)
async def driver_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🟢 Ishni boshlash (Live Location)", request_location=True)],
        [KeyboardButton(text="☕️ Pauza"), KeyboardButton(text="📴 Offline")]
    ], resize_keyboard=True)
    await message.answer("👨‍✈️ Haydovchi paneli. Navbatga turish uchun Live Location yuboring.", reply_markup=kb)

@dp.message(F.location & F.location.live_period, F.bot.id == driver_bot.id)
async def driver_queue(message: types.Message):
    st = find_closest(message.location.latitude, message.location.longitude)
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO queue (user_id, name, station_name, status, joined_at) VALUES (?, ?, ?, 'online', ?)",
                   (message.from_user.id, message.from_user.full_name, st, datetime.now().isoformat()))
    conn.commit(); conn.close()
    await message.answer(f"📍 Siz {st} bekati navbatiga turdingiz.")

@dp.message(F.text == "☕️ Pauza", F.bot.id == driver_bot.id)
async def driver_pause(message: types.Message):
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("UPDATE queue SET status = 'pauza' WHERE user_id = ?", (message.from_user.id,))
    conn.commit(); conn.close()
    await message.answer("☕️ Tanaffus. Navbatingiz to'xtatildi.")

# ==========================================
# 🚀 IKKALA BOTNI ISHGA TUSHIRISH
# ==========================================

async def main():
    init_db()
    # Har bir bot uchun dispatcher pollingni alohida boshlaydi
    await asyncio.gather(
        dp.start_polling(client_bot),
        dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Botlar to'xtatildi")
