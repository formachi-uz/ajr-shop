import asyncio
import os
import sys
import logging

# /app/bot/ ichidan ishlaganda /app/ ni path ga qo'shamiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from database.db import init_db, seed_categories
from bot.handlers import start, catalog, cart, order, admin
from bot.middlewares.admin_check import AdminMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN topilmadi! Railway Variables ga qo'shing.")
    sys.exit(1)


async def main():
    logger.info("🔄 Database ishga tushirilmoqda...")
    await init_db()
    await seed_categories()

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    dp = Dispatcher(storage=MemoryStorage())
    dp.message.middleware(AdminMiddleware())

    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(cart.router)
    dp.include_router(order.router)
    dp.include_router(admin.router)

    logger.info("✅ Bot ishga tushdi! @Formachi_uz")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
