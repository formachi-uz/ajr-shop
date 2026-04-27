"""
Qidiruv (Search) handler.
- Mahsulot nomi / jamoa / brend / model / liga / tavsif bo'yicha case-insensitive partial qidiruv.
- "🔍 Qidiruv" tugmasi bosilganda bot foydalanuvchidan matn so'raydi.
- Natijalar product cards ko'rinishida (rasm + matn + tugma) qaytariladi.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database.db import AsyncSessionLocal
from database.crud import search_products

logger = logging.getLogger(__name__)
router = Router()

MAX_RESULTS_PER_PAGE = 8


class SearchState(StatesGroup):
    waiting_query = State()


def normalize_query(text: str) -> str:
    """Lotin / Kirill tolerantligi uchun oddiy normalizatsiya."""
    if not text:
        return ""
    t = text.strip().lower()
    # Eng keng tarqalgan kirill → lotin (qidiruvni kuchaytirish uchun)
    cyr_to_lat = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
        "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k",
        "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts",
        "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "",
        "э": "e", "ю": "yu", "я": "ya",
        "ў": "o'", "ғ": "g'", "қ": "q", "ҳ": "h",
    })
    return t.translate(cyr_to_lat)


def _result_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔍 Batafsil", callback_data=f"prod_{product_id}"),
    ]])


@router.message(F.text == "🔍 Qidiruv")
async def start_search(message: Message, state: FSMContext):
    await state.set_state(SearchState.waiting_query)
    await message.answer(
        "🔍 <b>Qidiruv</b>\n\n"
        "Mahsulot nomini, jamoa nomini, brendi yoki modelni yozing.\n\n"
        "<i>Masalan: argentina, real, messi, nike, butsi</i>",
        parse_mode="HTML"
    )


@router.message(SearchState.waiting_query)
async def perform_search(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw or len(raw) < 2:
        await message.answer("⚠️ Kamida 2 ta belgi kiriting.")
        return

    # Foydalanuvchi qidiruvni tugatadi — state ni tozalaymiz
    await state.clear()

    norm = normalize_query(raw)

    try:
        async with AsyncSessionLocal() as session:
            # Asosiy qidiruv (raw + normalized variantlar bilan)
            results = await search_products(session, raw, limit=MAX_RESULTS_PER_PAGE * 2)
            if not results and norm and norm != raw.lower():
                results = await search_products(session, norm, limit=MAX_RESULTS_PER_PAGE * 2)

            # Stocklarni session ichida olib qo'yamiz (lazy load qilmaslik uchun)
            cards = []
            for p in results[:MAX_RESULTS_PER_PAGE]:
                final_price = p.price * (1 - p.discount_percent / 100) \
                    if p.discount_percent > 0 else p.price
                total_qty = sum(s.quantity for s in p.stocks) if p.stocks else 0
                cards.append({
                    "id": p.id,
                    "name": p.name,
                    "team": p.team,
                    "team_type": p.team_type,
                    "price": p.price,
                    "final_price": final_price,
                    "discount_percent": p.discount_percent,
                    "photo_url": p.photo_url,
                    "in_stock": p.in_stock,
                    "total_qty": total_qty,
                })
    except Exception as e:
        logger.exception("Search error: %s", e)
        await message.answer("⚠️ Qidiruvda xato yuz berdi. Qaytadan urinib ko'ring.")
        return

    if not cards:
        await message.answer(
            f"😕 <b>Mahsulot topilmadi</b>\n\n"
            f"So'rov: <i>{raw}</i>\n\n"
            f"Boshqa kalit so'z bilan urinib ko'ring yoki 🛍 Katalogni ochib tanlang.",
            parse_mode="HTML"
        )
        return

    await message.answer(
        f"🔍 <b>Topildi: {len(cards)} ta mahsulot</b>\n<i>So'rov: {raw}</i>",
        parse_mode="HTML"
    )

    for c in cards:
        team_line = ""
        if c["team"]:
            label = "🌍" if c["team_type"] == "national" else "🏟"
            team_line = f"\n{label} {c['team']}"

        if c["discount_percent"] and c["discount_percent"] > 0:
            price_str = (
                f"<s>{int(c['price']):,}</s> → "
                f"<b>{int(c['final_price']):,} so'm</b> "
                f"🔥 -{int(c['discount_percent'])}%"
            )
        else:
            price_str = f"<b>{int(c['price']):,} so'm</b>"

        if c["total_qty"] == 0:
            stock_line = "\n⛔ <b>Sotuvda: Qolmadi</b>"
        else:
            stock_line = f"\n📦 Mavjud: {c['total_qty']} dona"

        text = (
            f"<b>{c['name']}</b>"
            f"{team_line}\n\n"
            f"💰 {price_str}"
            f"{stock_line}"
        )

        try:
            if c["photo_url"]:
                await message.answer_photo(
                    photo=c["photo_url"],
                    caption=text,
                    parse_mode="HTML",
                    reply_markup=_result_kb(c["id"]),
                )
            else:
                await message.answer(
                    text, parse_mode="HTML", reply_markup=_result_kb(c["id"])
                )
        except Exception as e:
            logger.warning("Search result render failed for product %s: %s", c["id"], e)
            await message.answer(
                text, parse_mode="HTML", reply_markup=_result_kb(c["id"])
            )
