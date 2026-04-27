import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, Depends, HTTPException, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from dotenv import load_dotenv

load_dotenv()

from database.db import AsyncSessionLocal, init_db
from database.crud import (
    get_all_categories, get_all_products, get_products_by_category,
    get_product_by_id, create_product, update_product, delete_product,
    get_all_orders, get_pending_orders, update_order_status,
    get_order_with_items, get_category_by_id
)

app = FastAPI(title="Formachi Admin Panel")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

ADMIN_SECRET = os.getenv("ADMIN_PANEL_SECRET", "formachi2024")

STATUS_LABELS = {
    "pending": "⏳ Kutilmoqda",
    "confirmed": "✅ Tasdiqlangan",
    "delivering": "🚚 Yetkazilmoqda",
    "done": "✔️ Yetkazildi",
    "cancelled": "❌ Bekor qilindi",
}

PAYMENT_LABELS = {
    "cash": "💵 Naqd",
    "card": "💳 Karta",
    "credit": "🤝 Nasiya",
}


def check_auth(request: Request):
    token = request.cookies.get("admin_token")
    if token != ADMIN_SECRET:
        raise HTTPException(status_code=302, headers={"Location": "/admin/login"})
    return True


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ==================== AUTH ====================

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/admin/login")
async def login(request: Request, password: str = Form(...)):
    if password == ADMIN_SECRET:
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie("admin_token", ADMIN_SECRET, httponly=True, max_age=86400 * 7)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Noto'g'ri parol!"})


@app.get("/admin/logout")
async def logout():
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_token")
    return response


# ==================== DASHBOARD ====================

@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    pending = await get_pending_orders(db)
    all_orders = await get_all_orders(db, limit=100)
    products = await get_all_products(db)
    categories = await get_all_categories(db)

    total_revenue = sum(o.total_price for o in all_orders if o.status.value == "done")
    stats = {
        "pending_count": len(pending),
        "total_orders": len(all_orders),
        "total_products": len(products),
        "total_revenue": int(total_revenue),
        "categories_count": len(categories),
    }
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "stats": stats,
        "pending_orders": pending[:5],
        "STATUS_LABELS": STATUS_LABELS,
        "PAYMENT_LABELS": PAYMENT_LABELS,
    })


# ==================== ORDERS ====================

@app.get("/admin/orders", response_class=HTMLResponse)
async def orders_page(request: Request, status: str = None, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    orders = await get_all_orders(db, limit=100)
    if status:
        orders = [o for o in orders if o.status.value == status]
    return templates.TemplateResponse("orders.html", {
        "request": request,
        "orders": orders,
        "STATUS_LABELS": STATUS_LABELS,
        "PAYMENT_LABELS": PAYMENT_LABELS,
        "current_status": status,
    })


@app.get("/admin/orders/{order_id}", response_class=HTMLResponse)
async def order_detail(request: Request, order_id: int, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    order = await get_order_with_items(db, order_id)
    if not order:
        raise HTTPException(404, "Buyurtma topilmadi")
    return templates.TemplateResponse("order_detail.html", {
        "request": request,
        "order": order,
        "STATUS_LABELS": STATUS_LABELS,
        "PAYMENT_LABELS": PAYMENT_LABELS,
    })


@app.post("/admin/orders/{order_id}/status")
async def change_order_status(request: Request, order_id: int, status: str = Form(...), db: AsyncSession = Depends(get_db)):
    check_auth(request)
    await update_order_status(db, order_id, status)
    return RedirectResponse(url=f"/admin/orders/{order_id}", status_code=302)


# ==================== PRODUCTS ====================

@app.get("/admin/products", response_class=HTMLResponse)
async def products_page(request: Request, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    products = await get_all_products(db)
    categories = await get_all_categories(db)
    cat_map = {c.id: c for c in categories}
    return templates.TemplateResponse("products.html", {
        "request": request,
        "products": products,
        "categories": categories,
        "cat_map": cat_map,
    })


@app.get("/admin/products/add", response_class=HTMLResponse)
async def add_product_page(request: Request, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    categories = await get_all_categories(db)
    return templates.TemplateResponse("product_form.html", {
        "request": request,
        "categories": categories,
        "product": None,
        "stocks": [],
    })


@app.post("/admin/products/add")
async def add_product_submit(
    request: Request,
    name: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    discount_percent: float = Form(0),
    photo_url: str = Form(""),
    team_type: str = Form(""),
    team: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    check_auth(request)
    # team_type — faqat "club" yoki "national"; boshqasi → None
    tt = team_type.strip().lower() if team_type else ""
    tt_value = tt if tt in ("club", "national") else None
    team_value = team.strip() or None
    product = await create_product(
        db,
        name=name,
        category_id=category_id,
        description=description or None,
        price=price,
        discount_percent=discount_percent,
        photo_url=photo_url or None,
        team_type=tt_value,
        team=team_value,
    )
    # Stock o'lchamlarini saqlash
    from database.crud import set_product_stock
    all_sizes = ["XS","S","M","L","XL","XXL","3XL","36","37","38","39","40","41","42","43","44","45"]
    form_data = await request.form()
    for size in all_sizes:
        qty_str = form_data.get(f"stock_{size}", "0")
        try:
            qty = int(qty_str)
            if qty > 0:
                await set_product_stock(db, product.id, size, qty)
        except ValueError:
            pass
    return RedirectResponse(url="/admin/products?success=1", status_code=302)


@app.get("/admin/products/{product_id}/edit", response_class=HTMLResponse)
async def edit_product_page(request: Request, product_id: int, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    product = await get_product_by_id(db, product_id)
    categories = await get_all_categories(db)
    from database.crud import get_product_stocks
    stocks = await get_product_stocks(db, product_id)
    return templates.TemplateResponse("product_form.html", {
        "request": request,
        "categories": categories,
        "product": product,
        "stocks": stocks,
    })


@app.post("/admin/products/{product_id}/edit")
async def edit_product_submit(
    request: Request,
    product_id: int,
    name: str = Form(...),
    category_id: int = Form(...),
    description: str = Form(""),
    price: float = Form(...),
    discount_percent: float = Form(0),
    photo_url: str = Form(""),
    in_stock: str = Form("on"),
    team_type: str = Form(""),
    team: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    check_auth(request)
    tt = team_type.strip().lower() if team_type else ""
    tt_value = tt if tt in ("club", "national") else None
    team_value = team.strip() or None
    await update_product(
        db, product_id,
        name=name,
        category_id=category_id,
        description=description or None,
        price=price,
        discount_percent=discount_percent,
        photo_url=photo_url or None,
        in_stock=(in_stock == "on"),
        team_type=tt_value,
        team=team_value,
    )
    # Stock yangilash
    from database.crud import set_product_stock
    all_sizes = ["XS","S","M","L","XL","XXL","3XL","36","37","38","39","40","41","42","43","44","45"]
    form_data = await request.form()
    for size in all_sizes:
        qty_str = form_data.get(f"stock_{size}", "0")
        try:
            qty = int(qty_str)
            await set_product_stock(db, product_id, size, qty)
        except ValueError:
            pass
    return RedirectResponse(url="/admin/products?success=1", status_code=302)


@app.post("/admin/products/{product_id}/delete")
async def delete_product_endpoint(request: Request, product_id: int, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    await update_product(db, product_id, is_active=False)
    return RedirectResponse(url="/admin/products", status_code=302)


# ==================== CATEGORIES ====================

@app.get("/admin/categories", response_class=HTMLResponse)
async def categories_page(request: Request, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    categories = await get_all_categories(db)
    return templates.TemplateResponse("categories.html", {
        "request": request,
        "categories": categories,
    })


@app.post("/admin/categories/add")
async def add_category(
    request: Request,
    name: str = Form(...),
    emoji: str = Form("📦"),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    check_auth(request)
    from database.crud import create_category
    await create_category(db, name=name, emoji=emoji, description=description)
    return RedirectResponse(url="/admin/categories", status_code=302)




# ==================== OMBOR ====================

@app.get("/admin/stock", response_class=HTMLResponse)
async def stock_page(request: Request, db: AsyncSession = Depends(get_db)):
    check_auth(request)
    from database.crud import get_stock_report, get_low_stock_products
    stocks = await get_stock_report(db)
    low    = await get_low_stock_products(db, threshold=2)
    return templates.TemplateResponse("stock.html", {
        "request": request,
        "stocks": stocks,
        "low_count": len(low),
    })



# ==================== PUBLIC API (Sayt uchun) ====================

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # GitHub Pages dan ruxsat
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/categories")
async def api_categories(db: AsyncSession = Depends(get_db)):
    """Barcha kategoriyalar (id=4 ism yozish — ko'rsatilmaydi)"""
    cats = await get_all_categories(db)
    return [
        {
            "id": c.id,
            "name": c.name,
            "emoji": c.emoji,
            "description": c.description,
        }
        for c in cats if c.id != 4
    ]


@app.get("/api/products")
async def api_products(category_id: int = None, db: AsyncSession = Depends(get_db)):
    """Mahsulotlar ro'yxati (stock bilan)"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from database.models import Product, ProductStock
    from sqlalchemy import func as sqlfunc

    query = (
        select(Product)
        .options(selectinload(Product.stocks), selectinload(Product.reviews))
        .where(Product.is_active == True, Product.category_id != 4)
    )
    if category_id:
        query = query.where(Product.category_id == category_id)
    query = query.order_by(Product.id.desc())

    result = await db.execute(query)
    products = result.scalars().all()

    out = []
    for p in products:
        final_price = p.price * (1 - p.discount_percent / 100) if p.discount_percent > 0 else p.price
        stocks = [
            {"size": s.size, "quantity": s.quantity, "sort_order": s.sort_order}
            for s in sorted(p.stocks, key=lambda x: x.sort_order)
        ]
        avg_rating = round(sum(r.rating for r in p.reviews) / len(p.reviews), 1) if p.reviews else 0
        out.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "final_price": round(final_price),
            "discount_percent": p.discount_percent,
            "photo_url": p.photo_url,
            "in_stock": p.in_stock,
            "category_id": p.category_id,
            "team_type": p.team_type,
            "team_name": p.team,
            "stocks": stocks,
            "avg_rating": avg_rating,
            "review_count": len(p.reviews),
        })
    return out


@app.get("/api/products/{product_id}")
async def api_product_detail(product_id: int, db: AsyncSession = Depends(get_db)):
    """Bitta mahsulot detail"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from database.models import Product

    result = await db.execute(
        select(Product)
        .options(selectinload(Product.stocks), selectinload(Product.reviews))
        .where(Product.id == product_id, Product.is_active == True)
    )
    p = result.scalar_one_or_none()
    if not p:
        from fastapi import HTTPException
        raise HTTPException(404, "Mahsulot topilmadi")

    final_price = p.price * (1 - p.discount_percent / 100) if p.discount_percent > 0 else p.price
    stocks = [
        {"size": s.size, "quantity": s.quantity, "sort_order": s.sort_order}
        for s in sorted(p.stocks, key=lambda x: x.sort_order)
    ]
    reviews = [
        {"rating": r.rating, "text": r.text, "created_at": str(r.created_at)}
        for r in p.reviews if r.is_visible
    ]
    avg_rating = round(sum(r.rating for r in p.reviews) / len(p.reviews), 1) if p.reviews else 0

    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "price": p.price,
        "final_price": round(final_price),
        "discount_percent": p.discount_percent,
        "photo_url": p.photo_url,
        "in_stock": p.in_stock,
        "category_id": p.category_id,
        "team_type": p.team_type,
        "team_name": p.team,
        "stocks": stocks,
        "reviews": reviews,
        "avg_rating": avg_rating,
        "review_count": len(p.reviews),
    }


@app.get("/api/photo/{file_id:path}")
async def api_photo(file_id: str):
    """Telegram rasmini proxy orqali berish"""
    import httpx
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    async with httpx.AsyncClient() as client:
        file_res = await client.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
            params={"file_id": file_id}
        )
        file_data = file_res.json()
        if not file_data.get("ok"):
            from fastapi import HTTPException
            raise HTTPException(404, "Rasm topilmadi")
        file_path = file_data["result"]["file_path"]
        photo_res = await client.get(
            f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        )
    from fastapi.responses import Response
    return Response(
        content=photo_res.content,
        media_type=photo_res.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"}
    )


@app.post("/api/orders")
async def api_create_order(request: Request, db: AsyncSession = Depends(get_db)):
    """Saytdan buyurtma qabul qilish"""
    import httpx
    data = await request.json()

    customer_name  = data.get("customer_name", "")
    customer_phone = data.get("customer_phone", "")
    address        = data.get("address", "")
    payment_type   = data.get("payment_type", "card")
    items          = data.get("items", [])
    total          = data.get("total", 0)

    if not customer_name or not customer_phone or not address or not items:
        return JSONResponse({"error": "Ma'lumotlar to'liq emas"}, status_code=400)

    # User yaratish / topish
    from database.models import User
    from sqlalchemy import select as sa_select
    result = await db.execute(sa_select(User).where(User.telegram_id == 0))
    # Saytdan kelgan user uchun maxsus telegram_id ishlatmaymiz
    user = User(telegram_id=int(f"9{abs(hash(customer_phone)) % 10**9}"),
                full_name=customer_name, phone=customer_phone)
    db.add(user)
    await db.flush()

    from database.models import Order, OrderItem
    from database.models import PaymentType
    pay_map = {"card": PaymentType.CARD, "credit": PaymentType.CREDIT}
    order = Order(
        user_id=user.id,
        payment_type=pay_map.get(payment_type, PaymentType.CARD),
        delivery_address=address,
        comment=f"Ism: {customer_name} | Tel: {customer_phone} | Saytdan",
        total_price=total,
        status="pending"
    )
    db.add(order)
    await db.flush()

    for item in items:
        oi = OrderItem(
            order_id=order.id,
            product_id=item["product_id"],
            quantity=item["qty"],
            price_at_order=item["price"],
            size=item.get("size"),
            player_name=item.get("back_print")
        )
        db.add(oi)

    await db.commit()

    # Telegram guruhga xabar
    BOT_TOKEN     = os.getenv("BOT_TOKEN", "")
    GROUP_ID      = os.getenv("GROUP_CHAT_ID", "-5194049252")
    GLAVNIY_ADMIN = os.getenv("GLAVNIY_ADMIN_ID", "8156792282")

    pay_label = "💳 Karta/Paynet" if payment_type == "card" else "🤝 Uzum Nasiya"
    cart_lines = ""
    first_photo = None
    for item in items:
        extra = f" ({item['size']})" if item.get("size") else ""
        extra += f" | ✍️{item['back_print']}" if item.get("back_print") else ""
        cart_lines += f"• {item['name']}{extra} × {item['qty']} = {int(item['price'] * item['qty']):,} so'm\n"
        if not first_photo and item.get("photo_url"):
            first_photo = item["photo_url"]

    text = (
        f"🌐 <b>SAYTDAN BUYURTMA #{order.id}</b>\n"
        f"{'─'*28}\n"
        f"👤 {customer_name}\n"
        f"📱 {customer_phone}\n"
        f"{'─'*28}\n"
        f"📍 {address}\n"
        f"💳 {pay_label}\n"
        f"{'─'*28}\n"
        f"{cart_lines}"
        f"{'─'*28}\n"
        f"💰 <b>JAMI: {int(total):,} so'm</b>"
    )

    async with httpx.AsyncClient() as client:
        for target in list(set([GROUP_ID, GLAVNIY_ADMIN])):
            try:
                if first_photo:
                    caption = text[:1024]
                    await client.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                        json={"chat_id": target, "photo": first_photo,
                              "caption": caption, "parse_mode": "HTML"}
                    )
                else:
                    await client.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                        json={"chat_id": target, "text": text, "parse_mode": "HTML"}
                    )
            except Exception as e:
                print(f"Telegram xabar xatosi: {e}")

    return {"success": True, "order_id": order.id}


@app.on_event("startup")
async def startup():
    await init_db()
    print("✅ Admin Panel ishga tushdi!")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_panel.app:app", host="0.0.0.0", port=8000, reload=True)
