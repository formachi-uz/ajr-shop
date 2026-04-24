import os
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.db import AsyncSessionLocal
from database.crud import (
    get_all_categories, get_all_products, get_product_by_id,
    create_product, update_product, delete_product,
    get_pending_orders, get_all_orders, get_order_with_items,
    update_order_status, get_product_stocks, set_product_stock
)
from bot.middlewares.admin_check import is_admin, ADMIN_IDS, GROUP_CHAT_ID, GLAVNIY_ADMIN_ID
from bot.keyboards.admin_kb import (
    admin_menu_kb, order_actions_kb, postal_kb,
    check_confirm_kb, product_manage_kb
)
from bot.keyboards.main_menu import main_menu_kb

router = Router()

# O'lchamlar tartibi
SIZES        = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
FORMA_CAT_IDS = [1, 2]  # Razmer so'raladigan kategoriyalar
GROUP_CHECKS_ID  = int(os.getenv("GROUP_CHECKS_ID",  "-5284654949"))


# ─── FSM ──────────────────────────────────────────────────────────────────────
class AddProductState(StatesGroup):
    category    = State()
    name        = State()
    description = State()
    price       = State()
    discount    = State()
    photo       = State()
    stocks      = State()   # Razmerlar + miqdor (faqat forma/butsalar uchun)


class EditPriceState(StatesGroup):
    waiting_price = State()


class EditDiscountState(StatesGroup):
    waiting_discount = State()


class StockEditState(StatesGroup):
    waiting_size_qty = State()


# ─── ADMIN PANEL MENYU ────────────────────────────────────────────────────────
@router.message(F.text == "⚙️ Admin Panel")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Ruxsat yo'q!")
        return
    await message.answer(
        "⚙️ <b>Admin Panel</b>",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )


@router.message(F.text == "🏠 Asosiy menyu")
async def back_to_main(message: Message):
    admin = is_admin(message.from_user.id)
    await message.answer("🏠 Asosiy menyu", reply_markup=main_menu_kb(is_admin=admin))


# ─── YANGI BUYURTMALAR ────────────────────────────────────────────────────────
@router.message(F.text == "📋 Yangi buyurtmalar")
async def show_pending_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        orders = await get_pending_orders(session)
    if not orders:
        await message.answer("✅ Hozircha yangi buyurtmalar yo'q")
        return
    await message.answer(f"📋 <b>{len(orders)} ta yangi buyurtma:</b>", parse_mode="HTML")
    for order in orders:
        text = (
            f"🆕 <b>Buyurtma #{order.id}</b>\n"
            f"👤 {order.user.full_name}\n"
            f"📱 {order.user.phone or '—'}\n"
            f"📍 {order.delivery_address}\n"
            f"💰 {int(order.total_price):,} so'm\n"
            f"📅 {order.created_at.strftime('%d.%m.%Y %H:%M')}"
        )
        await message.answer(text, parse_mode="HTML", reply_markup=order_actions_kb(order.id))


# ─── TASDIQLANGAN BUYURTMALAR (Pochtaga topshirish uchun) ─────────────────────
@router.message(F.text == "✅ Tasdiqlangan buyurtmalar")
async def show_confirmed_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from database.models import Order, OrderStatus

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.user), selectinload(Order.items))
            .where(Order.status == OrderStatus.CONFIRMED)
            .order_by(Order.created_at.desc())
        )
        orders = result.scalars().all()

    if not orders:
        await message.answer("📭 Hozircha tasdiqlangan buyurtmalar yo'q")
        return

    await message.answer(
        f"✅ <b>{len(orders)} ta tasdiqlangan buyurtma</b>\n"
        "<i>Pochtaga topshirishga tayyor:</i>",
        parse_mode="HTML"
    )

    for order in orders:
        # Mahsulotlar ro'yxati
        items_text = ""
        for item in order.items:
            extra = f" ({item.size})" if item.size else ""
            extra += f" | ✍️{item.player_name}" if item.player_name else ""
            items_text += f"• {item.product.name if item.product else 'N/A'}{extra} × {item.quantity}\n"

        # Izohdan ism va telefon ajratamiz
        comment = order.comment or ""
        name_part = ""
        phone_part = ""
        if "Ism:" in comment and "Tel:" in comment:
            parts = comment.split("|")
            for p in parts:
                if "Ism:" in p:
                    name_part = p.replace("Ism:", "").strip()
                if "Tel:" in p:
                    phone_part = p.replace("Tel:", "").strip()

        text = (
            f"✅ <b>Buyurtma #{order.id}</b>\n"
            f"{'─' * 24}\n"
            f"👤 {name_part or order.user.full_name}\n"
            f"📱 {phone_part or order.user.phone or '—'}\n"
            f"📍 {order.delivery_address}\n"
            f"{'─' * 24}\n"
            f"{items_text}"
            f"{'─' * 24}\n"
            f"💰 {int(order.total_price):,} so'm"
        )
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=postal_kb(order.id)
        )


# ─── BARCHA BUYURTMALAR ───────────────────────────────────────────────────────
@router.message(F.text == "📊 Barcha buyurtmalar")
async def show_all_orders(message: Message):
    if not is_admin(message.from_user.id):
        return
    STATUS_EMOJI = {
        "pending": "⏳", "confirmed": "✅",
        "delivering": "📦", "done": "✔️", "cancelled": "❌"
    }
    async with AsyncSessionLocal() as session:
        orders = await get_all_orders(session, limit=20)
    if not orders:
        await message.answer("Buyurtmalar yo'q")
        return
    text = "📊 <b>So'nggi 20 ta buyurtma:</b>\n\n"
    for order in orders:
        emoji = STATUS_EMOJI.get(order.status.value, "❓")
        text += f"{emoji} <b>#{order.id}</b> | {order.user.full_name} | {int(order.total_price):,} so'm\n"
    await message.answer(text, parse_mode="HTML")


# ─── MAHSULOT QO'SHISH — FSM ──────────────────────────────────────────────────
@router.message(F.text == "➕ Mahsulot qo'shish")
async def start_add_product(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        categories = await get_all_categories(session)

    text = "📦 <b>Kategoriyani tanlang (raqam yuboring):</b>\n\n"
    for cat in categories:
        text += f"{cat.id}. {cat.emoji} {cat.name}\n"

    await state.set_state(AddProductState.category)
    await message.answer(text, parse_mode="HTML")


@router.message(AddProductState.category)
async def add_product_name(message: Message, state: FSMContext):
    try:
        category_id = int(message.text)
        await state.update_data(category_id=category_id)
        await state.set_state(AddProductState.name)
        await message.answer("✏️ <b>Mahsulot nomini yozing:</b>", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Raqam yuboring")


@router.message(AddProductState.name)
async def add_product_description(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProductState.description)
    await message.answer("📝 <b>Tavsif yozing</b> (o'tkazish uchun — yuboring):", parse_mode="HTML")


@router.message(AddProductState.description)
async def add_product_price(message: Message, state: FSMContext):
    desc = None if message.text.strip() == "-" else message.text
    await state.update_data(description=desc)
    await state.set_state(AddProductState.price)
    await message.answer("💰 <b>Narxni yozing</b> (so'mda, faqat raqam):", parse_mode="HTML")


@router.message(AddProductState.price)
async def add_product_discount(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "").replace(" ", ""))
        await state.update_data(price=price)
        await state.set_state(AddProductState.discount)
        await message.answer("🏷 <b>Skidka foizini yozing</b> (0 = yo'q):", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Faqat raqam yuboring")


@router.message(AddProductState.discount)
async def add_product_photo(message: Message, state: FSMContext):
    try:
        discount = float(message.text)
        await state.update_data(discount=discount)
        await state.set_state(AddProductState.photo)
        await message.answer("📸 <b>Rasm yuboring</b> (o'tkazish uchun — yuboring):", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Faqat raqam yuboring (masalan: 10)")


@router.message(AddProductState.photo)
async def add_product_stocks(message: Message, state: FSMContext):
    """Rasmdan keyin — razmerlar so'rash"""
    photo_url = None
    if message.photo:
        photo_url = message.photo[-1].file_id
    elif message.text and message.text.strip() != "-":
        photo_url = message.text.strip()

    await state.update_data(photo_url=photo_url)
    data = await state.get_data()
    cat_id = data.get("category_id", 0)

    # Razmer so'ralmaydigan kategoriyalar (4 = ism yozish)
    if cat_id == 4:
        await _save_product_final(message, state)
        return

    await state.set_state(AddProductState.stocks)
    await message.answer(
        "📦 <b>O'lchamlar va miqdorni kiriting:</b>\n\n"
        "Har bir o'lchamni quyidagi formatda yozing:\n"
        "<code>S:5 M:10 L:8 XL:3</code>\n\n"
        "Faqat mavjud o'lchamlarni kiriting!\n"
        "<i>Kiritilmagan o'lcham botda ko'rinmaydi.</i>",
        parse_mode="HTML"
    )


@router.message(AddProductState.stocks)
async def save_product_with_stocks(message: Message, state: FSMContext):
    """S:5 M:10 L:3 formatida parse qilish"""
    text = message.text.strip().upper()
    parsed = {}

    for part in text.replace(",", " ").split():
        if ":" in part:
            size, qty_str = part.split(":", 1)
            size = size.strip()
            if size in SIZES:
                try:
                    qty = int(qty_str.strip())
                    if qty > 0:
                        parsed[size] = qty
                except ValueError:
                    pass

    if not parsed:
        await message.answer(
            "⚠️ Format noto'g'ri. Qaytadan kiriting:\n"
            "<code>S:5 M:10 L:8 XL:3</code>",
            parse_mode="HTML"
        )
        return

    await state.update_data(stocks=parsed)

    # Tasdiqlash
    sizes_text = "  ".join(f"{s}: {q} ta" for s, q in parsed.items())
    data = await state.get_data()
    await message.answer(
        f"✅ <b>Kiritilgan o'lchamlar:</b>\n{sizes_text}\n\n"
        "Saqlashni tasdiqlang yoki qayta kiriting:",
        parse_mode="HTML",
        reply_markup=__import__('aiogram.types', fromlist=['InlineKeyboardMarkup']).InlineKeyboardMarkup(
            inline_keyboard=[[
                __import__('aiogram.types', fromlist=['InlineKeyboardButton']).InlineKeyboardButton(
                    text="✅ Saqlash", callback_data="save_product_stocks"
                ),
                __import__('aiogram.types', fromlist=['InlineKeyboardButton']).InlineKeyboardButton(
                    text="✏️ Qayta kiriting", callback_data="reenter_stocks"
                ),
            ]]
        )
    )


@router.callback_query(F.data == "reenter_stocks")
async def reenter_stocks(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "📦 Qaytadan kiriting:\n<code>S:5 M:10 L:8 XL:3</code>",
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "save_product_stocks")
async def confirm_save_stocks(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await _save_product_final(callback.message, state)
    await callback.answer()


async def _save_product_final(message: Message, state: FSMContext):
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
            is_active=True,
            in_stock=True
        )
        # Stocklarni saqlash
        for size, qty in stocks.items():
            await set_product_stock(session, product.id, size, qty)

    await state.clear()

    stocks_text = ""
    if stocks:
        stocks_text = "\n📦 " + "  ".join(f"{s}:{q}" for s, q in stocks.items())

    await message.answer(
        f"✅ <b>Mahsulot qo'shildi!</b>\n\n"
        f"📦 {data['name']}\n"
        f"💰 {int(data['price']):,} so'm"
        f"{stocks_text}",
        parse_mode="HTML",
        reply_markup=admin_menu_kb()
    )


# ─── MAHSULOTLAR RO'YXATI ─────────────────────────────────────────────────────
@router.message(F.text == "📦 Mahsulotlar")
async def list_products(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with AsyncSessionLocal() as session:
        products = await get_all_products(session)
    if not products:
        await message.answer("Mahsulotlar yo'q")
        return
    for product in products:
        text = (
            f"<b>{product.name}</b> (ID: {product.id})\n"
            f"💰 {int(product.price):,} so'm"
        )
        if product.discount_percent > 0:
            text += f" | Skidka: {int(product.discount_percent)}%"
        await message.answer(text, parse_mode="HTML", reply_markup=product_manage_kb(product.id))


# ─── NARX O'ZGARTIRISH ────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_price_"))
async def start_edit_price(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[2])
    await state.set_state(EditPriceState.waiting_price)
    await state.update_data(product_id=product_id)
    await callback.message.answer("💰 Yangi narxni yozing (so'mda):")
    await callback.answer()


@router.message(EditPriceState.waiting_price)
async def save_new_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "").replace(" ", ""))
        data = await state.get_data()
        async with AsyncSessionLocal() as session:
            await update_product(session, data["product_id"], price=price)
        await state.clear()
        await message.answer(f"✅ Narx yangilandi: <b>{int(price):,} so'm</b>", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Faqat raqam yuboring")


# ─── SKIDKA O'ZGARTIRISH ──────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("edit_discount_"))
async def start_edit_discount(callback: CallbackQuery, state: FSMContext):
    product_id = int(callback.data.split("_")[2])
    await state.set_state(EditDiscountState.waiting_discount)
    await state.update_data(product_id=product_id)
    await callback.message.answer("🏷 Yangi skidka foizini yozing (0-100):")
    await callback.answer()


@router.message(EditDiscountState.waiting_discount)
async def save_new_discount(message: Message, state: FSMContext):
    try:
        discount = float(message.text)
        if not 0 <= discount <= 100:
            await message.answer("⚠️ 0-100 oralig'ida raqam yuboring")
            return
        data = await state.get_data()
        async with AsyncSessionLocal() as session:
            await update_product(session, data["product_id"], discount_percent=discount)
        await state.clear()
        await message.answer(f"✅ Skidka: <b>{int(discount)}%</b>", parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Faqat raqam yuboring")


# ─── MAHSULOT O'CHIRISH ───────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("delete_prod_"))
async def delete_product_callback(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[2])
    async with AsyncSessionLocal() as session:
        await update_product(session, product_id, is_active=False)
    await callback.message.edit_text("🗑 Mahsulot o'chirildi")
    await callback.answer("✅ O'chirildi")


# ─── WEB PANEL ────────────────────────────────────────────────────────────────
@router.message(F.text == "🌐 Web Panel")
async def web_panel_link(message: Message):
    if not is_admin(message.from_user.id):
        return
    web_url = os.getenv("WEB_PANEL_URL", "Railway deploy qilingandan keyin URL bo'ladi")
    await message.answer(
        f"🌐 <b>Web Admin Panel:</b>\n\n{web_url}\n\n"
        f"🔑 Parol: ADMIN_PANEL_SECRET",
        parse_mode="HTML"
    )


# ─── ADMINLAR BOSHQARISH ──────────────────────────────────────────────────────
@router.message(F.text == "👥 Adminlar")
async def manage_admins(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = "👥 <b>Hozirgi adminlar:</b>\n\n"
    for i, aid in enumerate(ADMIN_IDS, 1):
        text += f"{i}. <code>{aid}</code>\n"
    text += (
        "\n<b>Admin qo'shish:</b> /addadmin 123456789\n"
        "<b>Admin o'chirish:</b> /removeadmin 123456789"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(lambda m: m.text and m.text.startswith("/addadmin"))
async def add_admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Ishlatish: /addadmin 123456789")
        return
    try:
        new_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ ID raqam bo'lishi kerak")
        return
    if new_id in ADMIN_IDS:
        await message.answer(f"✅ <code>{new_id}</code> allaqachon admin!", parse_mode="HTML")
        return
    ADMIN_IDS.append(new_id)
    await message.answer(
        f"✅ <code>{new_id}</code> admin qilindi!\n\n"
        f"Doimiy qilish uchun Railway Variables:\n"
        f"<code>ADMIN_IDS={','.join(str(x) for x in ADMIN_IDS)}</code>",
        parse_mode="HTML"
    )


@router.message(lambda m: m.text and m.text.startswith("/removeadmin"))
async def remove_admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Ishlatish: /removeadmin 123456789")
        return
    try:
        rem_id = int(parts[1])
    except ValueError:
        await message.answer("⚠️ ID raqam bo'lishi kerak")
        return
    if rem_id == message.from_user.id:
        await message.answer("⚠️ O'zingizni o'chira olmaysiz!")
        return
    if rem_id not in ADMIN_IDS:
        await message.answer(f"⚠️ <code>{rem_id}</code> adminlar ro'yxatida yo'q", parse_mode="HTML")
        return
    ADMIN_IDS.remove(rem_id)
    await message.answer(
        f"✅ <code>{rem_id}</code> o'chirildi!\n\n"
        f"<code>ADMIN_IDS={','.join(str(x) for x in ADMIN_IDS)}</code>",
        parse_mode="HTML"
    )


# ─── CHEK TASDIQLASH (Chek guruhidan) ─────────────────────────────────────────
@router.callback_query(F.data.startswith("check_confirm_"))
async def check_confirmed(callback: CallbackQuery, bot: Bot):
    """Admin chekni tasdiqladi → mijozga xabar → tasdiqlangan buyurtmalarga o'tadi"""
    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        await update_order_status(session, order_id, "confirmed")
        order = await get_order_with_items(session, order_id)

    # Stock -1 (faqat shu yerda!)
    try:
        from database.crud import decrease_stock
        async with AsyncSessionLocal() as session:
            for item in (order.items or []):
                if item.size:
                    await decrease_stock(session, item.product_id, item.size, item.quantity)
    except Exception as e:
        print(f"Stock decrease xatosi: {e}")

    # Chek guruhida tugmalarni o'chirish
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>To'lov tasdiqlandi</b> — {who}",
            parse_mode="HTML"
        )
    except:
        pass
    await callback.answer("✅ Tasdiqlandi!")

    # Mijozga xabar
    if order and order.user:
        try:
            from bot.handlers.order import PAYNET_LINK
            await bot.send_message(
                order.user.telegram_id,
                f"💳 <b>To'lovingiz tasdiqlandi!</b>\n\n"
                f"📦 Buyurtma #{order_id} pochtaga tayyorlanmoqda.\n"
                f"Tez orada jo'natiladi! ✅",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Mijozga xabar yuborishda xato: {e}")


@router.callback_query(F.data.startswith("check_reject_"))
async def check_rejected(callback: CallbackQuery, bot: Bot):
    """Chek noto'g'ri"""
    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n❌ <b>Chek rad etildi</b> — {who}",
            parse_mode="HTML"
        )
    except:
        pass
    await callback.answer("❌ Chek rad etildi")

    async with AsyncSessionLocal() as session:
        order = await get_order_with_items(session, order_id)

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"❌ <b>Chekingiz tasdiqlanmadi.</b>\n\n"
                f"Buyurtma #{order_id}\n"
                f"Iltimos, to'g'ri chek rasmini yuboring yoki "
                f"@formachi_admin bilan bog'laning.",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Mijozga xabar yuborishda xato: {e}")


# ─── POCHTAGA TOPSHIRILDI (Tasdiqlangan buyurtmalardan) ───────────────────────
@router.callback_query(F.data.startswith("admin_deliver_"))
async def admin_deliver(callback: CallbackQuery, bot: Bot):
    """
    Admin 'Pochtaga topshirildi' bosdi.
    - Order → delivering
    - Tugma yo'qoladi (1 martalik)
    - Mijozga xabar
    - 2-3 kundan keyin sharh so'rash (hozircha darhol)
    """
    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        await update_order_status(session, order_id, "delivering")
        order = await get_order_with_items(session, order_id)

    # Tugmalarni o'chirish
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n📦 <b>Pochtaga topshirildi</b> — {who}",
            parse_mode="HTML"
        )
    except:
        pass
    await callback.answer("📦 Pochtaga topshirildi!")

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"📦 <b>Buyurtma #{order_id} pochtaga topshirildi!</b>\n\n"
                f"📬 1-3 ish kuni ichida qo'lingizda bo'ladi.\n"
                f"Trek raqam tayyor bo'lgach yuboriladi.",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Mijozga xabar yuborishda xato: {e}")

        # Sharh so'rash — 2-3 kundan keyin ideal, hozircha asyncio delay bilan
        import asyncio
        async def delayed_review():
            await asyncio.sleep(60 * 60 * 48)  # 48 soat
            try:
                from bot.handlers.review import ask_review
                items = order.items or []
                prod_id = items[0].product_id if items else None
                await ask_review(bot, order.user.telegram_id, order_id, prod_id)
            except Exception as e:
                print(f"Review so'rovda xato: {e}")

        asyncio.create_task(delayed_review())


# ─── BUYURTMANI GURUHDA TASDIQLASH ────────────────────────────────────────────
@router.callback_query(F.data.startswith("admin_confirm_"))
async def admin_confirm_group(callback: CallbackQuery, bot: Bot):
    """
    Guruhda buyurtma tasdiqlash — 1 martalik.
    Tugmalar yo'qoladi. Mijozga faqat tasdiqlandi xabari.
    """
    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        # Allaqachon tasdiqlangan bo'lsa — qayta bosilmasin
        order = await get_order_with_items(session, order_id)
        if not order:
            await callback.answer("Buyurtma topilmadi!", show_alert=True)
            return
        if order.status.value != "pending":
            await callback.answer(f"Bu buyurtma allaqachon: {order.status.value}", show_alert=True)
            return
        await update_order_status(session, order_id, "confirmed")
        order = await get_order_with_items(session, order_id)

    # Tugmalarni o'chirish (1 martalik)
    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ <b>Tasdiqlandi</b> — {who}",
            parse_mode="HTML"
        )
    except:
        pass
    await callback.answer("✅ Tasdiqlandi!")

    # Mijozga faqat tasdiqlandi xabari — to'lov turiga qarab
    if order and order.user:
        pay_type = order.payment_type.value if order.payment_type else ""
        try:
            if pay_type == "card":
                # Card — chek allaqachon yuborilgan bo'lishi kerak
                # Faqat tasdiqlandi xabari
                await bot.send_message(
                    order.user.telegram_id,
                    f"✅ <b>Buyurtma #{order_id} tasdiqlandi!</b>\n\n"
                    f"Chekingiz qabul qilindi. Tez orada pochtaga tayyorlanadi 📦",
                    parse_mode="HTML"
                )
            elif pay_type == "credit":
                # Nasiya — faqat tasdiqlandi xabari, link yo'q
                await bot.send_message(
                    order.user.telegram_id,
                    f"✅ <b>Buyurtma #{order_id} tasdiqlandi!</b>\n\n"
                    f"Admin tez orada siz bilan bog'lanadi 📞",
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"Mijozga xabar yuborishda xato: {e}")


@router.callback_query(F.data.startswith("admin_cancel_"))
async def admin_cancel_group(callback: CallbackQuery, bot: Bot):
    order_id = int(callback.data.split("_")[2])
    who = f"@{callback.from_user.username}" if callback.from_user.username else callback.from_user.full_name

    async with AsyncSessionLocal() as session:
        await update_order_status(session, order_id, "cancelled")
        order = await get_order_with_items(session, order_id)

    try:
        await callback.message.edit_text(
            callback.message.text + f"\n\n❌ <b>Bekor qilindi</b> — {who}",
            parse_mode="HTML"
        )
    except:
        pass
    await callback.answer("❌ Bekor qilindi")

    if order and order.user:
        try:
            await bot.send_message(
                order.user.telegram_id,
                f"❌ <b>Buyurtma #{order_id} bekor qilindi.</b>\n\n"
                f"Savollar uchun @formachi_admin ga yozing.",
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Mijozga xabar yuborishda xato: {e}")
