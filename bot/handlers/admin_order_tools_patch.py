from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from bot.handlers.admin_delivery_patch import is_yandex_order
from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus, User

router = Router()
TRACK_PREFIX = "[FORMACHI_TRACK]"
ADMIN_NOTE_PREFIX = "[FORMACHI_ADMIN_NOTE]"


class OrderSearchState(StatesGroup):
    waiting_query = State()


class TrackCodeState(StatesGroup):
    waiting_code = State()


class AdminNoteState(StatesGroup):
    waiting_note = State()


def order_tools_kb(order) -> InlineKeyboardMarkup:
    rows = []
    if order.status == OrderStatus.PENDING:
        rows.append([
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm_{order.id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order.id}"),
        ])
    elif order.status == OrderStatus.CONFIRMED:
        rows.append([
            InlineKeyboardButton(
                text="🚕 Yandexga topshirildi" if is_yandex_order(order) else "📦 Pochtaga topshirildi",
                callback_data=f"admin_deliver_{order.id}",
            )
        ])
    elif order.status == OrderStatus.DELIVERING:
        rows.append([
            InlineKeyboardButton(text="🏷 Trek raqam", callback_data=f"admin_track_{order.id}"),
            InlineKeyboardButton(text="✔️ Yetkazildi", callback_data=f"admin_done_{order.id}"),
        ])
    rows.append([InlineKeyboardButton(text="📝 Admin izoh", callback_data=f"admin_note_{order.id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "🔍 Order qidirish")
async def start_order_search_message(message: Message, state: FSMContext):
    if is_admin(message.from_user.id):
        await start_order_search(message, state)


@router.callback_query(F.data == "admin_order_search")
async def start_order_search_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await start_order_search(callback.message, state)
    await callback.answer("Order qidirish")


async def start_order_search(message: Message, state: FSMContext):
    await state.set_state(OrderSearchState.waiting_query)
    await message.answer(
        "🔍 <b>Order qidirish</b>\n\n"
        "Zakaz kodi, telefon raqam yoki mijoz ismini yozing.\n"
        "Masalan: <code>#15</code>, <code>901234567</code>, <code>Muzaffar</code>",
        parse_mode="HTML",
    )


@router.message(OrderSearchState.waiting_query)
async def handle_order_search(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if query == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    if len(query) < 2:
        await message.answer("⚠️ Kamida 2 ta belgi yuboring.")
        return

    orders = await find_orders(query)
    await state.clear()
    if not orders:
        await message.answer("😕 Order topilmadi.", reply_markup=admin_menu_kb())
        return

    await message.answer(f"🔍 <b>{len(orders)} ta order topildi:</b>", parse_mode="HTML")
    for order in orders:
        await message.answer(format_order_admin(order), parse_mode="HTML", reply_markup=order_tools_kb(order), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("admin_track_"))
async def start_track_code(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        order = await get_order(session, order_id)
    if not order:
        await callback.answer("Order topilmadi", show_alert=True)
        return
    await state.set_state(TrackCodeState.waiting_code)
    await state.update_data(track_order_id=order_id)
    await callback.message.answer(
        f"🏷 <b>Buyurtma #{order_id}</b> uchun trek raqam yuboring.\n\n"
        "Masalan: <code>UZ123456789</code> yoki <code>FARGO-445566</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TrackCodeState.waiting_code)
async def save_track_code(message: Message, state: FSMContext, bot: Bot):
    code = (message.text or "").strip()
    if code == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    if len(code) < 3:
        await message.answer("⚠️ Trek raqam juda qisqa. Qaytadan yuboring.")
        return

    data = await state.get_data()
    order_id = int(data.get("track_order_id") or 0)
    async with AsyncSessionLocal() as session:
        order = await get_order(session, order_id)
        if not order:
            await state.clear()
            await message.answer("❌ Order topilmadi.", reply_markup=admin_menu_kb())
            return
        order.comment = upsert_meta_line(order.comment, TRACK_PREFIX, code)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Buyurtma #{order_id} uchun trek raqam saqlandi: <code>{code}</code>", parse_mode="HTML", reply_markup=admin_menu_kb())

    if order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"🏷 <b>Buyurtma #{order_id} trek raqami:</b>\n<code>{code}</code>\n\n"
                "Yetkazib berish holatini shu kod orqali tekshirishingiz mumkin.",
                parse_mode="HTML",
            )
        except Exception as exc:
            await message.answer(f"⚠️ Mijozga xabar borishda xato: <code>{type(exc).__name__}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("admin_note_"))
async def start_admin_note(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    await state.set_state(AdminNoteState.waiting_note)
    await state.update_data(note_order_id=order_id)
    await callback.message.answer(
        f"📝 <b>Buyurtma #{order_id}</b> uchun ichki admin izoh yozing.\n"
        "Bu mijozga yuborilmaydi.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminNoteState.waiting_note)
async def save_admin_note(message: Message, state: FSMContext):
    note = (message.text or "").strip()
    if note == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return
    if len(note) < 2:
        await message.answer("⚠️ Izoh juda qisqa.")
        return

    data = await state.get_data()
    order_id = int(data.get("note_order_id") or 0)
    async with AsyncSessionLocal() as session:
        order = await get_order(session, order_id)
        if not order:
            await state.clear()
            await message.answer("❌ Order topilmadi.", reply_markup=admin_menu_kb())
            return
        order.comment = upsert_meta_line(order.comment, ADMIN_NOTE_PREFIX, note)
        await session.commit()

    await state.clear()
    await message.answer(f"✅ Buyurtma #{order_id} uchun admin izoh saqlandi.", reply_markup=admin_menu_kb())


async def find_orders(query: str) -> list[Order]:
    clean = query.replace("#", "").strip()
    digits = "".join(ch for ch in query if ch.isdigit())
    async with AsyncSessionLocal() as session:
        stmt = (
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        if clean.isdigit() and len(clean) <= 7:
            stmt = stmt.where(Order.id == int(clean))
        else:
            pattern = f"%{query}%"
            conditions = [
                Order.customer_name.ilike(pattern),
                User.full_name.ilike(pattern),
                Order.delivery_address.ilike(pattern),
                Order.comment.ilike(pattern),
            ]
            if len(digits) >= 3:
                phone_pattern = f"%{digits}%"
                conditions.extend([
                    Order.customer_phone.ilike(phone_pattern),
                    User.phone.ilike(phone_pattern),
                ])
            stmt = stmt.join(User, Order.user_id == User.id).where(or_(*conditions))
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def get_order(session, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items).selectinload(OrderItem.product))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


def upsert_meta_line(comment: str | None, prefix: str, value: str) -> str:
    lines = [line for line in (comment or "").splitlines() if not line.startswith(prefix)]
    lines.append(f"{prefix} {value}")
    return "\n".join(line for line in lines if line.strip())


def read_meta_line(comment: str | None, prefix: str) -> str | None:
    for line in (comment or "").splitlines():
        if line.startswith(prefix):
            return line.replace(prefix, "", 1).strip()
    return None


def clean_comment(comment: str | None) -> str:
    visible = []
    for line in (comment or "").splitlines():
        if not line.startswith(TRACK_PREFIX) and not line.startswith(ADMIN_NOTE_PREFIX):
            visible.append(line)
    return "\n".join(visible).strip()


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


def format_order_admin(order) -> str:
    items_text = ""
    for item in order.items or []:
        product_name = item.product.name if item.product else "N/A"
        extra = f" ({item.size})" if item.size else ""
        extra += f" | ✍️{item.player_name}" if item.player_name else ""
        items_text += f"• {product_name}{extra} x {item.quantity}\n"
    if not items_text:
        items_text = "—\n"

    track = read_meta_line(order.comment, TRACK_PREFIX)
    note = read_meta_line(order.comment, ADMIN_NOTE_PREFIX)
    public_comment = clean_comment(order.comment)
    extra = ""
    if track:
        extra += f"\n🏷 Trek: <code>{track}</code>"
    if note:
        extra += f"\n📝 Admin izoh: {note}"
    if public_comment:
        extra += f"\n💬 Izoh: {public_comment}"

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
        f"{extra}"
    )
