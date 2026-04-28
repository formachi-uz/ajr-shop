from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from bot.middlewares.admin_check import is_admin
from database.crud import get_order_with_items, update_order_status
from database.db import AsyncSessionLocal

router = Router()


@router.callback_query(F.data.startswith("check_confirm_"))
async def check_confirmed_once(callback: CallbackQuery, bot: Bot):
    """Confirm receipt without the legacy second stock decrease."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        if order.status.value != "pending":
            await callback.answer("Bu chek allaqachon ko'rib chiqilgan!", show_alert=True)
            return
        await update_order_status(session, order_id, "confirmed")
        order = await get_order_with_items(session, order_id)

    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + f"\n\n✅ <b>To'lov tasdiqlandi</b> — {who}",
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await callback.message.edit_text(
                (callback.message.text or "") + f"\n\n✅ <b>To'lov tasdiqlandi</b> — {who}",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass

    await callback.answer("✅ Tasdiqlandi!")

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"💳 <b>To'lovingiz tasdiqlandi!</b>\n\n"
                f"📦 Buyurtma #{order_id} tayyorlanmoqda.\n"
                "Tez orada yetkazib berishga topshiriladi! ✅",
                parse_mode="HTML",
            )
        except Exception as exc:
            print(f"Mijozga xabar yuborishda xato: {exc}")


@router.callback_query(F.data.startswith("check_reject_"))
async def check_rejected_once(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if order and order.status.value != "pending":
            await callback.answer("Bu chek allaqachon ko'rib chiqilgan!", show_alert=True)
            return

    try:
        if callback.message.caption:
            await callback.message.edit_caption(
                caption=callback.message.caption + f"\n\n❌ <b>Chek rad etildi</b> — {who}",
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await callback.message.edit_text(
                (callback.message.text or "") + f"\n\n❌ <b>Chek rad etildi</b> — {who}",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass

    await callback.answer("❌ Chek rad etildi")

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"❌ <b>Chekingiz tasdiqlanmadi.</b>\n\n"
                f"Buyurtma #{order_id}\n"
                "Iltimos, to'g'ri chek rasmini yuboring yoki @formachi_admin bilan bog'laning.",
                parse_mode="HTML",
            )
        except Exception as exc:
            print(f"Mijozga xabar yuborishda xato: {exc}")
