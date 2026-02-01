import os, json, math, sqlite3, asyncio, time
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

# --- KONFIGURATSIYA ---
CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")
GROUP_ID = -1003356995649 
DB_FILE = 'taxi_master.db'

# TARIFLAR
START_PRICE = 10000  # 1 km gacha
NEXT_KM_PRICE = 1000 # 1 km dan keyin har bir km uchun
WAIT_PRICE = 1000    # 1 daqiqa kutish uchun

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
client_dp, driver_dp = Dispatcher(), Dispatcher()

class DriverReg(StatesGroup):
    phone = State()
    car_model = State()
    car_number = State()

class ClientOrder(StatesGroup):
    waiting_phone = State()

# --- MA'LUMOTLAR BAZASI ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Haydovchilar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS drivers 
        (user_id INTEGER PRIMARY KEY, name TEXT, phone TEXT, car TEXT, car_num TEXT, 
         status TEXT DEFAULT 'offline', lat REAL, lon REAL)''')
    # Safarlar jadvali
    cursor.execute('''CREATE TABLE IF NOT EXISTS trips 
        (driver_id INTEGER PRIMARY KEY, client_id INTEGER, client_phone TEXT,
         wait_start REAL DEFAULT 0, total_wait REAL DEFAULT 0,
         last_lat REAL, last_lon REAL, distance REAL DEFAULT 0, msg_id INTEGER)''')
    conn.commit()
    conn.close()

def get_dist(lat1, lon1, lat2, lon2):
    R = 6371
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def calculate_price(dist, wait_time):
    # 1 km gacha bo'lsa START_PRICE, oshsa har bir km uchun NEXT_KM_PRICE
    price = START_PRICE
    if dist > 1:
        price += (dist - 1) * NEXT_KM_PRICE
    price += (wait_time * WAIT_PRICE)
    return price

# ==========================================
# 🚕 MIJOZ BOTI LOGIKASI
# ==========================================

@client_dp.message(Command("start"))
async def client_start(message: types.Message):
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📍 Taksi chaqirish", request_location=True)]], resize_keyboard=True)
    await message.answer("Xush kelibsiz! Taksi kerak bo'lsa lokatsiyangizni yuboring 👇", reply_markup=kb)

@client_dp.message(F.location)
async def client_loc(message: types.Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await state.set_state(ClientOrder.waiting_phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqamni yuborish", request_contact=True)]], resize_keyboard=True)
    await message.answer("📱 Telefon raqamingizni yuboring:", reply_markup=kb)

@client_dp.message(ClientOrder.waiting_phone, F.contact)
async def client_order_final(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_lat, c_lon = data['lat'], data['lon']
    c_phone = message.contact.phone_number
    c_id = message.from_user.id
    c_name = message.from_user.full_name

    # Online haydovchini qidirish
    conn = sqlite3.connect(DB_FILE)
    driver = conn.execute("SELECT user_id FROM drivers WHERE status = 'online' LIMIT 1").fetchone()
    conn.close()

    if driver:
        d_id = driver[0]
        ikb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"acc_{c_id}_{c_phone}_{c_lat}_{c_lon}")]
        ])
        await driver_bot.send_location(d_id, c_lat, c_lon)
        await driver_bot.send_message(d_id, f"🚕 YANGI BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}", reply_markup=ikb)
        await message.answer("⏳ Buyurtma haydovchiga yuborildi. Tez orada bog'lanishadi.", reply_markup=ReplyKeyboardRemove())
    else:
        # Online haydovchi yo'q bo'lsa guruhga yuborish
        await client_bot.send_message(GROUP_ID, f"📢 OCHIQ BUYURTMA!\n👤 Mijoz: {c_name}\n📞 {c_phone}\n📍 Manzil: [Xaritada ko'rish](https://www.google.com/maps?q={c_lat},{c_lon})", parse_mode="Markdown")
        await message.answer("Hozircha bo'sh haydovchilar yo'q, buyurtma umumiy guruhga yuborildi.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

# ==========================================
# 👨‍✈️ HAYDOVCHI BOTI LOGIKASI
# ==========================================

@driver_dp.message(Command("start"))
async def driver_start_cmd(message: types.Message, state: FSMContext):
    conn = sqlite3.connect(DB_FILE)
    user = conn.execute("SELECT car_num FROM drivers WHERE user_id=?", (message.from_user.id,)).fetchone()
    conn.close()
    if user:
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🟢 Ishni boshlash (Online)", request_location=True)]], resize_keyboard=True)
        await message.answer("Xush kelibsiz! Ishni boshlash uchun lokatsiya yuboring.", reply_markup=kb)
    else:
        await state.set_state(DriverReg.phone)
        await message.answer("Ro'yxatdan o'tish:\n1. Telefon raqamingizni yuboring:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Raqam", request_contact=True)]], resize_keyboard=True))

@driver_dp.message(DriverReg.phone, F.contact)
async def reg_p(message: types.Message, state: FSMContext):
    await state.update_data(p=message.contact.phone_number)
    await state.set_state(DriverReg.car_model)
    await message.answer("2. Mashina rusumi (masalan: Cobalt):", reply_markup=ReplyKeyboardRemove())

@driver_dp.message(DriverReg.car_model)
async def reg_c(message: types.Message, state: FSMContext):
    await state.update_data(c=message.text)
    await state.set_state(DriverReg.car_number)
    await message.answer("3. Mashina raqami (masalan: 01A777AA):")

@driver_dp.message(DriverReg.car_number)
async def reg_f(message: types.Message, state: FSMContext):
    data = await state.get_data()
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO drivers (user_id, name, phone, car, car_num, status) VALUES (?,?,?,?,?,?)",
                 (message.from_user.id, message.from_user.full_name, data['p'], data['c'], message.text, 'offline'))
    conn.commit()
    conn.close()
    await state.clear()
    await message.answer("✅ Ro'yxatdan o'tdingiz. Ishni boshlash uchun lokatsiya yuboring.")

@driver_dp.message(F.location)
async def driver_online(message: types.Message):
    # Haydovchi lokatsiya yuborganda uni online qilamiz
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE drivers SET status='online', lat=?, lon=? WHERE user_id=?", (message.location.latitude, message.location.longitude, message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer("✅ Siz onlinesiz. Buyurtmalarni qabul qilishingiz mumkin.")

# --- TAKSOMETR VA SAFAR BOSHQARUVI ---

@driver_dp.callback_query(F.data.startswith("acc_"))
async def accept_order(call: CallbackQuery):
    _, cid, cph, lat, lon = call.data.split("_")
    did = call.from_user.id
    
    # Safar xabarini yuboramiz (shuni keyin yangilab boramiz)
    initial_text = f"🚖 **Safar boshlandi**\n\n📏 Masofa: 0.00 km\n💰 Summa: {START_PRICE:,.0f} so'm"
    ikb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
        [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
    ])
    msg = await call.message.answer(initial_text, reply_markup=ikb, parse_mode="Markdown")
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO trips (driver_id, client_id, client_phone, last_lat, last_lon, distance, msg_id) VALUES (?,?,?,?,?,0,?)",
                 (did, cid, cph, lat, lon, msg.message_id))
    conn.execute("UPDATE drivers SET status='busy' WHERE user_id=?", (did,))
    conn.commit()
    conn.close()
    
    await call.message.delete() # Eski xabarni o'chiramiz
    await client_bot.send_message(cid, "🚕 Haydovchi buyurtmani qabul qildi va yo'lga chiqdi.")

@driver_dp.edited_message(F.location)
async def taxi_meter_logic(message: types.Message):
    """Haydovchi harakatlanganda (Live Location) narxni yangilash"""
    did = message.from_user.id
    lat, lon = message.location.latitude, message.location.longitude
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    trip = cursor.execute("SELECT last_lat, last_lon, distance, total_wait, msg_id FROM trips WHERE driver_id=?", (did,)).fetchone()
    
    if trip:
        l_lat, l_lon, dist, twait, msg_id = trip
        new_dist = dist
        if l_lat and l_lon:
            step = get_dist(l_lat, l_lon, lat, lon)
            if step > 0.02: # 20 metrdan ortiq siljish bo'lsa hisoblaymiz
                new_dist += step
        
        cursor.execute("UPDATE trips SET last_lat=?, last_lon=?, distance=? WHERE driver_id=?", (lat, lon, new_dist, did))
        conn.commit()
        
        # Narxni hisoblash va xabarni yangilash
        price = calculate_price(new_dist, twait)
        text = (f"🚖 **TAKSOMETR (LIVE)**\n\n"
                f"📏 Masofa: {new_dist:.2f} km\n"
                f"⏳ Kutish: {int(twait)} daq\n"
                f"💰 **Summa: {price:,.0f} so'm**")
        
        try:
            await driver_bot.edit_message_text(text, did, msg_id, parse_mode="Markdown", 
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="⏳ Ojidaniya", callback_data="wait_on")],
                    [InlineKeyboardButton(text="🏁 Yakunlash", callback_data="fin_pre")]
                ]))
        except: pass
    conn.close()

@driver_dp.callback_query(F.data == "wait_on")
async def wait_on(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    await call.answer("Kutish vaqti hisoblanmoqda...")
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="▶️ Davom etish", callback_data="wait_off")]]))

@driver_dp.callback_query(F.data == "wait_off")
async def wait_off(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        diff = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=total_wait+? WHERE driver_id=?", (diff, call.from_user.id))
        conn.commit()
    conn.close()
    await call.answer("Safarni davom ettiring.")
    # Xabar keyingi location yangilanishida o'zgaradi

@driver_dp.callback_query(F.data == "fin_pre")
async def finish_trip(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT client_id, total_wait, distance FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr:
        cid, twait, dist = tr
        total = calculate_price(dist, twait)
        final_text = (f"🏁 **Safar yakunlandi**\n\n"
                      f"📏 Masofa: {dist:.2f} km\n"
                      f"⏳ Kutish: {int(twait)} daq\n"
                      f"💰 **Jami: {total:,.0f} so'm**")
        
        await call.message.edit_text(final_text, parse_mode="Markdown")
        if cid: await client_bot.send_message(cid, f"Safar yakunlandi. To'lov: {total:,.0f} so'm.\nRahmat!")
        
        conn.execute("UPDATE drivers SET status='online' WHERE user_id=?", (call.from_user.id,))
        conn.execute("DELETE FROM trips WHERE driver_id=?", (call.from_user.id,))
        conn.commit()
    conn.close()

# --- ASOSIY ---
async def main():
    init_db()
    print("Botlar muvaffaqiyatli ishga tushdi!")
    await asyncio.gather(
        client_dp.start_polling(client_bot, skip_updates=True),
        driver_dp.start_polling(driver_bot, skip_updates=True)
    )

if __name__ == '__main__':
    asyncio.run(main())
