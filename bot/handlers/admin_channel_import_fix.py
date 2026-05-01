from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.handlers.admin_channel_import import (
    ChannelImportState,
    RECENT_MEDIA_IMPORTS,
    STOP_WORDS,
    append_gallery_photo,
    format_import_result,
    importer_kb,
    parse_product_post,
    save_imported_product,
)
from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin

router = Router()


async def open_import_mode(message: Message, state: FSMContext):
    await state.set_state(ChannelImportState.waiting_posts)
    await message.answer(
        "📥 <b>Kanaldan mahsulot import qilish yoqildi</b>\n\n"
        "Endi kanalingizdagi mahsulot postlarini shu botga <b>forward</b> qiling.\n"
        "Bot rasm, nom, narx, kategoriya, jamoa/brend va razmerlarni avtomatik o'qib saqlaydi.\n\n"
        "Caption ichida quyidagilar bo'lsa yaxshi ishlaydi:\n"
        "<code>Real Madrid uy formasi 25/26\nNarx: 99 000 so'm\nS:5 M:10 L:8 XL:3</code>\n\n"
        "Tugatish uchun <b>tayyor</b> deb yozing.",
        parse_mode="HTML",
        reply_markup=importer_kb(),
    )


@router.callback_query(F.data == "channel_import_start")
async def start_channel_import_fixed(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await open_import_mode(callback.message, state)
    await callback.answer("Import rejimi yoqildi")


@router.message(F.text.in_({"📥 Kanaldan import", "/importkanal", "/import_channel"}))
async def start_channel_import_text_fixed(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q")
        return
    await open_import_mode(message, state)


@router.callback_query(F.data == "channel_import_stop")
async def stop_channel_import_fixed(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("✅ Kanaldan import tugatildi.", reply_markup=admin_menu_kb())
    await callback.answer("Tugatildi")


@router.message(ChannelImportState.waiting_posts)
async def import_forwarded_post_fixed(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    text = (message.caption or message.text or "").strip()
    if text.lower() in STOP_WORDS:
        await state.clear()
        await message.answer("✅ Kanaldan import tugatildi.", reply_markup=admin_menu_kb())
        return

    photo_id = message.photo[-1].file_id if message.photo else None
    media_group_id = str(message.media_group_id or "")

    if photo_id and media_group_id and not text:
        product_id = RECENT_MEDIA_IMPORTS.get((message.from_user.id, media_group_id))
        if product_id:
            await append_gallery_photo(product_id, photo_id)
            await message.answer(f"🖼 Album rasmi mahsulot ID {product_id} gallery qismiga qo'shildi.")
        return

    if not text:
        await message.answer(
            "⚠️ Bu postda caption matni topilmadi.\n"
            "Iltimos, narx yozilgan rasm/captionli postni forward qiling.",
            reply_markup=importer_kb(),
        )
        return

    try:
        parsed = parse_product_post(text)
        if photo_id:
            parsed["photo_url"] = photo_id
        parsed["description"] = text or parsed["name"]
        product_id = await save_imported_product(parsed)
    except Exception as exc:
        await message.answer(
            "❌ Import qilinmadi.\n\n"
            f"<code>{escape(type(exc).__name__)}: {escape(str(exc)[:900])}</code>",
            parse_mode="HTML",
            reply_markup=importer_kb(),
        )
        return

    if media_group_id:
        RECENT_MEDIA_IMPORTS[(message.from_user.id, media_group_id)] = product_id

    await message.answer(
        format_import_result(product_id, parsed),
        parse_mode="HTML",
        reply_markup=importer_kb(),
    )
