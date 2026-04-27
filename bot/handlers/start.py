from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from database.db import AsyncSessionLocal
from database.crud import get_or_create_user
from bot.keyboards.main_menu import main_menu_kb, phone_kb
from bot.middlewares.admin_check import is_admin

router = Router()

WELCOME_TEXT = """
👋 <b>Assalomu alaykum, {name}!</b>

⚽ <b>Formachi.uz</b> botiga xush kelibsiz!

Biz sizga taqdim etamiz:
🏟 Klub formalari (Real, Barca, Bayern...)
🌍 Terma jamoa formalari (Argentina, Brazil...)
🏆 Retro formalar
👟 Butsalar & sarakonjoshkalar
✍️ Futbolkaga ism yozish xizmati

🛍 <b>Katalog</b> — kategoriya/jamoa bo'yicha ko'rish
🔍 <b>Qidiruv</b> — nom, jamoa yoki brend bo'yicha topish
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
            username=user.username
        )

    # Telefon raqami yo'q bo'lsa so'rash
    if not db_user.phone:
        await message.answer(
            WELCOME_TEXT.format(name=user.first_name),
            parse_mode="HTML",
            reply_markup=phone_kb()
        )
        await message.answer(
            "📱 Davom etish uchun telefon raqamingizni yuboring:",
            reply_markup=phone_kb()
        )
    else:
        await message.answer(
            WELCOME_TEXT.format(name=user.first_name),
            parse_mode="HTML",
            reply_markup=main_menu_kb(is_admin=admin)
        )


@router.message(F.contact)
async def handle_contact(message: Message):
    from database.crud import update_user_phone
    phone = message.contact.phone_number
    admin = is_admin(message.from_user.id)

    async with AsyncSessionLocal() as session:
        await update_user_phone(session, message.from_user.id, phone)

    await message.answer(
        "✅ <b>Raqamingiz saqlandi!</b>\n\nEndi xarid qilishingiz mumkin 🎉",
        parse_mode="HTML",
        reply_markup=main_menu_kb(is_admin=admin)
    )


@router.message(F.text == "📞 Aloqa")
async def contact_info(message: Message):
    await message.answer(
        "📞 <b>Biz bilan bog'lanish:</b>\n\n"
        "👤 Admin: @formachi_admin\n"
        "📱 Telefon: +998 94 911-51-23\n"
        "📍 Manzil: Toshkent Uchtepa outlet center B157 do'kon\n\n"
        "⏰ Ish vaqti: 11:00 - 22:00",
        parse_mode="HTML"
    )


@router.message(F.text == "ℹ️ Do'kon haqida")
async def about_shop(message: Message):
    await message.answer(
        "ℹ️ <b>Formachi.uz haqida</b>\n\n"
        "⚽ Biz O'zbekistondagi futbol shinavandalari uchun "
        "professional formalar, retro kollektsiyalar, butsalar va "
        "sport aksessuarlarini taklif etamiz.\n\n"
        "🛍 <b>Bizda mavjud:</b>\n"
        "• 🏟 Klub formalari (Real, Barca, Bayern, Man Utd va b.)\n"
        "• 🌍 Terma jamoa formalari (Argentina, Brazil, Germany va b.)\n"
        "• 🏆 Retro formalar\n"
        "• 👟 Butsalar va sarakonjoshkalar\n"
        "• ✍️ Forma orqasiga ism/raqam yozish xizmati\n\n"
        "🚚 <b>Yetkazib berish:</b> butun O'zbekiston bo'ylab BTS pochta orqali.\n"
        "💳 <b>To'lov:</b> Karta / Paynet / Uzum Nasiya.\n\n"
        "📱 Aloqa: @formachi_admin",
        parse_mode="HTML"
    )
