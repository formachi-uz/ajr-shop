from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def admin_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Tasdiqlangan buyurtmalar"), KeyboardButton(text="📋 Yangi buyurtmalar")],
            [KeyboardButton(text="➕ Mahsulot qo'shish"), KeyboardButton(text="📦 Mahsulotlar")],
            [KeyboardButton(text="👥 Adminlar"), KeyboardButton(text="🌐 Web Panel")],
            [KeyboardButton(text="🏠 Asosiy menyu")],
        ],
        resize_keyboard=True
    )


def order_actions_kb(order_id: int) -> InlineKeyboardMarkup:
    """
    Guruhga keladigan yangi buyurtma tugmalari.
    1-BOSQICH: Faqat Tasdiqlash yoki Bekor qilish.
    Bosilgandan keyin tugmalar yo'qoladi (1 martalik).
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"admin_confirm_{order_id}"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"admin_cancel_{order_id}"),
        ],
    ])


def check_confirm_kb(order_id: int) -> InlineKeyboardMarkup:
    """
    Chek guruhiga keladigan tugma.
    Admin chekni ko'rib: "To'lov tasdiqlandi" bosadi.
    1 martalik.
    """
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
    """
    Tasdiqlangan buyurtmalar ro'yxatida.
    Admin pochtaga topshirganda bosadi — 1 martalik.
    """
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
