import os, math, time, asyncio, sqlite3
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

load_dotenv()

CLIENT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
DRIVER_TOKEN = os.getenv("DRIVER_BOT_TOKEN")

MIN_PRICE = 5000
KM_PRICE = 1000
WAIT_PRICE = 500

DB = "taxi_platform.db"

client_bot = Bot(CLIENT_TOKEN)
driver_bot = Bot(DRIVER_TOKEN)
client_dp = Dispatcher()
driver_dp = Dispatcher()

ACTIVE_METERS = set()

# ================= DATABASE =================
def db():
    return sqlite3.connect(DB)

def init_db():
    c = db()
    c.execute("""
    CREATE TABLE IF NOT EXISTS drivers(
        id INTEGER PRIMARY KEY,
        lat REAL,
        lon REAL,
        status TEXT DEFAULT 'offline'
    )""")

    c.execute("""
    CREATE TABLE IF NOT EXISTS trips(
        driver_id INTEGER PRIMARY KEY,
        client_id INTEGER,
        last_lat REAL,
        last_lon REAL,
        distance REAL DEFAULT 0,
        wait_start REAL DEFAULT 0,
        wait_total REAL DEFAULT 0,
        started INTEGER DEFAULT 0,
        driver_msg INTEGER,
        client_msg INTEGER
    )""")
    c.commit(); c.close()

# ================= UTILS =================
def haversine(a,b,c,d):
    R=6371
    dlat=math.radians(c-a)
    dlon=math.radians(d-b)
    x=math.sin(dlat/2)**2+math.cos(math.radians(a))*math.cos(math.radians(c))*math.sin(dlon/2)**2
    return R*2*math.atan2(math.sqrt(x),math.sqrt(1-x))

def calc_price(dist, wait):
    return int(MIN_PRICE + max(0,dist-1)*KM_PRICE + int(wait)*WAIT_PRICE)

# ================= TAXIMETER =================
async def taximeter(driver_id):
    if driver_id in ACTIVE_METERS:
        return
    ACTIVE_METERS.add(driver_id)

    while True:
        await asyncio.sleep(3)
        c = db()
        t = c.execute("SELECT * FROM trips WHERE driver_id=?", (driver_id,)).fetchone()
        if not t:
            ACTIVE_METERS.discard(driver_id)
            c.close()
            return

        wait = t[6]
        if t[5] > 0:
            wait += (time.time() - t[5]) / 60

        price = calc_price(t[4], wait)

        text = (
            f"🚖 SAFAR DAVOM ETMOQDA\n\n"
            f"🛣 Masofa: {t[4]:.2f} km\n"
            f"⏱ Kutish: {int(wait)} daqiqa\n"
            f"💰 Narx: {price} so‘m"
        )

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⏸ Kutishni to‘xtatish" if t[5] else "▶️ Kutishni boshlash",
                callback_data="wait_toggle"
            )],
            [InlineKeyboardButton(text="🏁 Safarni yakunlash", callback_data="finish")]
        ])

        try:
            await driver_bot.edit_message_text(text, driver_id, t[8], reply_markup=kb)
            await client_bot.edit_message_text(text, t[1], t[9])
        except:
            pass

        c.close()

# ================= DRIVER =================
@driver_dp.message(Command("start"))
async def driver_start(m: types.Message):
    c=db()
    c.execute("INSERT OR IGNORE INTO drivers(id) VALUES(?)",(m.from_user.id,))
    c.commit(); c.close()
    await m.answer("📍 Online bo‘lish uchun LIVE LOCATION yuboring")

@driver_dp.message(F.location)
async def driver_location(m: types.Message):
    did=m.from_user.id
    lat,lon=m.location.latitude,m.location.longitude
    c=db()
    c.execute("UPDATE drivers SET lat=?,lon=?,status='online' WHERE id=?",(lat,lon,did))

    t=c.execute("SELECT started,last_lat,last_lon,distance FROM trips WHERE driver_id=?",(did,)).fetchone()
    if t and t[0]==1:
        step=haversine(t[1],t[2],lat,lon)
        if 0.005<step<0.7:
            c.execute("UPDATE trips SET distance=?,last_lat=?,last_lon=? WHERE driver_id=?",
                      (t[3]+step,lat,lon,did))
    c.commit(); c.close()

@driver_dp.callback_query(F.data=="arrived")
async def arrived(cb):
    kb=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="▶️ Safarni boshlash",callback_data="start_trip")]
    ])
    await cb.message.edit_text("🚕 Mijoz yonidasiz",reply_markup=kb)

@driver_dp.callback_query(F.data=="start_trip")
async def start_trip(cb):
    did=cb.from_user.id
    c=db()
    d=c.execute("SELECT lat,lon FROM drivers WHERE id=?",(did,)).fetchone()
    c.execute("""UPDATE trips SET started=1,last_lat=?,last_lon=? WHERE driver_id=?""",
              (d[0],d[1],did))
    c.commit(); c.close()
    await cb.answer("Safar boshlandi")
    asyncio.create_task(taximeter(did))

@driver_dp.callback_query(F.data=="wait_toggle")
async def wait_toggle(cb):
    c=db()
    t=c.execute("SELECT wait_start,wait_total FROM trips WHERE driver_id=?",(cb.from_user.id,)).fetchone()
    if t[0]==0:
        c.execute("UPDATE trips SET wait_start=? WHERE driver_id=?",(time.time(),cb.from_user.id))
    else:
        c.execute("UPDATE trips SET wait_total=?,wait_start=0 WHERE driver_id=?",
                  (t[1]+(time.time()-t[0])/60,cb.from_user.id))
    c.commit(); c.close()

@driver_dp.callback_query(F.data=="finish")
async def finish(cb):
    c=db()
    t=c.execute("SELECT * FROM trips WHERE driver_id=?",(cb.from_user.id,)).fetchone()
    wait=t[6]
    if t[5]:
        wait+=(time.time()-t[5])/60
    total=calc_price(t[4],wait)

    text=f"🏁 SAFAR YAKUNLANDI\n🛣 {t[4]:.2f} km\n💰 {total} so‘m"
    await cb.message.edit_text(text)
    await client_bot.send_message(t[1],text)

    c.execute("DELETE FROM trips WHERE driver_id=?",(cb.from_user.id,))
    c.execute("UPDATE drivers SET status='offline' WHERE id=?",(cb.from_user.id,))
    c.commit(); c.close()

# ================= CLIENT =================
@client_dp.message(Command("start"))
async def client_start(m):
    await m.answer("📍 Taxi chaqirish uchun lokatsiya yuboring")

@client_dp.message(F.location)
async def client_location(m):
    c=db()
    d=c.execute("SELECT id FROM drivers WHERE status='online' LIMIT 1").fetchone()
    if not d:
        await m.answer("❌ Hozir bo‘sh haydovchi yo‘q")
        c.close(); return

    dmsg=await driver_bot.send_message(
        d[0],
        "🚕 Yangi buyurtma",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚕 Yetib keldim",callback_data="arrived")]
        ])
    )
    cmsg=await m.answer("🚖 Haydovchi yo‘lda")

    c.execute("""INSERT OR REPLACE INTO trips
        (driver_id,client_id,driver_msg,client_msg)
        VALUES(?,?,?,?)""",(d[0],m.from_user.id,dmsg.message_id,cmsg.message_id))
    c.commit(); c.close()

# ================= RUN =================
async def main():
    init_db()
    await asyncio.gather(
        client_dp.start_polling(client_bot),
        driver_dp.start_polling(driver_bot)
    )

if __name__=="__main__":
    asyncio.run(main())