import os
import json
import math
import sqlite3
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# Muhit o'zgaruvchilarini yuklash
load_dotenv()
API_TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = -1003356995649
DB_FILE = 'taxi_system.db'
GEOJSON_FILE = 'locations.json'

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Tariflar (Megasorpa logikasi)
START_PRICE, KM_PRICE, WAIT_PRICE = 5000, 3500, 500

# --- BAZA BILAN ISHLASH ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Haydovchilar navbati
    cursor.execute('''CREATE TABLE IF NOT EXISTS queue 
        (user_id INTEGER PRIMARY KEY, name TEXT, station_name TEXT, 
         lat REAL, lon REAL, status TEXT DEFAULT 'online', joined_at TEXT)''')
    # Faol safarlar
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, start_time TEXT, 
         start_lat REAL, start_lon REAL, status TEXT)''')
    conn.commit()
    conn.close()

# --- GEOGRAFIYA (Haversine formula) ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371 # km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest_station(u_lat, u_lon):
    if not os.path.exists(GEOJSON_FILE): return "Noma'lum"
    with open(GEOJSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    closest, min_dist = "Nukus", float('inf')
    for feat in data['features']:
        coords = feat['geometry']['coordinates']
        dist = calculate_distance(u_lat, u_lon, coords[1], coords[0])
        if dist < min_dist:
            min_dist, closest = dist, feat['properties']['name']
    return closest

# --- ASOSIY HANDLERLAR ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
    # Deep linking (Haydovchi buyurtmani qabul qilganda)
    if command.args and command.args.startswith("trip_"):
        client_id = command.args.split("_")[1]
        await start_trip_logic(message, client_id)
        return

    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚕 Taxi chaqirish", request_location=True)],
        [KeyboardButton(text="👨‍✈️ Haydovchi: Navbatga turish", request_location=True)]
    ], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Kerakli bo'limni tanlang:", reply_markup=kb)

# --- MIJOZ LOGIKASI ---
@dp.message(F.location & ~F.location.live_period)
async def customer_request(message: types.Message):
    u_lat, u_lon = message.location.latitude, message.location.longitude
    station = find_closest_station(u_lat, u_lon)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, name FROM queue WHERE station_name = ? AND status = 'online' ORDER BY joined_at ASC LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        # Buyurtma tugmasi
        link = f"https://t.me/{(await bot.get_me()).username}?start=trip_{message.from_user.id}"
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", url=link)]])
        
        await bot.send_location(GROUP_ID, u_lat, u_lon)
        await bot.send_message(GROUP_ID, f"🚕 YANGI BUYURTMA\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n👨‍✈️ Navbatdagi: {driver[1]}", reply_markup=ikb)
        await message.answer(f"⏳ Buyurtmangiz {station} bekatidagi haydovchiga yuborildi.")
    else:
        await message.answer(f"😔 Kechirasiz, {station} bekatida bo'sh haydovchi yo'q.")

# --- HAYDOVCHI NAVBATI ---
@dp.message(F.location & F.location.live_period)
async def driver_queue_handler(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    st_name = find_closest_station(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO queue (user_id, name, station_name, lat, lon, status, joined_at) VALUES (?, ?, ?, ?, ?, 'online', ?)",
                   (message.from_user.id, message.from_user.full_name, st_name, lat, lon, datetime.now().isoformat()))
    conn.commit(); conn.close()
    
    await message.answer(f"✅ Siz {st_name} bekatida navbatga turdingiz.\nStatus: Online")

# --- TAKSOMETR VA SAFAR (Megasorpa engine) ---
async def start_trip_logic(message, client_id):
    # Safarni bazaga yozish
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, start_time, status) VALUES (?, ?, ?, 'started')",
                   (message.from_user.id, client_id, datetime.now().isoformat()))
    # Haydovchini navbatdan vaqtincha ochirish
    cursor.execute("UPDATE queue SET status = 'busy' WHERE user_id = ?", (message.from_user.id,))
    conn.commit(); conn.close()

    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🏁 Safarni yakunlash")]], resize_keyboard=True)
    await message.answer("🚖 Safar boshlandi. Manzilga yetgach tugmani bosing.", reply_markup=kb)
    await bot.send_message(client_id, "🚕 Haydovchi buyurtmani qabul qildi va yo'lga chiqdi!")

@dp.message(F.text == "🏁 Safarni yakunlash")
async def finish_trip(message: types.Message):
    # Bu yerda megasorpa dagi chek chiqarish logikasi bo'ladi
    conn = sqlite3.connect(DB_FILE); cursor = conn.cursor()
    cursor.execute("DELETE FROM trips WHERE driver_id = ?", (message.from_user.id,))
    cursor.execute("UPDATE queue SET status = 'online', joined_at = ? WHERE user_id = ?", 
                   (datetime.now().isoformat(), message.from_user.id))
    conn.commit(); conn.close()
    
    await message.answer("✅ Safar yakunlandi. Siz yana navbatga qaytdingiz.", reply_markup=ReplyKeyboardRemove())

async def main():
    init_db()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
