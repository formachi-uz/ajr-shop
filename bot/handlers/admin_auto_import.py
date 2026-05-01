import re
from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.handlers.admin_channel_import import (
    RECENT_MEDIA_IMPORTS,
    append_gallery_photo,
    format_import_result,
    importer_kb,
    parse_product_post,
    save_imported_product,
)
from bot.middlewares.admin_check import is_admin

router = Router()
DEFAULT_IMPORTED_STOCK_QTY = 10


def normalize_imported_stocks(parsed: dict) -> dict:
    stocks = parsed.get("stocks") or {}
    if not stocks:
        return parsed
    parsed["stocks"] = {
        size: max(int(qty or 0), DEFAULT_IMPORTED_STOCK_QTY)
        for size, qty in stocks.items()
    }
    return parsed


def looks_like_product_post(message: Message) -> bool:
    if not message.from_user or not is_admin(message.from_user.id):
        return False

    media_group_id = str(message.media_group_id or "")
    if message.photo and media_group_id and (message.from_user.id, media_group_id) in RECENT_MEDIA_IMPORTS:
        return True

    text = (message.caption or message.text or "").strip().lower()
    if not text:
        return False

    has_price_word = any(word in text for word in ["narx", "so'm", "som", "sum", "ming", "uzs", "сум"])
    has_product_word = any(word in text for word in [
        "forma", "futbolka", "butsi", "butsa", "sarakan", "sorokon", "poyabzal",
        "razmer", "razmeri", "size", "nike", "adidas", "puma", "magista", "air zoom", "f50",
    ])
    has_money = bool(re.search(r"\d[\d\s.,]{2,}\s*(?:so['`‘’]?m|som|sum|uzs|сум|ming|k)", text, flags=re.I))
    return bool((message.photo or message.caption) and has_product_word and (has_price_word or has_money))


@router.message(looks_like_product_post)
async def auto_import_product_post(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    photo_id = message.photo[-1].file_id if message.photo else None
    media_group_id = str(message.media_group_id or "")
    text = (message.caption or message.text or "").strip()

    if photo_id and media_group_id and not text:
        product_id = RECENT_MEDIA_IMPORTS.get((message.from_user.id, media_group_id))
        if product_id:
            await append_gallery_photo(product_id, photo_id)
            await message.answer(f"🖼 Album rasmi mahsulot ID {product_id} gallery qismiga qo'shildi.")
        return

    try:
        parsed = normalize_imported_stocks(parse_product_post(text))
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
        "📥 <b>Avto-import ishladi</b>\n\n" + format_import_result(product_id, parsed),
        parse_mode="HTML",
        reply_markup=importer_kb(),
    )
