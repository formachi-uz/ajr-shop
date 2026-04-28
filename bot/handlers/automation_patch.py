import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from bot.middlewares.admin_check import GROUP_CHAT_ID, is_admin
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus, Review, User

router = Router()
logger = logging.getLogger(__name__)
_scheduler_task: asyncio.Task | None = None


class DeliveryReviewState(StatesGroup):
    waiting_city = State()
    waiting_text = State()


async def schedule_job(
    job_type: str,
    delay_seconds: int,
    user_telegram_id: int | None = None,
    order_id: int | None = None,
    payload: dict | None = None,
):
    """Create one pending scheduled job. Same job/user/order is de-duplicated."""
    due_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
    payload_text = json.dumps(payload or {}, ensure_ascii=False)
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                DELETE FROM scheduled_jobs
                WHERE status = 'pending'
                  AND job_type = :job_type
                  AND COALESCE(user_telegram_id, 0) = COALESCE(:user_telegram_id, 0)
                  AND COALESCE(order_id, 0) = COALESCE(:order_id, 0)
                """
            ),
            {"job_type": job_type, "user_telegram_id": user_telegram_id, "order_id": order_id},
        )
        await session.execute(
            text(
                """
                INSERT INTO scheduled_jobs
                    (job_type, user_telegram_id, order_id, payload, due_at, status, attempts)
                VALUES
                    (:job_type, :user_telegram_id, :order_id, :payload, :due_at, 'pending', 0)
                """
            ),
            {
                "job_type": job_type,
                "user_telegram_id": user_telegram_id,
                "order_id": order_id,
                "payload": payload_text,
                "due_at": due_at,
            },
        )
        await session.commit()


async def add_order_event(
    order_id: int,
    event_type: str,
    event_text: str,
    actor_telegram_id: int | None = None,
):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                INSERT INTO order_events (order_id, event_type, event_text, actor_telegram_id)
                VALUES (:order_id, :event_type, :event_text, :actor_telegram_id)
                """
            ),
            {
                "order_id": order_id,
                "event_type": event_type,
                "event_text": event_text,
                "actor_telegram_id": actor_telegram_id,
            },
        )
        await session.commit()


def start_background_jobs(bot: Bot):
    """Called from main.py after bot creation."""
    global _scheduler_task
    install_cart_abandoned_hook()
    install_order_tools_hook()
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop(bot))
        logger.info("FORMACHI automation scheduler started")


def install_cart_abandoned_hook():
    """Patch cart.set_cart so existing cart logic can stay untouched."""
    try:
        from bot.handlers import cart as cart_module

        if getattr(cart_module, "_automation_abandoned_hooked", False):
            return
        original_set_cart = cart_module.set_cart

        def wrapped_set_cart(user_id: int, cart: list):
            original_set_cart(user_id, cart)
            if cart:
                try:
                    asyncio.get_running_loop().create_task(
                        schedule_job("abandoned_cart", 3 * 60 * 60, user_telegram_id=user_id)
                    )
                except RuntimeError:
                    pass

        cart_module.set_cart = wrapped_set_cart
        cart_module._automation_abandoned_hooked = True
    except Exception as exc:
        logger.warning("Abandoned cart hook was not installed: %s", exc)


def install_order_tools_hook():
    """Add Timeline button to existing admin order cards without rewriting old handlers."""
    try:
        from bot.handlers import admin_order_tools_patch as tools

        if getattr(tools, "_automation_timeline_hooked", False):
            return
        original_order_tools_kb = tools.order_tools_kb

        def wrapped_order_tools_kb(order):
            kb = original_order_tools_kb(order)
            rows = list(kb.inline_keyboard)
            rows.append([InlineKeyboardButton(text="📜 Timeline", callback_data=f"admin_timeline_{order.id}")])
            return InlineKeyboardMarkup(inline_keyboard=rows)

        tools.order_tools_kb = wrapped_order_tools_kb
        tools._automation_timeline_hooked = True
    except Exception as exc:
        logger.warning("Timeline hook was not installed: %s", exc)


async def _scheduler_loop(bot: Bot):
    while True:
        try:
            await _process_due_jobs(bot)
        except Exception:
            logger.exception("Automation scheduler tick failed")
        await asyncio.sleep(60)


async def _process_due_jobs(bot: Bot):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT id, job_type, user_telegram_id, order_id, payload, attempts
                FROM scheduled_jobs
                WHERE status = 'pending' AND due_at <= now()
                ORDER BY due_at ASC
                LIMIT 20
                """
            )
        )
        jobs = list(result.mappings().all())

    for job in jobs:
        job_id = int(job["id"])
        try:
            await _mark_job(job_id, "processing")
            await _run_job(bot, job)
            await _mark_job(job_id, "done", processed=True)
        except Exception as exc:
            logger.exception("Scheduled job %s failed", job_id)
            attempts = int(job.get("attempts") or 0) + 1
            status = "failed" if attempts >= 3 else "pending"
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        """
                        UPDATE scheduled_jobs
                        SET status = :status, attempts = :attempts,
                            processed_at = CASE WHEN :status = 'failed' THEN now() ELSE processed_at END
                        WHERE id = :id
                        """
                    ),
                    {"id": job_id, "status": status, "attempts": attempts},
                )
                await session.commit()


async def _mark_job(job_id: int, status: str, processed: bool = False):
    async with AsyncSessionLocal() as session:
        await session.execute(
            text(
                """
                UPDATE scheduled_jobs
                SET status = :status,
                    processed_at = CASE WHEN :processed THEN now() ELSE processed_at END
                WHERE id = :id
                """
            ),
            {"id": job_id, "status": status, "processed": processed},
        )
        await session.commit()


async def _run_job(bot: Bot, job):
    job_type = job["job_type"]
    user_telegram_id = job.get("user_telegram_id")
    order_id = job.get("order_id")

    if job_type == "payment_reminder":
        await _send_payment_reminder(bot, int(order_id))
    elif job_type == "review_check":
        await _send_delivery_check(bot, int(order_id), retry=False)
    elif job_type == "review_check_retry":
        await _send_delivery_check(bot, int(order_id), retry=True)
    elif job_type == "abandoned_cart":
        await _send_abandoned_cart(bot, int(user_telegram_id))


async def _load_order(order_id: int) -> Order | None:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()


async def _send_payment_reminder(bot: Bot, order_id: int):
    order = await _load_order(order_id)
    if not order or not order.user or order.status != OrderStatus.PENDING:
        return
    from bot.handlers.admin_order_tools_patch import payment_reminder_text

    await bot.send_message(
        order.user.telegram_id,
        payment_reminder_text(order),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await add_order_event(order_id, "reminder", "To'lov/chek eslatmasi avtomatik yuborildi")


async def _send_delivery_check(bot: Bot, order_id: int, retry: bool):
    order = await _load_order(order_id)
    if not order or not order.user:
        return
    if order.status not in {OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.DONE}:
        return
    if await _order_has_review(order_id):
        return

    intro = "Yana bir bor so'raymiz:" if retry else "Buyurtmangiz bo'yicha qisqa tekshiruv:"
    await bot.send_message(
        order.user.telegram_id,
        f"📦 <b>Buyurtma #{order_id}</b>\n\n{intro}\nMahsulotimiz qo'lingizga yetib bordimi?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha, oldim", callback_data=f"delivery_yes_{order_id}")],
            [InlineKeyboardButton(text="⏳ Hali yetib olmadi", callback_data=f"delivery_no_{order_id}")],
        ]),
    )
    await add_order_event(order_id, "review_check", "Mijozdan yetkazib berish holati so'raldi")


async def _send_abandoned_cart(bot: Bot, user_telegram_id: int):
    from bot.handlers.cart import get_cart

    cart = get_cart(user_telegram_id)
    if not cart:
        return
    total = sum(float(item.get("price", 0)) * int(item.get("qty", 1)) for item in cart)
    await bot.send_message(
        user_telegram_id,
        "🛒 <b>Savatingizda mahsulot qolib ketdi</b>\n\n"
        f"Jami: <b>{int(total):,} so'm</b>\n"
        "Xohlasangiz buyurtmani hoziroq yakunlashingiz mumkin.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Savatim", callback_data="checkout")],
            [InlineKeyboardButton(text="🛍 Katalog", callback_data="catalog")],
        ]),
    )


async def _order_has_review(order_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Review.id).where(Review.order_id == order_id).limit(1))
        return result.scalar_one_or_none() is not None


@router.callback_query(F.data.startswith("admin_timeline_"))
async def show_order_timeline(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                """
                SELECT event_type, event_text, actor_telegram_id, created_at
                FROM order_events
                WHERE order_id = :order_id
                ORDER BY created_at ASC
                """
            ),
            {"order_id": order_id},
        )
        events = list(result.mappings().all())

    if not events:
        await callback.message.answer(f"📜 Buyurtma #{order_id} uchun timeline hali bo'sh.")
        await callback.answer()
        return

    lines = [f"📜 <b>Buyurtma #{order_id} timeline</b>\n"]
    for event in events[-20:]:
        created = event["created_at"]
        when = created.strftime("%d.%m %H:%M") if hasattr(created, "strftime") else str(created)
        actor = f" | admin: <code>{event['actor_telegram_id']}</code>" if event.get("actor_telegram_id") else ""
        lines.append(f"• <b>{when}</b> — {event['event_text'] or event['event_type']}{actor}")
    await callback.message.answer("\n".join(lines), parse_mode="HTML")
    await callback.answer("Timeline")


@router.callback_query(F.data.startswith("delivery_yes_"))
async def delivery_yes(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    if await _order_has_review(order_id):
        await callback.answer("Sharh avval qabul qilingan", show_alert=True)
        return
    await state.set_state(DeliveryReviewState.waiting_city)
    await state.update_data(delivery_order_id=order_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "✅ Juda yaxshi!\n\n"
        "Qaysi shahar/viloyatdan buyurtma qilgandingiz?\n"
        "Masalan: <b>Toshkent</b>, <b>Samarqand</b>",
        parse_mode="HTML",
    )
    await add_order_event(order_id, "delivered_feedback", "Mijoz mahsulotni olganini bildirdi")
    await callback.answer()


@router.callback_query(F.data.startswith("delivery_no_"))
async def delivery_no(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    await schedule_job("review_check_retry", 24 * 60 * 60, callback.from_user.id, order_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "Tushunarli. Tez orada qabul qilib olasiz.\n"
        "Ertaga kechga yana bir bor holatni so'raymiz."
    )
    await add_order_event(order_id, "delivery_not_received", "Mijoz hali mahsulot yetib kelmaganini bildirdi")
    await callback.answer()


@router.message(DeliveryReviewState.waiting_city)
async def delivery_city_received(message: Message, state: FSMContext):
    city = (message.text or "").strip()
    if len(city) < 2:
        await message.answer("Shahar/viloyat nomini yozing.")
        return
    data = await state.get_data()
    order_id = int(data.get("delivery_order_id") or 0)
    await state.update_data(delivery_city=city)
    await message.answer(
        "⭐ <b>Xizmatimizni baholang:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="1⭐", callback_data=f"delivery_rate_1_{order_id}"),
            InlineKeyboardButton(text="2⭐", callback_data=f"delivery_rate_2_{order_id}"),
            InlineKeyboardButton(text="3⭐", callback_data=f"delivery_rate_3_{order_id}"),
            InlineKeyboardButton(text="4⭐", callback_data=f"delivery_rate_4_{order_id}"),
            InlineKeyboardButton(text="5⭐", callback_data=f"delivery_rate_5_{order_id}"),
        ]]),
    )


@router.callback_query(F.data.startswith("delivery_rate_"))
async def delivery_rating(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    rating = int(parts[2])
    order_id = int(parts[3])
    await state.set_state(DeliveryReviewState.waiting_text)
    await state.update_data(delivery_rating=rating, delivery_order_id=order_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Siz <b>{rating}/5</b> baho berdingiz.\n\n"
        "Endi qisqacha sharh yozing. O'tkazib yuborish uchun <b>-</b> yuboring.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(DeliveryReviewState.waiting_text)
async def save_delivery_review(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = int(data.get("delivery_order_id") or 0)
    rating = int(data.get("delivery_rating") or 5)
    city = data.get("delivery_city") or "—"
    comment = None if (message.text or "").strip() == "-" else (message.text or "").strip()

    order = await _load_order(order_id)
    if not order or not order.user:
        await state.clear()
        await message.answer("Buyurtma topilmadi.")
        return

    product_id = order.items[0].product_id if order.items else None
    text_value = f"Shahar: {city}"
    if comment:
        text_value += f"\nSharh: {comment}"

    async with AsyncSessionLocal() as session:
        user_result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if user:
            session.add(Review(
                user_id=user.id,
                product_id=product_id,
                order_id=order_id,
                rating=rating,
                text=text_value,
                is_visible=True,
            ))
            await session.commit()

    await state.clear()
    await message.answer(
        "🙏 Rahmat! Bahoyingiz va sharhingiz qabul qilindi.\n"
        "FORMACHI bilan xarid qilganingiz uchun rahmat!"
    )
    await add_order_event(order_id, "review", f"Mijoz {rating}/5 baho qoldirdi. Shahar: {city}")

    review_text = (
        f"⭐ <b>YANGI YETKAZIB BERISH SHARHI</b>\n"
        f"{'─' * 24}\n"
        f"👤 {message.from_user.full_name}"
        f"{'  @' + message.from_user.username if message.from_user.username else ''}\n"
        f"🧾 Buyurtma #{order_id}\n"
        f"📍 {city}\n"
        f"⭐ <b>{rating}/5</b>\n"
    )
    if comment:
        review_text += f"💬 <i>{comment}</i>"
    try:
        await bot.send_message(GROUP_CHAT_ID, review_text, parse_mode="HTML")
    except Exception as exc:
        logger.warning("Review group send failed: %s", exc)
