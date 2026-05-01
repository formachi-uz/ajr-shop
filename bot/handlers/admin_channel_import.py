import re
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.admin_kb import admin_menu_kb
from bot.middlewares.admin_check import is_admin
from database.crud import create_product, get_product_by_id, set_product_stock, update_product
from database.db import AsyncSessionLocal
from database.models import CustomizationStatus

router = Router()

TEAM_ALIASES = {
    "real madrid": "Real Madrid",
    "real": "Real Madrid",
    "madrid": "Real Madrid",
    "barcelona": "Barcelona",
    "barselona": "Barcelona",
    "barca": "Barcelona",
    "barsa": "Barcelona",
    "manchester city": "Manchester City",
    "man city": "Manchester City",
    "city": "Manchester City",
    "chelsea": "Chelsea",
    "chelsi": "Chelsea",
    "liverpool": "Liverpool",
    "bayern": "Bayern Munich",
    "bavariya": "Bayern Munich",
    "bayern munich": "Bayern Munich",
    "psg": "PSG",
    "paris": "PSG",
    "arsenal": "Arsenal",
    "tottenham": "Tottenham",
    "manchester united": "Manchester United",
    "man united": "Manchester United",
    "mu": "Manchester United",
    "juventus": "Juventus",
    "milan": "AC Milan",
    "inter": "Inter Milan",
    "roma": "Roma",
    "napoli": "Napoli",
    "argentina": "Argentina",
    "brazil": "Brazil",
    "brasil": "Brazil",
    "portugal": "Portugal",
    "uzbekistan": "Uzbekistan",
    "o'zbekiston": "Uzbekistan",
    "ozbekiston": "Uzbekistan",
}

BRAND_ALIASES = {
    "nike": "Nike",
    "adidas": "Adidas",
    "puma": "Puma",
    "mizuno": "Mizuno",
    "new balance": "New Balance",
    "nb": "New Balance",
}

STOP_WORDS = {"tayyor", "done", "stop", "to'xta", "toxta", "bekor", "/cancel"}

DEFAULT_STOCK = {
    1: {"S": 1, "M": 1, "L": 1, "XL": 1, "XXL": 1},
    2: {"S": 1, "M": 1, "L": 1, "XL": 1, "XXL": 1},
    3: {"39": 1, "40": 1, "41": 1, "42": 1, "43": 1, "44": 1},
}

CATEGORY_LABELS = {
    1: "Formalar",
    2: "Retro formalar",
    3: "Butsiylar",
}

RECENT_MEDIA_IMPORTS: dict[tuple[int, str], int] = {}


class ChannelImportState(StatesGroup):
    waiting_posts = State()


def install_channel_import_hooks():
    """Add the import button to the existing products section without rewriting that module."""
    try:
        from bot.handlers import admin_menu_patch

        if getattr(admin_menu_patch, "_channel_import_hooked", False):
            return

        original_products_section_kb = admin_menu_patch.products_section_kb

        def products_section_with_import() -> InlineKeyboardMarkup:
            markup = original_products_section_kb()
            rows = list(markup.inline_keyboard)
            rows.insert(1, [InlineKeyboardButton(text="📥 Kanaldan import", callback_data="channel_import_start")])
            return InlineKeyboardMarkup(inline_keyboard=rows)

        admin_menu_patch.products_section_kb = products_section_with_import
        admin_menu_patch._channel_import_hooked = True
    except Exception as exc:
        print(f"Channel import hook skipped: {exc}")


def importer_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Importni tugatish", callback_data="channel_import_stop")],
    ])


@router.message(F.text.in_({"📥 Kanaldan import", "/importkanal", "/import_channel"}))
async def start_channel_import_from_text(message: Message, state: FSMContext):
    await start_channel_import(message, state, actor_id=message.from_user.id if message.from_user else None)


@router.callback_query(F.data == "channel_import_start")
async def start_channel_import_from_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await start_channel_import(callback.message, state, actor_id=callback.from_user.id)
    await callback.answer("Import rejimi yoqildi")


async def start_channel_import(message: Message, state: FSMContext, actor_id: int | None = None):
    user_id = actor_id or (message.from_user.id if message.from_user else message.chat.id)
    if not is_admin(user_id):
        await message.answer("⛔ Ruxsat yo'q")
        return
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


@router.callback_query(F.data == "channel_import_stop")
async def stop_channel_import_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    await state.clear()
    await callback.message.answer("✅ Kanaldan import tugatildi.", reply_markup=admin_menu_kb())
    await callback.answer("Tugatildi")


@router.message(ChannelImportState.waiting_posts)
async def import_forwarded_post(message: Message, state: FSMContext):
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

    if not text and not photo_id:
        await message.answer("⚠️ Mahsulot posti caption yoki rasm bilan bo'lishi kerak.", reply_markup=importer_kb())
        return

    parsed = parse_product_post(text)
    if photo_id:
        parsed["photo_url"] = photo_id
    parsed["description"] = text or parsed["name"]

    try:
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


def parse_product_post(raw_text: str) -> dict:
    text = raw_text or ""
    lower = text.lower()
    category_id = detect_category(lower)
    price = extract_price(text)
    name = extract_name(text)
    stocks = extract_stocks(text, category_id)
    team = detect_alias(lower, TEAM_ALIASES) if category_id in {1, 2} else None
    brand = detect_alias(lower, BRAND_ALIASES) if category_id == 3 else detect_alias(lower, BRAND_ALIASES)
    season = extract_season(text)
    kit_type = extract_kit_type(lower) if category_id in {1, 2} else None

    return {
        "category_id": category_id,
        "name": name,
        "description": text,
        "price": price,
        "discount_percent": 0,
        "photo_url": None,
        "team": team,
        "brand": brand,
        "season": season,
        "kit_type": kit_type,
        "league": detect_league_or_group(lower, team),
        "model": extract_model(text, brand) if category_id == 3 else None,
        "tags": build_tags(text, team, brand, season, kit_type),
        "customization_status": (
            CustomizationStatus.AVAILABLE_PAID.value if category_id == 1 else CustomizationStatus.NOT_AVAILABLE.value
        ),
        "customization_price": 50000,
        "is_active": True,
        "in_stock": True,
        "stocks": stocks,
    }


def detect_category(lower: str) -> int:
    if any(word in lower for word in ["retro", "classic", "klassik", "vintage", "old school"]):
        return 2
    if any(word in lower for word in ["butsi", "butsa", "boots", "futsal", "sarakan", "sorokon", "poyabzal"]):
        return 3
    if any(word in lower for word in BRAND_ALIASES) and not any(word in lower for word in ["forma", "futbolka", "jersey"]):
        return 3
    return 1


def detect_alias(lower: str, aliases: dict[str, str]) -> str | None:
    for key, value in aliases.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", lower):
            return value
    return None


def extract_price(text: str) -> float:
    candidates = []
    for match in re.finditer(r"(\d[\d\s\.,]{2,})\s*(?:so['`‘’]?m|som|sum|сум|uzs)", text, flags=re.I):
        value = normalize_money(match.group(1))
        if value:
            candidates.append(value)
    for match in re.finditer(r"(\d{2,4})\s*(?:ming|минг|k)\b", text, flags=re.I):
        candidates.append(float(match.group(1)) * 1000)
    if not candidates:
        for match in re.finditer(r"\b\d[\d\s\.,]{4,}\b", text):
            value = normalize_money(match.group(0))
            if value and value >= 10000:
                candidates.append(value)
    if not candidates:
        raise ValueError("Narx topilmadi. Captionda masalan: Narx: 99 000 so'm deb yozing.")
    return float(max(candidates))


def normalize_money(value: str) -> float | None:
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return None
    return float(digits)


def extract_name(text: str) -> str:
    for line in [item.strip() for item in text.splitlines() if item.strip()]:
        clean = re.sub(r"[#@][\w_]+", "", line).strip(" -–—:|•✅🔥💰🏷📦👕👟")
        if not clean:
            continue
        lower = clean.lower()
        if any(word in lower for word in ["narx", "price", "sum", "so'm", "som", "razmer", "size", "mavjud", "dostavka", "tel"]):
            continue
        return clean[:250]
    return "Import mahsulot"


def extract_stocks(text: str, category_id: int) -> dict[str, int]:
    normalized = normalize_stock_text(text)
    parsed: dict[str, int] = {}
    for size, qty_text in re.findall(r"\b([A-Z0-9]{1,4})\s*[:=\-]\s*(\d+)\b", normalized):
        label = normalize_size_label(size)
        if label in valid_sizes(category_id):
            qty = int(qty_text)
            if qty > 0:
                parsed[label] = qty
    if parsed:
        return parsed

    found = {}
    for size in valid_sizes(category_id):
        if re.search(rf"(?<![A-Z0-9]){re.escape(size)}(?![A-Z0-9])", normalized):
            found[size] = 1
    return found or dict(DEFAULT_STOCK.get(category_id, {}))


def normalize_stock_text(value: str) -> str:
    return (value or "").upper().replace("：", ":").replace(",", " ").replace(";", " ").replace("/", " ")


def normalize_size_label(value: str) -> str:
    label = value.strip().upper()
    if label in {"2XL", "XXL", "XLL"}:
        return "XXL"
    return label


def valid_sizes(category_id: int) -> set[str]:
    if category_id == 3:
        return {"36", "37", "38", "39", "40", "41", "42", "43", "44", "45"}
    return {"XS", "S", "M", "L", "XL", "XXL", "3XL"}


def extract_season(text: str) -> str | None:
    match = re.search(r"\b(20\d{2}\s*/\s*\d{2}|\d{2}\s*/\s*\d{2}|20\d{2})\b", text)
    return match.group(1).replace(" ", "") if match else None


def extract_kit_type(lower: str) -> str | None:
    if any(word in lower for word in ["safar", "away", "mehmon"]):
        return "away"
    if any(word in lower for word in ["third", "uchinchi", "3-forma"]):
        return "third"
    if any(word in lower for word in ["training", "mashg'ulot", "trenirovka"]):
        return "training"
    if any(word in lower for word in ["uy", "home", "asosiy"]):
        return "home"
    return None


def detect_league_or_group(lower: str, team: str | None) -> str | None:
    if team in {"Argentina", "Brazil", "Portugal", "Uzbekistan"} or "terma" in lower or "milliy" in lower:
        return "National Teams"
    if any(word in lower for word in ["laliga", "la liga"]):
        return "LaLiga"
    if any(word in lower for word in ["apl", "premier league"]):
        return "Premier League"
    if any(word in lower for word in ["serie a", "seria a"]):
        return "Serie A"
    if "bundesliga" in lower:
        return "Bundesliga"
    if any(word in lower for word in ["ligue 1", "fransiya"]):
        return "Ligue 1"
    return None


def extract_model(text: str, brand: str | None) -> str | None:
    name = extract_name(text)
    if brand and name.lower().startswith(brand.lower()):
        return name[len(brand):].strip(" -–—") or None
    return name


def build_tags(text: str, team: str | None, brand: str | None, season: str | None, kit_type: str | None) -> str:
    tags = set(re.findall(r"#([\w_]+)", text or ""))
    for value in [team, brand, season, kit_type]:
        if value:
            tags.add(str(value).replace(" ", "_"))
    return ",".join(sorted(tags)) if tags else ""


async def save_imported_product(data: dict) -> int:
    stocks = data.pop("stocks", {})
    async with AsyncSessionLocal() as session:
        product = await create_product(session, **data)
        for size, qty in stocks.items():
            await set_product_stock(session, product.id, size, qty)
        return product.id


async def append_gallery_photo(product_id: int, photo_id: str):
    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            return
        current = [item.strip() for item in (product.gallery or "").split(",") if item.strip()]
        if photo_id not in current:
            current.append(photo_id)
            await update_product(session, product_id, gallery=",".join(current))


def format_import_result(product_id: int, data: dict) -> str:
    stocks = data.get("stocks", {})
    stock_text = " ".join(f"{size}:{qty}" for size, qty in stocks.items()) or "—"
    meta = []
    if data.get("team"):
        meta.append(f"Jamoa: <b>{escape(data['team'])}</b>")
    if data.get("brand"):
        meta.append(f"Brend: <b>{escape(data['brand'])}</b>")
    if data.get("season"):
        meta.append(f"Season: <b>{escape(data['season'])}</b>")
    if data.get("kit_type"):
        meta.append(f"Kit: <b>{escape(data['kit_type'])}</b>")
    meta_text = "\n".join(meta)
    if meta_text:
        meta_text += "\n"
    return (
        f"✅ <b>Import qilindi: ID {product_id}</b>\n\n"
        f"📦 {escape(data['name'])}\n"
        f"🏷 {CATEGORY_LABELS.get(data['category_id'], data['category_id'])}\n"
        f"💰 {int(data['price']):,} so'm\n"
        f"{meta_text}"
        f"📏 {escape(stock_text)}"
    )
