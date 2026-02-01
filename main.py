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
START_PRICE = 5000
KM_PRICE = 3500
WAIT_PRICE = 500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
dp = Dispatcher()

# --- BAZA FUNKSIYALARI ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, car_info TEXT, 
         station TEXT, status TEXT DEFAULT 'offline', joined_at TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, 
         start_time REAL, wait_start REAL DEFAULT 0, client_name TEXT)''')
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
# 🚕 MIJOZ BOTI
# ==========================================

@dp.message(Command("start"), F.bot.id == client_bot.id)
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Lokatsiya yuborish", request_location=True)]],
        resize_keyboard=True
    )
    await message.answer(
        "Xush kelibsiz! Taxi chaqirish uchun lokatsiyangizni yuboring 👇",
        reply_markup=kb
    )

@dp.message(F.location, F.bot.id == client_bot.id)
async def client_loc(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT user_id, name FROM drivers WHERE station = ? AND status = 'online' ORDER BY joined_at ASC LIMIT 1",
        (station,)
    )
    driver = cursor.fetchone()
    conn.close()

    if driver:
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{message.from_user.id}"),
                InlineKeyboardButton(text="🔄 O'tkazib yuborish", callback_data=f"skip_{message.from_user.id}_{station}")
            ]
        ])

        # ✅ TUZATILGAN JOY (GROUP GA DARROV TUSHMAYDI)
        try:
            await driver_bot.send_message(
                driver[0],
                f"🚕 YANGI BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}\n\nQabul qilasizmi?",
                reply_markup=ikb
            )
            await message.answer(
                f"⏳ Buyurtma {station} bekatidagi haydovchiga ({driver[1]}) yuborildi.\n"
                f"Agar qabul qilinmasa, keyin guruhga tushadi."
            )
        except Exception:
            await message.answer("❌ Haydovchiga yuborib bo‘lmadi.")
    else:
        await send_to_group(message, station, lat, lon)

async def send_to_group(message, station, lat, lon):
    link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{message.from_user.id}"
    ikb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]]
    )
    await client_bot.send_location(GROUP_ID, lat, lon)
    await client_bot.send_message(
        GROUP_ID,
        f"📢 OCHIQ BUYURTMA!\n📍 Bekat: {station}\n👤 Mijoz: {message.from_user.full_name}",
        reply_markup=ikb
    )
    await message.answer("🚕 Bekatda bo‘sh haydovchi yo‘q, buyurtma guruhga yuborildi.")

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI
# ==========================================

@dp.message(Command("start"), F.bot.id == driver_bot.id)
async def driver_start(message: types.Message, command: CommandObject):
    if command.args and command.args.startswith("gr_"):
        client_id = int(command.args.split("_")[1])
        await start_trip_engine(message, client_id)
        return

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🟢 Ishni boshlash (Live)", request_location=True)],
            [KeyboardButton(text="🏁 Safarni yakunlash"), KeyboardButton(text="⏳ Kutishni boshlash")],
            [KeyboardButton(text="📴 Offline")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "👨‍✈️ Haydovchi paneli. Ishni boshlash uchun Live lokatsiya yuboring.",
        reply_markup=kb
    )

@dp.message(F.location & F.location.live_period, F.bot.id == driver_bot.id)
async def driver_queue_update(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    station = find_station(lat, lon)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO drivers (user_id, name, station, status, joined_at) VALUES (?, ?, ?, 'online', ?)",
        (message.from_user.id, message.from_user.full_name, station, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

    await message.answer(f"✅ Siz {station} bekati navbatiga turdingiz. Status: Online")

@dp.callback_query(F.data.startswith("acc_"), F.bot.id == driver_bot.id)
async def driver_accept_personal(call: CallbackQuery):
    client_id = int(call.data.split("_")[1])
    await call.message.edit_text("✅ Buyurtmani qabul qildingiz!")
    await start_trip_engine(call.message, client_id, call.from_user.id)

@dp.callback_query(F.data.startswith("skip_"), F.bot.id == driver_bot.id)
async def driver_skip(call: CallbackQuery):
    data = call.data.split("_")
    client_id, station = int(data[1]), data[2]

    await call.message.edit_text("🔄 Buyurtma o‘tkazib yuborildi (guruhga yuborildi).")

    link = f"https://t.me/{(await driver_bot.get_me()).username}?start=gr_{client_id}"
    ikb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚖 Buyurtmani olish", url=link)]]
    )

    await client_bot.send_message(
        GROUP_ID,
        f"📢 RAD ETILGAN BUYURTMA\n📍 Bekat: {station}",
        reply_markup=ikb
    )

async def start_trip_engine(message, client_id, driver_id=None):
    did = driver_id or message.from_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO trips (driver_id, client_id, start_time) VALUES (?, ?, ?)",
        (did, client_id, time.time())
    )
    cursor.execute(
        "UPDATE drivers SET status = 'busy' WHERE user_id = ?",
        (did,)
    )
    conn.commit()
    conn.close()

    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏳ Kutishni boshlash")],
            [KeyboardButton(text="🏁 Safarni yakunlash")]
        ],
        resize_keyboard=True
    )

    await driver_bot.send_message(did, "🚖 Safar boshlandi!", reply_markup=kb)
    await client_bot.send_message(client_id, "🚕 Haydovchi buyurtmani qabul qildi!")

@dp.message(F.text == "⏳ Kutishni boshlash", F.bot.id == driver_bot.id)
async def driver_wait(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE trips SET wait_start = ? WHERE driver_id = ?",
        (time.time(), message.from_user.id)
    )
    conn.commit()
    conn.close()

    await message.answer("⏱ Kutish vaqti hisoblanmoqda...")

@dp.message(F.text == "🏁 Safarni yakunlash", F.bot.id == driver_bot.id)
async def driver_end(message: types.Message):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT client_id, start_time, wait_start FROM trips WHERE driver_id = ?",
        (message.from_user.id,)
    )
    trip = cursor.fetchone()
    if not trip:
        return

    cid, start_t, wait_t = trip
    total_time = (time.time() - start_t) / 60
    wait_time = (time.time() - wait_t) / 60 if wait_t > 0 else 0

    jami = START_PRICE + (wait_time * WAIT_PRICE)

    chek = (
        f"🏁 SAFAR YAKUNLANDI\n\n"
        f"⏱ Umumiy vaqt: {int(total_time)} daq\n"
        f"⏳ Kutish: {int(wait_time)} daq\n"
        f"💰 To‘lov: {int(jami)} so‘m"
    )

    await message.answer(chek, reply_markup=ReplyKeyboardRemove())
    await client_bot.send_message(cid, chek + "\n\nRahmat!")

    cursor.execute("DELETE FROM trips WHERE driver_id = ?", (message.from_user.id,))
    cursor.execute(
        "UPDATE drivers SET status = 'online', joined_at = ? WHERE user_id = ?",
        (datetime.now().isoformat(), message.from_user.id)
    )
    conn.commit()
    conn.close()

    await message.answer("🔄 Siz yana navbatga qaytdingiz.")

# --- ASOSIY ---
async def main():
    init_db()
    await asyncio.gather(
        dp.start_polling(client_bot),
        dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())