import asyncio
from aiogram import Bot, Dispatcher
from config import CLIENT_TOKEN
from client_handlers import client_router

async def main():
    bot = Bot(token=CLIENT_TOKEN)
    dp = Dispatcher()
    dp.include_router(client_router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())