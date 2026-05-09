import os
from html import escape

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select, or_

from database.db import AsyncSessionLocal
from database.crud import get_all_categories, get_category_by_id
from database.models import Product, ProductStock

router = Router()

MAIN_CATEGORY_BY_ID = {
    1: "FORMLAR",
    2: "RETRO_FORMALAR",
    3: "BUTSIYLAR",
}

FORMA_CATEGORY_IDS = {1, 2}
BOOT_CATEGORY_ID = 3

LEAGUE_GROUPS = [
    {
        "code": "apl",
        "title": "🏴 APL",
        "desc": "Angliya klublari",
        "teams": ["man_city", "man_utd", "chelsea", "liverpool", "arsenal", "tottenham"],
    },
    {
        "code": "laliga",
        "title": "🇪🇸 LaLiga",
        "desc": "Ispaniya klublari",
        "teams": ["real_madrid", "barcelona", "atletico", "sevilla"],
    },
    {
        "code": "seriea",
        "title": "🇮🇹 Serie A",
        "desc": "Italiya klublari",
        "teams": ["milan", "inter", "juventus", "roma", "napoli"],
    },
    {
        "code": "bundesliga",
        "title": "🇩🇪 Bundesliga",
        "desc": "Germaniya klublari",
        "teams": ["bayern", "dortmund", "leverkusen"],
    },
    {
        "code": "ligue1",
        "title": "🇫🇷 Ligue 1",
        "desc": "Fransiya klublari",
        "teams": ["psg", "marseille", "monaco"],
    },
    {
        "code": "national",
        "title": "🌍 Terma jamoalar",
        "desc": "Davlat formalari",
        "teams": ["uzbekistan", "argentina", "brazil", "portugal", "france", "germany", "spain", "england", "italy", "netherlands"],
    },
    {
        "code": "other",
        "title": "⭐ Boshqa klublar",
        "desc": "Qolgan jamoalar",
        "teams": ["other"],
    },
]

TEAM_META = {
    "real_madrid": {"name": "Real Madrid", "emoji": "⚪", "aliases": ["real madrid", "real", "madrid", "реал"]},
    "barcelona": {"name": "Barcelona", "emoji": "🔵🔴", "aliases": ["barcelona", "barselona", "barca", "barsa", "барселона"]},
    "atletico": {"name": "Atletico Madrid", "emoji": "🔴⚪", "aliases": ["atletico", "atletiko", "atlético"]},
    "sevilla": {"name": "Sevilla", "emoji": "🔴", "aliases": ["sevilla", "sevilya"]},
    "man_city": {"name": "Manchester City", "emoji": "🔵", "aliases": ["manchester city", "man city", "city", "mancity"]},
    "man_utd": {"name": "Manchester United", "emoji": "🔴", "aliases": ["manchester united", "man united", "man utd", "united"]},
    "chelsea": {"name": "Chelsea", "emoji": "🔵", "aliases": ["chelsea", "chelsi", "челси"]},
    "liverpool": {"name": "Liverpool", "emoji": "🔴", "aliases": ["liverpool", "liverpul", "ливерпуль"]},
    "arsenal": {"name": "Arsenal", "emoji": "🔴", "aliases": ["arsenal", "арсенал"]},
    "tottenham": {"name": "Tottenham", "emoji": "⚪", "aliases": ["tottenham", "spurs", "totenhem"]},
    "milan": {"name": "AC Milan", "emoji": "🔴⚫", "aliases": ["ac milan", "milan", "милан"]},
    "inter": {"name": "Inter Milan", "emoji": "🔵⚫", "aliases": ["inter", "inter milan", "интер"]},
    "juventus": {"name": "Juventus", "emoji": "⚫⚪", "aliases": ["juventus", "yuventus", "ювентус"]},
    "roma": {"name": "Roma", "emoji": "🟡🔴", "aliases": ["roma", "rome", "рим"]},
    "napoli": {"name": "Napoli", "emoji": "🔵", "aliases": ["napoli", "наполи"]},
    "bayern": {"name": "Bayern Munich", "emoji": "🔴", "aliases": ["bayern", "bavariya", "bayern munich", "бавария"]},
    "dortmund": {"name": "Borussia Dortmund", "emoji": "🟡⚫", "aliases": ["dortmund", "borussia", "borussiya"]},
    "leverkusen": {"name": "Bayer Leverkusen", "emoji": "🔴⚫", "aliases": ["leverkusen", "bayer leverkusen"]},
    "psg": {"name": "PSG", "emoji": "🔵🔴", "aliases": ["psg", "paris", "psj", "псж"]},
    "marseille": {"name": "Marseille", "emoji": "🔵", "aliases": ["marseille", "marsel"]},
    "monaco": {"name": "Monaco", "emoji": "🔴⚪", "aliases": ["monaco", "monako"]},
    "uzbekistan": {"name": "Uzbekistan", "emoji": "🇺🇿", "aliases": ["uzbekistan", "o'zbekiston", "ozbekiston", "uzb", "уфа", "ufa"]},
    "argentina": {"name": "Argentina", "emoji": "🇦🇷", "aliases": ["argentina", "argentina"]},
    "brazil": {"name": "Brazil", "emoji": "🇧🇷", "aliases": ["brazil", "brasil", "braziliya"]},
    "portugal": {"name": "Portugal", "emoji": "🇵🇹", "aliases": ["portugal", "portugaliya"]},
    "france": {"name": "France", "emoji": "🇫🇷", "aliases": ["france", "fransiya"]},
    "germany": {"name": "Germany", "emoji": "🇩🇪", "aliases": ["germany", "germaniya", "deutschland"]},
    "spain": {"name": "Spain", "emoji": "🇪🇸", "aliases": ["spain", "ispaniya"]},
    "england": {"name": "England", "emoji": "🏴", "aliases": ["england", "angliya"]},
    "italy": {"name": "Italy", "emoji": "🇮🇹", "aliases": ["italy", "italiya"]},
    "netherlands": {"name": "Netherlands", "emoji": "🇳🇱", "aliases": ["netherlands", "holland", "niderlandiya"]},
    "other": {"name": "Boshqa jamoalar", "emoji": "⭐", "aliases": []},
}

BRAND_META = {
    "nike": {"name": "Nike", "emoji": "✅", "aliases": ["nike", "nayk"]},
    "adidas": {"name": "Adidas", "emoji": "🔺", "aliases": ["adidas", "adidos"]},
    "puma": {"name": "Puma", "emoji": "🐆", "aliases": ["puma"]},
    "mizuno": {"name": "Mizuno", "emoji": "🔷", "aliases": ["mizuno"]},
    "new_balance": {"name": "New Balance", "emoji": "🆕", "aliases": ["new balance", "nb"]},
    "other": {"name": "Boshqa brendlar", "emoji": "⭐", "aliases": []},
}

KIT_LABELS = {
    "home": "Uy",
    "away": "Safar",
    "third": "Third",
    "training": "Mashg'ulot",
    "goalkeeper": "Darvozabon",
}


def _webapp_url() -> str | None:
    for key in ("WEB_APP_URL", "WEBAPP_URL", "WEBAPP_BASE_URL", "FRONTEND_URL"):
        value = os.getenv(key)
        if value:
            return value.rstrip("/")
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}".rstrip("/")
    return None


def _catalog_url(category_id: int, team_slug: str | None = None, brand_code: str | None = None) -> str | None:
    base = _webapp_url()
    if not base:
        return None
    main_category = MAIN_CATEGORY_BY_ID.get(category_id)
    params = []
    if main_category:
        params.append(f"mainCategory={main_category}")
    if team_slug and team_slug != "other":
        params.append("team=" + TEAM_META[team_slug]["name"].replace(" ", "%20"))
    if brand_code and brand_code != "other":
        params.append("brand=" + BRAND_META[brand_code]["name"].replace(" ", "%20"))
    return f"{base}/catalog" + ("?" + "&".join(params) if params else "")


def _text_for_product(product: Product) -> str:
    values = [
        product.name,
        product.description,
        product.team,
        product.league,
        product.brand,
        product.model,
        product.tags,
        product.main_category,
        product.product_type,
    ]
    return " ".join(str(v or "") for v in values).lower()


def _detect_team_slug(product: Product) -> str:
    direct = (product.team or "").strip().lower()
    haystack = _text_for_product(product)
    for slug, meta in TEAM_META.items():
        if slug == "other":
            continue
        aliases = [meta["name"].lower(), *meta["aliases"]]
        if direct and any(alias == direct for alias in aliases):
            return slug
        if any(alias and alias in haystack for alias in aliases):
            return slug
    return "other"


def _detect_league_code(product: Product) -> str:
    league = (product.league or "").lower()
    haystack = _text_for_product(product)
    for group in LEAGUE_GROUPS:
        code = group["code"]
        if code == "other":
            continue
        if code in league or group["title"].lower().replace("🏴 ", "").replace("🇪🇸 ", "").replace("🇮🇹 ", "").replace("🇩🇪 ", "").replace("🇫🇷 ", "").replace("🌍 ", "") in league:
            return code
        slug = _detect_team_slug(product)
        if slug in group["teams"]:
            return code
    if any(word in haystack for word in ["national", "terma", "davlat", "milliy"]):
        return "national"
    return "other"


def _detect_brand_code(product: Product) -> str:
    direct = (product.brand or "").strip().lower()
    haystack = _text_for_product(product)
    for code, meta in BRAND_META.items():
        if code == "other":
            continue
        aliases = [meta["name"].lower(), *meta["aliases"]]
        if direct and any(alias == direct for alias in aliases):
            return code
        if any(alias and alias in haystack for alias in aliases):
            return code
    return "other"


def _format_price_value(product: Product) -> str:
    final_price = product.price * (1 - product.discount_percent / 100) if product.discount_percent else product.price
    return f"{int(final_price):,} so'm"


def _short_product_label(product: Product) -> str:
    season = (product.season or "").strip()
    kit_type = KIT_LABELS.get((product.kit_type or "").lower(), "")
    name = product.name
    if len(name) > 28:
        name = name[:25].rstrip() + "..."
    details = " ".join(part for part in [kit_type, season] if part).strip()
    if details:
        return f"{details} — {_format_price_value(product)}"
    return f"{name} — {_format_price_value(product)}"


def categories_kb(categories) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        if cat.id == 4:
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{cat.emoji} {cat.name}",
                callback_data=f"cat_{cat.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def category_nav_kb(category_id: int, products_with_stocks: list) -> InlineKeyboardMarkup:
    if category_id == BOOT_CATEGORY_ID:
        return brand_groups_kb(category_id, products_with_stocks)
    if category_id in FORMA_CATEGORY_IDS:
        return league_groups_kb(category_id, products_with_stocks)
    return products_kb(products_with_stocks, category_id)


def league_groups_kb(category_id: int, products_with_stocks: list) -> InlineKeyboardMarkup:
    rows = []
    products = [product for product, _ in products_with_stocks]
    for group in LEAGUE_GROUPS:
        count = sum(1 for product in products if _detect_league_code(product) == group["code"])
        if count:
            rows.append([
                InlineKeyboardButton(
                    text=f"{group['title']} ({count})",
                    callback_data=f"league_{category_id}_{group['code']}",
                )
            ])
    rows.append([InlineKeyboardButton(text="⬅️ Katalogga qaytish", callback_data="catalog")])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def team_groups_kb(category_id: int, league_code: str, products_with_stocks: list) -> InlineKeyboardMarkup:
    rows = []
    counts = {}
    for product, _ in products_with_stocks:
        if _detect_league_code(product) != league_code:
            continue
        slug = _detect_team_slug(product)
        counts[slug] = counts.get(slug, 0) + 1

    group = next((item for item in LEAGUE_GROUPS if item["code"] == league_code), None)
    preferred = group["teams"] if group else []
    ordered_slugs = [slug for slug in preferred if counts.get(slug)]
    ordered_slugs += sorted([slug for slug in counts if slug not in ordered_slugs and slug != "other"], key=lambda s: TEAM_META.get(s, {}).get("name", s))
    if counts.get("other") and "other" not in ordered_slugs:
        ordered_slugs.append("other")

    row = []
    for slug in ordered_slugs:
        meta = TEAM_META.get(slug, TEAM_META["other"])
        row.append(InlineKeyboardButton(
            text=f"{meta['emoji']} {meta['name']} ({counts[slug]})",
            callback_data=f"team_{category_id}_{league_code}_{slug}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(text="⬅️ Liga/guruhlar", callback_data=f"cat_{category_id}")])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def brand_groups_kb(category_id: int, products_with_stocks: list) -> InlineKeyboardMarkup:
    rows = []
    counts = {}
    for product, _ in products_with_stocks:
        code = _detect_brand_code(product)
        counts[code] = counts.get(code, 0) + 1
    ordered_codes = [code for code in BRAND_META if counts.get(code)]
    row = []
    for code in ordered_codes:
        meta = BRAND_META[code]
        row.append(InlineKeyboardButton(
            text=f"{meta['emoji']} {meta['name']} ({counts[code]})",
            callback_data=f"brand_{category_id}_{code}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Katalogga qaytish", callback_data="catalog")])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(products_with_stocks: list, category_id: int, back_callback: str = "catalog", web_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    for product, stocks in products_with_stocks[:12]:
        total_qty = sum(stock.quantity for stock in stocks)
        stock_icon = " ❌" if total_qty == 0 and stocks else " ⚠️" if 0 < total_qty <= 3 else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{_short_product_label(product)}{stock_icon}",
                callback_data=f"prod_{product.id}",
            )
        ])
    if web_url:
        rows.append([InlineKeyboardButton(text="🌐 Hammasini saytda ko'rish", url=web_url)])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def empty_category_kb(back_callback: str = "catalog") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data=back_callback)],
        [InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")],
    ])


async def load_products_with_stocks(session, category_id: int):
    category_filter = Product.category_id == category_id
    main_category = MAIN_CATEGORY_BY_ID.get(category_id)
    if main_category:
        category_filter = or_(Product.category_id == category_id, Product.main_category == main_category)

    result = await session.execute(
        select(Product)
        .where(category_filter, Product.is_active == True)
        .order_by(Product.id.desc())
    )
    products = list(result.scalars().all())

    items = []
    for product in products:
        stocks_result = await session.execute(
            select(ProductStock)
            .where(ProductStock.product_id == product.id)
            .order_by(ProductStock.sort_order)
        )
        items.append((product, list(stocks_result.scalars().all())))
    return items


async def _show_catalog_message(target):
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)

    text = (
        "🛍 <b>FORMACHI katalog</b>\n\n"
        "Kerakli bo'limni tanlang. Formalarda keyingi qadamda liga va jamoa bo'yicha ajratamiz."
    )
    await target.answer(text, parse_mode="HTML", reply_markup=categories_kb(categories))


@router.message(F.text == "🛍 Katalog")
async def catalog_message(message: Message):
    await _show_catalog_message(message)


@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)

    text = (
        "🛍 <b>FORMACHI katalog</b>\n\n"
        "Kerakli bo'limni tanlang."
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=categories_kb(categories))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=categories_kb(categories))
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def category_callback(callback: CallbackQuery):
    await callback.answer()
    try:
        category_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.message.answer("⚠️ Kategoriya xatosi. Katalogni qaytadan oching.")
        return

    async with AsyncSessionLocal() as session:
        category = await get_category_by_id(session, category_id)
        if not category:
            await callback.message.answer("⚠️ Kategoriya topilmadi. Katalogni qaytadan oching.")
            return
        products_with_stocks = await load_products_with_stocks(session, category_id)

    if not products_with_stocks:
        empty_text = (
            f"{category.emoji} <b>{escape(category.name)}</b>\n\n"
            "Bu kategoriyada hozircha mahsulot ko'rinmayapti.\n"
            "Admin paneldan mahsulot qo'shganda aynan shu kategoriyani tanlang."
        )
        try:
            await callback.message.edit_text(empty_text, parse_mode="HTML", reply_markup=empty_category_kb())
        except Exception:
            await callback.message.answer(empty_text, parse_mode="HTML", reply_markup=empty_category_kb())
        return

    if category_id in FORMA_CATEGORY_IDS:
        text = (
            f"{category.emoji} <b>{escape(category.name)}</b>\n\n"
            f"📦 {len(products_with_stocks)} ta mahsulot bor.\n"
            "Avval liga yoki guruhni tanlang, keyin jamoa bo'yicha formalaringiz chiqadi."
        )
    elif category_id == BOOT_CATEGORY_ID:
        text = (
            f"{category.emoji} <b>{escape(category.name)}</b>\n\n"
            f"📦 {len(products_with_stocks)} ta mahsulot bor.\n"
            "Brendni tanlang — keyin model va razmerlarni ko'rasiz."
        )
    else:
        text = f"{category.emoji} <b>{escape(category.name)}</b>\n\n📦 {len(products_with_stocks)} ta mahsulot\n\nTanlang 👇"

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=category_nav_kb(category_id, products_with_stocks),
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=category_nav_kb(category_id, products_with_stocks),
        )


@router.callback_query(F.data.startswith("league_"))
async def league_callback(callback: CallbackQuery):
    await callback.answer()
    try:
        _, category_id_text, league_code = callback.data.split("_", 2)
        category_id = int(category_id_text)
    except (ValueError, IndexError):
        await callback.message.answer("⚠️ Liga tanlashda xatolik. Katalogni qaytadan oching.")
        return

    async with AsyncSessionLocal() as session:
        category = await get_category_by_id(session, category_id)
        products_with_stocks = await load_products_with_stocks(session, category_id)

    products_in_group = [(p, s) for p, s in products_with_stocks if _detect_league_code(p) == league_code]
    group = next((item for item in LEAGUE_GROUPS if item["code"] == league_code), {"title": "Jamoalar", "desc": ""})
    text = (
        f"{group['title']} <b>{escape(category.name if category else 'Formalar')}</b>\n\n"
        f"📦 {len(products_in_group)} ta mahsulot\n"
        "Jamoani tanlang — shu jamoaga tegishli barcha formalari chiqadi."
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=team_groups_kb(category_id, league_code, products_with_stocks))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=team_groups_kb(category_id, league_code, products_with_stocks))


@router.callback_query(F.data.startswith("team_"))
async def team_callback(callback: CallbackQuery):
    await callback.answer()
    try:
        _, category_id_text, league_code, team_slug = callback.data.split("_", 3)
        category_id = int(category_id_text)
    except (ValueError, IndexError):
        await callback.message.answer("⚠️ Jamoa tanlashda xatolik. Katalogni qaytadan oching.")
        return

    async with AsyncSessionLocal() as session:
        products_with_stocks = await load_products_with_stocks(session, category_id)

    team_products = [
        (p, s) for p, s in products_with_stocks
        if _detect_league_code(p) == league_code and _detect_team_slug(p) == team_slug
    ]
    meta = TEAM_META.get(team_slug, TEAM_META["other"])
    text = (
        f"{meta['emoji']} <b>{escape(meta['name'])} formalari</b>\n\n"
        f"📦 {len(team_products)} ta mahsulot topildi.\n"
        "Pastdan modelni tanlang. Rasmlar faqat mahsulotga kirganda chiqadi."
    )
    kb = products_kb(
        team_products,
        category_id,
        back_callback=f"league_{category_id}_{league_code}",
        web_url=_catalog_url(category_id, team_slug=team_slug),
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("brand_"))
async def brand_callback(callback: CallbackQuery):
    await callback.answer()
    try:
        _, category_id_text, brand_code = callback.data.split("_", 2)
        category_id = int(category_id_text)
    except (ValueError, IndexError):
        await callback.message.answer("⚠️ Brend tanlashda xatolik. Katalogni qaytadan oching.")
        return

    async with AsyncSessionLocal() as session:
        products_with_stocks = await load_products_with_stocks(session, category_id)

    brand_products = [(p, s) for p, s in products_with_stocks if _detect_brand_code(p) == brand_code]
    meta = BRAND_META.get(brand_code, BRAND_META["other"])
    text = (
        f"{meta['emoji']} <b>{escape(meta['name'])}</b>\n\n"
        f"📦 {len(brand_products)} ta mahsulot topildi.\n"
        "Modelni tanlang — keyin rasm, narx va razmerlar chiqadi."
    )
    kb = products_kb(
        brand_products,
        category_id,
        back_callback=f"cat_{category_id}",
        web_url=_catalog_url(category_id, brand_code=brand_code),
    )
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
