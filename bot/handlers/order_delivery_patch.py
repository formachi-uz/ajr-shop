from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from bot.handlers import order
from bot.handlers.cart import get_cart, format_cart_text
from bot.keyboards.main_menu import cancel_kb
from bot.middlewares.admin_check import GROUP_CHAT_ID
from database.db import AsyncSessionLocal
from database.models import Order, OrderItem, OrderStatus, Review, User
from database.crud import get_user_by_telegram_id

router = Router()

STAR_ICONS = {
    1: "⭐",
    2: "⭐⭐",
    3: "⭐⭐⭐",
    4: "⭐⭐⭐⭐",
    5: "⭐⭐⭐⭐⭐",
}


class DeliveryAreaState(StatesGroup):
    waiting_area = State()
    waiting_tashkent_address = State()


class ReceivedReviewState(StatesGroup):
    waiting_text = State()


def delivery_area_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Toshkent shahri", callback_data="delivery_area_tashkent")],
        [InlineKeyboardButton(text="🚚 Viloyatlar", callback_data="delivery_area_regions")],
    ])


def rating_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="1⭐", callback_data=f"delivery_rate_1_{order_id}"),
        InlineKeyboardButton(text="2⭐", callback_data=f"delivery_rate_2_{order_id}"),
        InlineKeyboardButton(text="3⭐", callback_data=f"delivery_rate_3_{order_id}"),
        InlineKeyboardButton(text="4⭐", callback_data=f"delivery_rate_4_{order_id}"),
        InlineKeyboardButton(text="5⭐", callback_data=f"delivery_rate_5_{order_id}"),
    ]])


def infer_review_city(address: str | None) -> str:
    value = (address or "").strip()
    lower = value.lower()
    if not value:
        return "—"
    if "toshkent" in lower or "ташкент" in lower:
        return "Toshkent"
    for sep in [",", "|", "-"]:
        if sep in value:
            value = value.split(sep, 1)[0].strip()
            break
    return value[:40] if value else "—"


@router.message(order.OrderState.waiting_phone)
async def handle_phone_with_delivery_area(message: Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(phone) < 7:
        await message.answer("⚠️ Telefon raqam noto'g'ri. Qaytadan kiriting:")
        return

    await state.update_data(customer_phone=phone)
    await state.set_state(DeliveryAreaState.waiting_area)
    await message.answer(
        f"📱 Telefon: <b>{phone}</b>\n\n"
        "📍 <b>Yetkazib berish hududini tanlang:</b>\n\n"
        "🏙 <b>Toshkent shahri</b> — Yandex orqali yetkaziladi, manzil yozasiz\n"
        "🚚 <b>Viloyatlar</b> — BTS pochta orqali, manzil yozasiz",
        parse_mode="HTML",
        reply_markup=delivery_area_kb(),
    )


@router.callback_query(DeliveryAreaState.waiting_area, F.data == "delivery_area_regions")
async def choose_regions(callback: CallbackQuery, state: FSMContext):
    await state.update_data(delivery_area="regions", delivery_method="pochta")
    await state.set_state(order.OrderState.waiting_address)
    await callback.message.answer(
        "🚚 <b>Viloyatlar uchun yetkazish manzilingizni yozing:</b>\n"
        "<i>Viloyat, tuman va aniq joyni kiriting\n"
        "Masalan: Samarqand viloyati, Tayloq tumani, Musurmon</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.callback_query(DeliveryAreaState.waiting_area, F.data == "delivery_area_tashkent")
async def choose_tashkent(callback: CallbackQuery, state: FSMContext):
    await state.update_data(delivery_area="tashkent", delivery_method="yandex")
    await state.set_state(DeliveryAreaState.waiting_tashkent_address)
    await callback.message.answer(
        "🏙 <b>Toshkent shahri</b>\n\n"
        "Buyurtma Yandex orqali yetkaziladi.\n"
        "Iltimos, aniq manzilingizni yozing.\n\n"
        "<i>Masalan: Chilonzor tumani, 12-kvartal, 45-uy, 18-xonadon</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(DeliveryAreaState.waiting_tashkent_address)
async def handle_tashkent_address(message: Message, state: FSMContext):
    address_text = (message.text or "").strip()
    if len(address_text) < 8:
        await message.answer(
            "⚠️ Manzil juda qisqa. Toshkentdagi tuman, ko'cha/uy/xonadon yoki mo'ljalni yozing.",
            reply_markup=cancel_kb(),
        )
        return

    address = f"Toshkent shahri | Yandex manzil: {address_text}"
    await state.update_data(
        address=address,
        delivery_area="tashkent",
        delivery_method="yandex",
    )
    await state.set_state(order.OrderState.waiting_confirm)
    await send_order_summary(message, state, address)


@router.callback_query(F.data == "confirm_cart")
async def confirm_cart_with_delivery_note(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    delivery_method = data.get("delivery_method")
    await state.set_state(order.OrderState.waiting_payment)
    await callback.message.edit_reply_markup(reply_markup=None)

    if delivery_method == "yandex":
        delivery_note = (
            "🚕 <i>Toshkent bo'yicha Yandex yetkazish: buyurtmani Yandexga topshirishdan oldin "
            "admin siz bilan bog'lanadi.</i>"
        )
    else:
        delivery_note = "📦 <i>Viloyatlarga BTS pochta: 20,000 - 30,000 so'm</i>"

    await callback.message.answer(
        "💳 <b>To'lov usulini tanlang:</b>\n\n"
        "💳 <b>Karta / Paynet</b> — to'lov linki yuboriladi\n"
        "🤝 <b>Uzum Nasiya</b> — admin tez orada aloqaga chiqadi\n\n"
        f"{delivery_note}\n\n"
        "📦 Mahsulotni olgach <b>Buyurtmalarim</b> bo'limidan "
        "<b>Mahsulotni oldim</b> tugmasini bosishni unutmang.\n"
        "⭐ O'sha yerda faoliyatimiz uchun iliq fikringizni qoldirishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=order.payment_kb(),
    )
    await callback.answer()


async def send_order_summary(message: Message, state: FSMContext, address: str):
    data = await state.get_data()
    cart = get_cart(message.from_user.id)
    cart_text = format_cart_text(cart)

    delivery_label = "Yandex dostavka" if data.get("delivery_method") == "yandex" else "BTS pochta"

    summary = (
        "📋 <b>Buyurtmangizni tekshiring:</b>\n"
        f"{'─' * 28}\n"
        f"👤 {data.get('customer_name')}\n"
        f"📱 {data.get('customer_phone')}\n"
        f"🚚 {delivery_label}\n"
        f"📍 {address}\n"
        f"{'─' * 28}\n"
        f"{cart_text}\n"
        f"{'─' * 28}\n"
        "✅ Ma'lumotlar to'g'rimi?"
    )
    await message.answer(summary, parse_mode="HTML", reply_markup=order.confirm_cart_kb(), disable_web_page_preview=True)


@router.message(F.text == "📦 Buyurtmalarim")
async def my_orders_with_received_button(message: Message):
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("📦 Hali buyurtma yo'q.\n\n🛍 Katalogdan xarid qiling!")
            return

        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        orders = list(result.scalars().all())
        order_ids = [o.id for o in orders]
        review_result = await session.execute(
            select(Review.order_id).where(Review.order_id.in_(order_ids)) if order_ids else select(Review.order_id).where(Review.order_id == -1)
        )
        reviewed_order_ids = {int(order_id) for order_id in review_result.scalars().all() if order_id}

    if not orders:
        await message.answer("📦 Hali buyurtma yo'q.\n\n🛍 Katalogdan xarid qiling!")
        return

    for order_obj in orders:
        status_key = order_obj.status.value if hasattr(order_obj.status, "value") else str(order_obj.status)
        status = order.STATUS_TEXT.get(status_key, status_key)
        payment_key = order_obj.payment_type.value if hasattr(order_obj.payment_type, "value") else str(order_obj.payment_type or "")
        payment = order.PAYMENT_EMOJI.get(payment_key, "")
        date_text = order_obj.created_at.strftime('%d.%m.%Y %H:%M') if order_obj.created_at else "—"
        items_text = ""
        for item in order_obj.items:
            product_name = item.product.name if item.product else "Mahsulot"
            size = f" ({item.size})" if item.size else ""
            items_text += f"• {product_name}{size} × {item.quantity}\n"

        text = (
            f"📦 <b>Buyurtma #{order_obj.id}</b>\n"
            f"{'─' * 24}\n"
            f"Holati: {status}\n"
            f"💰 {int(order_obj.total_price or 0):,} so'm {payment}\n"
            f"📅 {date_text}\n"
            f"📍 {order_obj.delivery_address}\n"
            f"{'─' * 24}\n"
            f"{items_text or 'Mahsulot: —'}"
        )

        buttons = []
        if order_obj.id not in reviewed_order_ids and status_key in {
            OrderStatus.CONFIRMED.value,
            OrderStatus.DELIVERING.value,
            OrderStatus.DONE.value,
        }:
            buttons.append([InlineKeyboardButton(text="✅ Mahsulotni oldim", callback_data=f"delivery_yes_{order_obj.id}")])
        elif order_obj.id in reviewed_order_ids:
            buttons.append([InlineKeyboardButton(text="⭐ Sharh qabul qilingan", callback_data=f"review_already_{order_obj.id}")])

        reply_markup = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        await message.answer(text, parse_mode="HTML", reply_markup=reply_markup)

    await message.answer(
        "✅ Mahsulot qo'lingizga yetgach, yuqoridagi <b>Mahsulotni oldim</b> tugmasini bosing.\n"
        "⭐ Shu orqali faoliyatimiz uchun iliq fikringizni qoldirishingiz mumkin.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("review_already_"))
async def review_already(callback: CallbackQuery):
    await callback.answer("Bu buyurtma bo'yicha sharh qabul qilingan", show_alert=True)


@router.callback_query(F.data.startswith("delivery_yes_"))
async def customer_received_order(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("_")[2])
    review_city = "—"
    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.id == order_id, Order.user_id == user.id)
        )
        order_obj = result.scalar_one_or_none()
        if not order_obj:
            await callback.answer("Bu buyurtma sizga tegishli emas", show_alert=True)
            return
        review_exists = await session.execute(select(Review.id).where(Review.order_id == order_id).limit(1))
        if review_exists.scalar_one_or_none():
            await callback.answer("Sharh avval qabul qilingan", show_alert=True)
            return
        review_city = infer_review_city(order_obj.delivery_address)
        if order_obj.status in {OrderStatus.CONFIRMED, OrderStatus.DELIVERING}:
            order_obj.status = OrderStatus.DONE
            await session.commit()

    await state.update_data(received_order_id=order_id, received_city=review_city)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        "✅ <b>Mahsulotni olganingiz belgilandi!</b>\n\n"
        "Faoliyatimiz uchun iliq fikringizni qoldirsangiz juda xursand bo'lamiz.\n\n"
        "⭐ <b>Faoliyatimizni baholang:</b>",
        parse_mode="HTML",
        reply_markup=rating_kb(order_id),
    )
    await callback.answer("Rahmat")


@router.callback_query(F.data.startswith("delivery_rate_"))
async def received_rating(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    rating = int(parts[2])
    order_id = int(parts[3])
    await state.set_state(ReceivedReviewState.waiting_text)
    await state.update_data(received_rating=rating, received_order_id=order_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"Siz <b>{STAR_ICONS.get(rating, '⭐')} ({rating}/5)</b> baho berdingiz.\n\n"
        "✍️ Qisqacha sharh yozing:\n"
        "<i>Masalan: Forma sifati zo'r, yetkazish tez bo'ldi!</i>\n\n"
        "O'tkazib yuborish uchun <b>-</b> yuboring.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ReceivedReviewState.waiting_text)
async def save_received_review(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    order_id = int(data.get("received_order_id") or 0)
    rating = int(data.get("received_rating") or 5)
    city = data.get("received_city") or "—"
    comment = None if (message.text or "").strip() == "-" else (message.text or "").strip()

    async with AsyncSessionLocal() as session:
        user_result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = user_result.scalar_one_or_none()
        if not user:
            await state.clear()
            await message.answer("Foydalanuvchi topilmadi.")
            return
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
            .where(Order.id == order_id, Order.user_id == user.id)
        )
        order_obj = result.scalar_one_or_none()
        if not order_obj:
            await state.clear()
            await message.answer("Buyurtma topilmadi.")
            return

        product_ids = []
        product_names = []
        for item in order_obj.items:
            if item.product_id and item.product_id not in product_ids:
                product_ids.append(item.product_id)
                product_names.append(item.product.name if item.product else f"Mahsulot #{item.product_id}")
        if not product_ids:
            product_names = ["Mahsulot"]

        for product_id in product_ids:
            session.add(Review(
                user_id=user.id,
                product_id=product_id,
                order_id=order_id,
                rating=rating,
                text=comment,
                is_visible=True,
            ))
        await session.commit()

    await state.clear()
    await message.answer(
        "🙏 <b>Rahmat!</b>\n\n"
        f"{STAR_ICONS.get(rating, '⭐')} Bahoyingiz va sharhingiz qabul qilindi.\n"
        "Fikringiz mahsulot sahifasidagi sharhlar bo'limida ko'rinadi.",
        parse_mode="HTML",
    )

    review_text = (
        "⭐ <b>YANGI MIJOZ SHARHI</b>\n"
        f"{'─' * 24}\n"
        f"👤 {message.from_user.full_name}"
        f"{'  @' + message.from_user.username if message.from_user.username else ''}\n"
        f"🧾 Buyurtma #{order_id}\n"
        f"📍 {city}\n"
        f"🛍 {', '.join(product_names)}\n"
        f"⭐ <b>{rating}/5</b>\n"
    )
    if comment:
        review_text += f"💬 <i>{comment}</i>"
    try:
        await bot.send_message(GROUP_CHAT_ID, review_text, parse_mode="HTML")
    except Exception as exc:
        print(f"Sharh guruhga yuborilmadi: {exc}")
