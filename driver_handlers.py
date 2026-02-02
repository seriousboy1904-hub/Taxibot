from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import database as db

router = driver_router

# Holatlarni aniqlaymiz
class DriverReg(StatesGroup):
    name = State()
    car_info = State()
    phone = State()
    location = State()

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    # Bazadan haydovchini tekshiramiz
    driver = db.get_driver(message.from_user.id)
    if driver:
        await message.answer("Siz allaqachon ro'yxatdan o'tgansiz. Buyurtmalar kutishingiz mumkin!")
    else:
        await message.answer("Xush kelibsiz! Haydovchi sifatida ro'yxatdan o'tamiz.\nIsmingizni kiriting:")
        await state.set_state(DriverReg.name)

@router.message(DriverReg.name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Mashina rusumi va davlat raqamini kiriting (masalan: Gentra 01 A 777 AA):")
    await state.set_state(DriverReg.car_info)

@router.message(DriverReg.car_info)
async def process_car(message: Message, state: FSMContext):
    await state.update_data(car_info=message.text)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Kontaktni yuborish", request_contact=True)]
    ], resize_keyboard=True)
    
    await message.answer("Telefon raqamingizni yuboring:", reply_markup=kb)
    await state.set_state(DriverReg.phone)

@router.message(DriverReg.phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Joylashuvni yuborish", request_location=True)]
    ], resize_keyboard=True)
    
    await message.answer("Hozirgi turgan joyingizni yuboring:", reply_markup=kb)
    await state.set_state(DriverReg.location)

@router.message(DriverReg.location, F.location)
async def process_location(message: Message, state: FSMContext):
    data = await state.get_data()
    lat = message.location.latitude
    lon = message.location.longitude
    
    # Bazaga saqlaymiz
    db.add_driver(
        message.from_user.id, 
        data['name'], 
        data['car_info'], 
        data['phone'], 
        lat, 
        lon
    )
    
    await message.answer("Muvaffaqiyatli ro'yxatdan o'tdingiz! Endi buyurtmalarni qabul qilishingiz mumkin.", reply_markup=ReplyKeyboardRemove())
    await state.clear()
