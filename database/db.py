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
        await ensure_runtime_schema(conn)
    print("✅ Database jadvallari yaratildi!")


async def ensure_runtime_schema(conn):
    """Existing Railway databases need additive columns when the product model grows."""
    statements = [
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS slug VARCHAR(255)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS main_category VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS product_type VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS team VARCHAR(100)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS season VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS kit_type VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS league VARCHAR(100)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS brand VARCHAR(100)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS model VARCHAR(100)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS tags TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS gallery TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS customization_status VARCHAR(30) DEFAULT 'NOT_AVAILABLE'",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS customization_price FLOAT DEFAULT 50000",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_featured BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_top_forma BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_premium_boot BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_customizable BOOLEAN DEFAULT FALSE",
        "ALTER TABLE product_stocks ADD COLUMN IF NOT EXISTS reserved INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_name VARCHAR(255)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_phone VARCHAR(20)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS total_price FLOAT DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS receipt_file_id VARCHAR(500)",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS player_name VARCHAR(100)",
        "ALTER TABLE order_items ADD COLUMN IF NOT EXISTS back_print VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS ix_products_team ON products(team)",
        "CREATE INDEX IF NOT EXISTS ix_products_brand ON products(brand)",
        "CREATE INDEX IF NOT EXISTS ix_products_main_category ON products(main_category)",
        "CREATE INDEX IF NOT EXISTS ix_products_product_type ON products(product_type)",
    ]

    for statement in statements:
        try:
            await conn.execute(text(statement))
        except Exception as exc:
            print(f"Schema migration skipped: {statement} -> {exc}")


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
