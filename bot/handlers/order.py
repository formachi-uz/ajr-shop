import os
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.db import AsyncSessionLocal
from database.crud import (
    get_user_by_telegram_id, get_product_by_id,
    create_order, add_order_item,
    update_order_total, get_order_with_items, update_order_status
)
from bot.handlers.cart import get_cart, clear_cart, format_cart_text
from bot.keyboards.main_menu import main_menu_kb, cancel_kb
from bot.keyboards.admin_kb import order_actions_kb
from bot.middlewares.admin_check import is_admin, ADMIN_IDS, GROUP_CHAT_ID

router = Router()

PAYNET_LINK = (
    "https://app.paynet.uz/qr-online/00020101021140440012qr-online.uz"
    "01186r0C2GWSuXEb8UE7KQ0202115204531153038605802UZ5910AO'PAYNET'"
    "6008Tashkent610610002164280002uz0106PAYNET0208Toshkent80520012"
    "qr-online.uz03097120207070419marketing@paynet.uz6304A3D2"
)

# Guruh ID lar — env dan o'qiladi, default qiymatlar ham bor
GROUP_ORDERS_ID  = int(os.getenv("GROUP_CHAT_ID",    "-5194049252"))
GROUP_CHECKS_ID  = int(os.getenv("GROUP_CHECKS_ID",  "-5284654949"))
GLAVNIY_ADMIN_ID = int(os.getenv("GLAVNIY_ADMIN_ID", "8156792282"))

PAYMENT_EMOJI = {
    "card":   "💳 Karta / Paynet",
    "credit": "🤝 Uzum Nasiya",
}
STATUS_TEXT = {
    "pending":    "⏳ Kutilmoqda",
    "confirmed":  "✅ Tasdiqlangan",
    "delivering": "📦 Pochtaga topshirildi",
    "done":       "✔️ Yakunlandi",
    "cancelled":  "❌ Bekor qilindi",
}


def payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Karta / Paynet", callback_data="pay_card")],
        [InlineKeyboardButton(text="🤝 Uzum Nasiya",    callback_data="pay_credit")],
        [InlineKeyboardButton(text="❌ Bekor qilish",   callback_data="pay_cancel")],
    ])


def confirm_cart_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash",  callback_data="confirm_cart"),
        InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="edit_cart"),
    ]])


class OrderState(StatesGroup):
    waiting_name    = State()
    waiting_phone   = State()
    waiting_address = State()
    waiting_confirm = State()
    waiting_payment = State()


class CheckState(StatesGroup):
    waiting_check_photo = State()


# ─── Cancel ───────────────────────────────────────────────────────────────────
@router.message(F.text == "❌ Bekor qilish")
async def cancel_order_flow(message: Message, state: FSMContext):
    await state.clear()
    admin = is_admin(message.from_user.id)
    await message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb(is_admin=admin))


# ─── Step 1: Ism ─────────────────────────────────────────────────────────────
@router.message(OrderState.waiting_name)
async def handle_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer(
            "⚠️ Ism juda qisqa. To'liq ismingizni kiriting:\n"
            "<i>Masalan: Musurmon Husanov</i>",
            parse_mode="HTML"
        )
        return
    await state.update_data(customer_name=name)
    await state.set_state(OrderState.waiting_phone)
    await message.answer(
        f"👤 Ism: <b>{name}</b>\n\n"
        "📱 <b>Telefon raqamingizni yozing:</b>\n"
        "<i>Masalan: +998 93 107 13 08</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


# ─── Step 2: Telefon ──────────────────────────────────────────────────────────
@router.message(OrderState.waiting_phone)
async def handle_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if message.contact:
        phone = message.contact.phone_number
    if len(phone) < 7:
        await message.answer("⚠️ Telefon raqam noto'g'ri. Qaytadan kiriting:")
        return
    await state.update_data(customer_phone=phone)
    await state.set_state(OrderState.waiting_address)
    await message.answer(
        f"📱 Telefon: <b>{phone}</b>\n\n"
        "📍 <b>Yetkazish manzilingizni yozing:</b>\n"
        "<i>Viloyat, tuman va aniq joyni kiriting\n"
        "Masalan: Samarqand viloyati, Tayloq tumani, Musurmon</i>",
        parse_mode="HTML",
        reply_markup=cancel_kb()
    )


# ─── Step 3: Manzil ───────────────────────────────────────────────────────────
@router.message(OrderState.waiting_address)
async def handle_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if len(address) < 8:
        await message.answer(
            "⚠️ Manzil juda qisqa. Viloyat va tumanni ham yozing:\n"
            "<i>Masalan: Samarqand viloyati, Tayloq tumani, Musurmon</i>",
            parse_mode="HTML"
        )
        return
    await state.update_data(address=address)
    await state.set_state(OrderState.waiting_confirm)

    data      = await state.get_data()
    cart      = get_cart(message.from_user.id)
    cart_text = format_cart_text(cart)

    summary = (
        f"📋 <b>Buyurtmangizni tekshiring:</b>\n"
        f"{'─' * 28}\n"
        f"👤 {data.get('customer_name')}\n"
        f"📱 {data.get('customer_phone')}\n"
        f"📍 {address}\n"
        f"{'─' * 28}\n"
        f"{cart_text}\n"
        f"{'─' * 28}\n"
        "✅ Ma'lumotlar to'g'rimi?"
    )
    await message.answer(summary, parse_mode="HTML", reply_markup=confirm_cart_kb())


# ─── Step 4: Tasdiqlash ───────────────────────────────────────────────────────
@router.callback_query(F.data == "confirm_cart")
async def confirm_cart_cb(callback: CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.waiting_payment)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "💳 <b>To'lov usulini tanlang:</b>\n\n"
        "💳 <b>Karta / Paynet</b> — to'lov linki yuboriladi\n"
        "🤝 <b>Uzum Nasiya</b> — admin tez orada aloqaga chiqadi\n\n"
        "📦 <i>Viloyatlarga BTS pochta: 20,000 - 30,000 so'm</i>",
        parse_mode="HTML",
        reply_markup=payment_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "edit_cart")
async def edit_cart_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    from bot.handlers.cart import cart_inline_kb
    cart = get_cart(callback.from_user.id)
    await callback.message.edit_text(
        format_cart_text(cart),
        parse_mode="HTML",
        reply_markup=cart_inline_kb(cart)
    )
    await callback.answer()


@router.callback_query(F.data == "pay_cancel")
async def pay_cancel_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    admin = is_admin(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ Bekor qilindi.", reply_markup=main_menu_kb(is_admin=admin))
    await callback.answer()


# ─── Step 5: To'lov ───────────────────────────────────────────────────────────
@router.callback_query(F.data.in_({"pay_card", "pay_credit"}))
async def handle_payment(callback: CallbackQuery, state: FSMContext, bot: Bot):
    payment_type   = "card" if callback.data == "pay_card" else "credit"
    data           = await state.get_data()
    customer_name  = data.get("customer_name", callback.from_user.full_name)
    customer_phone = data.get("customer_phone", "—")
    address        = data.get("address", "—")
    cart           = get_cart(callback.from_user.id)
    admin          = is_admin(callback.from_user.id)

    if not cart:
        await state.clear()
        await callback.message.answer("❌ Savat bo'sh!", reply_markup=main_menu_kb(is_admin=admin))
        await callback.answer()
        return

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, callback.from_user.id)
        if not user:
            await callback.message.answer("Xato! /start bosing.")
            await callback.answer()
            return

        order = await create_order(
            session,
            user_id=user.id,
            payment_type=payment_type,
            delivery_address=address,
            comment=f"Ism: {customer_name} | Tel: {customer_phone}"
        )

        total = 0
        for item in cart:
            await add_order_item(
                session,
                order_id=order.id,
                product_id=item["product_id"],
                quantity=item["qty"],
                price=item["price"],
                size=item.get("size"),
                player_name=item.get("back_print") or item.get("player_name")
            )
            total += item["price"] * item["qty"]

        await update_order_total(session, order.id, total)

    cart_snapshot = list(cart)
    clear_cart(callback.from_user.id)
    await state.clear()

    payment_label = PAYMENT_EMOJI.get(payment_type, "")

    cart_lines = ""
    for item in cart_snapshot:
        extra = ""
        if item.get("size"):        extra += f" ({item['size']})"
        if item.get("back_print"):  extra += f" | ✍️ {item['back_print']}"
        if item.get("player_name"): extra += f" | ✍️ {item['player_name']}"
        cart_lines += f"• {item['name']}{extra} × {item['qty']} = {int(item['price'] * item['qty']):,} so'm\n"

    base_text = (
        f"✅ <b>Buyurtmangiz qabul qilindi!</b>\n"
        f"{'─' * 28}\n"
        f"🔢 Buyurtma: <b>#{order.id}</b>\n"
        f"👤 {customer_name} | 📱 {customer_phone}\n"
        f"📍 {address}\n"
        f"💳 {payment_label}\n"
        f"{'─' * 28}\n"
        f"{cart_lines}"
        f"{'─' * 28}\n"
        f"💰 <b>Jami: {int(total):,} so'm</b>"
    )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("✅", reply_markup=main_menu_kb(is_admin=admin))

    if payment_type == "card":
        await callback.message.answer(
            base_text + "\n\n💳 <b>To'lovni amalga oshiring:</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="💳 Paynet orqali to'lash", url=PAYNET_LINK)
            ]])
        )
        # Chek so'rash
        await state.set_state(CheckState.waiting_check_photo)
        await state.update_data(check_order_id=order.id)
        await callback.message.answer(
            "📸 <b>To'lov chekini yuboring:</b>\n\n"
            "To'lovdan so'ng chek rasmini shu yerga yuboring.\n"
            "<i>Chek tasdiqlangach buyurtmangiz rasmiylashadi ✅</i>",
            parse_mode="HTML"
        )
    else:
        # Nasiya — faqat xabar, bot aralashmaydi
        await callback.message.answer(
            base_text + "\n\n🤝 <b>Uzum Nasiya</b>\n\n"
            "Buyurtmangiz qabul qilindi!\n"
            "Admin tez orada siz bilan bog'lanib nasiya shartlarini tushuntiradi 📞",
            parse_mode="HTML"
        )

    await callback.answer()

    # ─── Guruhga + Glavniy adminga xabar ─────────────────────────────────────
    nasiya_note = "\n⚠️ <b>UZUM NASIYA — aloqaga chiqing!</b>" if payment_type == "credit" else ""
    admin_text = (
        f"🆕 <b>YANGI BUYURTMA #{order.id}</b>{nasiya_note}\n"
        f"{'─' * 28}\n"
        f"👤 {customer_name}"
        f"{'  @' + callback.from_user.username if callback.from_user.username else ''}\n"
        f"🆔 <code>{callback.from_user.id}</code>\n"
        f"📱 {customer_phone}\n"
        f"{'─' * 28}\n"
        f"📍 {address}\n"
        f"💳 {payment_label}\n"
        f"{'─' * 28}\n"
        f"{cart_lines}"
        f"{'─' * 28}\n"
        f"💰 <b>JAMI: {int(total):,} so'm</b>"
    )

    targets = list(set([GROUP_ORDERS_ID, GLAVNIY_ADMIN_ID]))
    for target_id in targets:
        try:
            # Mahsulot rasmlari
            for item in cart_snapshot:
                async with AsyncSessionLocal() as session:
                    product = await get_product_by_id(session, item["product_id"])
                if product and product.photo_url:
                    s   = f" ({item['size']})"      if item.get("size")       else ""
                    b   = f" | ✍️ {item['back_print']}"  if item.get("back_print") else ""
                    p   = f" | ✍️ {item['player_name']}" if item.get("player_name") else ""
                    cap = f"🖼 <b>{product.name}</b>{s}{b}{p}\n💰 {int(item['price']):,} so'm × {item['qty']}"
                    await bot.send_photo(target_id, photo=product.photo_url,
                                         caption=cap, parse_mode="HTML")
            # Asosiy xabar + tugmalar
            await bot.send_message(target_id, admin_text, parse_mode="HTML",
                                   reply_markup=order_actions_kb(order.id))
        except Exception as e:
            print(f"❌ Target {target_id}ga xabar yuborishda xato: {e}")


# ─── Chek qabul qilish ────────────────────────────────────────────────────────
@router.message(CheckState.waiting_check_photo)
async def receive_check(message: Message, state: FSMContext, bot: Bot):
    data     = await state.get_data()
    order_id = data.get("check_order_id")

    if not message.photo and not message.document:
        await message.answer(
            "📸 Iltimos, chek <b>rasmini</b> yuboring.\n"
            "<i>Skrinshot yoki foto bo'lishi mumkin</i>",
            parse_mode="HTML"
        )
        return

    await state.clear()
    await message.answer(
        "✅ <b>Chek qabul qilindi!</b>\n\n"
        "Admin chekni tekshirgach buyurtmangiz tasdiqlanadi.\n"
        "Rahmat! ⚽",
        parse_mode="HTML"
    )

    caption = (
        f"💳 <b>YANGI CHEK — Buyurtma #{order_id}</b>\n"
        f"{'─' * 24}\n"
        f"👤 {message.from_user.full_name}"
        f"{'  @' + message.from_user.username if message.from_user.username else ''}\n"
        f"🆔 <code>{message.from_user.id}</code>"
    )

    from bot.keyboards.admin_kb import check_confirm_kb
    kb = check_confirm_kb(order_id)

    # Chek guruhiga yuborish — xato bo'lsa adminlarga to'g'ridan
    file_id  = message.photo[-1].file_id if message.photo else None
    doc_id   = message.document.file_id if message.document else None
    is_photo = bool(file_id)

    sent_ok = False

    # 1. Chek guruhiga urinib ko'ramiz
    try:
        if is_photo:
            await bot.send_photo(GROUP_CHECKS_ID, photo=file_id,
                                 caption=caption, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_document(GROUP_CHECKS_ID, document=doc_id,
                                    caption=caption, parse_mode="HTML", reply_markup=kb)
        sent_ok = True
        print(f"✅ Chek guruhiga yuborildi: {GROUP_CHECKS_ID}")
    except Exception as e:
        print(f"⚠️ Chek guruhiga yuborishda xato ({GROUP_CHECKS_ID}): {e}")

    # 2. Adminlarga to'g'ridan yuborish (552003748 ham chek admini)
    check_targets = list(set([GLAVNIY_ADMIN_ID, 552003748]))
    for admin_id in check_targets:
        try:
            if is_photo:
                await bot.send_photo(admin_id, photo=file_id,
                                     caption=caption, parse_mode="HTML", reply_markup=kb)
            else:
                await bot.send_document(admin_id, document=doc_id,
                                        caption=caption, parse_mode="HTML", reply_markup=kb)
            sent_ok = True
            print(f"✅ Chek adminga yuborildi: {admin_id}")
        except Exception as e:
            print(f"⚠️ Admin {admin_id}ga yuborishda xato: {e}")

    if not sent_ok:
        await message.answer(
            "⚠️ Chek yuborishda xato yuz berdi.\n"
            "Iltimos, to'g'ridan @formachi_admin ga yuboring.",
            parse_mode="HTML"
        )


# ─── My orders ────────────────────────────────────────────────────────────────
@router.message(F.text == "📦 Buyurtmalarim")
async def my_orders(message: Message):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from database.models import Order

    async with AsyncSessionLocal() as session:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            await message.answer("Hali buyurtma yo'q.")
            return
        result = await session.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(10)
        )
        orders = result.scalars().all()
        # Session ichida ma'lumot olish
        orders_data = []
        for o in orders:
            orders_data.append({
                "id": o.id,
                "status": o.status.value,
                "total": o.total_price,
                "payment": o.payment_type.value if o.payment_type else "",
                "date": o.created_at.strftime('%d.%m.%Y %H:%M')
            })

    if not orders_data:
        await message.answer("📦 Hali buyurtma yo'q.\n\n🛍 Katalogdan xarid qiling!")
        return

    text = "📦 <b>Sizning buyurtmalaringiz:</b>\n\n"
    for o in orders_data:
        status  = STATUS_TEXT.get(o["status"], o["status"])
        payment = PAYMENT_EMOJI.get(o["payment"], "")
        text += (
            f"🔢 <b>#{o['id']}</b>  {status}\n"
            f"💰 {int(o['total']):,} so'm  {payment}\n"
            f"📅 {o['date']}\n\n"
        )
    await message.answer(text, parse_mode="HTML")
