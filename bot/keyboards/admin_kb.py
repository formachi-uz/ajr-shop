from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧾 Buyurtmalar"), KeyboardButton(text="🔍 Order qidirish")],
            [KeyboardButton(text="📦 Mahsulotlar bo'limi")],
            [KeyboardButton(text="📢 Marketing"), KeyboardButton(text="📊 Hisobotlar")],
            [KeyboardButton(text="⚙️ Sozlamalar")],
            [KeyboardButton(text="🏠 Asosiy menyu")],
        ],
        resize_keyboard=True
    )


def order_actions_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm_{order_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}"),
        ],
        [
            InlineKeyboardButton(text="🔔 Chek eslatish", callback_data=f"admin_remind_payment_{order_id}"),
        ],
    ])


def check_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ To'lov tasdiqlandi — Pochtaga tayyorlaymiz",
                callback_data=f"check_confirm_{order_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Chek noto'g'ri",
                callback_data=f"check_reject_{order_id}"
            ),
        ],
    ])


def postal_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="📦 Pochtaga topshirildi",
                callback_data=f"admin_deliver_{order_id}"
            ),
        ],
    ])


def product_manage_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Narx", callback_data=f"edit_price_{product_id}"),
            InlineKeyboardButton(text="🏷 Skidka", callback_data=f"edit_discount_{product_id}"),
        ],
        [
            InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"delete_prod_{product_id}"),
        ]
    ])
