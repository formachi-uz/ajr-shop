import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from bot.handlers import admin
from bot.handlers.admin_delivery_patch import delivery_kb, is_yandex_order, send_confirmed_orders
from bot.handlers.admin_status_patch import delivering_kb, format_delivering_order
from bot.handlers.admin_tools_patch import (
    ProductSearchState,
    StockManageState,
    admin_product_tools_kb,
    format_product_admin,
    scalar_count,
)
from bot.keyboards.admin_kb import admin_menu_kb, order_actions_kb
from bot.middlewares.admin_check import ADMIN_IDS, GLAVNIY_ADMIN_ID, is_admin
from database.crud import get_all_categories, get_all_products, get_pending_orders
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus, Product, ProductStock, User

router = Router()
TASHKENT_TZ = timezone(timedelta(hours=5))


class MarketingState(StatesGroup):
    waiting_all_message = State()
    waiting_all_confirm = State()
    waiting_order_code = State()
    waiting_order_message = State()
    waiting_order_confirm = State()


def orders_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Bugungi zakazlar", callback_data="admin_orders_today")],
        [
            InlineKeyboardButton(text="📋 Yangi", callback_data="admin_orders_new"),
            InlineKeyboardButton(text="✅ Tasdiqlangan", callback_data="admin_orders_confirmed"),
        ],
        [
            InlineKeyboardButton(text="🚚 Yetkazilayotgan", callback_data="admin_orders_delivering"),
            InlineKeyboardButton(text="✔️ Yetkazilgan", callback_data="admin_orders_done"),
        ],
        [InlineKeyboardButton(text="🚕 Toshkent/Yandex", callback_data="admin_orders_yandex")],
        [InlineKeyboardButton(text="🗂 7 kundan eski orderlarni arxivlash", callback_data="archive_old_orders_start")],
    ])


def products_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Mahsulot qo'shish", callback_data="admin_product_add")],
        [
            InlineKeyboardButton(text="📦 Mahsulotlar", callback_data="admin_products_list"),
            InlineKeyboardButton(text="🔎 Qidirish", callback_data="admin_product_search"),
        ],
        [
            InlineKeyboardButton(text="📦 Stock boshqarish", callback_data="admin_stock_manage"),
            InlineKeyboardButton(text="📉 Kam qolgan stock", callback_data="admin_low_stock"),
        ],
    ])


def marketing_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Umumiy xabar", callback_data="marketing_all_start")],
        [InlineKeyboardButton(text="#️⃣ Zakaz kodi orqali xabar", callback_data="marketing_order_start")],
    ])


def reports_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Umumiy statistika", callback_data="admin_stats_open")],
        [InlineKeyboardButton(text="📅 Bugungi zakazlar", callback_data="admin_orders_today")],
        [InlineKeyboardButton(text="📉 Kam qolgan stock", callback_data="admin_low_stock")],
    ])


def settings_section_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 To'liq test bazani tozalash", callback_data="reset_db_start")],
        [InlineKeyboardButton(text="🗂 Eski orderlarni arxivlash", callback_data="archive_old_orders_start")],
        [InlineKeyboardButton(text="👥 Adminlar", callback_data="admin_admins_list")],
        [InlineKeyboardButton(text="🌐 Web Panel", callback_data="admin_web_panel")],
    ])


@router.message(F.text == "🧾 Buyurtmalar")
async def open_orders_section(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("🧾 <b>Buyurtmalar bo'limi</b>", parse_mode="HTML", reply_markup=orders_section_kb())


@router.message(F.text == "📦 Mahsulotlar bo'limi")
async def open_products_section(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("📦 <b>Mahsulotlar bo'limi</b>", parse_mode="HTML", reply_markup=products_section_kb())


@router.message(F.text.in_({"📢 Marketing", "📢 Xabar yuborish"}))
async def open_marketing_section(message: Message):
    if is_admin(message.from_user.id):
        await message.answer(
            "📢 <b>Xabar yuborish</b>\n\n"
            "1) Umumiy xabar - barcha mijozlarga.\n"
            "2) Zakaz kodi orqali - faqat o'sha buyurtma egasiga.",
            parse_mode="HTML",
            reply_markup=marketing_section_kb(),
        )


@router.message(F.text == "📊 Hisobotlar")
async def open_reports_section(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("📊 <b>Hisobotlar</b>", parse_mode="HTML", reply_markup=reports_section_kb())


@router.message(F.text == "⚙️ Sozlamalar")
async def open_settings_section(message: Message):
    if is_admin(message.from_user.id):
        await message.answer("⚙️ <b>Sozlamalar</b>", parse_mode="HTML", reply_markup=settings_section_kb())


@router.callback_query(F.data == "admin_orders_today")
async def callback_today_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_today_orders(callback.message)
    await callback.answer("Bugungi zakazlar")


@router.callback_query(F.data == "admin_orders_new")
async def callback_new_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_pending_orders(callback.message)
    await callback.answer("Yangi zakazlar")


@router.callback_query(F.data == "admin_orders_confirmed")
async def callback_confirmed_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_confirmed_orders(callback.message)
    await callback.answer("Tasdiqlangan")


@router.callback_query(F.data == "admin_orders_delivering")
async def callback_delivering_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_delivering_orders(callback.message)
    await callback.answer("Yetkazilayotgan")


@router.callback_query(F.data == "admin_orders_done")
async def callback_done_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_done_orders(callback.message)
    await callback.answer("Yetkazilgan")


@router.callback_query(F.data == "admin_orders_yandex")
async def callback_yandex_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_yandex_orders(callback.message)
    await callback.answer("Toshkent/Yandex")


@router.callback_query(F.data == "admin_product_add")
async def callback_product_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)
    text = "📦 <b>Kategoriyani tanlang (raqam yuboring):</b>\n\n"
    for cat in categories:
        text += f"{cat.id}. {cat.emoji} {cat.name}\n"
    await state.set_state(admin.AddProductState.category)
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer("Mahsulot qo'shish")


@router.callback_query(F.data == "admin_products_list")
async def callback_products_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    async with AsyncSessionLocal() as session:
        products = await get_all_products(session)
    if not products:
        await callback.message.answer("Mahsulotlar yo'q")
    else:
        await callback.message.answer(f"📦 <b>{len(products)} ta mahsulot:</b>", parse_mode="HTML")
        for product in products[:30]:
            await callback.message.answer(format_product_admin(product), parse_mode="HTML", reply_markup=admin_product_tools_kb(product.id))
    await callback.answer("Mahsulotlar")


@router.callback_query(F.data == "admin_product_search")
async def callback_product_search(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(ProductSearchState.waiting_query)
    await callback.message.answer(
        "🔎 <b>Mahsulot qidirish</b>\n\nID, nom, jamoa yoki brend yozing.",
        parse_mode="HTML",
    )
    await callback.answer("Qidirish")


@router.callback_query(F.data == "admin_stock_manage")
async def callback_stock_manage(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(StockManageState.waiting_product)
    await callback.message.answer(
        "📦 <b>Stock boshqarish</b>\n\n"
        "Mahsulot ID yuboring yoki birdan yozing:\n"
        "<code>15 S:5 M:10 XL:3</code>\n"
        "<code>22 39:2 40:1 41:4</code>",
        parse_mode="HTML",
    )
    await callback.answer("Stock")


@router.callback_query(F.data == "admin_low_stock")
async def callback_low_stock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_low_stock(callback.message)
    await callback.answer("Kam stock")


@router.callback_query(F.data == "admin_stats_open")
async def callback_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_admin_stats(callback.message)
    await callback.answer("Statistika")


@router.callback_query(F.data == "admin_admins_list")
async def callback_admins_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    text = "👥 <b>Hozirgi adminlar:</b>\n\n"
    for index, admin_id in enumerate(ADMIN_IDS, 1):
        prefix = "👑 " if GLAVNIY_ADMIN_ID and admin_id == GLAVNIY_ADMIN_ID else ""
        text += f"{index}. {prefix}<code>{admin_id}</code>\n"
    text += "\nQo'shish: <code>/addadmin 123456789</code>\nO'chirish: <code>/removeadmin 123456789</code>"
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer("Adminlar")


@router.callback_query(F.data == "admin_web_panel")
async def callback_web_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    web_url = os.getenv("WEB_PANEL_URL", "Railway deploy qilingandan keyin URL bo'ladi")
    await callback.message.answer(f"🌐 <b>Web Admin Panel:</b>\n\n{web_url}\n\n🔑 Parol: ADMIN_PANEL_SECRET", parse_mode="HTML")
    await callback.answer("Web Panel")


@router.callback_query(F.data == "marketing_all_start")
async def marketing_all_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(MarketingState.waiting_all_message)
    await callback.message.answer("📢 <b>Umumiy xabar</b>\n\nBarcha mijozlarga yuboriladigan xabarni yozing.", parse_mode="HTML")
    await callback.answer()


@router.message(MarketingState.waiting_all_message)
async def marketing_all_preview(message: Message, state: FSMContext):
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    text = message.html_text or message.text or ""
    await state.update_data(marketing_text=text)
    await state.set_state(MarketingState.waiting_all_confirm)
    await message.answer(
        f"📢 <b>Bu xabar barcha mijozlarga yuborilsinmi?</b>\n\n{text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yuborish", callback_data="marketing_all_confirm"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="marketing_cancel"),
        ]]),
    )


@router.callback_query(F.data == "marketing_order_start")
async def marketing_order_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.set_state(MarketingState.waiting_order_code)
    await callback.message.answer(
        "#️⃣ <b>Zakaz kodi orqali xabar</b>\n\nBuyurtma raqamini yuboring. Masalan: <code>15</code> yoki <code>#15</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketingState.waiting_order_code)
async def marketing_order_code_received(message: Message, state: FSMContext):
    clean = (message.text or "").replace("#", "").strip()
    if clean == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    if not clean.isdigit():
        await message.answer("⚠️ Zakaz kodi raqam bo'lishi kerak. Masalan: <code>#15</code>", parse_mode="HTML")
        return

    async with AsyncSessionLocal() as session:
        order = await get_order(session, int(clean))
    if not order or not order.user:
        await message.answer("❌ Bu zakaz topilmadi yoki mijoz telegram ID yo'q.")
        return

    await state.update_data(target_order_id=order.id, target_telegram_id=order.user.telegram_id)
    await state.set_state(MarketingState.waiting_order_message)
    await message.answer(
        f"✅ <b>Buyurtma #{order.id} topildi</b>\n👤 {customer_name(order)}\n📱 {customer_phone(order)}\n\nEndi xabarni yozing.",
        parse_mode="HTML",
    )


@router.message(MarketingState.waiting_order_message)
async def marketing_order_preview(message: Message, state: FSMContext):
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    text = message.html_text or message.text or ""
    data = await state.get_data()
    await state.update_data(marketing_text=text)
    await state.set_state(MarketingState.waiting_order_confirm)
    await message.answer(
        f"#️⃣ <b>Buyurtma #{data.get('target_order_id')} egasiga yuborilsinmi?</b>\n\n{text}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Yuborish", callback_data="marketing_order_confirm"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="marketing_cancel"),
        ]]),
    )


@router.callback_query(F.data == "marketing_cancel")
async def marketing_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Xabar yuborish bekor qilindi.", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(MarketingState.waiting_all_confirm, F.data == "marketing_all_confirm")
async def marketing_all_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    text = data.get("marketing_text")
    await state.clear()
    if not text:
        await callback.message.answer("❌ Xabar topilmadi.", reply_markup=admin_menu_kb())
        await callback.answer()
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = [row[0] for row in result.all() if row[0]]
    ok = fail = 0
    for telegram_id in user_ids:
        try:
            await bot.send_message(telegram_id, text, parse_mode="HTML")
            ok += 1
        except Exception:
            fail += 1
    await callback.message.answer(f"📢 Umumiy xabar yakunlandi.\n✅ Yuborildi: {ok}\n❌ Yetmadi: {fail}", reply_markup=admin_menu_kb())
    await callback.answer("Yuborildi")


@router.callback_query(MarketingState.waiting_order_confirm, F.data == "marketing_order_confirm")
async def marketing_order_confirm(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    try:
        await bot.send_message(data.get("target_telegram_id"), data.get("marketing_text"), parse_mode="HTML")
    except Exception as exc:
        await callback.message.answer(f"❌ Xabar yuborilmadi: <code>{type(exc).__name__}: {str(exc)[:500]}</code>", parse_mode="HTML", reply_markup=admin_menu_kb())
        await callback.answer()
        return
    await callback.message.answer(f"✅ Xabar buyurtma #{data.get('target_order_id')} egasiga yuborildi.", reply_markup=admin_menu_kb())
    await callback.answer("Yuborildi")


async def send_pending_orders(message: Message):
    async with AsyncSessionLocal() as session:
        orders = await get_pending_orders(session)
    if not orders:
        await message.answer("✅ Hozircha yangi buyurtmalar yo'q")
        return
    await message.answer(f"📋 <b>{len(orders)} ta yangi buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        await message.answer(format_order_short(order), parse_mode="HTML", reply_markup=order_actions_kb(order.id))


async def send_today_orders(message: Message):
    now = datetime.now(TASHKENT_TZ)
    start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    end_utc = (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).astimezone(timezone.utc)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.created_at >= start_utc, Order.created_at < end_utc)
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()
    if not orders:
        await message.answer(f"📅 Bugun ({now:%d.%m.%Y}) zakaz yo'q.")
        return
    await message.answer(f"📅 <b>Bugungi zakazlar ({now:%d.%m.%Y}): {len(orders)} ta</b>", parse_mode="HTML")
    for order in orders:
        markup = None
        if order.status == OrderStatus.PENDING:
            markup = order_actions_kb(order.id)
        elif order.status == OrderStatus.CONFIRMED:
            markup = delivery_kb(order.id, is_yandex_order(order))
        elif order.status == OrderStatus.DELIVERING:
            markup = delivering_kb(order.id)
        await message.answer(format_order_short(order), parse_mode="HTML", reply_markup=markup)


async def send_delivering_orders(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.status == OrderStatus.DELIVERING)
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()
    if not orders:
        await message.answer("📭 Hozircha yetkazilayotgan buyurtmalar yo'q")
        return
    await message.answer(f"🚚 <b>{len(orders)} ta yetkazilayotgan buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        await message.answer(format_delivering_order(order), parse_mode="HTML", reply_markup=delivering_kb(order.id))


async def send_done_orders(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order).options(selectinload(Order.user)).where(Order.status == OrderStatus.DONE).order_by(Order.created_at.desc()).limit(20)
        )
        orders = result.scalars().all()
    if not orders:
        await message.answer("✔️ Hali yetkazilgan buyurtmalar yo'q.")
        return
    text = "✔️ <b>So'nggi yetkazilgan buyurtmalar:</b>\n\n"
    for order in orders:
        text += f"✔️ <b>#{order.id}</b> | {customer_name(order)} | {int(order.total_price or 0):,} so'm\n"
    await message.answer(text, parse_mode="HTML")


async def send_yandex_orders(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where((Order.delivery_address.ilike("%yandex%")) | (Order.delivery_address.ilike("%toshkent%")) | (Order.delivery_address.ilike("%lokatsiya%")))
            .order_by(Order.created_at.desc())
            .limit(15)
        )
        orders = result.scalars().all()
    if not orders:
        await message.answer("🚕 Toshkent/Yandex buyurtmalar topilmadi.")
        return
    await message.answer(f"🚕 <b>{len(orders)} ta Toshkent/Yandex buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        markup = delivery_kb(order.id, True) if order.status == OrderStatus.CONFIRMED else None
        await message.answer(format_order_short(order), parse_mode="HTML", reply_markup=markup)


async def send_low_stock(message: Message):
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


async def send_admin_stats(message: Message):
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        products_count = await scalar_count(session, select(func.count(Product.id)).where(Product.is_active == True))
        users_count = await scalar_count(session, select(func.count(User.id)))
        orders_count = await scalar_count(session, select(func.count(Order.id)))
        today_orders = await scalar_count(session, select(func.count(Order.id)).where(Order.created_at >= now - timedelta(days=1)))
        pending = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.PENDING))
        confirmed = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.CONFIRMED))
        delivering = await scalar_count(session, select(func.count(Order.id)).where(Order.status == OrderStatus.DELIVERING))
        revenue_result = await session.execute(select(func.coalesce(func.sum(Order.total_price), 0)).where(Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.DONE])))
        revenue = revenue_result.scalar_one() or 0
    await message.answer(
        "📊 <b>FORMACHI statistika</b>\n\n"
        f"📦 Mahsulotlar: <b>{products_count}</b>\n"
        f"👥 Mijozlar: <b>{users_count}</b>\n"
        f"🧾 Buyurtmalar jami: <b>{orders_count}</b>\n"
        f"🕒 Oxirgi 24 soat: <b>{today_orders}</b>\n\n"
        f"⏳ Yangi: <b>{pending}</b>\n"
        f"✅ Tasdiqlangan: <b>{confirmed}</b>\n"
        f"🚚 Yetkazilmoqda: <b>{delivering}</b>\n\n"
        f"💰 Savdo summasi: <b>{int(revenue):,} so'm</b>",
        parse_mode="HTML",
    )


async def get_order(session, order_id: int):
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


def customer_name(order) -> str:
    return order.customer_name or (order.user.full_name if order and order.user else "—")


def customer_phone(order) -> str:
    return order.customer_phone or (order.user.phone if order and order.user else "—") or "—"


def status_label(order) -> str:
    labels = {
        OrderStatus.PENDING: "⏳ YANGI",
        OrderStatus.CONFIRMED: "✅ TASDIQLANDI",
        OrderStatus.DELIVERING: "🚚 YETKAZILMOQDA",
        OrderStatus.DONE: "✔️ YETKAZILDI",
        OrderStatus.CANCELLED: "❌ BEKOR",
    }
    return labels.get(order.status, order.status.value if order.status else "—")


def format_order_short(order) -> str:
    items_text = ""
    for item in order.items or []:
        product_name = item.product.name if item.product else "N/A"
        extra = f" ({item.size})" if item.size else ""
        extra += f" | ✍️{item.player_name}" if item.player_name else ""
        items_text += f"• {product_name}{extra} x {item.quantity}\n"
    if not items_text:
        items_text = "—\n"
    return (
        f"🧾 <b>Buyurtma #{order.id}</b> | {status_label(order)}\n"
        f"{'─' * 24}\n"
        f"👤 {customer_name(order)}\n"
        f"📱 {customer_phone(order)}\n"
        f"📍 {order.delivery_address or '—'}\n"
        f"{'─' * 24}\n"
        f"{items_text}"
        f"{'─' * 24}\n"
        f"💰 {int(order.total_price or 0):,} so'm"
    )
