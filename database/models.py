from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float,
    Boolean, DateTime, ForeignKey, Enum, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class OrderStatus(str, enum.Enum):
    PENDING    = "pending"
    CONFIRMED  = "confirmed"
    DELIVERING = "delivering"
    DONE       = "done"
    CANCELLED  = "cancelled"

class PaymentType(str, enum.Enum):
    CASH   = "cash"
    CARD   = "card"
    CREDIT = "credit"

class User(Base):
    __tablename__ = "users"
    id          = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    full_name   = Column(String(255))
    username    = Column(String(255), nullable=True)
    phone       = Column(String(20), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    orders  = relationship("Order", back_populates="user")
    reviews = relationship("Review", back_populates="user")

class Category(Base):
    __tablename__ = "categories"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(255), nullable=False)
    emoji       = Column(String(10), default="📦")
    description = Column(Text, nullable=True)
    is_active   = Column(Boolean, default=True)
    sort_order  = Column(Integer, default=0)

    products = relationship("Product", back_populates="category")

class Product(Base):
    __tablename__ = "products"
    id               = Column(Integer, primary_key=True)
    category_id      = Column(Integer, ForeignKey("categories.id"))
    
    # --- NEW METADATA FIELDS FOR FILTERING ---
    team             = Column(String(100), nullable=True, index=True) # e.g., 'Real Madrid'
    season           = Column(String(50), nullable=True)  # e.g., '23/24'
    kit_type         = Column(String(50), nullable=True)  # e.g., 'Home', 'Away', 'Third'
    league           = Column(String(100), nullable=True) # e.g., 'La Liga', 'National'
    
    # --- NEW CUSTOMIZATION FIELDS ---
    is_customizable  = Column(Boolean, default=False)
    customization_price = Column(Float, default=50000.0)
    
    name             = Column(String(255), nullable=False)
    description      = Column(Text, nullable=True)
    price            = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0)
    photo_url        = Column(String(500), nullable=True)
    is_active        = Column(Boolean, default=True)
    in_stock         = Column(Boolean, default=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    category    = relationship("Category", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    reviews     = relationship("Review", back_populates="product")
    stocks      = relationship("ProductStock", back_populates="product",
                               cascade="all, delete-orphan")

    @property
    def final_price(self):
        if self.discount_percent > 0:
            return self.price * (1 - self.discount_percent / 100)
        return self.price

    @property
    def avg_rating(self):
        if not self.reviews:
            return 0
        return round(sum(r.rating for r in self.reviews) / len(self.reviews), 1)

    def get_stock(self, size: str) -> int:
        for s in self.stocks:
            if s.size == size:
                return s.quantity
        return 0

    def available_sizes(self):
        return [s for s in self.stocks if s.quantity > 0]

# ... [Keep ProductStock, Order, OrderItem, Review, AdminUser exactly the same] ...
