import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import CLIENT_TOKEN, DRIVER_TOKEN
from client_handlers import router as client_router
from driver_handlers import router as driver_router
import database as db

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # Ma'lumotlar bazasini yaratish
    db.init_db()

    # Botlarni yaratish
    client_bot = Bot(token=CLIENT_TOKEN)
    driver_bot = Bot(token=DRIVER_TOKEN)

    dp = Dispatcher()

    # Routerlarni ulash
    dp.include_router(client_router)
    dp.include_router(driver_router)

    # Ikkala botni bir vaqtda ishga tushirish
    await dp.start_polling(client_bot, driver_bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi")
