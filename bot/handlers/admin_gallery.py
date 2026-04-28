import re
from aiogram import Router
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.handlers import admin
from bot.keyboards.admin_kb import admin_menu_kb
from database.db import AsyncSessionLocal
from database.crud import create_product, set_product_stock

router = Router()


class GalleryState(StatesGroup):
    gallery = State()
    stocks = State()


@router.message(admin.AddProductState.photo)
async def collect_main_product_photo(message: Message, state: FSMContext):
    """Collect the main image, then allow 2-3 optional gallery images."""
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
    if text and text.lower() not in {"-", "tayyor", "done"}:
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
    cat_id = data.get("category_id", 0)

    if cat_id == 4:
        await save_product_final(message, state)
        return

    # Use the legacy state too; this router is registered before admin.router and handles it robustly.
    await state.set_state(admin.AddProductState.stocks)

    if cat_id == 3:
        size_hint = "37:5 38:10 39:8 40:3 41:5 42:2"
        size_info = "Butsalar uchun: 36-45 raqamli o'lchamlar"
    else:
        size_hint = "S:5 M:10 L:8 XL:3"
        size_info = "Kiyimlar uchun: XS S M L XL XXL 3XL"

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
@router.message(admin.AddProductState.stocks)
async def save_product_with_gallery_stocks(message: Message, state: FSMContext):
    parsed = parse_stock_text(message.text or "")

    if not parsed:
        await message.answer(
            "⚠️ Format noto'g'ri. Qaytadan kiriting:\n"
            "<code>S:5 M:10 L:8 XL:3</code>\n"
            "yoki <code>S=5, M=10, L=8, XL=3</code>",
            parse_mode="HTML",
        )
        return

    await state.update_data(stocks=parsed)
    await save_product_final(message, state)


async def save_product_final(message: Message, state: FSMContext):
    data = await state.get_data()
    stocks = data.get("stocks", {})

    async with AsyncSessionLocal() as session:
        product = await create_product(
            session,
            category_id=data["category_id"],
            name=data["name"],
            description=data.get("description"),
            price=data["price"],
            discount_percent=data.get("discount", 0),
            photo_url=data.get("photo_url"),
            gallery=data.get("gallery"),
            is_active=True,
            in_stock=True,
        )
        for size, qty in stocks.items():
            await set_product_stock(session, product.id, size, qty)

    await state.clear()

    stocks_text = ""
    if stocks:
        stocks_text = "\n📦 " + "  ".join(f"{size}:{qty}" for size, qty in stocks.items())

    gallery_count = len([item for item in str(data.get("gallery") or "").split(",") if item.strip()])
    gallery_text = f"\n🖼 Gallery: {gallery_count} ta qo'shimcha rasm" if gallery_count else ""

    await message.answer(
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"📦 {data['name']}\n"
        f"💰 {int(data['price']):,} so'm"
        f"{stocks_text}"
        f"{gallery_text}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb(),
    )


def parse_stock_text(value: str) -> dict[str, int]:
    text = normalize_stock_text(value)
    parsed: dict[str, int] = {}

    for size, qty_text in re.findall(r"([A-Z0-9]{1,4})\s*[:=]\s*(\d+)", text):
        if size not in admin.SIZES:
            continue
        qty = int(qty_text)
        if qty > 0:
            parsed[size] = qty

    return parsed


def normalize_stock_text(value: str) -> str:
    # Telegram desktop sometimes sends visually similar Cyrillic letters.
    table = str.maketrans({
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "а": "A",
        "в": "B",
        "е": "E",
        "к": "K",
        "м": "M",
        "н": "H",
        "о": "O",
        "р": "P",
        "с": "C",
        "т": "T",
        "х": "X",
    })
    return value.translate(table).upper().replace("：", ":").replace(";", " ").replace("/", " ")
