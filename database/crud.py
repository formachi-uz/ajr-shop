from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import selectinload
from database.models import User, Category, Product, Order, OrderItem, OrderStatus, PaymentType


# ==================== USER ====================

async def get_or_create_user(session: AsyncSession, telegram_id: int, full_name: str, username: str = None):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=telegram_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def update_user_phone(session: AsyncSession, telegram_id: int, phone: str):
    await session.execute(
        update(User).where(User.telegram_id == telegram_id).values(phone=phone)
    )
    await session.commit()


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int):
    result = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return result.scalar_one_or_none()


# ==================== CATEGORY ====================

async def get_all_categories(session: AsyncSession):
    result = await session.execute(
        select(Category).where(Category.is_active == True).order_by(Category.sort_order)
    )
    return result.scalars().all()


async def create_category(session: AsyncSession, name: str, emoji: str, description: str, sort_order: int = 0):
    cat = Category(name=name, emoji=emoji, description=description, sort_order=sort_order)
    session.add(cat)
    await session.commit()
    return cat


async def get_category_by_id(session: AsyncSession, category_id: int):
    result = await session.execute(select(Category).where(Category.id == category_id))
    return result.scalar_one_or_none()


# ==================== PRODUCT ====================

async def get_products_by_category(session: AsyncSession, category_id: int):
    result = await session.execute(
        select(Product).where(
            Product.category_id == category_id,
            Product.is_active == True
        )
    )
    return result.scalars().all()


async def get_product_by_id(session: AsyncSession, product_id: int):
    result = await session.execute(select(Product).where(Product.id == product_id))
    return result.scalar_one_or_none()


async def create_product(session: AsyncSession, **kwargs):
    product = Product(**kwargs)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def update_product(session: AsyncSession, product_id: int, **kwargs):
    await session.execute(
        update(Product).where(Product.id == product_id).values(**kwargs)
    )
    await session.commit()


async def delete_product(session: AsyncSession, product_id: int):
    await session.execute(delete(Product).where(Product.id == product_id))
    await session.commit()


async def get_all_products(session: AsyncSession):
    result = await session.execute(
        select(Product).where(Product.is_active == True).order_by(Product.category_id)
    )
    return result.scalars().all()


# ==================== ORDER ====================

async def create_order(session: AsyncSession, user_id: int, payment_type: str,
                        delivery_address: str, comment: str = None):
    order = Order(
        user_id=user_id,
        payment_type=PaymentType(payment_type),
        delivery_address=delivery_address,
        comment=comment,
        status=OrderStatus.PENDING
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def add_order_item(session: AsyncSession, order_id: int, product_id: int,
                          quantity: int, price: float, size: str = None, player_name: str = None):
    item = OrderItem(
        order_id=order_id,
        product_id=product_id,
        quantity=quantity,
        price_at_order=price,
        size=size,
        player_name=player_name
    )
    session.add(item)
    await session.commit()
    return item


async def update_order_total(session: AsyncSession, order_id: int, total: float):
    await session.execute(
        update(Order).where(Order.id == order_id).values(total_price=total)
    )
    await session.commit()


async def get_order_with_items(session: AsyncSession, order_id: int):
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product),
                 selectinload(Order.user))
        .where(Order.id == order_id)
    )
    return result.scalar_one_or_none()


async def get_pending_orders(session: AsyncSession):
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items))
        .where(Order.status == OrderStatus.PENDING)
        .order_by(Order.created_at.desc())
    )
    return result.scalars().all()


async def get_all_orders(session: AsyncSession, limit: int = 50):
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.items))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def update_order_status(session: AsyncSession, order_id: int, status: str):
    await session.execute(
        update(Order).where(Order.id == order_id).values(status=OrderStatus(status))
    )
    await session.commit()


# ==================== PRODUCT STOCK ====================

SIZE_ORDER = {
    # Kiyim o'lchamlari
    "XS": 1, "S": 2, "M": 3, "L": 4, "XL": 5, "XXL": 6, "3XL": 7,
    # Poyabzal o'lchamlari
    "36": 10, "37": 11, "38": 12, "39": 13, "40": 14,
    "41": 15, "42": 16, "43": 17, "44": 18, "45": 19,
}


async def get_product_stocks(session: AsyncSession, product_id: int):
    """Mahsulotning barcha o'lchamlari (tartibli)"""
    from database.models import ProductStock
    result = await session.execute(
        select(ProductStock)
        .where(ProductStock.product_id == product_id)
        .order_by(ProductStock.sort_order)
    )
    return result.scalars().all()


async def set_product_stock(session: AsyncSession, product_id: int,
                             size: str, quantity: int):
    """O'lcham uchun miqdor qo'yish yoki yangilash"""
    from database.models import ProductStock
    result = await session.execute(
        select(ProductStock).where(
            ProductStock.product_id == product_id,
            ProductStock.size == size
        )
    )
    stock = result.scalar_one_or_none()
    sort_order = SIZE_ORDER.get(size, 99)

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


async def decrease_stock(session: AsyncSession, product_id: int,
                          size: str, qty: int = 1) -> bool:
    """
    Faqat admin tasdiqlasa chaqiriladi!
    Miqdorni kamaytiradi. Muvaffaqiyatli bo'lsa True qaytaradi.
    """
    from database.models import ProductStock
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


async def get_low_stock_products(session: AsyncSession, threshold: int = 2):
    """Kam qolgan mahsulotlar (admin ogohlantirishlari uchun)"""
    from database.models import ProductStock, Product
    from sqlalchemy.orm import selectinload
    result = await session.execute(
        select(ProductStock)
        .options(selectinload(ProductStock.product))
        .where(ProductStock.quantity > 0, ProductStock.quantity <= threshold)
        .order_by(ProductStock.quantity)
    )
    return result.scalars().all()


async def get_stock_report(session: AsyncSession):
    """To'liq ombor hisoboti"""
    from database.models import ProductStock, Product
    from sqlalchemy.orm import selectinload
    result = await session.execute(
        select(ProductStock)
        .options(selectinload(ProductStock.product))
        .order_by(ProductStock.product_id, ProductStock.sort_order)
    )
    return result.scalars().all()
