import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from dotenv import load_dotenv
from database.models import Base

load_dotenv()

# Railway PostgreSQL URL ni async formatga o'tkazish
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Barcha jadvallarni yaratish"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database jadvallari yaratildi!")


async def seed_categories():
    """Boshlang'ich kategoriyalarni qo'shish"""
    from database.crud import get_all_categories, create_category
    async with AsyncSessionLocal() as session:
        existing = await get_all_categories(session)
        if existing:
            return  # Allaqachon bor

        categories = [
            {"name": "Formalar", "emoji": "👕", "description": "Terma jamoa, klub va bez komanda formalari", "sort_order": 1},
            {"name": "Retro Formalar", "emoji": "🏆", "description": "Klassik va retro formalar kolleksiyasi", "sort_order": 2},
            {"name": "Butsalar & Sarakonjoshkalar", "emoji": "👟", "description": "Futbol butsalari va sport poyabzallari", "sort_order": 3},
            {"name": "Ism Yozish Xizmati", "emoji": "✍️", "description": "Futbolka va formalarga ism/raqam yozish — 30.000 so'm", "sort_order": 4},
        ]
        for cat in categories:
            await create_category(session, **cat)
        print("✅ Kategoriyalar qo'shildi!")


async def get_session():
    """Dependency injection uchun"""
    async with AsyncSessionLocal() as session:
        yield session
