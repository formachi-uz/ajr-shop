from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import GLAVNIY_ADMIN_ID, is_admin
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus

router = Router()

RESET_PHRASE = "FORMACHI RESET"
ARCHIVE_DAYS = 7


class ResetDbState(StatesGroup):
    waiting_phrase = State()


def reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Ha, bazani tozalash", callback_data="reset_db_final_confirm")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="reset_db_cancel")],
    ])


def archive_old_orders_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗂 Ha, arxivlash", callback_data="archive_old_orders_confirm")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="archive_old_orders_cancel")],
    ])


@router.message(F.text == "🧹 Bazani tozalash")
async def start_database_reset(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if GLAVNIY_ADMIN_ID and message.from_user.id != GLAVNIY_ADMIN_ID:
        await message.answer("⛔ Bu amal faqat glavnyi admin uchun ruxsat etilgan.")
        return
    await request_full_reset_phrase(message, state)


@router.callback_query(F.data == "reset_db_start")
async def start_database_reset_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    if GLAVNIY_ADMIN_ID and callback.from_user.id != GLAVNIY_ADMIN_ID:
        await callback.message.answer("⛔ Bu amal faqat glavnyi admin uchun ruxsat etilgan.")
        await callback.answer()
        return
    await request_full_reset_phrase(callback.message, state)
    await callback.answer()


async def request_full_reset_phrase(message: Message, state: FSMContext):
    await state.set_state(ResetDbState.waiting_phrase)
    await message.answer(
        "⚠️ <b>Diqqat! Bu amal test ma'lumotlarini o'chiradi.</b>\n\n"
        "O'chiriladi:\n"
        "• barcha mahsulotlar\n"
        "• barcha stocklar\n"
        "• barcha buyurtmalar\n"
        "• barcha order itemlar\n"
        "• barcha reviewlar\n\n"
        "Qoladi:\n"
        "• kategoriyalar\n"
        "• foydalanuvchilar/adminlar\n\n"
        "ID sequence qayta 1 dan boshlanadi. Davom etish uchun aynan shuni yozing:\n"
        f"<code>{RESET_PHRASE}</code>",
        parse_mode="HTML",
    )


@router.message(ResetDbState.waiting_phrase)
async def reset_phrase_received(message: Message, state: FSMContext):
    phrase = (message.text or "").strip()
    if phrase != RESET_PHRASE:
        await state.clear()
        await message.answer("❌ Tasdiq matni noto'g'ri. Reset bekor qilindi.", reply_markup=admin_menu_kb())
        return
    await message.answer(
        "🧹 <b>Oxirgi tasdiq:</b> bazani tozalaymizmi?\n\n"
        "Bu amal qaytarilmaydi.",
        parse_mode="HTML",
        reply_markup=reset_confirm_kb(),
    )


@router.callback_query(F.data == "reset_db_cancel")
async def reset_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Reset bekor qilindi.", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "reset_db_final_confirm")
async def reset_final_confirm(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    if GLAVNIY_ADMIN_ID and callback.from_user.id != GLAVNIY_ADMIN_ID:
        await callback.answer("Faqat glavnyi admin", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🧹 Baza tozalanyapti...")
    try:
        summary = await reset_shop_database()
    except Exception as exc:
        await callback.message.answer(
            "❌ Resetda xato bo'ldi:\n"
            f"<code>{type(exc).__name__}: {str(exc)[:900]}</code>",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
        await callback.answer()
        return

    await callback.message.answer(
        "✅ <b>Baza tozalandi!</b>\n\n"
        f"{summary}\n\n"
        "Endi mahsulotlarni 0 dan kiritamiz. Keyingi buyurtma <b>#1</b> dan boshlanadi.",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer("Baza tozalandi")


@router.callback_query(F.data == "archive_old_orders_start")
async def archive_old_orders_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    count = await count_archivable_orders()
    await callback.message.answer(
        "🗂 <b>Eski orderlarni arxivlash</b>\n\n"
        f"Qoidasi: <b>{ARCHIVE_DAYS} kundan eski</b> va holati <b>YETKAZILDI/BEKOR</b> bo'lgan orderlar "
        "arxiv jadvaliga yozilib, asosiy orders jadvalidan o'chiriladi.\n\n"
        f"Topildi: <b>{count}</b> ta order.\n\n"
        "Yangi, tasdiqlangan va yetkazilayotgan zakazlarga tegilmaydi.",
        parse_mode="HTML",
        reply_markup=archive_old_orders_kb() if count else None,
    )
    await callback.answer()


@router.callback_query(F.data == "archive_old_orders_cancel")
async def archive_old_orders_cancel(callback: CallbackQuery):
    await callback.message.answer("❌ Arxivlash bekor qilindi.", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "archive_old_orders_confirm")
async def archive_old_orders_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🗂 Eski orderlar arxivlanyapti...")
    try:
        summary = await archive_old_orders()
    except Exception as exc:
        await callback.message.answer(
            "❌ Arxivlashda xato bo'ldi:\n"
            f"<code>{type(exc).__name__}: {str(exc)[:900]}</code>",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
        await callback.answer()
        return

    await callback.message.answer(
        "✅ <b>Arxivlash tugadi.</b>\n\n"
        f"{summary}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer("Arxivlandi")


async def reset_shop_database() -> str:
    async with AsyncSessionLocal() as session:
        before = {}
        for table_name in ["products", "product_stocks", "orders", "order_items", "reviews"]:
            try:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                before[table_name] = int(result.scalar_one() or 0)
            except Exception:
                before[table_name] = 0

        await session.execute(text(
            "TRUNCATE TABLE "
            "order_items, orders, product_stocks, reviews, products "
            "RESTART IDENTITY CASCADE"
        ))
        await session.commit()

    return (
        f"🧾 Orders: {before.get('orders', 0)} -> 0\n"
        f"📦 Products: {before.get('products', 0)} -> 0\n"
        f"📊 Stocks: {before.get('product_stocks', 0)} -> 0\n"
        f"⭐ Reviews: {before.get('reviews', 0)} -> 0"
    )


async def ensure_order_archive_table(session):
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS order_archives (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL,
            status VARCHAR(40),
            total_price FLOAT,
            customer_name VARCHAR(255),
            customer_phone VARCHAR(50),
            delivery_address TEXT,
            summary TEXT,
            original_created_at TIMESTAMPTZ,
            archived_at TIMESTAMPTZ DEFAULT NOW()
        )
    """))


async def count_archivable_orders() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order.id).where(
                Order.created_at < cutoff,
                Order.status.in_([OrderStatus.DONE, OrderStatus.CANCELLED]),
            )
        )
        return len(result.scalars().all())


async def archive_old_orders() -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(days=ARCHIVE_DAYS)
    async with AsyncSessionLocal() as session:
        await ensure_order_archive_table(session)
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .where(
                Order.created_at < cutoff,
                Order.status.in_([OrderStatus.DONE, OrderStatus.CANCELLED]),
            )
            .order_by(Order.created_at.asc())
        )
        orders = result.scalars().all()

        if not orders:
            await session.commit()
            return "Arxivlanadigan eski order topilmadi."

        for order in orders:
            await session.execute(
                text("""
                    INSERT INTO order_archives (
                        order_id, status, total_price, customer_name, customer_phone,
                        delivery_address, summary, original_created_at
                    )
                    VALUES (
                        :order_id, :status, :total_price, :customer_name, :customer_phone,
                        :delivery_address, :summary, :original_created_at
                    )
                """),
                {
                    "order_id": order.id,
                    "status": order.status.value if order.status else None,
                    "total_price": order.total_price or 0,
                    "customer_name": order.customer_name or (order.user.full_name if order.user else None),
                    "customer_phone": order.customer_phone or (order.user.phone if order.user else None),
                    "delivery_address": order.delivery_address,
                    "summary": build_order_archive_summary(order),
                    "original_created_at": order.created_at,
                },
            )
            await session.delete(order)
        await session.commit()

    return (
        f"🗂 Arxivlandi: <b>{len(orders)}</b> ta order\n"
        f"📌 Qolgan aktiv orderlarga tegilmadi.\n"
        f"⏱ Chegara: {ARCHIVE_DAYS} kundan eski YETKAZILDI/BEKOR orderlar"
    )


def build_order_archive_summary(order) -> str:
    lines = []
    for item in order.items or []:
        product_name = item.product.name if item.product else "N/A"
        size = f" ({item.size})" if item.size else ""
        lines.append(f"{product_name}{size} x {item.quantity}")
    return "; ".join(lines) or "items yo'q"
