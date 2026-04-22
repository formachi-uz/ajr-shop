import os
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
import hashlib

from database.models import Base, User, OrderStatus, PaymentType
from database.crud import (
    get_all_categories, get_all_products, get_products_by_category,
    get_product_by_id, create_order, add_order_item, update_order_total
)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="AJR Shop Web")
templates = Jinja2Templates(directory="web/templates")

# Static files (create web/static folder if needed)
os.makedirs("web/static", exist_ok=True)
app.mount("/static", StaticFiles(directory="web/static"), name="static")


# ── Helper: web user ──────────────────────────────────────────────────────────
def phone_to_fake_id(phone: str) -> int:
    """Phone raqamdan unikal salbiy ID yaratamiz (real Telegram ID bilan to'qnashmaydi)"""
    h = int(hashlib.md5(phone.encode()).hexdigest(), 16)
    return -(h % 999_999_999_999)


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    categories = await get_all_categories(session)
    products = await get_all_products(session)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "categories": categories,
        "products": products,
    })


# ── API: Catalog ──────────────────────────────────────────────────────────────
@app.get("/api/categories")
async def api_categories(session: AsyncSession = Depends(get_session)):
    cats = await get_all_categories(session)
    return [{"id": c.id, "name": c.name, "emoji": c.emoji} for c in cats]


@app.get("/api/products")
async def api_products(
    category_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session)
):
    if category_id:
        products = await get_products_by_category(session, category_id)
    else:
        products = await get_all_products(session)

    return [{
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "final_price": p.final_price,
        "discount_percent": p.discount_percent,
        "photo_url": p.photo_url,
        "in_stock": p.in_stock,
        "category_id": p.category_id,
    } for p in products]


@app.get("/api/products/{product_id}")
async def api_product(product_id: int, session: AsyncSession = Depends(get_session)):
    p = await get_product_by_id(session, product_id)
    if not p:
        raise HTTPException(404, "Mahsulot topilmadi")
    return {
        "id": p.id, "name": p.name, "description": p.description,
        "price": p.price, "final_price": p.final_price,
        "discount_percent": p.discount_percent, "photo_url": p.photo_url,
        "in_stock": p.in_stock,
    }


# ── API: Order ────────────────────────────────────────────────────────────────
class CartItem(BaseModel):
    product_id: int
    quantity: int
    size: Optional[str] = None
    player_name: Optional[str] = None


class OrderRequest(BaseModel):
    full_name: str
    phone: str
    delivery_address: str
    payment_type: str        # cash | card | credit
    comment: Optional[str] = None
    items: List[CartItem]


@app.post("/api/order")
async def create_order_api(
    order_req: OrderRequest,
    session: AsyncSession = Depends(get_session)
):
    if not order_req.items:
        raise HTTPException(400, "Savat bo'sh")

    # Web user yaratamiz yoki topamiz
    fake_tg_id = phone_to_fake_id(order_req.phone)
    result = await session.execute(select(User).where(User.telegram_id == fake_tg_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            telegram_id=fake_tg_id,
            full_name=order_req.full_name,
            phone=order_req.phone,
            username=f"web_{order_req.phone}"
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    # Buyurtma yaratamiz
    order = await create_order(
        session,
        user_id=user.id,
        payment_type=order_req.payment_type,
        delivery_address=order_req.delivery_address,
        comment=order_req.comment,
    )

    total = 0.0
    for item in order_req.items:
        product = await get_product_by_id(session, item.product_id)
        if not product or not product.in_stock:
            continue
        price = product.final_price
        await add_order_item(
            session,
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            price=price,
            size=item.size,
            player_name=item.player_name,
        )
        total += price * item.quantity

    await update_order_total(session, order.id, total)

    return {"success": True, "order_id": order.id, "total": total}


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("web_app:app", host="0.0.0.0", port=port)
