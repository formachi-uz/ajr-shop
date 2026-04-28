from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin
from database.crud import get_product_by_id, update_product
from database.db import AsyncSessionLocal

router = Router()


class ProductQuickEditState(StatesGroup):
    waiting_value = State()


def install_product_edit_hooks():
    """Add extra edit buttons everywhere product_manage_kb is used."""
    try:
        import bot.keyboards.admin_kb as admin_kb
        from bot.handlers import admin as admin_module
        from bot.handlers import admin_tools_patch

        if getattr(admin_kb, "_product_edit_hooked", False):
            return
        original_product_manage_kb = admin_kb.product_manage_kb

        def enhanced_product_manage_kb(product_id: int) -> InlineKeyboardMarkup:
            kb = original_product_manage_kb(product_id)
            rows = list(kb.inline_keyboard)
            extra_rows = [
                [
                    InlineKeyboardButton(text="✏️ Nom", callback_data=f"edit_name_{product_id}"),
                    InlineKeyboardButton(text="📝 Tavsif", callback_data=f"edit_desc_{product_id}"),
                ],
                [
                    InlineKeyboardButton(text="🖼 Rasm", callback_data=f"edit_photo_{product_id}"),
                    InlineKeyboardButton(text="🔁 Aktiv/Passiv", callback_data=f"toggle_active_{product_id}"),
                ],
            ]
            return InlineKeyboardMarkup(inline_keyboard=extra_rows + rows)

        admin_kb.product_manage_kb = enhanced_product_manage_kb
        admin_module.product_manage_kb = enhanced_product_manage_kb
        admin_tools_patch.product_manage_kb = enhanced_product_manage_kb
        admin_kb._product_edit_hooked = True
    except Exception as exc:
        print(f"Product edit hook skipped: {exc}")


@router.callback_query(F.data.startswith("edit_name_"))
async def start_edit_name(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(callback, state, "name", "✏️ Yangi mahsulot nomini yuboring:")


@router.callback_query(F.data.startswith("edit_desc_"))
async def start_edit_desc(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(callback, state, "description", "📝 Yangi tavsifni yuboring. O'chirish uchun <b>-</b> yuboring:")


@router.callback_query(F.data.startswith("edit_photo_"))
async def start_edit_photo(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(callback, state, "photo_url", "🖼 Yangi rasm yuboring yoki rasm URL/file_id yuboring:")


async def _start_text_edit(callback: CallbackQuery, state: FSMContext, field: str, prompt: str):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    await state.set_state(ProductQuickEditState.waiting_value)
    await state.update_data(edit_product_id=product_id, edit_field=field)
    await callback.message.answer(
        f"📦 <b>{product.name}</b>\n\n{prompt}\n\nBekor qilish: /cancel",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ProductQuickEditState.waiting_value)
async def save_quick_edit(message: Message, state: FSMContext):
    if (message.text or "").strip() == "/cancel":
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=admin_menu_kb())
        return

    data = await state.get_data()
    product_id = int(data.get("edit_product_id") or 0)
    field = data.get("edit_field")
    if not product_id or field not in {"name", "description", "photo_url"}:
        await state.clear()
        await message.answer("Tahrirlash holati yo'qoldi. Qaytadan boshlang.", reply_markup=admin_menu_kb())
        return

    if field == "photo_url":
        value = None
        if message.photo:
            value = message.photo[-1].file_id
        elif message.document:
            value = message.document.file_id
        elif message.text:
            value = message.text.strip()
        if not value or len(value) < 2:
            await message.answer("Rasm yoki URL/file_id yuboring.")
            return
    else:
        value = (message.text or "").strip()
        if field == "description" and value == "-":
            value = None
        elif len(value) < 2:
            await message.answer("Kamida 2 ta belgi yuboring.")
            return

    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, **{field: value})
        product = await get_product_by_id(session, product_id)

    await state.clear()
    field_label = {"name": "Nomi", "description": "Tavsif", "photo_url": "Rasm"}.get(field, field)
    await message.answer(
        f"✅ <b>{field_label} yangilandi!</b>\n\n"
        f"📦 {product.name if product else product_id}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


@router.callback_query(F.data.startswith("toggle_active_"))
async def toggle_product_active(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await callback.answer("Mahsulot topilmadi", show_alert=True)
            return
        new_value = not bool(product.is_active)
        await update_product(session, product_id, is_active=new_value)

    label = "aktiv" if new_value else "passiv"
    await callback.message.answer(f"✅ Product ID <code>{product_id}</code> {label} qilindi.", parse_mode="HTML")
    await callback.answer(label)
