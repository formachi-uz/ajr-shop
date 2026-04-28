from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Tasdiqlangan buyurtmalar"), KeyboardButton(text="📋 Yangi buyurtmalar")],
            [KeyboardButton(text="🚚 Yetkazilayotgan"), KeyboardButton(text="📊 Statistika")],
            [KeyboardButton(text="➕ Mahsulot qo'shish"), KeyboardButton(text="📦 Mahsulotlar")],
            [KeyboardButton(text="🔎 Mahsulot qidirish"), KeyboardButton(text="📦 Stock boshqarish")],
            [KeyboardButton(text="🚕 Toshkent/Yandex"), KeyboardButton(text="📉 Kam qolgan stock")],
            [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🌐 Web Panel")],
            [KeyboardButton(text="👥 Adminlar"), KeyboardButton(text="🏠 Asosiy menyu")],
        ],
        resize_keyboard=True
    )


def order_actions_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm_{order_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}"),
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
