from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin
from database.crud import get_product_by_id, update_product
from database.db import AsyncSessionLocal

router = Router()

TEXT_EDIT_FIELDS = {
    "name",
    "description",
    "photo_url",
    "team",
    "brand",
    "season",
    "model",
    "league",
    "customization_price",
}

FIELD_LABELS = {
    "name": "Nomi",
    "description": "Tavsif",
    "photo_url": "Rasm",
    "team": "Jamoa",
    "brand": "Brend",
    "season": "Season/Yil",
    "model": "Model",
    "league": "Liga/Guruh",
    "customization_price": "Ism yozish narxi",
}

KIT_TYPES = {
    "home": "Home",
    "away": "Away",
    "third": "Third",
    "training": "Training",
    "goalkeeper": "Goalkeeper",
    "none": "Yo'q",
}

CUSTOMIZATION_STATUSES = {
    "available_paid": "Pullik (+ narx)",
    "included_bonus": "Bonus/bepul",
    "not_available": "Mavjud emas",
}


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
                    InlineKeyboardButton(text="🏟 Jamoa", callback_data=f"edit_team_{product_id}"),
                    InlineKeyboardButton(text="👟 Brend", callback_data=f"edit_brand_{product_id}"),
                ],
                [
                    InlineKeyboardButton(text="📅 Season", callback_data=f"edit_season_{product_id}"),
                    InlineKeyboardButton(text="🎽 Kit type", callback_data=f"edit_kit_{product_id}"),
                ],
                [
                    InlineKeyboardButton(text="✍️ Ism yozish", callback_data=f"edit_custom_{product_id}"),
                    InlineKeyboardButton(text="💵 Yozish narxi", callback_data=f"edit_custom_price_{product_id}"),
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


@router.callback_query(F.data.startswith("edit_team_"))
async def start_edit_team(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(
        callback,
        state,
        "team",
        "🏟 Jamoa nomini yuboring. Tozalash uchun <b>-</b> yuboring:\nMasalan: <code>Barcelona</code>",
    )


@router.callback_query(F.data.startswith("edit_brand_"))
async def start_edit_brand(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(
        callback,
        state,
        "brand",
        "👟 Brend nomini yuboring. Tozalash uchun <b>-</b> yuboring:\nMasalan: <code>Nike</code>, <code>Adidas</code>",
    )


@router.callback_query(F.data.startswith("edit_season_"))
async def start_edit_season(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(
        callback,
        state,
        "season",
        "📅 Season/yilni yuboring. Tozalash uchun <b>-</b> yuboring:\nMasalan: <code>2024/25</code>",
    )


@router.callback_query(F.data.startswith("edit_custom_price_"))
async def start_edit_custom_price(callback: CallbackQuery, state: FSMContext):
    await _start_text_edit(
        callback,
        state,
        "customization_price",
        "💵 Ism yozish narxini yuboring. Masalan: <code>50000</code>",
    )


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
        format_product_meta(product) + f"\n\n{prompt}\n\nBekor qilish: /cancel",
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
    if not product_id or field not in TEXT_EDIT_FIELDS:
        await state.clear()
        await message.answer("Tahrirlash holati yo'qoldi. Qaytadan boshlang.", reply_markup=admin_menu_kb())
        return

    value = await _extract_text_edit_value(message, field)
    if value == "__INVALID__":
        return

    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, **{field: value})
        product = await get_product_by_id(session, product_id)

    await state.clear()
    field_label = FIELD_LABELS.get(field, field)
    await message.answer(
        f"✅ <b>{field_label} yangilandi!</b>\n\n"
        f"{format_product_meta(product) if product else 'Product ID: ' + str(product_id)}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


async def _extract_text_edit_value(message: Message, field: str):
    if field == "photo_url":
        if message.photo:
            return message.photo[-1].file_id
        if message.document:
            return message.document.file_id
        if message.text and len(message.text.strip()) >= 2:
            return message.text.strip()
        await message.answer("Rasm yoki URL/file_id yuboring.")
        return "__INVALID__"

    raw = (message.text or "").strip()
    if field in {"description", "team", "brand", "season", "model", "league"} and raw == "-":
        return None

    if field == "customization_price":
        try:
            value = float(raw.replace(",", "").replace(" ", ""))
        except ValueError:
            await message.answer("Narx faqat raqam bo'lishi kerak. Masalan: <code>50000</code>", parse_mode="HTML")
            return "__INVALID__"
        if value < 0:
            await message.answer("Narx manfiy bo'lmaydi.")
            return "__INVALID__"
        return value

    if len(raw) < 2:
        await message.answer("Kamida 2 ta belgi yuboring.")
        return "__INVALID__"
    return raw


@router.callback_query(F.data.startswith("edit_kit_"))
async def start_edit_kit(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"set_kit_{value}_{product_id}")]
        for value, label in KIT_TYPES.items()
    ]
    await callback.message.answer(
        format_product_meta(product) + "\n\n🎽 <b>Kit type tanlang:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_kit_"))
async def set_kit_type(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    payload = callback.data.replace("set_kit_", "", 1)
    kit_type, product_id_text = payload.rsplit("_", 1)
    product_id = int(product_id_text)
    value = None if kit_type == "none" else kit_type

    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, kit_type=value)
        product = await get_product_by_id(session, product_id)

    await callback.message.edit_text(
        f"✅ <b>Kit type yangilandi!</b>\n\n{format_product_meta(product)}",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer(KIT_TYPES.get(kit_type, kit_type))


@router.callback_query(F.data.startswith("edit_custom_"))
async def start_edit_customization(callback: CallbackQuery):
    if callback.data.startswith("edit_custom_price_"):
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"set_custom_{value}_{product_id}")]
        for value, label in CUSTOMIZATION_STATUSES.items()
    ]
    await callback.message.answer(
        format_product_meta(product) + "\n\n✍️ <b>Ism yozish holatini tanlang:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_custom_"))
async def set_customization_status(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    payload = callback.data.replace("set_custom_", "", 1)
    status, product_id_text = payload.rsplit("_", 1)
    product_id = int(product_id_text)
    if status not in CUSTOMIZATION_STATUSES:
        await callback.answer("Status noto'g'ri", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, customization_status=status)
        product = await get_product_by_id(session, product_id)

    await callback.message.edit_text(
        f"✅ <b>Ism yozish holati yangilandi!</b>\n\n{format_product_meta(product)}",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer(CUSTOMIZATION_STATUSES[status])


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
        product = await get_product_by_id(session, product_id)

    label = "aktiv" if new_value else "passiv"
    await callback.message.answer(
        f"✅ Product ID <code>{product_id}</code> {label} qilindi.\n\n{format_product_meta(product)}",
        parse_mode="HTML",
    )
    await callback.answer(label)


def format_product_meta(product) -> str:
    if not product:
        return "📦 Product topilmadi"
    active = "aktiv" if product.is_active else "passiv"
    custom_status = product.customization_status or "not_available"
    custom_label = CUSTOMIZATION_STATUSES.get(str(custom_status), str(custom_status))
    return (
        f"📦 <b>{product.name}</b>\n"
        f"ID: <code>{product.id}</code> | {active}\n"
        f"🏟 Jamoa: <b>{product.team or '—'}</b>\n"
        f"👟 Brend: <b>{product.brand or '—'}</b>\n"
        f"📅 Season: <b>{product.season or '—'}</b>\n"
        f"🎽 Kit: <b>{product.kit_type or '—'}</b>\n"
        f"✍️ Ism yozish: <b>{custom_label}</b>\n"
        f"💵 Yozish narxi: <b>{int(product.customization_price or 0):,} so'm</b>"
    )
