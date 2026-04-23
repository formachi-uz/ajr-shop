from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from database.db import AsyncSessionLocal
from database.models import Product, Category, ProductStock
from database.crud import (
    get_all_categories, get_category_by_id,
    get_product_by_id, get_product_stocks
)

router = Router()

FORMA_CATEGORIES = [1, 2]


def format_price(product) -> str:
    if product.discount_percent > 0:
        old = f"{int(product.price):,}"
        new = f"{int(product.final_price):,}"
        return f"<s>{old}</s> → <b>{new} so'm</b> 🔥 -{int(product.discount_percent)}%"
    return f"<b>{int(product.price):,} so'm</b>"


# ─── Keyboards ────────────────────────────────────────────────────────────────
def categories_kb(categories) -> InlineKeyboardMarkup:
    rows = []
    for cat in categories:
        if cat.id == 4:
            continue
        rows.append([InlineKeyboardButton(
            text=f"{cat.emoji} {cat.name}",
            callback_data=f"cat_{cat.id}"
        )])
    rows.append([InlineKeyboardButton(text="🏠 Asosiy menyu", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def products_kb(products_with_stocks: list, category_id: int) -> InlineKeyboardMarkup:
    """products_with_stocks = [(product, stocks_list), ...]"""
    rows = []
    for product, stocks in products_with_stocks:
        price_str = f"{int(product.final_price):,} so'm"
        if product.discount_percent > 0:
            price_str += f" (-{int(product.discount_percent)}%)"
        total_qty = sum(s.quantity for s in stocks)
        if total_qty == 0 and stocks:
            stock_icon = " ❌"
        elif total_qty <= 3 and stocks:
            stock_icon = " ⚠️"
        else:
            stock_icon = ""
        rows.append([InlineKeyboardButton(
            text=f"{product.name}{stock_icon} — {price_str}",
            callback_data=f"prod_{product.id}"
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="catalog")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_detail_kb(product, has_stock: bool) -> InlineKeyboardMarkup:
    rows = []
    if has_stock:
        rows.append([
            InlineKeyboardButton(text="🛒 Savatga", callback_data=f"add_cart_{product.id}"),
            InlineKeyboardButton(text="⚡ Tezkor buyurtma", callback_data=f"buy_now_{product.id}"),
        ])
    rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"cat_{product.category_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def size_kb_with_stock(stocks: list, product_id: int, buy_now: bool = False) -> InlineKeyboardMarkup:
    prefix = "buynow_size" if buy_now else "size"
    rows = []
    row = []
    for stock in sorted(stocks, key=lambda s: s.sort_order):
        if stock.quantity == 0:
            btn = InlineKeyboardButton(text=f"{stock.size} ❌", callback_data="stock_out")
        elif stock.quantity <= 2:
            btn = InlineKeyboardButton(
                text=f"{stock.size} ⚠️{stock.quantity}",
                callback_data=f"{prefix}_{product_id}_{stock.size}"
            )
        else:
            btn = InlineKeyboardButton(
                text=f"{stock.size} ✅",
                callback_data=f"{prefix}_{product_id}_{stock.size}"
            )
        row.append(btn)
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data=f"prod_{product_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_print_kb(product_id: int, buy_now: bool = False) -> InlineKeyboardMarkup:
    prefix = "buynow" if buy_now else "cart"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Ha (+50,000 so'm)", callback_data=f"{prefix}_print_yes_{product_id}"),
        InlineKeyboardButton(text="❌ Yo'q", callback_data=f"{prefix}_print_no_{product_id}"),
    ]])


# ─── Helper: mahsulotlarni stocklar bilan yuklash ─────────────────────────────
async def _load_products_with_stocks(session, category_id: int):
    """Kategoriya mahsulotlarini stocklar bilan birga yuklash"""
    result = await session.execute(
        select(Product)
        .where(Product.category_id == category_id, Product.is_active == True)
        .order_by(Product.id)
    )
    products = result.scalars().all()

    products_with_stocks = []
    for product in products:
        stocks_result = await session.execute(
            select(ProductStock)
            .where(ProductStock.product_id == product.id)
            .order_by(ProductStock.sort_order)
        )
        stocks = stocks_result.scalars().all()
        products_with_stocks.append((product, stocks))

    return products_with_stocks


# ─── Handlers ─────────────────────────────────────────────────────────────────
@router.message(F.text == "🛍 Katalog")
async def show_catalog(message: Message):
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)
    if not categories:
        await message.answer("😕 Hozircha mahsulotlar mavjud emas.")
        return
    await message.answer(
        "🛍 <b>Kategoriyani tanlang:</b>",
        parse_mode="HTML",
        reply_markup=categories_kb(categories)
    )


@router.callback_query(F.data == "catalog")
async def callback_catalog(callback: CallbackQuery):
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)
    try:
        await callback.message.edit_text(
            "🛍 <b>Kategoriyani tanlang:</b>",
            parse_mode="HTML",
            reply_markup=categories_kb(categories)
        )
    except:
        await callback.message.answer(
            "🛍 <b>Kategoriyani tanlang:</b>",
            parse_mode="HTML",
            reply_markup=categories_kb(categories)
        )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    from bot.middlewares.admin_check import is_admin
    from bot.keyboards.main_menu import main_menu_kb
    admin = is_admin(callback.from_user.id)
    await callback.message.answer("🏠 Asosiy menyu", reply_markup=main_menu_kb(is_admin=admin))
    await callback.answer()


@router.callback_query(F.data.startswith("cat_"))
async def show_category_products(callback: CallbackQuery):
    category_id = int(callback.data.split("_")[1])

    async with AsyncSessionLocal() as session:
        category = await get_category_by_id(session, category_id)
        if not category:
            await callback.answer("Kategoriya topilmadi!", show_alert=True)
            return
        # Mahsulot va stocklarni session ichida yuklash
        products_with_stocks = await _load_products_with_stocks(session, category_id)

        # session yopilishidan oldin kerakli ma'lumotlarni olamiz
        cat_name = category.name
        cat_emoji = category.emoji
        cat_desc = category.description

    if not products_with_stocks:
        await callback.answer("😕 Bu kategoriyada hozircha mahsulot yo'q", show_alert=True)
        return

    text = f"{cat_emoji} <b>{cat_name}</b>\n"
    if cat_desc:
        text += f"\n📝 {cat_desc}\n"
    text += f"\n📦 {len(products_with_stocks)} ta mahsulot\n\nTanlang 👇"

    try:
        await callback.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=products_kb(products_with_stocks, category_id)
        )
    except:
        await callback.message.answer(
            text, parse_mode="HTML",
            reply_markup=products_kb(products_with_stocks, category_id)
        )
    await callback.answer()


@router.callback_query(F.data.startswith("prod_"))
async def show_product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await callback.answer("Mahsulot topilmadi", show_alert=True)
            return

        stocks_result = await session.execute(
            select(ProductStock)
            .where(ProductStock.product_id == product_id)
            .order_by(ProductStock.sort_order)
        )
        stocks = stocks_result.scalars().all()

        # session ichida kerakli ma'lumotlarni olamiz
        prod_name     = product.name
        prod_desc     = product.description
        prod_price    = format_price(product)
        prod_cat_id   = product.category_id
        prod_in_stock = product.in_stock
        prod_photo    = product.photo_url
        prod_discount = product.discount_percent

        # Stock holati
        stocks_data = [(s.size, s.quantity, s.sort_order) for s in stocks]

    # Stock matni
    stock_text = ""
    if stocks_data:
        all_zero = all(qty == 0 for _, qty, _ in stocks_data)
        if all_zero:
            stock_text = "\n⛔ <b>Hamma o'lchamlar tugagan</b>"
        else:
            sizes_info = []
            for size, qty, _ in sorted(stocks_data, key=lambda x: x[2]):
                if qty == 0:
                    sizes_info.append(f"{size}❌")
                elif qty <= 2:
                    sizes_info.append(f"{size}⚠️{qty}")
                else:
                    sizes_info.append(f"{size}✅")
            stock_text = "\n📦 O'lchamlar: " + "  ".join(sizes_info)

    text = f"<b>{prod_name}</b>\n\n"
    if prod_desc:
        text += f"📝 {prod_desc}\n\n"
    text += f"💰 Narxi: {prod_price}"
    text += stock_text

    if prod_cat_id in FORMA_CATEGORIES:
        text += "\n\n✍️ <i>Forma orqasiga ism yozish: +50,000 so'm</i>"

    has_stock = any(qty > 0 for _, qty, _ in stocks_data) if stocks_data else prod_in_stock

    # Stock obyektlarini qayta yasash (keyboard uchun)
    class StockItem:
        def __init__(self, size, quantity, sort_order):
            self.size = size
            self.quantity = quantity
            self.sort_order = sort_order

    stock_objs = [StockItem(s, q, o) for s, q, o in stocks_data]

    # Keyboard
    if has_stock and stock_objs:
        kb = product_detail_kb(
            type('P', (), {'id': product_id, 'category_id': prod_cat_id, 'in_stock': prod_in_stock})(),
            has_stock=True
        )
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⬅️ Orqaga", callback_data=f"cat_{prod_cat_id}")
        ]])

    if prod_photo:
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer_photo(
            photo=prod_photo,
            caption=text,
            parse_mode="HTML",
            reply_markup=kb
        )
    else:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "stock_out")
async def stock_out_click(callback: CallbackQuery):
    await callback.answer("❌ Bu o'lcham tugagan!", show_alert=True)


# ─── Savatga qo'shish ─────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("add_cart_"))
async def ask_size_or_add(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await callback.answer("Mahsulot topilmadi!", show_alert=True)
            return
        cat_id = product.category_id

        stocks_result = await session.execute(
            select(ProductStock)
            .where(ProductStock.product_id == product_id)
            .order_by(ProductStock.sort_order)
        )
        stocks = stocks_result.scalars().all()
        stocks_data = [(s.size, s.quantity, s.sort_order) for s in stocks]

    if cat_id == 4:
        from bot.handlers.cart import add_to_cart_direct
        await add_to_cart_direct(callback, product_id, None, state)
        return

    if not stocks_data:
        await callback.answer("😕 O'lchamlar kiritilmagan", show_alert=True)
        return

    class StockItem:
        def __init__(self, size, quantity, sort_order):
            self.size = size
            self.quantity = quantity
            self.sort_order = sort_order
            self.status = "out" if quantity == 0 else ("low" if quantity <= 2 else "ok")

    stock_objs = [StockItem(s, q, o) for s, q, o in stocks_data]

    try:
        await callback.message.edit_reply_markup(
            reply_markup=size_kb_with_stock(stock_objs, product_id, buy_now=False)
        )
    except:
        await callback.message.answer(
            "📏 O'lchamni tanlang:",
            reply_markup=size_kb_with_stock(stock_objs, product_id, buy_now=False)
        )
    await callback.answer("📏 O'lchamni tanlang 👇")


@router.callback_query(F.data.startswith("size_"))
async def handle_size_cart(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)
    product_id = int(parts[1])
    size = parts[2]

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        stocks_result = await session.execute(
            select(ProductStock).where(ProductStock.product_id == product_id)
        )
        stocks = stocks_result.scalars().all()
        stock_qty = next((s.quantity for s in stocks if s.size == size), 0)
        cat_id = product.category_id

    if stock_qty == 0:
        await callback.answer("❌ Bu o'lcham tugagan!", show_alert=True)
        return

    if cat_id in FORMA_CATEGORIES:
        await state.update_data(pending_product_id=product_id, pending_size=size, pending_mode="cart")
        try:
            await callback.message.edit_reply_markup(
                reply_markup=back_print_kb(product_id, buy_now=False)
            )
        except:
            await callback.message.answer(
                f"✍️ Forma orqasiga <b>ism va raqam</b> yozdirasizmi?\n<i>+50,000 so'm</i>",
                parse_mode="HTML",
                reply_markup=back_print_kb(product_id, buy_now=False)
            )
        await callback.answer(f"✅ O'lcham: {size}")
    else:
        from bot.handlers.cart import add_to_cart_direct
        await add_to_cart_direct(callback, product_id, size, state)


@router.callback_query(F.data.startswith("cart_print_yes_"))
async def cart_print_yes(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    size = data.get("pending_size")
    await state.update_data(print_product_id=product_id, print_size=size, print_mode="cart")
    from bot.handlers.cart import PrintNameState
    await state.set_state(PrintNameState.waiting_name)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await callback.message.answer(
        "✍️ <b>Forma orqasiga yoziladigan ism va raqamni kiriting:</b>\n\n"
        "<i>Masalan: HUSANOV 45</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cart_print_no_"))
async def cart_print_no(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    size = data.get("pending_size")
    await state.update_data(pending_product_id=None, pending_size=None)
    from bot.handlers.cart import add_to_cart_direct
    await add_to_cart_direct(callback, product_id, size, state)


# ─── Tezkor buyurtma ──────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("buy_now_"))
async def buy_now(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[2])

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        if not product:
            await callback.answer("Mahsulot topilmadi!", show_alert=True)
            return
        cat_id = product.category_id
        stocks_result = await session.execute(
            select(ProductStock)
            .where(ProductStock.product_id == product_id)
            .order_by(ProductStock.sort_order)
        )
        stocks = stocks_result.scalars().all()
        stocks_data = [(s.size, s.quantity, s.sort_order) for s in stocks]

    if cat_id == 4:
        from bot.handlers.cart import add_to_cart_direct
        await add_to_cart_direct(callback, product_id, None, state)
        await state.update_data(buy_now_after=True)
        return

    if not stocks_data:
        await callback.answer("😕 O'lchamlar kiritilmagan", show_alert=True)
        return

    class StockItem:
        def __init__(self, size, quantity, sort_order):
            self.size = size
            self.quantity = quantity
            self.sort_order = sort_order
            self.status = "out" if quantity == 0 else ("low" if quantity <= 2 else "ok")

    stock_objs = [StockItem(s, q, o) for s, q, o in stocks_data]

    try:
        await callback.message.edit_reply_markup(
            reply_markup=size_kb_with_stock(stock_objs, product_id, buy_now=True)
        )
    except:
        await callback.message.answer(
            "📏 O'lchamni tanlang:",
            reply_markup=size_kb_with_stock(stock_objs, product_id, buy_now=True)
        )
    await callback.answer("📏 O'lchamni tanlang 👇")


@router.callback_query(F.data.startswith("buynow_size_"))
async def handle_size_buynow(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 3)
    product_id = int(parts[2])
    size = parts[3]

    async with AsyncSessionLocal() as session:
        product = await get_product_by_id(session, product_id)
        stocks_result = await session.execute(
            select(ProductStock).where(ProductStock.product_id == product_id)
        )
        stocks = stocks_result.scalars().all()
        stock_qty = next((s.quantity for s in stocks if s.size == size), 0)
        cat_id = product.category_id

    if stock_qty == 0:
        await callback.answer("❌ Bu o'lcham tugagan!", show_alert=True)
        return

    if cat_id in FORMA_CATEGORIES:
        await state.update_data(pending_product_id=product_id, pending_size=size, pending_mode="buynow")
        try:
            await callback.message.edit_reply_markup(
                reply_markup=back_print_kb(product_id, buy_now=True)
            )
        except:
            await callback.message.answer(
                f"✍️ Forma orqasiga <b>ism va raqam</b> yozdirasizmi?\n<i>+50,000 so'm</i>",
                parse_mode="HTML",
                reply_markup=back_print_kb(product_id, buy_now=True)
            )
        await callback.answer(f"✅ O'lcham: {size}")
    else:
        from bot.handlers.cart import add_to_cart_direct
        await add_to_cart_direct(callback, product_id, size, state)
        await _go_to_checkout(callback, state)


@router.callback_query(F.data.startswith("buynow_print_yes_"))
async def buynow_print_yes(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    size = data.get("pending_size")
    await state.update_data(print_product_id=product_id, print_size=size, print_mode="buynow")
    from bot.handlers.cart import PrintNameState
    await state.set_state(PrintNameState.waiting_name)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    await callback.message.answer(
        "✍️ <b>Ism va raqamni kiriting:</b>\n\n<i>Masalan: HUSANOV 45</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buynow_print_no_"))
async def buynow_print_no(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[3])
    data = await state.get_data()
    size = data.get("pending_size")
    from bot.handlers.cart import add_to_cart_direct
    await add_to_cart_direct(callback, product_id, size, state)
    await _go_to_checkout(callback, state)


async def _go_to_checkout(callback: CallbackQuery, state: FSMContext):
    from bot.handlers.order import OrderState
    from bot.keyboards.main_menu import cancel_kb
    await state.set_state(OrderState.waiting_name)
    await callback.message.answer(
        "⚡ <b>Tezkor buyurtma!</b>\n\n"
        "👤 Ismingizni kiriting:\n"
        "<i>Masalan: Musurmon Husanov</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )
