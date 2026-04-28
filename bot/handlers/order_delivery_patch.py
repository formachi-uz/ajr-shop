from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.handlers import order
from bot.handlers.cart import get_cart, format_cart_text
from bot.keyboards.main_menu import cancel_kb

router = Router()


class DeliveryAreaState(StatesGroup):
    waiting_area = State()
    waiting_tashkent_location = State()


def delivery_area_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏙 Toshkent shahri", callback_data="delivery_area_tashkent")],
        [InlineKeyboardButton(text="🚚 Viloyatlar", callback_data="delivery_area_regions")],
    ])


def location_request_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Lokatsiyani yuborish", request_location=True)],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


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
        "🏙 <b>Toshkent shahri</b> — Yandex orqali, lokatsiya yuborasiz\n"
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
    await state.set_state(DeliveryAreaState.waiting_tashkent_location)
    await callback.message.answer(
        "🏙 <b>Toshkent shahri</b>\n\n"
        "Buyurtma Yandex orqali yetkaziladi.\n"
        "Iltimos, boradigan joy lokatsiyasini yuboring.",
        parse_mode="HTML",
        reply_markup=location_request_kb(),
    )
    await callback.answer()


@router.message(DeliveryAreaState.waiting_tashkent_location)
async def handle_tashkent_location(message: Message, state: FSMContext):
    if not message.location:
        await message.answer(
            "📍 Iltimos, Telegram lokatsiya yuboring.\n"
            "Pastdagi <b>📍 Lokatsiyani yuborish</b> tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=location_request_kb(),
        )
        return

    latitude = message.location.latitude
    longitude = message.location.longitude
    location_url = f"https://maps.google.com/?q={latitude},{longitude}"
    address = f"Toshkent shahri | Yandex lokatsiya: {latitude:.6f}, {longitude:.6f}"

    await state.update_data(
        address=address,
        delivery_area="tashkent",
        delivery_method="yandex",
        delivery_latitude=latitude,
        delivery_longitude=longitude,
        delivery_location_url=location_url,
    )
    await state.set_state(order.OrderState.waiting_confirm)
    await send_order_summary(message, state, address, location_url)


async def send_order_summary(message: Message, state: FSMContext, address: str, location_url: str | None = None):
    data = await state.get_data()
    cart = get_cart(message.from_user.id)
    cart_text = format_cart_text(cart)

    location_line = f"\n🗺 <a href='{location_url}'>Lokatsiyani ochish</a>" if location_url else ""
    delivery_label = "Yandex dostavka" if data.get("delivery_method") == "yandex" else "Pochta"

    summary = (
        "📋 <b>Buyurtmangizni tekshiring:</b>\n"
        f"{'─' * 28}\n"
        f"👤 {data.get('customer_name')}\n"
        f"📱 {data.get('customer_phone')}\n"
        f"🚚 {delivery_label}\n"
        f"📍 {address}{location_line}\n"
        f"{'─' * 28}\n"
        f"{cart_text}\n"
        f"{'─' * 28}\n"
        "✅ Ma'lumotlar to'g'rimi?"
    )
    await message.answer(summary, parse_mode="HTML", reply_markup=order.confirm_cart_kb(), disable_web_page_preview=True)
