from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.handlers.order_live_patch import edit_channel_order, is_yandex_order
from bot.middlewares.admin_check import is_admin
from database.crud import get_order_with_items, update_order_status
from database.db import AsyncSessionLocal
from database.models import Order, OrderStatus

router = Router()


@router.callback_query(F.data == "admin_deliver_all_confirmed")
async def deliver_all_confirmed_live(callback: CallbackQuery, bot: Bot):
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
        orders = list(result.scalars().all())

    if not orders:
        await callback.answer("Tasdiqlangan buyurtma yo'q", show_alert=True)
        return

    count = 0
    for order in orders:
        async with AsyncSessionLocal() as session:
            await update_order_status(session, order.id, "delivering")
            updated = await get_order_with_items(session, order.id)
        if updated:
            count += 1
            await edit_channel_order(bot, updated)
            if updated.user:
                try:
                    if is_yandex_order(updated):
                        text_value = f"🚕 <b>Buyurtma #{updated.id} Yandex dostavkaga topshirildi!</b>"
                    else:
                        text_value = f"📦 <b>Buyurtma #{updated.id} pochtaga topshirildi!</b>"
                    await bot.send_message(updated.user.telegram_id, text_value, parse_mode="HTML")
                except Exception:
                    pass

    try:
        await callback.message.edit_text(
            f"📦 <b>{count} ta buyurtma pochtaga/Yandexga topshirildi.</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        await callback.message.answer(f"📦 {count} ta buyurtma pochtaga/Yandexga topshirildi.")
    await callback.answer("Hammasi topshirildi")
