from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.handlers import order
from bot.handlers.cart import get_cart, format_cart_text
from bot.keyboards.main_menu import cancel_kb

router = Router()


class DeliveryAreaState(StatesGroup):
    waiting_area = State()
    waiting_tashkent_address = State()


def delivery_area_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Toshkent shahri", callback_data="delivery_area_tashkent")],
        [InlineKeyboardButton(text="🚚 Viloyatlar", callback_data="delivery_area_regions")],
    ])


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
        "🚚 <b>Viloyatlar</b> — pochta orqali, manzil yozasiz",
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


async def send_order_summary(message: Message, state: FSMContext, address: str):
    data = await state.get_data()
    cart = get_cart(message.from_user.id)
    cart_text = format_cart_text(cart)

    delivery_label = "Yandex dostavka" if data.get("delivery_method") == "yandex" else "Pochta"

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
