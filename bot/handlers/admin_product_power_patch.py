from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.handlers.admin_product_edit_patch import format_product_meta
from bot.middlewares.admin_check import is_admin
from database.crud import get_all_categories, get_product_by_id, update_product
from database.db import AsyncSessionLocal

router = Router()

PROMO_FIELDS = {
    "featured": ("is_featured", "⭐ Featured"),
    "top": ("is_top_forma", "🔥 Top forma"),
    "boot": ("is_premium_boot", "👟 Premium butsi"),
}


def install_product_power_hooks():
    """Extend the existing product edit keyboard after admin_product_edit_patch wraps it."""
    try:
        import bot.keyboards.admin_kb as admin_kb
        from bot.handlers import admin as admin_module
        from bot.handlers import admin_tools_patch

        if getattr(admin_kb, "_product_power_hooked", False):
            return

        original_kb = admin_kb.product_manage_kb

        def power_product_manage_kb(product_id: int) -> InlineKeyboardMarkup:
            rows = [
                [
                    InlineKeyboardButton(text="🏷 Kategoriya", callback_data=f"edit_category_{product_id}"),
                    InlineKeyboardButton(text="⭐ Promo flaglar", callback_data=f"edit_promo_{product_id}"),
                ],
            ]
            rows.extend(original_kb(product_id).inline_keyboard)
            return InlineKeyboardMarkup(inline_keyboard=rows)

        admin_kb.product_manage_kb = power_product_manage_kb
        admin_module.product_manage_kb = power_product_manage_kb
        admin_tools_patch.product_manage_kb = power_product_manage_kb
        admin_kb._product_power_hooked = True
    except Exception as exc:
        print(f"Product power hook skipped: {exc}")


@router.callback_query(F.data.startswith("edit_category_"))
async def edit_product_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        categories = await get_all_categories(session)
    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    rows = [
        [InlineKeyboardButton(text=f"{cat.emoji} {cat.name}", callback_data=f"set_category_{cat.id}_{product_id}")]
        for cat in categories[:8]
    ]
    await callback.message.answer(
        format_product_meta(product) + "\n\n🏷 <b>Yangi kategoriyani tanlang:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_category_"))
async def set_product_category(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    payload = callback.data.replace("set_category_", "", 1)
    category_id_text, product_id_text = payload.rsplit("_", 1)
    category_id = int(category_id_text)
    product_id = int(product_id_text)
    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, category_id=category_id)
        product = await get_product_by_id(session, product_id)
    await callback.message.edit_text(
        f"✅ <b>Kategoriya yangilandi!</b>\n\n{format_product_meta(product)}",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer("Kategoriya yangilandi")


@router.callback_query(F.data.startswith("edit_promo_"))
async def edit_product_promo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    product_id = int(callback.data.split("_")[-1])
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
    if not product:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    rows = []
    for key, (field, label) in PROMO_FIELDS.items():
        enabled = bool(getattr(product, field, False))
        mark = "✅" if enabled else "⬜"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"toggle_promo_{key}_{product_id}")])
    await callback.message.answer(
        format_product_meta(product) + "\n\n⭐ <b>Promo flaglarni yoqing/o'chiring:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_promo_"))
async def toggle_product_promo(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    payload = callback.data.replace("toggle_promo_", "", 1)
    key, product_id_text = payload.rsplit("_", 1)
    if key not in PROMO_FIELDS:
        await callback.answer("Flag noto'g'ri", show_alert=True)
        return
    field, label = PROMO_FIELDS[key]
    product_id = int(product_id_text)
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await callback.answer("Mahsulot topilmadi", show_alert=True)
            return
        new_value = not bool(getattr(product, field, False))
        await update_product(session, product_id, **{field: new_value})
        product = await get_product_by_id(session, product_id)
    status = "yoqildi" if new_value else "o'chirildi"
    await callback.message.edit_text(
        f"✅ <b>{label} {status}</b>\n\n{format_product_meta(product)}",
        parse_mode="HTML",
        reply_markup=None,
    )
    await callback.answer(status)
