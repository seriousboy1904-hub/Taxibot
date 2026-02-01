import os, json, math, sqlite3, asyncio, time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)

# --- SOZLAMALAR ---
CLIENT_TOKEN = "CLIENT_TOKEN_SHU_YERGA"
DRIVER_TOKEN = "DRIVER_TOKEN_SHU_YERGA"
DB_FILE = 'taxi_master.db'

MIN_PRICE = 5000       
KM_PRICE = 1000          
WAIT_PRICE = 500         

client_bot = Bot(token=CLIENT_TOKEN)
driver_bot = Bot(token=DRIVER_TOKEN)
driver_dp = Dispatcher()

# ==========================================
# 🔄 ASOSIY MONITORING (TUGMALAR SHU YERDA)
# ==========================================

async def taximeter_loop(did):
    """Har 4 soniyada tugmalarni va hisobni yangilab turadi"""
    while True:
        await asyncio.sleep(4)
        conn = sqlite3.connect(DB_FILE)
        tr = conn.execute("SELECT * FROM trips WHERE driver_id=?", (did,)).fetchone()
        
        if not tr: 
            conn.close()
            break # Safar tugasa tsikl to'xtaydi
        
        cid, wait_start, total_wait_min = tr[1], tr[3], tr[4]
        total_dist, is_riding = tr[7], tr[8]
        d_msg_id, c_msg_id = tr[9], tr[10]

        # Kutish vaqtini hisoblash
        curr_wait = total_wait_min
        if wait_start > 0:
            curr_wait += (time.time() - wait_start) / 60

        # Narx: Minimalka 5000 + (km > 1 bo'lsa har km ga 1000) + kutish
        dist_cost = (total_dist - 1.0) * KM_PRICE if total_dist > 1.0 else 0
        summa = int(MIN_PRICE + dist_cost + (int(curr_wait) * WAIT_PRICE))
        
        # TUGMALARNI QAT'IY BELGILASH
        buttons = []
        
        # 1-qator: Ojidaniye nazorati
        if wait_start > 0:
            buttons.append([InlineKeyboardButton(text="⏸ Pauza (Kutish)", callback_data="wait_pause")])
        else:
            buttons.append([InlineKeyboardButton(text="▶️ Davom etish (Kutish)", callback_data="wait_play")])
        
        # 2-qator: Safar holatiga qarab tugma
        if is_riding == 0:
            buttons.append([InlineKeyboardButton(text="🚖 SAFARNI BOSHLASH", callback_data="ride_start")])
        else:
            buttons.append([InlineKeyboardButton(text="🏁 SAFARNI YAKUNLASH", callback_data="fin_pre")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        status = "🚖 Safarda" if is_riding else "⏳ Kutishda"
        text = (f"{status}\n\n"
                f"🛣 Masofa: {total_dist:.2f} km\n"
                f"⏱ Kutish: {int(curr_wait)} daq\n"
                f"💰 Hisob: {summa} so'm")
        
        try:
            # Haydovchida xabarni yangilash
            await driver_bot.edit_message_text(text, did, d_msg_id, reply_markup=keyboard)
            # Mijozda xabarni yangilash (tugmalarsiz)
            await client_bot.edit_message_text(text, cid, c_msg_id)
        except Exception as e:
            print(f"Update error: {e}")
        
        conn.close()

# ==========================================
# 🚕 CALLBACK HANDLERS
# ==========================================

@driver_dp.callback_query(F.data == "arrived")
async def arrived_handler(call: CallbackQuery):
    """Yetib keldim bosilganda ojidaniye boshlanadi va loop ishga tushadi"""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    
    # Loopni ishga tushirish (xabar edit qilinishini loop ichida qiladi)
    asyncio.create_task(taximeter_loop(call.from_user.id))
    await call.answer("Kutish rejimi yoqildi")

@driver_dp.callback_query(F.data == "ride_start")
async def ride_start_handler(call: CallbackQuery):
    """Mijoz mashinaga o'tirdi, safar va GPS hisobi boshlanadi"""
    conn = sqlite3.connect(DB_FILE)
    # Joriy ojidaniyani saqlab, statusni 'riding' ga o'tkazish
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    
    new_wait = tr[1]
    if tr[0] > 0:
        new_wait += (time.time() - tr[0]) / 60
        
    conn.execute("UPDATE trips SET is_riding=1, wait_start=0, total_wait=? WHERE driver_id=?", 
                 (new_wait, call.from_user.id))
    conn.commit()
    conn.close()
    await call.answer("Oq yo'l! Masofa hisoblanmoqda.")

@driver_dp.callback_query(F.data == "wait_pause")
async def pause_handler(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    tr = conn.execute("SELECT wait_start, total_wait FROM trips WHERE driver_id=?", (call.from_user.id,)).fetchone()
    if tr and tr[0] > 0:
        added_wait = (time.time() - tr[0]) / 60
        conn.execute("UPDATE trips SET wait_start=0, total_wait=? WHERE driver_id=?", (tr[1] + added_wait, call.from_user.id))
        conn.commit()
    conn.close()
    await call.answer("Kutish to'xtatildi")

@driver_dp.callback_query(F.data == "wait_play")
async def play_handler(call: CallbackQuery):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("UPDATE trips SET wait_start=? WHERE driver_id=?", (time.time(), call.from_user.id))
    conn.commit()
    conn.close()
    await call.answer("Kutish davom ettirilmoqda")
