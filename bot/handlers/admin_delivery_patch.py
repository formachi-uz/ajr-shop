from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.middlewares.admin_check import is_admin
from database.db import AsyncSessionLocal
from database.models import Order, OrderStatus
from database.crud import update_order_status, get_order_with_items

router = Router()


def confirmed_orders_header_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Hammasi pochtaga/Yandexga topshirildi", callback_data="admin_deliver_all_confirmed")],
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin_refresh_confirmed_orders")],
    ])


def delivery_kb(order_id: int, is_yandex: bool = False) -> InlineKeyboardMarkup:
    label = "🚕 Yandexga topshirildi" if is_yandex else "📦 Pochtaga topshirildi"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"admin_deliver_{order_id}")],
    ])


def is_yandex_order(order) -> bool:
    text = f"{order.delivery_address or ''} {order.comment or ''}".lower()
    return "yandex" in text or "toshkent" in text or "lokatsiya" in text


@router.message(F.text == "✅ Tasdiqlangan buyurtmalar")
async def show_confirmed_orders_patch(message: Message):
    if not is_admin(message.from_user.id):
        return
    await send_confirmed_orders(message)


@router.callback_query(F.data == "admin_refresh_confirmed_orders")
async def refresh_confirmed_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await send_confirmed_orders(callback.message)
    await callback.answer("Yangilandi")


async def send_confirmed_orders(message: Message):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(getattr(Order.items.property.mapper.class_, "product")))
            .where(Order.status == OrderStatus.CONFIRMED)
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("📭 Hozircha tasdiqlangan buyurtmalar yo'q")
        return

    await message.answer(
        f"✅ <b>{len(orders)} ta tasdiqlangan buyurtma</b>\n"
        "Pochtaga yoki Yandex dostavkaga topshirishga tayyor.",
        parse_mode="HTML",
        reply_markup=confirmed_orders_header_kb(),
    )

    for order in orders:
        await message.answer(
            format_confirmed_order(order),
            parse_mode="HTML",
            reply_markup=delivery_kb(order.id, is_yandex_order(order)),
            disable_web_page_preview=True,
        )


def format_confirmed_order(order) -> str:
    items_text = ""
    for item in order.items:
        product_name = item.product.name if item.product else "N/A"
        extra = f" ({item.size})" if item.size else ""
        extra += f" | ✍️{item.player_name}" if item.player_name else ""
        items_text += f"• {product_name}{extra} × {item.quantity}\n"

    customer_name = order.customer_name or (order.user.full_name if order.user else "—")
    customer_phone = order.customer_phone or (order.user.phone if order.user else "—")
    comment = order.comment or ""
    if (not order.customer_name or not order.customer_phone) and "Ism:" in comment and "Tel:" in comment:
        parts = comment.split("|")
        for part in parts:
            if "Ism:" in part and not order.customer_name:
                customer_name = part.replace("Ism:", "").strip()
            if "Tel:" in part and not order.customer_phone:
                customer_phone = part.replace("Tel:", "").strip()

    delivery_type = "🚕 Yandex" if is_yandex_order(order) else "📦 Pochta"
    map_link = ""
    if "Yandex lokatsiya:" in (order.delivery_address or ""):
        try:
            coords = order.delivery_address.split("Yandex lokatsiya:", 1)[1].strip()
            lat, lon = [item.strip() for item in coords.split(",", 1)]
            map_link = f"\n🗺 <a href='https://maps.google.com/?q={lat},{lon}'>Lokatsiyani ochish</a>"
        except Exception:
            map_link = ""

    return (
        f"✅ <b>Buyurtma #{order.id}</b>\n"
        f"{'─' * 24}\n"
        f"👤 {customer_name}\n"
        f"📱 {customer_phone or '—'}\n"
        f"🚚 {delivery_type}\n"
        f"📍 {order.delivery_address}{map_link}\n"
        f"{'─' * 24}\n"
        f"{items_text}"
        f"{'─' * 24}\n"
        f"💰 {int(order.total_price):,} so'm"
    )


@router.callback_query(F.data == "admin_deliver_all_confirmed")
async def deliver_all_confirmed(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user))
            .where(Order.status == OrderStatus.CONFIRMED)
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()

    if not orders:
        await callback.answer("Tasdiqlangan buyurtma yo'q", show_alert=True)
        return

    count = 0
    for order in orders:
        async with AsyncSessionLocal() as session:
            await update_order_status(session, order.id, "delivering")
            updated = await get_order_with_items(session, order.id)
        count += 1
        await notify_delivery(bot, updated or order)

    try:
        await callback.message.edit_text(
            f"📦 <b>{count} ta buyurtma pochtaga/Yandexga topshirildi.</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        await callback.message.answer(f"📦 {count} ta buyurtma pochtaga/Yandexga topshirildi.")
    await callback.answer("Hammasi topshirildi")


@router.callback_query(F.data.startswith("admin_deliver_"))
async def deliver_one_confirmed(callback: CallbackQuery, bot: Bot):
    if callback.data == "admin_deliver_all_confirmed":
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.CONFIRMED:
            await callback.answer(f"Buyurtma holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "delivering")
        order = await get_order_with_items(session, order_id)

    await notify_delivery(bot, order)
    try:
        await callback.message.edit_text(
            (callback.message.text or "") + "\n\n📦 <b>Topshirildi</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass
    await callback.answer("Topshirildi")


async def notify_delivery(bot: Bot, order):
    if not order or not order.user:
        return
    is_yandex = is_yandex_order(order)
    text = (
        f"🚕 <b>Buyurtma #{order.id} Yandex dostavkaga topshirildi!</b>\n\n"
        "Kuryer yetkazib beradi. Telefoningiz yoqilgan bo'lsin."
        if is_yandex else
        f"📦 <b>Buyurtma #{order.id} pochtaga topshirildi!</b>\n\n"
        "📬 1-3 ish kuni ichida yetkaziladi. Trek raqam tayyor bo'lgach yuboriladi."
    )
    try:
        await bot.send_message(order.user.telegram_id, text, parse_mode="HTML")
    except Exception as exc:
        print(f"Delivery notification error: {exc}")
