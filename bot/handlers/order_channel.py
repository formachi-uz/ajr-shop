import os
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models import OrderStatus, PaymentType


PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "9860340101082121 - Xolbo'tayev Bobur")

STATUS_LABELS = {
    OrderStatus.PENDING: "⏳ To'lov kutilmoqda",
    OrderStatus.CONFIRMED: "✅ To'lov qilingan / tasdiqlangan",
    OrderStatus.DELIVERING: "📦 Pochtaga topshirilgan",
    OrderStatus.DONE: "✔️ Yetkazildi",
    OrderStatus.CANCELLED: "❌ Bekor qilingan",
    "pending": "⏳ To'lov kutilmoqda",
    "confirmed": "✅ To'lov qilingan / tasdiqlangan",
    "delivering": "📦 Pochtaga topshirilgan",
    "done": "✔️ Yetkazildi",
    "cancelled": "❌ Bekor qilingan",
}

PAYMENT_LABELS = {
    PaymentType.CARD: "✅ Paynet / karta",
    PaymentType.CREDIT: "🤝 Uzum Nasiya",
    PaymentType.CASH: "💵 Naqd",
    "card": "✅ Paynet / karta",
    "credit": "🤝 Uzum Nasiya",
    "cash": "💵 Naqd",
}


def _value(value):
    return value.value if hasattr(value, "value") else value


def _safe(value, fallback="—") -> str:
    value = fallback if value is None or value == "" else value
    return escape(str(value))


def _status_key(status) -> str:
    return str(_value(status) or "pending")


def order_status_kb(order_id: int, status) -> InlineKeyboardMarkup | None:
    status_key = _status_key(status)

    if status_key == OrderStatus.PENDING.value:
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ To'lov tasdiqlandi", callback_data=f"admin_confirm_{order_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}"),
            ],
            [
                InlineKeyboardButton(text="🔔 Chek eslatish", callback_data=f"admin_remind_payment_{order_id}"),
            ],
        ])

    if status_key == OrderStatus.CONFIRMED.value:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📦 Pochtaga topshirildi", callback_data=f"admin_deliver_{order_id}")],
            [InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}")],
        ])

    if status_key == OrderStatus.DELIVERING.value:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✔️ Mijoz qabul qildi", callback_data=f"admin_done_{order_id}")],
        ])

    return None


def _customer_name(order) -> str:
    if getattr(order, "customer_name", None):
        return order.customer_name
    if getattr(order, "user", None) and getattr(order.user, "full_name", None):
        return order.user.full_name
    return "—"


def _customer_phone(order) -> str:
    if getattr(order, "customer_phone", None):
        return order.customer_phone
    if getattr(order, "user", None) and getattr(order.user, "phone", None):
        return order.user.phone
    comment = getattr(order, "comment", "") or ""
    if "Tel:" in comment:
        try:
            return comment.split("Tel:", 1)[1].split("|", 1)[0].strip()
        except Exception:
            return "—"
    return "—"


def _payment_label(order) -> str:
    payment = _value(getattr(order, "payment_type", None))
    label = PAYMENT_LABELS.get(payment, PAYMENT_LABELS.get(getattr(order, "payment_type", None), "—"))
    total = int(getattr(order, "total_price", 0) or 0)
    text = f"{total:,} so'm {label}".replace(",", " ")
    if payment == PaymentType.CARD.value:
        text += f"\nKarta: {PAYMENT_CARD_NUMBER}"
    if payment == PaymentType.CREDIT.value:
        text += "\nIzoh: mijoz Uzum Nasiya orqali olishni xohlaydi"
    return text


def _delivery_label(order) -> str:
    address = getattr(order, "delivery_address", None) or "—"
    lower = address.lower()
    if "toshkent" in lower or "ташкент" in lower:
        return f"Yandex: {address}"
    return address


def _format_items(order) -> str:
    lines = []
    for index, item in enumerate(getattr(order, "items", []) or [], 1):
        product = getattr(item, "product", None)
        name = getattr(product, "name", None) or "Mahsulot"
        size = getattr(item, "size", None) or "—"
        player_name = getattr(item, "player_name", None) or getattr(item, "back_print", None)
        qty = getattr(item, "quantity", 1) or 1
        line = [
            f"{index}. <b>{_safe(name)}</b>",
            f"Razmeri: <b>{_safe(size)}</b>",
        ]
        if player_name:
            line.append(f"Yozilishi: <b>{_safe(player_name)}</b>")
        if qty > 1:
            line.append(f"Soni: <b>{qty}</b>")
        lines.append("\n".join(line))
    return "\n\n".join(lines) if lines else "Mahsulot: —"


def format_order_channel_text(order, actor: str | None = None) -> str:
    status = getattr(order, "status", OrderStatus.PENDING)
    status_label = STATUS_LABELS.get(status, STATUS_LABELS.get(_status_key(status), _status_key(status)))
    created_at = getattr(order, "created_at", None)
    date_text = created_at.strftime("%d.%m.%Y %H:%M") if created_at else "—"

    parts = [
        f"🧾 <b>ZAKAZ #{order.id}</b>",
        f"Holati: <b>{status_label}</b>",
        f"Sana: {_safe(date_text)}",
        "",
        _format_items(order),
        "",
        f"To'lov: <b>{_safe(_payment_label(order))}</b>",
        f"Dastavka: <b>{_safe(_delivery_label(order))}</b>",
        f"Ism: <b>{_safe(_customer_name(order))}</b>",
        f"Tel: <b>{_safe(_customer_phone(order))}</b>",
    ]
    if actor:
        parts.append(f"Admin: <b>{_safe(actor)}</b>")
    return "\n".join(parts)


def as_order_caption(text: str) -> str:
    if len(text) <= 1000:
        return text
    trimmed = text[:997]
    last_break = trimmed.rfind("\n")
    if last_break > 650:
        trimmed = trimmed[:last_break]
    return trimmed + "..."


async def refresh_order_channel_message(bot: Bot, order, actor: str | None = None) -> bool:
    chat_id = getattr(order, "order_channel_chat_id", None)
    message_id = getattr(order, "order_channel_message_id", None)
    if not chat_id or not message_id:
        return False

    text = format_order_channel_text(order, actor=actor)
    reply_markup = order_status_kb(order.id, getattr(order, "status", None))
    has_media = bool(getattr(order, "order_channel_has_media", False))

    try:
        if has_media:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=as_order_caption(text),
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        else:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        print(f"Order channel refresh failed for #{order.id}: {exc}")
    except Exception as exc:
        print(f"Order channel refresh failed for #{order.id}: {exc}")
    return False
