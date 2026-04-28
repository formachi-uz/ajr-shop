from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import text

from bot.middlewares.admin_check import is_admin, GLAVNIY_ADMIN_ID
from bot.keyboards.admin_kb import admin_menu_kb
from database.db import AsyncSessionLocal

router = Router()

RESET_PHRASE = "FORMACHI RESET"


class ResetDbState(StatesGroup):
    waiting_phrase = State()


def reset_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧹 Ha, bazani tozalash", callback_data="reset_db_final_confirm")],
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="reset_db_cancel")],
    ])


@router.message(F.text == "🧹 Bazani tozalash")
async def start_database_reset(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if GLAVNIY_ADMIN_ID and message.from_user.id != GLAVNIY_ADMIN_ID:
        await message.answer("⛔ Bu amal faqat glavnyi admin uchun ruxsat etilgan.")
        return

    await state.set_state(ResetDbState.waiting_phrase)
    await message.answer(
        "⚠️ <b>Diqqat! Bu amal test ma'lumotlarini o'chiradi.</b>\n\n"
        "O'chiriladi:\n"
        "• barcha mahsulotlar\n"
        "• barcha stocklar\n"
        "• barcha buyurtmalar\n"
        "• barcha order itemlar\n"
        "• barcha reviewlar\n\n"
        "Qoladi:\n"
        "• kategoriyalar\n"
        "• foydalanuvchilar/adminlar\n\n"
        "ID sequence qayta 1 dan boshlanadi. Davom etish uchun aynan shuni yozing:\n"
        f"<code>{RESET_PHRASE}</code>",
        parse_mode="HTML",
    )


@router.message(ResetDbState.waiting_phrase)
async def reset_phrase_received(message: Message, state: FSMContext):
    phrase = (message.text or "").strip()
    if phrase != RESET_PHRASE:
        await state.clear()
        await message.answer("❌ Tasdiq matni noto'g'ri. Reset bekor qilindi.", reply_markup=admin_menu_kb())
        return

    await message.answer(
        "🧹 <b>Oxirgi tasdiq:</b> bazani tozalaymizmi?\n\n"
        "Bu amal qaytarilmaydi.",
        parse_mode="HTML",
        reply_markup=reset_confirm_kb(),
    )


@router.callback_query(F.data == "reset_db_cancel")
async def reset_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Reset bekor qilindi.", reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "reset_db_final_confirm")
async def reset_final_confirm(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    if GLAVNIY_ADMIN_ID and callback.from_user.id != GLAVNIY_ADMIN_ID:
        await callback.answer("Faqat glavnyi admin", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("🧹 Baza tozalanyapti...")

    try:
        summary = await reset_shop_database()
    except Exception as exc:
        await callback.message.answer(
            "❌ Resetda xato bo'ldi:\n"
            f"<code>{type(exc).__name__}: {str(exc)[:900]}</code>",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
        await callback.answer()
        return

    await callback.message.answer(
        "✅ <b>Baza tozalandi!</b>\n\n"
        f"{summary}\n\n"
        "Endi mahsulotlarni 0 dan kiritamiz. Keyingi buyurtma <b>#1</b> dan boshlanadi.",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )
    await callback.answer("Baza tozalandi")


async def reset_shop_database() -> str:
    async with AsyncSessionLocal() as session:
        before = {}
        for table_name in ["products", "product_stocks", "orders", "order_items", "reviews"]:
            try:
                result = await session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                before[table_name] = int(result.scalar_one() or 0)
            except Exception:
                before[table_name] = 0

        await session.execute(text(
            "TRUNCATE TABLE "
            "order_items, orders, product_stocks, reviews, products "
            "RESTART IDENTITY CASCADE"
        ))
        await session.commit()

    return (
        f"🧾 Orders: {before.get('orders', 0)} -> 0\n"
        f"📦 Products: {before.get('products', 0)} -> 0\n"
        f"📊 Stocks: {before.get('product_stocks', 0)} -> 0\n"
        f"⭐ Reviews: {before.get('reviews', 0)} -> 0"
    )
