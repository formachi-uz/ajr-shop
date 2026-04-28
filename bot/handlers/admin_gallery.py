import asyncio
import re
import traceback
from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.handlers import admin
from bot.keyboards.admin_kb import admin_menu_kb
from database.db import AsyncSessionLocal
from database.crud import create_product, set_product_stock
from database.models import CustomizationStatus

router = Router()

ADMIN_MENU_TEXTS = {
    "⚙️ Admin Panel",
    "✅ Tasdiqlangan buyurtmalar",
    "📋 Yangi buyurtmalar",
    "➕ Mahsulot qo'shish",
    "📦 Mahsulotlar",
    "👥 Adminlar",
    "🌐 Web Panel",
    "🏠 Asosiy menyu",
    "🛍 Katalog",
    "🛒 Savatim",
    "📦 Buyurtmalarim",
    "📞 Aloqa",
}

MAIN_CATEGORY_BY_ID = {
    1: "FORMLAR",
    2: "RETRO_FORMALAR",
    3: "BUTSIYLAR",
}

PRODUCT_TYPE_BY_ID = {
    1: "jersey",
    2: "retro_jersey",
    3: "boots",
}

CUSTOMIZATION_BY_ID = {
    1: CustomizationStatus.AVAILABLE_PAID,
    2: CustomizationStatus.NOT_AVAILABLE,
    3: CustomizationStatus.NOT_AVAILABLE,
}

CUSTOMIZATION_ALIASES = {
    "paid": CustomizationStatus.AVAILABLE_PAID,
    "available_paid": CustomizationStatus.AVAILABLE_PAID,
    "pullik": CustomizationStatus.AVAILABLE_PAID,
    "ha": CustomizationStatus.AVAILABLE_PAID,
    "bonus": CustomizationStatus.INCLUDED_BONUS,
    "included_bonus": CustomizationStatus.INCLUDED_BONUS,
    "bepul": CustomizationStatus.INCLUDED_BONUS,
    "no": CustomizationStatus.NOT_AVAILABLE,
    "none": CustomizationStatus.NOT_AVAILABLE,
    "not_available": CustomizationStatus.NOT_AVAILABLE,
    "yoq": CustomizationStatus.NOT_AVAILABLE,
    "yo'q": CustomizationStatus.NOT_AVAILABLE,
}


class GalleryState(StatesGroup):
    gallery = State()
    stocks = State()


@router.message(admin.AddProductState.photo)
async def collect_main_product_photo(message: Message, state: FSMContext):
    photo_url = None
    if message.photo:
        photo_url = message.photo[-1].file_id
    elif message.text and message.text.strip() != "-":
        photo_url = message.text.strip()

    await state.update_data(photo_url=photo_url, gallery_items=[])
    await state.set_state(GalleryState.gallery)
    await message.answer(
        "📸 <b>Qo'shimcha rasmlar yuboring</b>\n\n"
        "Mahsulot ichida 2-3 xil rasm ko'rinishi uchun yana rasm yuboring.\n"
        "Tugatish uchun <b>tayyor</b> yoki <b>-</b> yuboring.",
        parse_mode="HTML",
    )


@router.message(GalleryState.gallery)
async def collect_product_gallery(message: Message, state: FSMContext):
    data = await state.get_data()
    gallery_items = list(data.get("gallery_items") or [])

    if message.photo:
        gallery_items.append(message.photo[-1].file_id)
        await state.update_data(gallery_items=gallery_items, gallery=",".join(gallery_items))
        await message.answer(
            f"✅ Rasm qo'shildi. Hozir: {len(gallery_items)} ta qo'shimcha rasm.\n"
            "Yana rasm yuboring yoki <b>tayyor</b> deb yozing.",
            parse_mode="HTML",
        )
        return

    text = (message.text or "").strip()
    if text in ADMIN_MENU_TEXTS:
        await state.clear()
        await message.answer(
            "ℹ️ Mahsulot qo'shish bekor qilindi. Kerakli bo'lim tugmasini yana bir marta bosing.",
            reply_markup=admin_menu_kb(),
        )
        return

    if text and text.lower() not in {"-", "tayyor", "done", "готово"}:
        gallery_items.extend([item.strip() for item in text.split(",") if item.strip()])
        await state.update_data(gallery_items=gallery_items, gallery=",".join(gallery_items))
        await message.answer(
            f"✅ Gallery ma'lumoti saqlandi. Hozir: {len(gallery_items)} ta qo'shimcha rasm.\n"
            "Yana rasm yuboring yoki <b>tayyor</b> deb yozing.",
            parse_mode="HTML",
        )
        return

    await ask_product_stocks_or_save(message, state)


async def ask_product_stocks_or_save(message: Message, state: FSMContext):
    data = await state.get_data()
    cat_id = int(data.get("category_id", 0) or 0)

    if cat_id == 4:
        await state.clear()
        await save_product_from_data(message, data, {})
        return

    await state.set_state(GalleryState.stocks)

    if cat_id == 3:
        size_hint = "37:5 38:10 39:8 40:3 41:5 42:2"
        size_info = "Butsalar uchun: 36-45 raqamli o'lchamlar"
    else:
        size_hint = "S:5 M:10 L:8 XL:3 2XL:1"
        size_info = "Kiyimlar uchun: XS S M L XL 2XL 3XL"

    await message.answer(
        f"📦 <b>O'lchamlar va miqdorni kiriting:</b>\n\n"
        f"<i>{size_info}</i>\n\n"
        "Har birini quyidagi formatda yozing:\n"
        f"<code>{size_hint}</code>\n\n"
        "✅ Faqat mavjud o'lchamlarni kiriting!\n"
        "<i>Kiritilmagan o'lcham botda ko'rinmaydi.</i>",
        parse_mode="HTML",
    )


@router.message(GalleryState.stocks)
async def save_product_with_gallery_stocks(message: Message, state: FSMContext):
    await accept_and_save_stock_message(message, state)


@router.message(admin.AddProductState.stocks)
async def save_legacy_stock_state(message: Message, state: FSMContext):
    await accept_and_save_stock_message(message, state)


async def accept_and_save_stock_message(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text in ADMIN_MENU_TEXTS:
        await state.clear()
        await message.answer(
            "ℹ️ Mahsulot qo'shish bekor qilindi. Kerakli bo'lim tugmasini yana bir marta bosing.",
            reply_markup=admin_menu_kb(),
        )
        return

    parsed = parse_stock_text(text)

    if not parsed:
        data = await state.get_data()
        cat_id = int(data.get("category_id", 0) or 0)
        example = "37:5 38:10 39:8 40:3" if cat_id == 3 else "S:5 M:10 L:8 XL:3"
        await message.answer(
            "⚠️ Format noto'g'ri. Qaytadan kiriting:\n"
            f"<code>{example}</code>\n"
            "yoki <code>S=5, M=10, L=8, XL=3</code>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    data["stocks"] = parsed

    await state.clear()
    await message.answer("✅ O'lchamlar qabul qilindi, mahsulot saqlanyapti...")

    try:
        await asyncio.wait_for(save_product_from_data(message, data, parsed), timeout=20)
    except asyncio.TimeoutError:
        await message.answer(
            "❌ Saqlash 20 soniyada yakunlanmadi. State tozalandi, bot ishlayveradi.\n"
            "Railway/PostgreSQL sekin javob berdi. Mahsulot ro'yxatda chiqmasa, qayta qo'shib ko'ramiz.",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
    except Exception as exc:
        traceback.print_exc()
        await message.answer(
            "❌ Mahsulotni saqlashda xato bo'ldi. State tozalandi.\n"
            f"<code>{type(exc).__name__}: {str(exc)[:900]}</code>\n\n"
            "Shu xabarni menga yuboring, aniq joyini tuzataman.",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )


async def save_product_from_data(message: Message, data: dict, stocks: dict[str, int]):
    missing = [key for key in ("category_id", "name", "price") if key not in data]
    if missing:
        raise ValueError(f"FSM data missing: {', '.join(missing)}")

    category_id = int(data["category_id"])
    product_kwargs = dict(
        category_id=category_id,
        main_category=data.get("main_category") or MAIN_CATEGORY_BY_ID.get(category_id),
        product_type=data.get("product_type") or PRODUCT_TYPE_BY_ID.get(category_id),
        team=data.get("team"),
        season=data.get("season"),
        kit_type=data.get("kit_type"),
        league=data.get("league"),
        brand=data.get("brand"),
        model=data.get("model"),
        tags=data.get("tags"),
        customization_status=normalize_customization_status(
            data.get("customization_status") or CUSTOMIZATION_BY_ID.get(category_id)
        ),
        customization_price=data.get("customization_price", 50000),
        is_featured=bool(data.get("is_featured", False)),
        is_top_forma=bool(data.get("is_top_forma", False)),
        is_premium_boot=bool(data.get("is_premium_boot", False)),
        name=data["name"],
        description=data.get("description"),
        price=float(data["price"]),
        discount_percent=float(data.get("discount", 0) or 0),
        photo_url=data.get("photo_url"),
        is_active=True,
        in_stock=True,
    )
    if data.get("gallery"):
        product_kwargs["gallery"] = data.get("gallery")

    async with AsyncSessionLocal() as session:
        try:
            product = await create_product(session, **product_kwargs)
        except TypeError:
            for key in (
                "gallery",
                "main_category",
                "product_type",
                "team",
                "season",
                "kit_type",
                "league",
                "brand",
                "model",
                "tags",
                "customization_status",
                "customization_price",
                "is_featured",
                "is_top_forma",
                "is_premium_boot",
            ):
                product_kwargs.pop(key, None)
            product = await create_product(session, **product_kwargs)

        for size, qty in stocks.items():
            await set_product_stock(session, product.id, size, qty)

    stocks_text = ""
    if stocks:
        stocks_text = "\n📦 " + "  ".join(f"{size}:{qty}" for size, qty in stocks.items())

    gallery_count = len([item for item in str(data.get("gallery") or "").split(",") if item.strip()])
    gallery_text = f"\n🖼 Gallery: {gallery_count} ta qo'shimcha rasm" if gallery_count else ""

    await message.answer(
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"📦 {data['name']}\n"
        f"💰 {int(float(data['price'])):,} so'm"
        f"{stocks_text}"
        f"{gallery_text}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


def normalize_customization_status(value):
    if isinstance(value, CustomizationStatus):
        return value
    return CUSTOMIZATION_ALIASES.get(str(value or "").strip().lower(), CustomizationStatus.NOT_AVAILABLE)


def parse_stock_text(value: str) -> dict[str, int]:
    text = normalize_stock_text(value)
    parsed: dict[str, int] = {}

    for size, qty_text in re.findall(r"([A-Z0-9]{1,4})\s*[:=\-]\s*(\d+)", text):
        size_label = normalize_size_label(size)
        if size_label not in valid_sizes():
            continue
        qty = int(qty_text)
        if qty > 0:
            parsed[size_label] = qty

    return parsed


def valid_sizes() -> set[str]:
    return set(admin.SIZES) | {"2XL", "XXL"}


def normalize_size_label(value: str) -> str:
    label = value.strip().upper()
    if label in {"2XL", "XXL", "XLL"}:
        return "XXL"
    return label


def normalize_stock_text(value: str) -> str:
    table = str.maketrans({
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
        "а": "A", "в": "B", "е": "E", "к": "K", "м": "M", "н": "H",
        "о": "O", "р": "P", "с": "C", "т": "T", "х": "X",
    })
    return (
        value.translate(table)
        .upper()
        .replace("：", ":")
        .replace(";", " ")
        .replace("/", " ")
        .replace(",", " ")
    )
