from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.middlewares.admin_check import is_admin
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus
from database.crud import update_order_status, get_order_with_items

router = Router()


def delivering_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏷 Trek raqam", callback_data=f"admin_track_{order_id}")],
        [InlineKeyboardButton(text="✔️ Yetkazildi", callback_data=f"admin_done_{order_id}")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}")],
    ])


@router.message(F.text == "🚚 Yetkazilayotgan")
async def show_delivering_orders(message: Message):
    if not is_admin(message.from_user.id):
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(
                selectinload(Order.user),
                selectinload(Order.items).selectinload(OrderItem.product),
            )
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


@router.callback_query(F.data.startswith("admin_done_"))
async def mark_order_done(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.DELIVERING:
            await callback.answer(f"Buyurtma holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "done")
        order = await get_order_with_items(session, order_id)

    try:
        await callback.message.edit_text(
            (callback.message.text or "") + "\n\n✔️ <b>Yetkazildi</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"✔️ <b>Buyurtma #{order.id} yetkazildi!</b>\n\n"
                "FORMACHI bilan xarid qilganingiz uchun rahmat. ⚽",
                parse_mode="HTML",
            )
        except Exception as exc:
            print(f"Done notification error: {exc}")

    await callback.answer("Yetkazildi")


def format_delivering_order(order) -> str:
    items_text = ""
    for item in order.items:
        product_name = item.product.name if item.product else "N/A"
        extra = f" ({item.size})" if item.size else ""
        extra += f" | ✍️{item.player_name}" if item.player_name else ""
        items_text += f"• {product_name}{extra} × {item.quantity}\n"

    customer_name = order.customer_name or (order.user.full_name if order.user else "—")
    customer_phone = order.customer_phone or (order.user.phone if order.user else "—")
    return (
        f"🚚 <b>Buyurtma #{order.id}</b>\n"
        f"{'─' * 24}\n"
        f"👤 {customer_name}\n"
        f"📱 {customer_phone or '—'}\n"
        f"📍 {order.delivery_address}\n"
        f"{'─' * 24}\n"
        f"{items_text}"
        f"{'─' * 24}\n"
        f"💰 {int(order.total_price):,} so'm"
    )
