from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, func, text
from sqlalchemy.orm import selectinload

from database.models import (
    User, Category, Product, ProductStock,
    Order, OrderItem, OrderStatus, PaymentType,
    Review, CustomizationStatus
)


# ─── SIZE ORDER ───────────────────────────────────────────────────────────────

SIZE_ORDER = {
    "XS": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "XXL": 6, "3XL": 7,
    "36": 10, "37": 11, "38": 12, "39": 13, "40": 14,
    "41": 15, "42": 16, "43": 17, "44": 18, "45": 19,
}

MAIN_CATEGORY_BY_CATEGORY_ID = {
    1: "FORMLAR",
    2: "RETRO_FORMALAR",
    3: "BUTSIYLAR",
}

PRODUCT_TYPE_BY_CATEGORY_ID = {
    1: "jersey",
    2: "retro_jersey",
    3: "boots",
}


def _status_value(status) -> str:
    if isinstance(status, CustomizationStatus):
        return status.value
    return str(status or CustomizationStatus.NOT_AVAILABLE.value).lower()


def _normalize_product_payload(kwargs: dict) -> dict:
    category_id = int(kwargs.get("category_id") or 0)
    kwargs.setdefault("main_category", MAIN_CATEGORY_BY_CATEGORY_ID.get(category_id))
    kwargs.setdefault("product_type", PRODUCT_TYPE_BY_CATEGORY_ID.get(category_id))

    if "customization_status" not in kwargs:
        kwargs["customization_status"] = (
            CustomizationStatus.AVAILABLE_PAID.value if category_id == 1 else CustomizationStatus.NOT_AVAILABLE.value
        )

    status = _status_value(kwargs.get("customization_status"))
    status_map = {
        "paid": CustomizationStatus.AVAILABLE_PAID.value,
        "available_paid": CustomizationStatus.AVAILABLE_PAID.value,
        "bonus": CustomizationStatus.INCLUDED_BONUS.value,
        "free": CustomizationStatus.INCLUDED_BONUS.value,
        "included_bonus": CustomizationStatus.INCLUDED_BONUS.value,
        "no": CustomizationStatus.NOT_AVAILABLE.value,
        "none": CustomizationStatus.NOT_AVAILABLE.value,
        "not_available": CustomizationStatus.NOT_AVAILABLE.value,
    }
    kwargs["customization_status"] = status_map.get(status, CustomizationStatus.NOT_AVAILABLE.value)
    kwargs.setdefault("customization_price", 50000.0)
    kwargs["is_customizable"] = kwargs["customization_status"] in {
        CustomizationStatus.AVAILABLE_PAID.value,
        CustomizationStatus.INCLUDED_BONUS.value,
    }
    return kwargs


async def _safe_order_event(order_id: int, event_type: str, event_text: str, actor_telegram_id: int | None = None):
    try:
        from bot.handlers.automation_patch import add_order_event
        await add_order_event(order_id, event_type, event_text, actor_telegram_id)
    except Exception as exc:
        print(f"Order event skipped: {exc}")


async def _safe_schedule_job(job_type: str, delay_seconds: int, user_telegram_id: int | None, order_id: int):
    try:
        from bot.handlers.automation_patch import schedule_job
        await schedule_job(job_type, delay_seconds, user_telegram_id=user_telegram_id, order_id=order_id)
    except Exception as exc:
        print(f"Scheduled job skipped: {exc}")


# ─── USER ─────────────────────────────────────────────────────────────────────

async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    full_name: str,
    username: str = None
) -> User:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


async def update_user_phone(session: AsyncSession, telegram_id: int, phone: str):
    await session.execute(
        update(User).where(User.telegram_id == telegram_id).values(phone=phone)
    )
    await session.commit()


# ─── CATEGORY ─────────────────────────────────────────────────────────────────

async def get_all_categories(session: AsyncSession) -> list[Category]:
    result = await session.execute(
        select(Category)
        .where(Category.is_active == True)
        .order_by(Category.sort_order)
    )
    return list(result.scalars().all())


async def get_category_by_id(session: AsyncSession, category_id: int) -> Category | None:
    result = await session.execute(
        select(Category).where(Category.id == category_id)
    )
    return result.scalar_one_or_none()


async def create_category(
    session: AsyncSession,
    name: str,
    emoji: str = "📦",
    description: str = None,
    sort_order: int = 0
) -> Category:
    cat = Category(name=name, emoji=emoji, description=description, sort_order=sort_order)
    session.add(cat)
    await session.commit()
    await session.refresh(cat)
    return cat


# ─── PRODUCT ──────────────────────────────────────────────────────────────────

async def get_all_products(session: AsyncSession) -> list[Product]:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.stocks), selectinload(Product.reviews))
        .where(Product.is_active == True)
        .order_by(Product.id.desc())
    )
    return list(result.scalars().all())


async def get_products_by_category(session: AsyncSession, category_id: int) -> list[Product]:
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.stocks))
        .where(Product.category_id == category_id, Product.is_active == True)
        .order_by(Product.id.desc())
    )
    return list(result.scalars().all())


async def get_product_by_id(session: AsyncSession, product_id: int) -> Product | None:
    result = await session.execute(
        select(Product)
        .options(
            selectinload(Product.stocks),
            selectinload(Product.reviews),
            selectinload(Product.category)
        )
        .where(Product.id == product_id)
    )
    return result.scalar_one_or_none()


async def create_product(session: AsyncSession, **kwargs) -> Product:
    kwargs = _normalize_product_payload(kwargs)
    product = Product(**kwargs)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, product_id: int, **kwargs):
    if "category_id" in kwargs or "customization_status" in kwargs:
        kwargs = _normalize_product_payload(kwargs)
    await session.execute(
        update(Product).where(Product.id == product_id).values(**kwargs)
    )
    await session.commit()


async def delete_product(session: AsyncSession, product_id: int):
    """Soft delete"""
    await update_product(session, product_id, is_active=False)


# ─── STOCK ────────────────────────────────────────────────────────────────────

async def get_product_stocks(session: AsyncSession, product_id: int) -> list[ProductStock]:
    result = await session.execute(
        select(ProductStock)
        .where(ProductStock.product_id == product_id)
        .order_by(ProductStock.sort_order)
    )
    return list(result.scalars().all())


async def set_product_stock(
    session: AsyncSession,
    product_id: int,
    size: str,
    quantity: int
) -> ProductStock:
    result = await session.execute(
        select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
    )
    stock = result.scalar_one_or_none()
    sort_order = SIZE_ORDER.get(size.upper(), 99)

    if stock:
        stock.quantity = quantity
        stock.sort_order = sort_order
    else:
        stock = ProductStock(
            product_id=product_id,
            size=size,
            quantity=quantity,
            sort_order=sort_order
        )
        session.add(stock)
    await session.commit()
    return stock


async def decrease_stock(
    session: AsyncSession,
    product_id: int,
    size: str,
    qty: int = 1
) -> bool:
    """
    Admin buyurtmani tasdiqlaganda chaqiriladi.
    True = muvaffaqiyatli, False = yetarli zaxira yo'q.
    """
    result = await session.execute(
        select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
    )
    stock = result.scalar_one_or_none()
    if not stock or stock.quantity < qty:
        return False
    stock.quantity -= qty
    await session.commit()
    return True


async def reserve_stock(
    session: AsyncSession,
    product_id: int,
    size: str,
    qty: int = 1
) -> bool:
    """Buyurtma yaratilganda vaqtinchalik zaxiralash"""
    result = await session.execute(
        select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
    )
    stock = result.scalar_one_or_none()
    if not stock:
        return False
    if stock.available < qty:
        return False
    stock.reserved += qty
    await session.commit()
    return True


async def release_stock(
    session: AsyncSession,
    product_id: int,
    size: str,
    qty: int = 1
):
    """Buyurtma bekor qilinganda zaxirani qaytarish"""
    result = await session.execute(
        select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
    )
    stock = result.scalar_one_or_none()
    if stock:
        stock.reserved = max(0, stock.reserved - qty)
        await session.commit()


async def get_low_stock_products(
    session: AsyncSession,
    threshold: int = 2
) -> list[ProductStock]:
    result = await session.execute(
        select(ProductStock)
        .options(selectinload(ProductStock.product))
        .where(
            ProductStock.quantity > 0,
            ProductStock.quantity <= threshold,
            ProductStock.product.has(is_active=True)
        )
        .order_by(ProductStock.quantity)
    )
    return list(result.scalars().all())


async def get_stock_report(session: AsyncSession) -> list[ProductStock]:
    result = await session.execute(
        select(ProductStock)
        .options(selectinload(ProductStock.product))
        .join(Product)
        .where(Product.is_active == True)
        .order_by(ProductStock.product_id, ProductStock.sort_order)
    )
    return list(result.scalars().all())


# ─── ORDER ────────────────────────────────────────────────────────────────────

async def create_order(
    session: AsyncSession,
    user_id: int,
    payment_type: str,
    delivery_address: str,
    comment: str = None,
    customer_name: str = None,
    customer_phone: str = None,
) -> Order:
    order = Order(
        user_id=user_id,
        payment_type=PaymentType(payment_type),
        delivery_address=delivery_address,
        comment=comment,
        customer_name=customer_name,
        customer_phone=customer_phone,
        status=OrderStatus.PENDING
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    result = await session.execute(select(User.telegram_id).where(User.id == user_id))
    user_telegram_id = result.scalar_one_or_none()
    await _safe_order_event(order.id, "created", "Buyurtma yaratildi")
    if user_telegram_id:
        await _safe_schedule_job("payment_reminder", 2 * 60 * 60, int(user_telegram_id), order.id)
    return order


async def add_order_item(
    session: AsyncSession,
    order_id: int,
    product_id: int,
    quantity: int,
    price: float,
    size: str = None,
    player_name: str = None
) -> OrderItem:
    item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        price_at_order=price,
        size=size,
        player_name=player_name,
        back_print=player_name,
    )
    session.add(item)
    await session.commit()
    return item


async def update_order_total(session: AsyncSession, order_id: int, total: float):
    await session.execute(
        update(Order).where(Order.id == order_id).values(total_price=total)
    )
    await session.commit()


async def update_order_status(
    session: AsyncSession,
    order_id: int,
    status: str
):
    order = await get_order_with_items(session, order_id)
    if not order:
        return

    previous_status = order.status
    new_status = OrderStatus(status)

    await session.execute(
        update(Order).where(Order.id == order_id).values(status=new_status)
    )

    # Stock: faqat admin TASDIQLASH bosganida kamaytirish
    if previous_status == OrderStatus.PENDING and new_status == OrderStatus.CONFIRMED:
        for item in (order.items or []):
            if item.size:
                # Avval zaxirani bo'shat, keyin haqiqiy kamayt
                await release_stock(session, item.product_id, item.size, item.quantity)
                await decrease_stock(session, item.product_id, item.size, item.quantity)

    # Bekor qilinganda: zaxirani qaytarish
    if new_status == OrderStatus.CANCELLED:
        if previous_status == OrderStatus.PENDING:
            for item in (order.items or []):
                if item.size:
                    await release_stock(session, item.product_id, item.size, item.quantity)

    await session.commit()

    await _safe_order_event(
        order_id,
        "status",
        f"Status: {previous_status.value if previous_status else 'unknown'} -> {new_status.value}",
    )
    if new_status == OrderStatus.CONFIRMED and order.user:
        await _safe_schedule_job("review_check", 2 * 24 * 60 * 60, order.user.telegram_id, order_id)


async def get_order_with_items(session: AsyncSession, order_id: int) -> Order | None:
    result = await session.execute(
        select(Order)
        .options(
            selectinload(Order.items).selectinload(OrderItem.product),
            selectinload(Order.user)
        )
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def get_pending_orders(session: AsyncSession) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items))
        .where(Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


async def get_all_orders(session: AsyncSession, limit: int = 50) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_orders_by_status(session: AsyncSession, status: str) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items))
        .where(Order.status == OrderStatus(status))
        .order_by(Order.created_at.desc())
    )
    return list(result.scalars().all())


# ─── REVIEW ───────────────────────────────────────────────────────────────────

async def get_reviews(
    session: AsyncSession,
    product_id: int = None,
    limit: int = 20
) -> list[Review]:
    query = (
        select(Review)
        .options(selectinload(Review.user), selectinload(Review.product))
        .where(Review.is_visible == True)
    )
    if product_id:
        query = query.where(Review.product_id == product_id)
    query = query.order_by(Review.created_at.desc()).limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())
