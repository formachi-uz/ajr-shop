from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float,
    Boolean, DateTime, ForeignKey, Enum, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DELIVERING = "delivering"
    DONE = "done"
    CANCELLED = "cancelled"


class PaymentType(str, enum.Enum):
    CASH = "cash"
    CARD = "card"
    CREDIT = "credit"


class CustomizationStatus(str, enum.Enum):
    AVAILABLE_PAID = "available_paid"
    INCLUDED_BONUS = "included_bonus"
    NOT_AVAILABLE = "not_available"


def _status_value(status) -> str:
    if isinstance(status, CustomizationStatus):
        return status.value
    return str(status or "not_available").lower()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String(255))
    username = Column(String(255), nullable=True)
    phone = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    orders = relationship("Order", back_populates="user")
    reviews = relationship("Review", back_populates="user")


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    emoji = Column(String(10), default="📦")
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    products = relationship("Product", back_populates="category")


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)

    slug = Column(String(255), nullable=True, unique=True, index=True)
    main_category = Column(String(50), nullable=True, index=True)
    product_type = Column(String(50), nullable=True, index=True)
    team = Column(String(100), nullable=True, index=True)
    season = Column(String(50), nullable=True)
    kit_type = Column(String(50), nullable=True)
    league = Column(String(100), nullable=True)
    brand = Column(String(100), nullable=True, index=True)
    model = Column(String(100), nullable=True)
    tags = Column(Text, nullable=True)
    gallery = Column(Text, nullable=True)

    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0)
    photo_url = Column(String(500), nullable=True)
    is_active = Column(Boolean, default=True)
    in_stock = Column(Boolean, default=True)

    customization_status = Column(String(30), default=CustomizationStatus.NOT_AVAILABLE.value, nullable=False)
    customization_price = Column(Float, default=50000.0)

    is_featured = Column(Boolean, default=False)
    is_top_forma = Column(Boolean, default=False)
    is_premium_boot = Column(Boolean, default=False)
    is_customizable = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category = relationship("Category", back_populates="products")
    stocks = relationship(
        "ProductStock",
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    order_items = relationship("OrderItem", back_populates="product")
    reviews = relationship("Review", back_populates="product")

    @property
    def final_price(self) -> float:
        if self.discount_percent and self.discount_percent > 0:
            return self.price * (1 - self.discount_percent / 100)
        return self.price

    @property
    def avg_rating(self) -> float:
        visible = [r for r in self.reviews if r.is_visible]
        if not visible:
            return 0.0
        return round(sum(r.rating for r in visible) / len(visible), 1)

    @property
    def total_stock(self) -> int:
        return sum(s.quantity for s in self.stocks)

    @property
    def stock_status(self) -> str:
        total = self.total_stock
        if total == 0:
            return "out_of_stock"
        if total <= 3:
            return "low_stock"
        return "in_stock"

    def get_stock(self, size: str) -> int:
        for s in self.stocks:
            if s.size == size:
                return s.quantity
        return 0

    def available_sizes(self) -> list:
        return [s for s in self.stocks if s.quantity > 0]

    def can_customize(self) -> bool:
        return _status_value(self.customization_status) in {
            CustomizationStatus.AVAILABLE_PAID.value,
            CustomizationStatus.INCLUDED_BONUS.value,
            "available_paid",
            "included_bonus",
        }

    def customization_extra_price(self) -> float:
        if _status_value(self.customization_status) == CustomizationStatus.AVAILABLE_PAID.value:
            return self.customization_price or 50000.0
        return 0.0


class ProductStock(Base):
    __tablename__ = "product_stocks"
    __table_args__ = (UniqueConstraint("product_id", "size", name="uq_product_size"),)

    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    size = Column(String(20), nullable=False)
    quantity = Column(Integer, default=0, nullable=False)
    reserved = Column(Integer, default=0, nullable=False)
    sort_order = Column(Integer, default=0)

    product = relationship("Product", back_populates="stocks")

    @property
    def available(self) -> int:
        return max(0, self.quantity - self.reserved)


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False)
    payment_type = Column(Enum(PaymentType), nullable=False)
    delivery_address = Column(Text, nullable=False)
    comment = Column(Text, nullable=True)
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(20), nullable=True)
    total_price = Column(Float, default=0.0)
    receipt_file_id = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False, default=1)
    price_at_order = Column(Float, nullable=False)
    size = Column(String(20), nullable=True)
    player_name = Column(String(100), nullable=True)
    back_print = Column(String(100), nullable=True)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")

    @property
    def subtotal(self) -> float:
        return self.price_at_order * self.quantity


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    rating = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    is_visible = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reviews")
    product = relationship("Product", back_populates="reviews")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
