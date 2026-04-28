from datetime import datetime, timedelta, timezone
import re

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from bot.middlewares.admin_check import is_admin
from bot.keyboards.admin_kb import admin_menu_kb, product_manage_kb
from database.db import AsyncSessionLocal
from database.models import Product, ProductStock, Order, OrderItem, OrderStatus, User
from database.crud import set_product_stock, get_product_by_id

router = Router()


class ProductSearchState(StatesGroup):
    waiting_query = State()


class StockManageState(StatesGroup):
    waiting_product = State()
    waiting_stock = State()


class BroadcastState(StatesGroup):
    waiting_message = State()
    waiting_confirm = State()


@router.message(F.text == "🔎 Mahsulot qidirish")
async def start_product_search(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(ProductSearchState.waiting_query)
    await message.answer(
        "🔎 <b>Mahsulot qidirish</b>\n\n"
        "ID, nom, jamoa yoki brend yozing.\n"
        "Masalan: <code>arsenal</code>, <code>nike</code>, <code>15</code>",
        parse_mode="HTML",
    )


@router.message(ProductSearchState.waiting_query)
async def handle_product_search(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if len(query) < 2 and not query.isdigit():
        await message.answer("⚠️ Kamida 2 ta belgi yoki product ID yuboring.")
        return

    async with AsyncSessionLocal() as session:
        stmt = select(Product).options(selectinload(Product.stocks)).where(Product.is_active == True)
        if query.isdigit():
            stmt = stmt.where(Product.id == int(query))
        else:
            pattern = f"%{query}%"
            stmt = stmt.where(or_(
                Product.name.ilike(pattern),
                Product.team.ilike(pattern),
                Product.brand.ilike(pattern),
                Product.model.ilike(pattern),
                Product.season.ilike(pattern),
            ))
        result = await session.execute(stmt.order_by(Product.id.desc()).limit(10))
        products = result.scalars().all()

    await state.clear()
    if not products:
        await message.answer("😕 Mahsulot topilmadi.", reply_markup=admin_menu_kb())
        return

    await message.answer(f"🔎 <b>{len(products)} ta mahsulot topildi:</b>", parse_mode="HTML")
    for product in products:
        await message.answer(format_product_admin(product), parse_mode="HTML", reply_markup=admin_product_tools_kb(product.id))


@router.message(F.text == "📦 Stock boshqarish")
async def start_stock_manage(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(StockManageState.waiting_product)
    await message.answer(
        "📦 <b>Stock boshqarish</b>\n\n"
        "Mahsulot ID yuboring yoki birdan yozing:\n"
        "<code>15 S:5 M:10 XL:3</code>\n"
        "<code>22 39:2 40:1 41:4</code>",
        parse_mode="HTML",
    )


@router.message(StockManageState.waiting_product)
async def handle_stock_product(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    match = re.match(r"^(\d+)(?:\s+(.+))?$", text)
    if not match:
        await message.answer("⚠️ Format: <code>15</code> yoki <code>15 S:5 M:10</code>", parse_mode="HTML")
        return

    product_id = int(match.group(1))
    stock_text = match.group(2)
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)

    if not product:
        await message.answer("❌ Mahsulot topilmadi.")
        return

    if stock_text:
        await save_stock_values(message, state, product_id, stock_text)
        return

    await state.update_data(stock_product_id=product_id)
    await state.set_state(StockManageState.waiting_stock)
    await message.answer(
        format_product_admin(product) + "\n\n"
        "Yangi stockni yuboring:\n"
        "<code>S:5 M:10 L:8 XL:3</code> yoki <code>39:2 40:3</code>",
        parse_mode="HTML",
    )


@router.message(StockManageState.waiting_stock)
async def handle_stock_values(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = int(data.get("stock_product_id", 0) or 0)
    if not product_id:
        await state.clear()
        await message.answer("❌ Product ID yo'qoldi. Qaytadan boshlang.", reply_markup=admin_menu_kb())
        return
    await save_stock_values(message, state, product_id, message.text or "")


@router.callback_query(F.data.startswith("stock_manage_"))
async def stock_manage_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[2])
    await state.update_data(stock_product_id=product_id)
    await state.set_state(StockManageState.waiting_stock)
    await callback.message.answer(
        "📦 Yangi stockni yuboring:\n"
        "<code>S:5 M:10 L:8 XL:3</code> yoki <code>39:2 40:3</code>",
        parse_mode="HTML",
    )
    await callback.answer()


async def save_stock_values(message: Message, state: FSMContext, product_id: int, stock_text: str):
    parsed = parse_stock_text(stock_text)
    if not parsed:
        await message.answer("⚠️ Stock formati noto'g'ri. Masalan: <code>S:5 M:10 XL:3</code>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await message.answer("❌ Mahsulot topilmadi.")
            return
        for size, qty in parsed.items():
            await set_product_stock(session, product_id, size, qty)

    await state.clear()
    await message.answer(
        f"✅ <b>Stock yangilandi!</b>\n"
        f"📦 Product ID: <code>{product_id}</code>\n"
        + "  ".join(f"{size}:{qty}" for size, qty in parsed.items()),
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


@router.message(F.text == "📉 Kam qolgan stock")
async def low_stock_report(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProductStock)
            .options(selectinload(ProductStock.product))
            .where(ProductStock.quantity <= 2, ProductStock.quantity >= 0, ProductStock.product.has(is_active=True))
            .order_by(ProductStock.quantity.asc())
            .limit(30)
        )
        stocks = result.scalars().all()

    if not stocks:
        await message.answer("✅ Kam qolgan stock yo'q.")
        return

    text = "📉 <b>Kam qolgan stocklar:</b>\n\n"
    for stock in stocks:
        name = stock.product.name if stock.product else "N/A"
        icon = "❌" if stock.quantity == 0 else "⚠️"
        text += f"{icon} ID {stock.product_id} | {name} | {stock.size}: {stock.quantity}\n"
    await message.answer(text, parse_mode="HTML")


@router.message(F.text == "🚕 Toshkent/Yandex")
async def yandex_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where(
                or_(
                    Order.delivery_address.ilike("%yandex%"),
                    Order.delivery_address.ilike("%toshkent%"),
                    Order.delivery_address.ilike("%lokatsiya%"),
                )
            )
            .order_by(Order.created_at.desc())
            .limit(15)
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("🚕 Toshkent/Yandex buyurtmalar topilmadi.")
        return

    await message.answer(f"🚕 <b>{len(orders)} ta Toshkent/Yandex buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        status = order.status.value if order.status else ""
        text = (
            f"#{order.id} | <b>{status}</b>\n"
            f"👤 {order.customer_name or (order.user.full_name if order.user else '—')}\n"
            f"📱 {order.customer_phone or (order.user.phone if order.user else '—')}\n"
            f"📍 {order.delivery_address}\n"
            f"💰 {int(order.total_price):,} so'm"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=yandex_order_kb(order.id, status))


@router.message(F.text == "📊 Statistika")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    now = datetime.now(timezone.utc)
    day_start = now - timedelta(days=1)

    async with AsyncSessionLocal() as session:
        products_count = await scalar_count(session, select(func.count(Product.id)).where(Product.is_active == True))
        users_count = await scalar_count(session, select(func.count(User.id)))
        orders_count = await scalar_count(session, select(func.count(Order.id)))
        today_orders = await scalar_count(session, select(func.count(Order.id)).where(Order.created_at >= day_start))
        pending = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING))
        confirmed = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.CONFIRMED))
        delivering = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.DELIVERING))
        revenue_result = await session.execute(
            select(func.coalesce(func.sum(Order.total_price), 0)).where(
                Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.DONE])
            )
        )
        revenue = revenue_result.scalar_one() or 0
        low_stock = await scalar_count(session, select(func.count(ProductStock.id)).where(ProductStock.quantity <= 2))

    await message.answer(
        "📊 <b>FORMACHI statistika</b>\n\n"
        f"📦 Mahsulotlar: <b>{products_count}</b>\n"
        f"👥 Mijozlar: <b>{users_count}</b>\n"
        f"🧾 Buyurtmalar jami: <b>{orders_count}</b>\n"
        f"🕒 Oxirgi 24 soat: <b>{today_orders}</b>\n\n"
        f"⏳ Yangi/kutilmoqda: <b>{pending}</b>\n"
        f"✅ Tasdiqlangan: <b>{confirmed}</b>\n"
        f"📦 Yetkazilmoqda: <b>{delivering}</b>\n"
        f"📉 Kam stock: <b>{low_stock}</b>\n\n"
        f"💰 Savdo summasi: <b>{int(revenue):,} so'm</b>",
        parse_mode="HTML",
    )


@router.message(F.text == "📢 Xabar yuborish")
async def start_broadcast(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastState.waiting_message)
    await message.answer(
        "📢 <b>Broadcast xabar</b>\n\n"
        "Mijozlarga yuboriladigan matnni yuboring.\n"
        "Bekor qilish uchun: /cancel",
        parse_mode="HTML",
    )


@router.message(BroadcastState.waiting_message)
async def broadcast_preview(message: Message, state: FSMContext):
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    await state.update_data(broadcast_text=message.html_text or message.text or "")
    await state.set_state(BroadcastState.waiting_confirm)
    await message.answer(
        "📢 <b>Quyidagi xabar yuborilsinmi?</b>\n\n"
        f"{message.html_text or message.text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yuborish", callback_data="broadcast_confirm"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="broadcast_cancel"),
        ]]),
    )


@router.callback_query(BroadcastState.waiting_confirm, F.data == "broadcast_cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Broadcast bekor qilindi.", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(BroadcastState.waiting_confirm, F.data == "broadcast_confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("broadcast_text")
    await state.clear()
    if not text:
        await callback.message.answer("❌ Xabar topilmadi.", reply_markup=admin_menu_kb())
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = [row[0] for row in result.all()]

    ok = 0
    fail = 0
    for telegram_id in user_ids:
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1

    await callback.message.answer(
        f"📢 Broadcast yakunlandi.\n✅ Yuborildi: {ok}\n❌ Yetmadi: {fail}",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer("Yuborildi")


def admin_product_tools_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = product_manage_kb(product_id).inline_keyboard
    rows.insert(0, [InlineKeyboardButton(text="📦 Stock", callback_data=f"stock_manage_{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yandex_order_kb(order_id: int, status: str) -> InlineKeyboardMarkup | None:
    if status == "confirmed":
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🚕 Yandexga topshirildi", callback_data=f"admin_deliver_{order_id}"),
        ]])
    return None


def format_product_admin(product: Product) -> str:
    meta = []
    if product.team:
        meta.append(product.team)
    if product.brand:
        meta.append(product.brand)
    if product.season:
        meta.append(product.season)
    stock_text = " ".join(f"{stock.size}:{stock.quantity}" for stock in (product.stocks or [])) or "stock yo'q"
    return (
        f"📦 <b>{product.name}</b>\n"
        f"ID: <code>{product.id}</code>\n"
        f"💰 {int(product.price):,} so'm"
        f"{' | Skidka: ' + str(int(product.discount_percent)) + '%' if product.discount_percent else ''}\n"
        f"{' / '.join(meta) if meta else '—'}\n"
        f"📊 {stock_text}"
    )


def parse_stock_text(value: str) -> dict[str, int]:
    parsed = {}
    text = (value or "").upper().replace(",", " ").replace(";", " ").replace("=", ":")
    for size, qty_text in re.findall(r"([A-Z0-9]{1,4})\s*[:\-]\s*(\d+)", text):
        size = "XXL" if size in {"2XL", "XXL"} else size
        qty = int(qty_text)
        if qty >= 0:
            parsed[size] = qty
    return parsed


async def scalar_count(session, stmt) -> int:
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)
