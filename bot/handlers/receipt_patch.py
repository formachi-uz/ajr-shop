import os
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, Message
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from bot.handlers.order import CheckState
from bot.keyboards.admin_kb import check_confirm_kb
from bot.middlewares.admin_check import GLAVNIY_ADMIN_ID, GROUP_CHECKS_ID
from database.db import AsyncSessionLocal
from database.models import Order, OrderStatus, PaymentType, User

router = Router()
EXTRA_CHECK_ADMIN_ID = int(os.getenv("EXTRA_CHECK_ADMIN_ID", "552003748"))


@router.message(CheckState.waiting_check_photo, F.photo | F.document)
async def receive_check_by_state(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = int(data.get("check_order_id") or 0)
    if not order_id:
        order_id = await find_latest_pending_card_order_id(message.from_user.id)
    if not order_id:
        await message.answer("⚠️ Buyurtma topilmadi. Iltimos, @formachi_admin ga yozing.")
        await state.clear()
        return

    await state.clear()
    await accept_receipt(message, bot, order_id)


@router.message(F.photo | F.document)
async def receive_check_fallback(message: Message, state: FSMContext, bot: Bot):
    """If FSM state was lost, still accept receipt for the latest pending Paynet order."""
    current_state = await state.get_state()
    if current_state and current_state != CheckState.waiting_check_photo.state:
        return

    order_id = await find_latest_pending_card_order_id(message.from_user.id)
    if not order_id:
        return

    await state.clear()
    await accept_receipt(message, bot, order_id)


async def find_latest_pending_card_order_id(user_telegram_id: int) -> int | None:
    since = datetime.now(timezone.utc) - timedelta(days=2)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order.id)
            .join(User, Order.user_id == User.id)
            .where(
                User.telegram_id == user_telegram_id,
                Order.status == OrderStatus.PENDING,
                Order.payment_type == PaymentType.CARD,
                Order.created_at >= since,
            )
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def accept_receipt(message: Message, bot: Bot, order_id: int):
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    is_photo = bool(message.photo)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(Order).where(Order.id == order_id).values(receipt_file_id=file_id)
        )
        await session.commit()
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user))
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()

    await message.answer(
        "✅ <b>Chek qabul qilindi!</b>\n\n"
        "Admin chekni tekshirgach buyurtmangiz tasdiqlanadi.\n"
        "Rahmat! ⚽",
        parse_mode="HTML",
    )

    caption = (
        f"💳 <b>YANGI CHEK — Buyurtma #{order_id}</b>\n"
        f"{'─' * 24}\n"
        f"👤 {message.from_user.full_name}"
        f"{'  @' + message.from_user.username if message.from_user.username else ''}\n"
        f"🆔 <code>{message.from_user.id}</code>"
    )
    if order:
        caption += f"\n💰 {int(order.total_price or 0):,} so'm"

    kb = check_confirm_kb(order_id)
    sent_ok = await send_receipt_targets(bot, file_id, is_photo, caption, kb)
    if not sent_ok:
        await message.answer(
            "⚠️ Chek adminga yuborishda xato bo'ldi.\n"
            "Iltimos, chekni to'g'ridan @formachi_admin ga ham yuboring.",
            parse_mode="HTML",
        )


async def send_receipt_targets(
    bot: Bot,
    file_id: str,
    is_photo: bool,
    caption: str,
    kb: InlineKeyboardMarkup,
) -> bool:
    targets = list({GROUP_CHECKS_ID, GLAVNIY_ADMIN_ID, EXTRA_CHECK_ADMIN_ID})
    sent_ok = False
    for target_id in targets:
        try:
            if is_photo:
                await bot.send_photo(target_id, photo=file_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_document(target_id, document=file_id, caption=caption, parse_mode="HTML", reply_markup=kb)
            sent_ok = True
        except Exception as exc:
            print(f"Receipt send error to {target_id}: {exc}")
    return sent_ok
