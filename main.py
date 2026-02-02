import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import CLIENT_TOKEN, DRIVER_TOKEN
from client_handlers import client_router # Nomiga e'tibor bering
from driver_handlers import driver_router # Nomiga e'tibor bering
import database as db

async def main():
    logging.basicConfig(level=logging.INFO)
    db.init_db()

    bot_client = Bot(token=CLIENT_TOKEN)
    bot_driver = Bot(token=DRIVER_TOKEN)

    dp = Dispatcher()
    dp.include_router(client_router)
    dp.include_router(driver_router)

    logging.info("Botlar ishga tushdi...")
    await dp.start_polling(bot_client, bot_driver)

if __name__ == "__main__":
    asyncio.run(main())
