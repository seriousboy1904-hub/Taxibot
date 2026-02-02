import os, asyncio, math, json, aiosqlite
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)

load_dotenv()

# --- SOZLAMALAR ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'
GEOJSON_FILE = 'locations.json'

# Tariflar
START_PRICE = 10000
NEXT_KM_PRICE = 1500

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class ClientOrder(StatesGroup):
    waiting_loc = State()
    waiting_phone = State()

# --- GEODATA VA BAZA FUNKSIYALARI ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371  # km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS drivers 
            (user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'offline', 
             lat REAL, lon REAL, last_seen TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS orders 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, 
             client_phone TEXT, client_name TEXT, lat REAL, lon REAL, 
             status TEXT DEFAULT 'pending')''')
        await db.commit()

# --- 👨‍✈️ HAYDOVCHI BOTI QISMI ---

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚀 Online bo'lish", request_location=True)],
        [KeyboardButton(text="🔴 Offline bo'lish")]
    ], resize_keyboard=True)
    await message.answer("Xush kelibsiz, haydovchi! Ish boshlash uchun lokatsiya yuboring.", reply_markup=kb)

@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO drivers (user_id, status, lat, lon, last_seen) VALUES (?, 'online', ?, ?, ?)",
                         (message.from_user.id, 'online', lat, lon, datetime.now().isoformat()))
        await db.commit()
    await message.answer("✅ Siz onlayn holatdasiz va buyurtmalarni qabul qila olasiz.")

@driver_dp.message(F.text == "🔴 Offline bo'lish")
async def driver_offline(message: types.Message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE drivers SET status = 'offline' WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    await message.answer("Kuningiz xayrli o'tsin! Siz offlayn bo'ldingiz.", reply_markup=ReplyKeyboardRemove())

# --- 🚕 MIJOZ BOTI QISMI ---

@client_dp.message(Command("start"))
async def client_start(message: types.Message, state: FSMContext):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚕 Taksiga buyurtma berish", request_location=True)]], resize_keyboard=True)
    await message.answer("Assalomu alaykum! Taksi chaqirish uchun lokatsiyangizni yuboring.", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc_received(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Telefonni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("Raqamingizni yuboring:", reply_markup=kb)
    await state.set_state(ClientOrder.waiting_phone)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_final_order(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data['lat'], data['lon']
    c_phone = message.contact.phone_number
    c_id, c_name = message.from_user.id, message.from_user.full_name

    async with aiosqlite.connect(DB_FILE) as db:
        # Buyurtmani bazaga yozamiz
        cursor = await db.execute("INSERT INTO orders (client_id, client_phone, client_name, lat, lon) VALUES (?, ?, ?, ?, ?)",
                                  (c_id, c_phone, c_name, c_lat, c_lon))
        order_id = cursor.lastrowid
        
        # Eng yaqin haydovchini topish (5 km radiusda)
        cursor = await db.execute("SELECT user_id, lat, lon FROM drivers WHERE status = 'online'")
        drivers = await cursor.fetchall()
        
        best_driver = None
        min_dist = 5.0 # km
        
        for d_id, d_lat, d_lon in drivers:
            dist = calculate_distance(c_lat, c_lon, d_lat, d_lon)
            if dist < min_dist:
                min_dist = dist
                best_driver = d_id

        if best_driver:
            ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{order_id}")]])
            await driver_bot.send_location(best_driver, c_lat, c_lon)
            await driver_bot.send_message(best_driver, f"🚕 Yangi buyurtma!\n👤 {c_name}\n📞 {c_phone}\nMasofa: {min_dist:.1f} km", reply_markup=ikb)
            await message.answer("⏳ Haydovchi qidirilmoqda...", reply_markup=ReplyKeyboardRemove())
        else:
            await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n📍 Lokatsiya: {c_lat}, {c_lon}\n📞 {c_phone}")
            await message.answer("Atrofda bo'sh haydovchi topilmadi, buyurtma guruhga yuborildi.")
        
        await db.commit()
    await state.clear()

# --- 🔄 CALLBACK HANDLER (HAYDOVCHI QABUL QILGANDA) ---

@driver_dp.callback_query(F.data.startswith("accept_"))
async def driver_accept(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM orders WHERE id = ? AND status = 'pending'", (order_id,))
        order = await cursor.fetchone()
        
        if order:
            await db.execute("UPDATE orders SET status = 'accepted' WHERE id = ?", (order_id,))
            await db.execute("UPDATE drivers SET status = 'busy' WHERE user_id = ?", (callback.from_user.id,))
            await db.commit()
            
            # Mijozga xabar yuborish
            await client_bot.send_message(order[1], "✅ Haydovchi buyurtmani qabul qildi va yo'lga chiqdi!")
            await callback.message.edit_text(f"✅ Buyurtma qabul qilindi. Mijoz: {order[2]}")
        else:
            await callback.answer("Bu buyurtma allaqachon olingan yoki bekor qilingan.", show_alert=True)

# --- ASOSIY ISHLATISH ---
async def main():
    await init_db()
    print("Botlar ishga tushdi...")
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
