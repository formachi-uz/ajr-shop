from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from bot.keyboards.main_menu import main_menu_kb, phone_kb, web_app_inline_kb
from bot.middlewares.admin_check import is_admin
from database.crud import get_or_create_user
from database.db import AsyncSessionLocal

router = Router()

WELCOME_TEXT = """
👋 <b>Assalomu alaykum, {name}!</b>

⚽ <b>FORMACHI</b> botiga xush kelibsiz!

Bu yerda siz:
👕 Formalar va retro formalarni ko'rasiz
👟 Butsiylar va sarakanojshkalarni tanlaysiz
✍️ Forma orqasiga ism va raqam yozdirasiz
🌐 Saytda mahsulotlarni to'liqroq ko'rib buyurtma berasiz

Xaridni boshlash uchun pastdagi menyudan foydalaning.
"""


@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    admin = is_admin(user.id)

    async with AsyncSessionLocal() as session:
        db_user = await get_or_create_user(
            session,
            telegram_id=user.id,
            full_name=user.full_name,
            username=user.username,
        )

    if not db_user.phone:
        await message.answer(
            WELCOME_TEXT.format(name=user.first_name),
            parse_mode="HTML",
            reply_markup=phone_kb(),
        )
        await message.answer(
            "📱 Buyurtmalar Telegram akkauntingizga bog'lanishi uchun telefon raqamingizni yuboring:",
            reply_markup=phone_kb(),
        )
        return

    await message.answer(
        WELCOME_TEXT.format(name=user.first_name),
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin),
    )
    await message.answer(
        "🌐 Saytda rasmlar, o'lchamlar va checkout to'liqroq ko'rinadi.",
        reply_markup=web_app_inline_kb(),
    )


@router.message(F.contact)
async def handle_contact(message: Message):
    from database.crud import update_user_phone

    phone = message.contact.phone_number
    admin = is_admin(message.from_user.id)

    async with AsyncSessionLocal() as session:
        await update_user_phone(session, message.from_user.id, phone)

    await message.answer(
        "✅ <b>Ro'yxatdan o'tdingiz!</b>\n\nEndi sayt yoki bot orqali buyurtma berishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin),
    )
    await message.answer(
        "🌐 Mahsulotlarni rasm, o'lcham va to'lov bilan qulay ko'rish uchun saytni oching:",
        reply_markup=web_app_inline_kb(),
    )


@router.message(F.text == "📞 Aloqa")
async def contact_info(message: Message):
    await message.answer(
        "📞 <b>Biz bilan bog'lanish:</b>\n\n"
        "👤 Admin: @formachi_admin\n"
        "📱 Telefon: +998 94 911-51-23\n"
        "📍 Manzil: Toshkent Uchtepa outlet center B157 do'kon\n\n"
        "⏰ Ish vaqti: 11:00 - 22:00",
        parse_mode="HTML",
    )
