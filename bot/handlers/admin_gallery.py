import asyncio
import re
import traceback
from html import escape

from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.handlers import admin
from bot.keyboards.admin_kb import admin_menu_kb
from database.db import AsyncSessionLocal
from database.crud import create_product, set_product_stock, update_product
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

MAIN_CATEGORY_BY_ID = {1: "FORMLAR", 2: "RETRO_FORMALAR", 3: "BUTSIYLAR"}
PRODUCT_TYPE_BY_ID = {1: "jersey", 2: "retro_jersey", 3: "boots"}
CUSTOMIZATION_BY_ID = {
    1: CustomizationStatus.AVAILABLE_PAID.value,
    2: CustomizationStatus.NOT_AVAILABLE.value,
    3: CustomizationStatus.NOT_AVAILABLE.value,
}
CUSTOMIZATION_ALIASES = {
    "paid": CustomizationStatus.AVAILABLE_PAID.value,
    "available_paid": CustomizationStatus.AVAILABLE_PAID.value,
    "pullik": CustomizationStatus.AVAILABLE_PAID.value,
    "ha": CustomizationStatus.AVAILABLE_PAID.value,
    "bonus": CustomizationStatus.INCLUDED_BONUS.value,
    "included_bonus": CustomizationStatus.INCLUDED_BONUS.value,
    "bepul": CustomizationStatus.INCLUDED_BONUS.value,
    "no": CustomizationStatus.NOT_AVAILABLE.value,
    "none": CustomizationStatus.NOT_AVAILABLE.value,
    "not_available": CustomizationStatus.NOT_AVAILABLE.value,
    "yoq": CustomizationStatus.NOT_AVAILABLE.value,
    "yo'q": CustomizationStatus.NOT_AVAILABLE.value,
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
        await cancel_product_flow(message, state)
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
        await cancel_product_flow(message, state)
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
        await asyncio.wait_for(save_product_from_data(message, data, parsed), timeout=30)
    except asyncio.TimeoutError:
        await send_save_error(
            message,
            "Saqlash 30 soniyada yakunlanmadi. Railway/PostgreSQL javobi sekinlashgan bo'lishi mumkin.",
        )
    except Exception as exc:
        traceback.print_exc()
        await send_save_error(message, f"{type(exc).__name__}: {exc}")


async def save_product_from_data(message: Message, data: dict, stocks: dict[str, int]):
    missing = [key for key in ("category_id", "name", "price") if key not in data]
    if missing:
        raise ValueError(f"FSM data missing: {', '.join(missing)}")

    category_id = int(data["category_id"])
    legacy_kwargs = {
        "category_id": category_id,
        "name": data["name"],
        "description": data.get("description"),
        "price": float(data["price"]),
        "discount_percent": float(data.get("discount", 0) or 0),
        "photo_url": data.get("photo_url"),
        "is_active": True,
        "in_stock": True,
    }

    async with AsyncSessionLocal() as session:
        product = await create_product(session, **legacy_kwargs)
        await message.answer(f"✅ Mahsulot bazaga yozildi: ID {product.id}. Stock saqlanyapti...")

        stock_errors = []
        for size, qty in stocks.items():
            try:
                await set_product_stock(session, product.id, size, qty)
            except Exception as exc:
                await session.rollback()
                stock_errors.append(f"{size}:{qty} ({type(exc).__name__})")

        metadata_saved = await try_save_extra_metadata(session, product.id, category_id, data)

    stocks_text = ""
    if stocks:
        stocks_text = "\n📦 " + "  ".join(f"{size}:{qty}" for size, qty in stocks.items())

    gallery_count = len([item for item in str(data.get("gallery") or "").split(",") if item.strip()])
    gallery_text = f"\n🖼 Gallery: {gallery_count} ta qo'shimcha rasm" if gallery_count and metadata_saved else ""
    metadata_text = "\nℹ️ Qo'shimcha metadata keyinroq yangilanadi" if not metadata_saved else ""
    stock_error_text = "\n⚠️ Stock xatosi: " + ", ".join(stock_errors) if stock_errors else ""

    await message.answer(
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"📦 {data['name']}\n"
        f"💰 {int(float(data['price'])):,} so'm"
        f"{stocks_text}"
        f"{gallery_text}"
        f"{metadata_text}"
        f"{stock_error_text}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


async def try_save_extra_metadata(session, product_id: int, category_id: int, data: dict) -> bool:
    extra = {
        "main_category": data.get("main_category") or MAIN_CATEGORY_BY_ID.get(category_id),
        "product_type": data.get("product_type") or PRODUCT_TYPE_BY_ID.get(category_id),
        "team": data.get("team"),
        "season": data.get("season"),
        "kit_type": data.get("kit_type"),
        "league": data.get("league"),
        "brand": data.get("brand"),
        "model": data.get("model"),
        "tags": data.get("tags"),
        "customization_status": normalize_customization_status(
            data.get("customization_status") or CUSTOMIZATION_BY_ID.get(category_id)
        ),
        "customization_price": data.get("customization_price", 50000),
        "is_featured": bool(data.get("is_featured", False)),
        "is_top_forma": bool(data.get("is_top_forma", False)),
        "is_premium_boot": bool(data.get("is_premium_boot", False)),
    }
    if data.get("gallery"):
        extra["gallery"] = data.get("gallery")
    extra = {key: value for key, value in extra.items() if value is not None}

    try:
        await update_product(session, product_id, **extra)
        return True
    except Exception:
        await session.rollback()
        traceback.print_exc()
        return False


async def cancel_product_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "ℹ️ Mahsulot qo'shish bekor qilindi. Kerakli bo'lim tugmasini yana bir marta bosing.",
        reply_markup=admin_menu_kb(),
    )


async def send_save_error(message: Message, detail: str):
    safe_detail = escape(str(detail)[:1200])
    try:
        await message.answer(
            "❌ Mahsulot saqlanmadi.\n\n"
            f"<code>{safe_detail}</code>\n\n"
            "Bot state tozalandi. Admin paneldan qayta qo'shib ko'ring.",
            parse_mode="HTML",
            reply_markup=admin_menu_kb(),
        )
    except Exception:
        await message.answer(
            "❌ Mahsulot saqlanmadi. Bot state tozalandi. Xato matni Telegram HTML formatiga sig'madi.",
            reply_markup=admin_menu_kb(),
        )


def normalize_customization_status(value):
    if isinstance(value, CustomizationStatus):
        return value.value
    return CUSTOMIZATION_ALIASES.get(str(value or "").strip().lower(), CustomizationStatus.NOT_AVAILABLE.value)


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
