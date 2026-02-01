import os, sqlite3, asyncio, math, time, json
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")

START_PRICE = 10000
KM_PRICE = 1000
WAIT_PRICE = 1000  # minut

STATE_FILE = "locations.json"

client_bot = Bot(CLIENT_TOKEN)
driver_bot = Bot(DRIVER_TOKEN)

client_dp = Dispatcher()
driver_dp = Dispatcher()

# ================= JSON =================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(data):
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ================= DB =================
def db():
    return sqlite3.connect("taxi.db")

def init_db():
    c = db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS trips(
        driver_id INTEGER,
        client_id INTEGER,
        distance REAL,
        wait_time REAL,
        price INTEGER,
        finished_at TEXT
    )
    """)
    c.commit(); c.close()

# ================= GEO =================
def distance(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d1 = math.radians(lat2 - lat1)
    d2 = math.radians(lon2 - lon1)
    a = math.sin(d1/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(d2/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# ================= START =================
@client_dp.message(F.text == "/start")
async def c_start(m: types.Message):
    await m.answer("📍 Lokatsiya yuboring — taksi chaqiramiz")

@driver_dp.message(F.text == "/start")
async def d_start(m: types.Message):
    await m.answer("📍 Lokatsiya yuboring — ONLINE bo‘lasiz")

# ================= ACCEPT =================
@driver_dp.callback_query(F.data == "accept")
async def accept(call: types.CallbackQuery):
    data = load_state()
    data[str(call.from_user.id)] = {
        "client_id": 0,
        "status": "accepted",
        "last_lat": None,
        "last_lon": None,
        "distance": 0,
        "price": START_PRICE,
        "wait_start": None
    }
    save_state(data)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚖 Yetib keldim", callback_data="arrived")]
    ])
    await call.message.edit_text("✅ Buyurtma qabul qilindi", reply_markup=kb)

# ================= ARRIVED =================
@driver_dp.callback_query(F.data == "arrived")
async def arrived(call: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Safarni boshlash", callback_data="start")]
    ])
    await call.message.edit_text("📍 Yetib keldingiz", reply_markup=kb)

# ================= START TRIP =================
@driver_dp.callback_query(F.data == "start")
async def start_trip(call: types.CallbackQuery):
    data = load_state()
    data[str(call.from_user.id)]["status"] = "started"
    save_state(data)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ Kutish", callback_data="wait")],
        [InlineKeyboardButton(text="🛑 Yakunlash", callback_data="finish")]
    ])
    await call.message.edit_text("🚕 Safar boshlandi", reply_markup=kb)

# ================= DRIVER LOCATION =================
@driver_dp.message(F.location)
async def driver_location(m: types.Message):
    data = load_state()
    d_id = str(m.from_user.id)
    if d_id not in data or data[d_id]["status"] != "started":
        return

    st = data[d_id]
    if st["last_lat"] is not None:
        d = distance(
            st["last_lat"], st["last_lon"],
            m.location.latitude, m.location.longitude
        )
        st["distance"] += d / 1000
        st["price"] += (d / 1000) * KM_PRICE

    st["last_lat"] = m.location.latitude
    st["last_lon"] = m.location.longitude
    save_state(data)

# ================= WAIT =================
@driver_dp.callback_query(F.data == "wait")
async def wait(call: types.CallbackQuery):
    data = load_state()
    data[str(call.from_user.id)]["status"] = "waiting"
    data[str(call.from_user.id)]["wait_start"] = time.time()
    save_state(data)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Davom ettirish", callback_data="resume")]
    ])
    await call.message.edit_text("⏸ Kutish rejimi", reply_markup=kb)

@driver_dp.callback_query(F.data == "resume")
async def resume(call: types.CallbackQuery):
    data = load_state()
    st = data[str(call.from_user.id)]
    waited = (time.time() - st["wait_start"]) / 60
    st["price"] += waited * WAIT_PRICE
    st["status"] = "started"
    st["wait_start"] = None
    save_state(data)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏸ Kutish", callback_data="wait")],
        [InlineKeyboardButton(text="🛑 Yakunlash", callback_data="finish")]
    ])
    await call.message.edit_text("▶️ Davom etmoqda", reply_markup=kb)

# ================= FINISH =================
@driver_dp.callback_query(F.data == "finish")
async def finish(call: types.CallbackQuery):
    data = load_state()
    st = data.pop(str(call.from_user.id))
    save_state(data)

    c = db()
    c.execute(
        "INSERT INTO trips VALUES (?,?,?,?,?)",
        (call.from_user.id, st["client_id"], st["distance"], 0, int(st["price"]))
    )
    c.commit(); c.close()

    await call.message.edit_text(
        f"🛑 Safar yakunlandi\n"
        f"📏 Masofa: {st['distance']:.2f} km\n"
        f"💰 {int(st['price'])} so‘m"
    )

# ================= RUN =================
async def main():
    init_db()
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

asyncio.run(main())