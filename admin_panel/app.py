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
    db: AsyncSession = Depends(get_db)
):
    check_auth(request)
    product = await create_product(
        db,
        name=name,
        category_id=category_id,
        description=description or None,
        price=price,
        discount_percent=discount_percent,
        photo_url=photo_url or None,
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
    db: AsyncSession = Depends(get_db)
):
    check_auth(request)
    await update_product(
        db, product_id,
        name=name,
        category_id=category_id,
        description=description or None,
        price=price,
        discount_percent=discount_percent,
        photo_url=photo_url or None,
        in_stock=(in_stock == "on"),
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

@app.on_event("startup")
async def startup():
    await init_db()
    print("✅ Admin Panel ishga tushdi!")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("admin_panel.app:app", host="0.0.0.0", port=8000, reload=True)
