import os, sqlite3, asyncio, math, json
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

# ========= SOZLAMALAR =========
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649

DB_FILE = "taxi_master.db"
GEOJSON_FILE = "locations.json"

client_bot = Bot(CLIENT_TOKEN)
driver_bot = Bot(DRIVER_TOKEN)

client_dp = Dispatcher()
driver_dp = Dispatcher()

# ========= FSM =========
class ClientOrder(StatesGroup):
    waiting_phone = State()

# ========= GEO =========
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def find_closest_station(lat, lon):
    if not os.path.exists(GEOJSON_FILE):
        return "Noma'lum", 0
    with open(GEOJSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    best = ("Noma'lum", float("inf"))
    for ftr in data.get("features", []):
        c = ftr["geometry"]["coordinates"]
        d = calculate_distance(lat, lon, c[1], c[0])
        if d < best[1]:
            best = (ftr["properties"].get("name", "Bekat"), d)
    return best

# ========= DB =========
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS drivers(
        user_id INTEGER PRIMARY KEY,
        status TEXT,
        lat REAL,
        lon REAL,
        station TEXT,
        joined_at TEXT
    )""")

    conn.execute("""
    CREATE TABLE IF NOT EXISTS trips(
        driver_id INTEGER,
        client_id INTEGER,
        phone TEXT,
        s_lat REAL,
        s_lon REAL,
        started_at TEXT
    )""")
    conn.commit()
    conn.close()

# =====================================================
# 🧑‍💼 MIJOZ
# =====================================================
@client_dp.message(F.location)
async def client_location(message: types.Message, state: FSMContext):
    st, _ = find_closest_station(
        message.location.latitude,
        message.location.longitude
    )

    await state.update_data(
        lat=message.location.latitude,
        lon=message.location.longitude,
        station=st
    )

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]],
        resize_keyboard=True
    )

    await state.set_state(ClientOrder.waiting_phone)
    await message.answer(
        f"📍 Hudud: {st}\nTelefon raqamingizni yuboring:",
        reply_markup=kb
    )

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data["lat"], data["lon"]
    phone = message.contact.phone_number
    client_id = message.from_user.id

    conn = sqlite3.connect(DB_FILE)
    drivers = conn.execute(
        "SELECT user_id, lat, lon FROM drivers WHERE status='online'"
    ).fetchall()
    conn.close()

    best_driver = None
    min_d = 5000

    for d_id, d_lat, d_lon in drivers:
        d = calculate_distance(c_lat, c_lon, d_lat, d_lon)
        if d < min_d:
            min_d = d
            best_driver = d_id

    if not best_driver:
        await client_bot.send_message(
            GROUP_ID,
            f"📢 OCHIQ BUYURTMA\n📞 {phone}"
        )
        await message.answer("❌ Haydovchi topilmadi.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    ikb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Qabul qilish",
                callback_data=f"acc:{client_id}:{c_lat}:{c_lon}:{phone}"
            )
        ]]
    )

    await driver_bot.send_location(best_driver, c_lat, c_lon)
    await driver_bot.send_message(
        best_driver,
        f"🚕 YANGI BUYURTMA\n📞 {phone}",
        reply_markup=ikb
    )

    await message.answer("⏳ Haydovchi qidirilmoqda...", reply_markup=ReplyKeyboardRemove())
    await state.clear()

# =====================================================
# 🚖 HAYDOVCHI
# =====================================================
@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    lat, lon = message.location.latitude, message.location.longitude
    st, _ = find_closest_station(lat, lon)

    conn = sqlite3.connect(DB_FILE)
    conn.execute("""
        INSERT OR REPLACE INTO drivers
        VALUES (?, 'online', ?, ?, ?, ?)
    """, (message.from_user.id, lat, lon, st, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    await message.answer(f"✅ Online\n📍 {st}")

@driver_dp.callback_query(F.data.startswith("acc:"))
async def accept_order(call: CallbackQuery):
    _, client_id, lat, lon, phone = call.data.split(":")
    driver_id = call.from_user.id

    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (driver_id,))
    conn.execute("""
        INSERT INTO trips VALUES (?, ?, ?, ?, ?, ?)
    """, (
        driver_id,
        int(client_id),
        phone,
        float(lat),
        float(lon),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    await call.message.edit_text("✅ Buyurtma qabul qilindi")
    await call.answer("Qabul qilindi 🚖")

    try:
        await client_bot.send_message(
            int(client_id),
            "🚖 Haydovchi yo‘lga chiqdi!"
        )
    except:
        pass

# ========= RUN =========
async def main():
    init_db()
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__ == "__main__":
    asyncio.run(main())