import os

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)


WEB_APP_URL = os.getenv("WEB_APP_URL", "https://webapp-production-8738.up.railway.app")


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="🌐 Saytda xarid qilish", web_app=WebAppInfo(url=WEB_APP_URL))],
        [KeyboardButton(text="🛍 Katalog"), KeyboardButton(text="🛒 Savatim")],
        [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="📞 Aloqa")],
    ]
    if is_admin:
        buttons.append([KeyboardButton(text="⚙️ Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def phone_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def web_app_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Saytga kirish", web_app=WebAppInfo(url=WEB_APP_URL))],
        [InlineKeyboardButton(text="🛍 Bot katalogi", callback_data="catalog")],
    ])


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
        resize_keyboard=True,
    )


def payment_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💳 Karta / Paynet")],
            [KeyboardButton(text="🤝 Uzum Nasiya")],
            [KeyboardButton(text="🚶 O'zim borib olaman")],
            [KeyboardButton(text="❌ Bekor qilish")],
        ],
        resize_keyboard=True,
    )
