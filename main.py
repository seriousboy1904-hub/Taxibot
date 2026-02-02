import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import CLIENT_TOKEN, DRIVER_TOKEN
from client_handlers import client_router
from driver_handlers import driver_router
from database import Database

# Loglarni ko'rish (Crash sababini bilish uchun shart)
logging.basicConfig(level=logging.INFO)

async def main():
    # Bazani bir marta ishga tushirib olish
    db = Database("taxi.db")
    
    client_bot = Bot(token=CLIENT_TOKEN)
    driver_bot = Bot(token=DRIVER_TOKEN)

    dp_client = Dispatcher()
    dp_driver = Dispatcher()

    dp_client.include_router(client_router)
    dp_driver.include_router(driver_router)

    print("✅ Botlar muvaffaqiyatli ishga tushdi!")
    
    try:
        await asyncio.gather(
            dp_client.start_polling(client_bot),
            dp_driver.start_polling(driver_bot)
        )
    except Exception as e:
        logging.error(f"❌ CRASH BO'LDI: {e}")
    finally:
        await client_bot.session.close()
        await driver_bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
