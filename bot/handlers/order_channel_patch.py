import html
import os

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import text

from bot.handlers.cart import clear_cart, get_cart
from bot.keyboards.main_menu import main_menu_kb
from bot.keyboards.admin_kb import check_confirm_kb, order_actions_kb
from bot.middlewares.admin_check import GROUP_CHAT_ID, GLAVNIY_ADMIN_ID, is_admin
from database.crud import (
    add_order_item,
    create_order,
    get_order_with_items,
    get_product_by_id,
    get_user_by_telegram_id,
    update_order_status,
    update_order_total,
)
from database.db import AsyncSessionLocal
from database.models import OrderStatus

router = Router()

PAYNET_LINK = (
    "https://app.paynet.uz/qr-online/00020101021140440012qr-online.uz"
    "01186r0C2GWSuXEb8UE7KQ0202115204531153038605802UZ5910AO'PAYNET'"
    "6008Tashkent610610002164280002uz0106PAYNET0208Toshkent80520012"
    "qr-online.uz03097120207070419marketing@paynet.uz6304A3D2"
)
CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "9860340101082121")
CARD_OWNER = os.getenv("PAYMENT_CARD_OWNER", "Xolbo'tayev Bobur")


async def ensure_channel_table(session):
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS order_channel_messages (
            order_id INTEGER PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            message_id INTEGER NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
    """))
    await session.commit()


async def save_channel_message(order_id: int, chat_id: int, message_id: int):
    async with AsyncSessionLocal() as session:
        await ensure_channel_table(session)
        await session.execute(
            text("""
                INSERT INTO order_channel_messages(order_id, chat_id, message_id, updated_at)
                VALUES (:order_id, :chat_id, :message_id, now())
                ON CONFLICT (order_id) DO UPDATE
                SET chat_id = EXCLUDED.chat_id,
                    message_id = EXCLUDED.message_id,
                    updated_at = now()
            """),
            {"order_id": order_id, "chat_id": chat_id, "message_id": message_id},
        )
        await session.commit()


async def get_channel_message(order_id: int) -> tuple[int, int] | None:
    async with AsyncSessionLocal() as session:
        await ensure_channel_table(session)
        result = await session.execute(
            text("SELECT chat_id, message_id FROM order_channel_messages WHERE order_id = :order_id"),
            {"order_id": order_id},
        )
        row = result.first()
        if not row:
            return None
        return int(row[0]), int(row[1])


def esc(value) -> str:
    return html.escape(str(value or "—"), quote=False)


def money(value) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def is_yandex_order(order) -> bool:
    text_value = f"{order.delivery_address or ''} {order.comment or ''}".lower()
    return "toshkent" in text_value or "yandex" in text_value or "lokatsiya" in text_value


def channel_status_label(order) -> str:
    labels = {
        OrderStatus.PENDING: "⏳ TO'LOV/TEKSHIRUV KUTILMOQDA",
        OrderStatus.CONFIRMED: "✅ TO'LOV QILINDI / TASDIQLANDI",
        OrderStatus.DELIVERING: "📦 POCHTA/YANDEXGA TOPSHIRILDI",
        OrderStatus.DONE: "✔️ MIJOZGA YETKAZILDI",
        OrderStatus.CANCELLED: "❌ BEKOR QILINDI",
    }
    return labels.get(order.status, str(order.status.value if order.status else "—"))


def payment_line(order) -> str:
    payment_type = order.payment_type.value if order.payment_type else ""
    if payment_type == "card":
        if order.status in {OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.DONE}:
            return f"{money(order.total_price)} so'm ✅ Paynet / karta"
        return f"{money(order.total_price)} so'm ⏳ Paynet / karta cheki kutilmoqda"
    if payment_type == "credit":
        if order.status in {OrderStatus.CONFIRMED, OrderStatus.DELIVERING, OrderStatus.DONE}:
            return f"{money(order.total_price)} so'm ✅ Uzum Nasiya tasdiqlandi"
        return f"{money(order.total_price)} so'm 🤝 Uzum Nasiya — admin bog'lanadi"
    return f"{money(order.total_price)} so'm"


def delivery_line(order) -> str:
    prefix = "Yandex" if is_yandex_order(order) else "Pochta"
    return f"{prefix}: {order.delivery_address or '—'}"


def order_items_lines(order) -> list[str]:
    items = list(order.items or [])
    if not items:
        return ["📦 <b>Mahsulot:</b> —"]

    lines: list[str] = []
    for index, item in enumerate(items, 1):
        product_name = item.product.name if item.product else "Mahsulot"
        label = "📦" if len(items) == 1 else f"📦 {index}."
        lines.append(f"{label} <b>{esc(product_name)}</b>")
        lines.append(f"Razmeri: <b>{esc(item.size)}</b>")
        print_value = item.player_name or item.back_print
        lines.append(f"Yozilishi: <b>{esc(print_value) if print_value else "yo'q"}</b>")
        if item.quantity and item.quantity > 1:
            lines.append(f"Soni: <b>{item.quantity}</b>")
        if index != len(items):
            lines.append("")
    return lines


def first_order_photo(order):
    for item in order.items or []:
        if item.product and item.product.photo_url:
            return item.product.photo_url
    return None


def order_keyboard(order) -> InlineKeyboardMarkup | None:
    if order.status == OrderStatus.PENDING:
        return order_actions_kb(order.id)
    if order.status == OrderStatus.CONFIRMED:
        label = "🚕 Yandexga topshirildi" if is_yandex_order(order) else "📦 Pochtaga topshirildi"
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=label, callback_data=f"admin_deliver_{order.id}"),
        ]])
    if order.status == OrderStatus.DELIVERING:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✔️ Yetkazildi", callback_data=f"admin_done_{order.id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order.id}")],
        ])
    return None


def format_channel_order(order) -> str:
    customer_name = order.customer_name or (order.user.full_name if order.user else "—")
    customer_phone = order.customer_phone or (order.user.phone if order.user else "—")
    lines = [
        f"🧾 <b>Zakaz #{order.id}</b>",
        f"Status: <b>{channel_status_label(order)}</b>",
        "",
        *order_items_lines(order),
        "",
        f"To'lov: <b>{esc(payment_line(order))}</b>",
    ]
    if (order.payment_type.value if order.payment_type else "") == "card":
        lines.append(f"Karta: <code>{CARD_NUMBER}</code> - {esc(CARD_OWNER)}")
    lines.extend([
        f"Dastavka: <b>{esc(delivery_line(order))}</b>",
        f"Ism: <b>{esc(customer_name)}</b>",
        f"Tel: <code>{esc(customer_phone)}</code>",
    ])
    return "\n".join(lines)


async def send_order_channel_posts(bot: Bot, order):
    text_value = format_channel_order(order)
    photo = first_order_photo(order)
    targets = list(dict.fromkeys([GROUP_CHAT_ID, GLAVNIY_ADMIN_ID]))
    for target_id in targets:
        try:
            if photo and len(text_value) <= 1024:
                sent = await bot.send_photo(
                    target_id,
                    photo=photo,
                    caption=text_value,
                    parse_mode="HTML",
                    reply_markup=order_keyboard(order),
                )
            else:
                sent = await bot.send_message(
                    target_id,
                    text_value,
                    parse_mode="HTML",
                    reply_markup=order_keyboard(order),
                    disable_web_page_preview=True,
                )
            if int(target_id) == int(GROUP_CHAT_ID):
                await save_channel_message(order.id, sent.chat.id, sent.message_id)
        except Exception as exc:
            print(f"Order channel post error ({target_id}): {exc}")


async def update_order_channel_post(bot: Bot, order):
    stored = await get_channel_message(order.id)
    if not stored:
        return
    chat_id, message_id = stored
    text_value = format_channel_order(order)
    markup = order_keyboard(order)
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=text_value[:1024],
            parse_mode="HTML",
            reply_markup=markup,
        )
        return
    except Exception:
        pass
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text_value,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        print(f"Order channel edit skipped: {exc}")


async def remember_callback_message(callback: CallbackQuery, order_id: int):
    if callback.message and int(callback.message.chat.id) == int(GROUP_CHAT_ID):
        await save_channel_message(order_id, callback.message.chat.id, callback.message.message_id)


@router.callback_query(F.data.in_({"pay_card", "pay_credit"}))
async def handle_payment_with_channel(callback: CallbackQuery, state: FSMContext, bot: Bot):
    payment_type = "card" if callback.data == "pay_card" else "credit"
    data = await state.get_data()
    customer_name = data.get("customer_name", callback.from_user.full_name)
    customer_phone = data.get("customer_phone", "—")
    address = data.get("address", "—")
    cart = get_cart(callback.from_user.id)
    admin = is_admin(callback.from_user.id)

    if not cart:
        await state.clear()
        await callback.message.answer("❌ Savat bo'sh!", reply_markup=main_menu_kb(is_admin=admin))
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.message.answer("Xato! /start bosing.")
            await callback.answer()
            return
        order = await create_order(
            session,
            user_id=user.id,
            payment_type=payment_type,
            delivery_address=address,
            comment=f"Ism: {customer_name} | Tel: {customer_phone}",
            customer_name=customer_name,
            customer_phone=customer_phone,
        )
        total = 0
        for item in cart:
            await add_order_item(
                session,
                order_id=order.id,
                product_id=item["product_id"],
                quantity=item["qty"],
                price=item["price"],
                size=item.get("size"),
                player_name=item.get("back_print") or item.get("player_name"),
            )
            total += item["price"] * item["qty"]
        await update_order_total(session, order.id, total)
        order = await get_order_with_items(session, order.id)

    clear_cart(callback.from_user.id)
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅", reply_markup=main_menu_kb(is_admin=admin))

    if payment_type == "card":
        await callback.message.answer(
            f"✅ <b>Buyurtmangiz qabul qilindi! #{order.id}</b>\n\n"
            f"💰 Jami: <b>{money(total)} so'm</b>\n\n"
            "💳 <b>To'lov usullari:</b>\n"
            f"Paynet: tugma orqali\n"
            f"Karta: <code>{CARD_NUMBER}</code> - {esc(CARD_OWNER)}\n\n"
            "To'lovdan so'ng chek rasmini shu yerga yuboring.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 Paynet orqali to'lash", url=PAYNET_LINK)
            ]]),
        )
        from bot.handlers.order import CheckState
        await state.set_state(CheckState.waiting_check_photo)
        await state.update_data(check_order_id=order.id)
    else:
        await callback.message.answer(
            f"✅ <b>Buyurtmangiz qabul qilindi! #{order.id}</b>\n\n"
            "🤝 <b>Uzum Nasiya</b>\n"
            "Admin tez orada siz bilan bog'lanib shartlarni tushuntiradi.",
            parse_mode="HTML",
        )

    await send_order_channel_posts(bot, order)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_confirm_"))
async def confirm_order_live(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    await remember_callback_message(callback, order_id)
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.PENDING:
            await callback.answer(f"Holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "confirmed")
        order = await get_order_with_items(session, order_id)
    await update_order_channel_post(bot, order)
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=order_keyboard(order))
        except Exception:
            pass
    if order and order.user:
        try:
            await bot.send_message(order.user.telegram_id, f"✅ <b>Buyurtma #{order.id} tasdiqlandi!</b>", parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("check_confirm_"))
async def confirm_check_live(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.PENDING:
            await callback.answer("Bu chek allaqachon ko'rib chiqilgan", show_alert=True)
            return
        await update_order_status(session, order_id, "confirmed")
        order = await get_order_with_items(session, order_id)
    await update_order_channel_post(bot, order)
    try:
        if callback.message.caption:
            await callback.message.edit_caption(callback.message.caption + "\n\n✅ <b>To'lov tasdiqlandi</b>", parse_mode="HTML", reply_markup=None)
        else:
            await callback.message.edit_text((callback.message.text or "") + "\n\n✅ <b>To'lov tasdiqlandi</b>", parse_mode="HTML", reply_markup=None)
    except Exception:
        pass
    if order and order.user:
        try:
            await bot.send_message(order.user.telegram_id, f"💳 <b>To'lovingiz tasdiqlandi!</b>\n\nBuyurtma #{order.id} tayyorlanmoqda.", parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("To'lov tasdiqlandi")


@router.callback_query(F.data.startswith("check_reject_"))
async def reject_check_live(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
    try:
        if callback.message.caption:
            await callback.message.edit_caption(callback.message.caption + "\n\n❌ <b>Chek rad etildi</b>", parse_mode="HTML", reply_markup=None)
        else:
            await callback.message.edit_text((callback.message.text or "") + "\n\n❌ <b>Chek rad etildi</b>", parse_mode="HTML", reply_markup=None)
    except Exception:
        pass
    if order and order.user:
        try:
            await bot.send_message(order.user.telegram_id, f"❌ <b>Chekingiz tasdiqlanmadi.</b>\n\nBuyurtma #{order_id}. Iltimos, to'g'ri chek yuboring.", parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("Chek rad etildi")


@router.callback_query(F.data.startswith("admin_deliver_"))
async def deliver_order_live(callback: CallbackQuery, bot: Bot):
    if callback.data == "admin_deliver_all_confirmed":
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    await remember_callback_message(callback, order_id)
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.CONFIRMED:
            await callback.answer(f"Holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "delivering")
        order = await get_order_with_items(session, order_id)
    await update_order_channel_post(bot, order)
    if order and order.user:
        try:
            if is_yandex_order(order):
                text_value = f"🚕 <b>Buyurtma #{order.id} Yandex dostavkaga topshirildi!</b>"
            else:
                text_value = f"📦 <b>Buyurtma #{order.id} pochtaga topshirildi!</b>"
            await bot.send_message(order.user.telegram_id, text_value, parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("Topshirildi")


@router.callback_query(F.data.startswith("admin_done_"))
async def done_order_live(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    await remember_callback_message(callback, order_id)
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status != OrderStatus.DELIVERING:
            await callback.answer(f"Holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "done")
        order = await get_order_with_items(session, order_id)
    await update_order_channel_post(bot, order)
    if order and order.user:
        try:
            await bot.send_message(order.user.telegram_id, f"✔️ <b>Buyurtma #{order.id} yetkazildi!</b>\n\nFORMACHI bilan xarid qilganingiz uchun rahmat.", parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("Yetkazildi")


@router.callback_query(F.data.startswith("admin_cancel_"))
async def cancel_order_live(callback: CallbackQuery, bot: Bot):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    order_id = int(callback.data.split("_")[2])
    await remember_callback_message(callback, order_id)
    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi", show_alert=True)
            return
        if order.status in {OrderStatus.DONE, OrderStatus.CANCELLED}:
            await callback.answer(f"Holati: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "cancelled")
        order = await get_order_with_items(session, order_id)
    await update_order_channel_post(bot, order)
    if order and order.user:
        try:
            await bot.send_message(order.user.telegram_id, f"❌ <b>Buyurtma #{order.id} bekor qilindi.</b>", parse_mode="HTML")
        except Exception:
            pass
    await callback.answer("Bekor qilindi")
