import asyncio
from aiogram import Bot, Dispatcher
from config import CLIENT_TOKEN, DRIVER_TOKEN
from client_handlers import client_router
from driver_handlers import driver_router

async def main():
    # Botlarni yaratamiz
    client_bot = Bot(token=CLIENT_TOKEN)
    driver_bot = Bot(token=DRIVER_TOKEN)

    # Har bir bot uchun alohida dispatcher yoki bitta dispatcherni bo'lish
    dp_client = Dispatcher()
    dp_driver = Dispatcher()

    # Routerlarni ulaymiz
    dp_client.include_router(client_router)
    dp_driver.include_router(driver_router)

    # Ikkala botni ham bir vaqtda ishga tushiramiz
    print("Botlar ishga tushdi...")
    await asyncio.gather(
        dp_client.start_polling(client_bot),
        dp_driver.start_polling(driver_bot)
    )

if __name__ == "__main__":
    asyncio.run(main())
