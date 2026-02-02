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
GROUP_ID = -1003356995649 # Ochiq buyurtmalar uchun guruh
DB_FILE = 'taxi_master.db'

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- GEODATA FUNKSIYASI ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371 # km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlambda = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- BAZANI INICIALIZATSIYA QILISH ---
async def init_db():
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS drivers 
            (user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'offline', 
             lat REAL, lon REAL, last_seen TEXT)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS orders 
            (id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER, 
             client_phone TEXT, client_name TEXT, lat REAL, lon REAL, 
             status TEXT DEFAULT 'pending', driver_id INTEGER)''')
        await db.commit()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI (LIVE LOCATION BILAN)
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🚀 Ishni boshlash (Online)", request_location=True)],
        [KeyboardButton(text="🔴 Ishni tugatish (Offline)")]
    ], resize_keyboard=True)
    await message.answer("Taksi Master Haydovchi tizimi.\nNavbatga turish uchun 'Online' tugmasini bosing va lokatsiyani **8 soatlik (Live)** qilib yuboring.", reply_markup=kb)

# 1. Haydovchi birinchi marta lokatsiya yuborganda
@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("INSERT OR REPLACE INTO drivers (user_id, status, lat, lon, last_seen) VALUES (?, 'online', ?, ?, ?)",
                         (message.from_user.id, 'online', lat, lon, datetime.now().isoformat()))
        await db.commit()
    
    msg = "✅ Siz onlaynsiz. Navbatga qo'shildingiz."
    if message.location.live_period is None:
        msg += "\n\n⚠️ DIQQAT: Siz oddiy lokatsiya yubordingiz. Harakatlanayotganingizda navbatingiz yangilanishi uchun lokatsiyani **'Live Location'** qilib qayta yuboring!"
    
    await message.answer(msg)

# 2. Haydovchi harakatlanganda (Live Location yangilanganda)
@driver_dp.edited_message(F.location)
async def driver_location_update(message: types.Message):
    if message.location:
        async with aiosqlite.connect(DB_FILE) as db:
            # Faqat online haydovchilarni koordinatasini yangilaymiz
            await db.execute("UPDATE drivers SET lat = ?, lon = ?, last_seen = ? WHERE user_id = ? AND status = 'online'",
                             (message.location.latitude, message.location.longitude, datetime.now().isoformat(), message.from_user.id))
            await db.commit()

@driver_dp.message(F.text == "🔴 Ishni tugatish (Offline)")
async def driver_offline(message: types.Message):
    async with aiosqlite.connect(DB_FILE) as db:
        await db.execute("UPDATE drivers SET status = 'offline' WHERE user_id = ?", (message.from_user.id,))
        await db.commit()
    await message.answer("Siz offlayn bo'ldingiz. Endi buyurtmalar kelmaydi.", reply_markup=ReplyKeyboardRemove())

# ==========================================
# 🚕 MIJOZ BOTI (BUYURTMA BERISH)
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🚕 Taksi chaqirish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi chaqirish uchun lokatsiyangizni yuboring.", reply_markup=kb)

@client_dp.message(F.location)
async def client_request(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("Telefon raqamingizni tasdiqlang:", reply_markup=kb)
    await state.set_state(ClientOrder.waiting_phone)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def order_finalizing(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data['lat'], data['lon']
    c_phone, c_name = message.contact.phone_number, message.from_user.full_name
    
    async with aiosqlite.connect(DB_FILE) as db:
        # Buyurtmani saqlash
        cursor = await db.execute("INSERT INTO orders (client_id, client_phone, client_name, lat, lon) VALUES (?, ?, ?, ?, ?)",
                                  (message.from_user.id, c_phone, c_name, c_lat, c_lon))
        order_id = cursor.lastrowid
        
        # Eng yaqin online haydovchini topish
        cursor = await db.execute("SELECT user_id, lat, lon FROM drivers WHERE status = 'online'")
        drivers = await cursor.fetchall()
        
        best_driver = None
        min_d = 5.0 # Max 5 km masofa

        for d_id, d_lat, d_lon in drivers:
            dist = calculate_distance(c_lat, c_lon, d_lat, d_lon)
            if dist < min_d:
                min_d = dist
                best_driver = d_id
        
        if best_driver:
            ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{order_id}")]])
            await driver_bot.send_location(best_driver, c_lat, c_lon)
            await driver_bot.send_message(best_driver, f"🚕 YANGI BUYURTMA!\n👤 {c_name}\n📞 {c_phone}\nMasofa: {min_d:.1f} km", reply_markup=ikb)
            await message.answer("⏳ Eng yaqin haydovchiga xabar yuborildi. Iltimos, kuting...", reply_markup=ReplyKeyboardRemove())
        else:
            await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n👤 {c_name}\n📞 {c_phone}\n📍 Xaritadan ko'ring.")
            await message.answer("Atrofda bo'sh haydovchi topilmadi, buyurtma barcha haydovchilar guruhiga yuborildi.")
        
        await db.commit()
    await state.clear()

# --- QABUL QILISH ---
@driver_dp.callback_query(F.data.startswith("acc_"))
async def handle_accept(callback: types.CallbackQuery):
    order_id = callback.data.split("_")[1]
    async with aiosqlite.connect(DB_FILE) as db:
        cursor = await db.execute("SELECT * FROM orders WHERE id = ? AND status = 'pending'", (order_id,))
        order = await cursor.fetchone()
        
        if order:
            await db.execute("UPDATE orders SET status = 'accepted', driver_id = ? WHERE id = ?", (callback.from_user.id, order_id))
            await db.execute("UPDATE drivers SET status = 'busy' WHERE user_id = ?", (callback.from_user.id,))
            await db.commit()
            
            await client_bot.send_message(order[1], f"✅ Haydovchi buyurtmani qabul qildi!\n📞 Aloqa: {callback.from_user.full_name}")
            await callback.message.edit_text(f"🚀 Buyurtma qabul qilindi. Mijoz: {order[3]}")
        else:
            await callback.answer("Kechirasiz, buyurtma allaqachon olingan.", show_alert=True)

# --- ASOSIY FUNKSIYA ---
async def main():
    await init_db()
    print("Robotlar ishlamoqda...")
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == '__main__':
    asyncio.run(main())
