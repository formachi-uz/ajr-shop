from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select

from database.db import AsyncSessionLocal
from database.crud import get_all_categories, get_category_by_id
from database.models import Product, ProductStock

router = Router()


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


def products_kb(products_with_stocks: list, category_id: int) -> InlineKeyboardMarkup:
    rows = []
    for product, stocks in products_with_stocks:
        final_price = product.price * (1 - product.discount_percent / 100) if product.discount_percent else product.price
        price_text = f"{int(final_price):,} so'm"
        total_qty = sum(stock.quantity for stock in stocks)
        stock_icon = " ❌" if total_qty == 0 and stocks else " ⚠️" if 0 < total_qty <= 3 else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{product.name}{stock_icon} — {price_text}",
                callback_data=f"prod_{product.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def load_products_with_stocks(session, category_id: int):
    result = await session.execute(
        select(Product)
        .where(Product.category_id == category_id, Product.is_active == True)
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


@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)

    text = "🛍 <b>Kategoriyani tanlang:</b>"
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=categories_kb(categories))
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=categories_kb(categories))
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def category_callback(callback: CallbackQuery):
    try:
        category_id = int(callback.data.split("_", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Kategoriya xatosi", show_alert=True)
        return

    async with AsyncSessionLocal() as session:
        category = await get_category_by_id(session, category_id)
        if not category:
            await callback.answer("Kategoriya topilmadi", show_alert=True)
            return
        products_with_stocks = await load_products_with_stocks(session, category_id)
        categories = await get_all_categories(session)

    if not products_with_stocks:
        empty_text = (
            f"{category.emoji} <b>{category.name}</b>\n\n"
            "Bu kategoriyada hozircha mahsulot ko'rinmayapti.\n"
            "Admin paneldan mahsulot qo'shganda aynan shu kategoriyani tanlang."
        )
        try:
            await callback.message.edit_text(empty_text, parse_mode="HTML", reply_markup=categories_kb(categories))
        except Exception:
            await callback.message.answer(empty_text, parse_mode="HTML", reply_markup=categories_kb(categories))
        await callback.answer("Bu kategoriyada mahsulot yo'q")
        return

    text = f"{category.emoji} <b>{category.name}</b>\n"
    if category.description:
        text += f"\n📝 {category.description}\n"
    text += f"\n📦 {len(products_with_stocks)} ta mahsulot\n\nTanlang 👇"

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=products_kb(products_with_stocks, category_id),
        )
    except Exception:
        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=products_kb(products_with_stocks, category_id),
        )
    await callback.answer()
