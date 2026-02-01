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
GROUP_ID = -1003356995649 # Guruh ID sini tekshiring
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# Tariflar
START_PRICE = 5000
KM_PRICE = 3500
WAIT_PRICE = 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)

# Ikkita alohida dispatcher xatolarni oldini oladi
client_dp = Dispatcher()
driver_dp = Dispatcher()

# --- BAZA FUNKSIYALARI ---
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
        closest, min_dist = "Nukus", float('inf')
        for feat in data['features']:
            c = feat['geometry']['coordinates']
            d = get_dist(lat, lon, c[1], c[0])
            if d < min_dist:
                min_dist, closest = d, feat['properties']['name']
        return closest
    except:
        return "Markaz"

# ==========================================
# 🚕 MIJOZ BOTI (client_dp)
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

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Eng birinchi navbatga turgan haydovchini olish
    cursor.execute("SELECT user_id, name FROM drivers WHERE station = ? AND status = 'online' ORDER BY joined_at ASC LIMIT 1", (station,))
    driver = cursor.fetchone()
    conn.close()

    if driver:
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{message.from_user.id}_{lat}_{lon}"),
                InlineKeyboardButton(text="🔄 Guruhga yuborish", callback_data=f"skip_{message.from_user.id}_{station}_{lat}_{lon}")
            ]
        ])
        
        try:
            # Haydovchiga shaxsiy xabar yuborish
            await driver_bot.send_message(
                driver[0],
                f"🚕 YANGI BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n\nQabul qilasizmi?",
                reply_markup=ikb
            )
            await message.answer(f"⏳ Buyurtmangiz {station} bekatidagi haydovchiga yuborildi. Kuting...")
        except:
            await send_to_group(message, station, lat, lon)
    else:
        await send_to_group(message, station, lat, lon)

async def send_to_group(message, station, lat, lon):
    bot_info = await driver_bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=gr_{message.from_user.id}_{lat}_{lon}"
    ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]])
    
    await client_bot.send_location(GROUP_ID, lat, lon)
    await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}", reply_markup=ikb)
    await message.answer("🚕 Bekatda bo‘sh haydovchi yo‘q, buyurtma guruhga yuborildi.")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (driver_dp)
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message, command: CommandObject):
    if command.args and command.args.startswith("gr_"):
        # Guruhdan kelgan buyurtmani qabul qilish
        parts = command.args.split("_")
        client_id, c_lat, c_lon = int(parts[1]), float(parts[2]), float(parts[3])
        await start_trip_engine(message.from_user.id, client_id, c_lat, c_lon)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)],
            [KeyboardButton(text="🏁 Safarni yakunlash"), KeyboardButton(text="⏳ Kutish")],
            [KeyboardButton(text="📴 Offline")]
        ], resize_keyboard=True
    )
    await message.answer("👨‍✈️ Haydovchi paneli. Ishni boshlash uchun Live lokatsiya yuboring.", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_update_status(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO drivers (user_id, name, station, status, joined_at) VALUES (?, ?, ?, 'online', ?)",
                   (message.from_user.id, message.from_user.full_name, station, datetime.now().isoformat()))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Status: Online\n📍 Bekat: {station}")

@driver_dp.callback_query(F.data.startswith("acc_"))
async def driver_accept(call: CallbackQuery):
    _, client_id, c_lat, c_lon = call.data.split("_")
    await call.message.edit_text("✅ Buyurtma qabul qilindi!")
    await start_trip_engine(call.from_user.id, int(client_id), float(c_lat), float(c_lon))

async def start_trip_engine(driver_id, client_id, c_lat, c_lon):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, start_time, start_lat, start_lon) VALUES (?, ?, ?, ?, ?)",
                   (driver_id, client_id, time.time(), c_lat, c_lon))
    cursor.execute("UPDATE drivers SET status = 'busy' WHERE user_id = ?", (driver_id,))
    conn.commit()
    conn.close()

    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="⏳ Kutish")], [KeyboardButton(text="🏁 Safarni yakunlash", request_location=True)]], resize_keyboard=True)
    await driver_bot.send_message(driver_id, "🚖 Safar boshlandi! Manzilga borgach 'Yakunlash' tugmasini bosing (lokatsiya bilan).", reply_markup=kb)
    await client_bot.send_message(client_id, "🚕 Haydovchi buyurtmani qabul qildi va yo'lga chiqdi!")

@driver_dp.message(F.text == "⏳ Kutish")
async def driver_wait_start(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE trips SET wait_start = ? WHERE driver_id = ?", (time.time(), message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer("⏱ Kutish vaqti hisoblanmoqda...")

@driver_dp.message(F.location, F.text == "🏁 Safarni yakunlash") # Lokatsiya bilan yakunlash
async def driver_end_trip(message: types.Message):
    e_lat, e_lon = message.location.latitude, message.location.longitude
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT client_id, start_time, wait_start, start_lat, start_lon FROM trips WHERE driver_id = ?", (message.from_user.id,))
    trip = cursor.fetchone()
    
    if trip:
        cid, s_time, w_start, s_lat, s_lon = trip
        
        # Masofa va narx
        distance = get_dist(s_lat, s_lon, e_lat, e_lon) * 1.2 # 1.2 egrilik koeffitsienti
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
    # Har ikkala botni bir vaqtda ishga tushirish
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
