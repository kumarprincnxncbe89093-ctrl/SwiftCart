from __future__ import annotations

import logging
import os
import random
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
from pathlib import Path
from re import search, sub
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import bcrypt
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from werkzeug.security import check_password_hash

from backend.imported_product_benchmarks import IMPORTED_PRODUCT_MARKET_DATA


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "database.db"
DEFAULT_SQLITE_URL = f"sqlite:///{DATABASE_PATH}"
logger = logging.getLogger(__name__)
ENV_NAME = (os.getenv("FLASK_ENV") or "development").strip().lower()
IS_PRODUCTION = ENV_NAME == "production"


def _env_int(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r. Falling back to %s.", name, raw_value, default)
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def _default_seed_value(value: str) -> str:
    return "" if IS_PRODUCTION else value


def _sanitize_benchmark_note(value: str) -> str:
    note = str(value or "").strip()
    if not note:
        return "Current India market pricing reference, Mar 2026"
    replacements = {
        "Amazon India": "leading India marketplace",
        "Amazon": "leading marketplace",
        "Flipkart": "leading marketplace",
        "Smartprix and Amazon India": "India market data sources",
    }
    for old_value, new_value in replacements.items():
        note = note.replace(old_value, new_value)
    return note


def _normalize_database_url(raw_url: str | None) -> str:
    url = str(raw_url or "").strip().strip("'\"")
    if "\n" in url:
        url = url.splitlines()[0].strip()
    for prefix in ("DATABASE_URL=", "DATABASE_PRIVATE_URL=", "DATABASE_PUBLIC_URL="):
        if url.startswith(prefix):
            url = url.split("=", 1)[1].strip().strip("'\"")
    matched_url = search(r"(postgres(?:ql)?://\S+|postgresql\+psycopg://\S+|sqlite:///\S+)", url)
    if matched_url:
        url = matched_url.group(1).strip().strip("'\"")
    for marker in (
        "SECRET_KEY=",
        "FLASK_ENV=",
        "FLASK_DEBUG=",
        "FLASK_HOST=",
        "DB_POOL_SIZE=",
        "DB_MAX_OVERFLOW=",
        "DB_POOL_RECYCLE=",
        "GUNICORN_BIND=",
        "GUNICORN_WORKERS=",
        "GUNICORN_THREADS=",
        "GUNICORN_TIMEOUT=",
        "GUNICORN_KEEPALIVE=",
        "GUNICORN_GRACEFUL_TIMEOUT=",
    ):
        if marker in url:
            url = url.split(marker, 1)[0].strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _ensure_postgres_sslmode(url: str) -> str:
    if not url or url.startswith("sqlite"):
        return url

    parts = urlsplit(url)
    query_items = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_items.setdefault("sslmode", os.getenv("PGSSLMODE", "require").strip() or "require")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_items), parts.fragment))


def _looks_like_placeholder_database_url(url: str) -> bool:
    lowered = url.lower()
    placeholder_tokens = ("user", "password", "host", "dbname")
    if all(token in lowered for token in placeholder_tokens):
        return True
    if "reference to" in lowered and ("database_url" in lowered or "postgres" in lowered):
        return True
    return (
        url.startswith("${{")
        or url.startswith("{{")
        or lowered in {"postgres://", "postgresql://", "postgresql+psycopg://"}
        or ("railway.internal" in lowered and "@" not in url)
    )


def _usable_database_url_from_env(env_key: str) -> str | None:
    candidate = _normalize_database_url(os.getenv(env_key))
    if not candidate:
        return None
    if _looks_like_placeholder_database_url(candidate):
        logger.warning("Ignoring placeholder %s value.", env_key)
        return None
    return candidate


def _build_database_url_from_pg_env() -> str | None:
    host = (os.getenv("PGHOST") or "").strip()
    port = (os.getenv("PGPORT") or "").strip()
    user = (os.getenv("PGUSER") or "").strip()
    password = (os.getenv("PGPASSWORD") or "").strip()
    database = (os.getenv("PGDATABASE") or "").strip()

    if not all((host, port, user, password, database)):
        return None

    try:
        port_value = int(port)
    except ValueError:
        logger.warning("Ignoring PGHOST/PGPORT variables because PGPORT is not a valid integer.")
        return None

    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=host,
        port=port_value,
        database=database,
    ).render_as_string(hide_password=False)


def _resolve_database_url() -> str:
    raw_database_url = _usable_database_url_from_env("DATABASE_URL")
    if raw_database_url:
        return raw_database_url

    for env_key in ("DATABASE_PRIVATE_URL", "DATABASE_PUBLIC_URL"):
        candidate = _usable_database_url_from_env(env_key)
        if candidate:
            return candidate

    built_from_pg_env = _build_database_url_from_pg_env()
    if built_from_pg_env:
        return built_from_pg_env

    if os.getenv("DATABASE_URL"):
        logger.warning(
            "Ignoring DATABASE_URL value that does not look usable. On Railway, set DATABASE_URL to a "
            "reference like ${{Postgres.DATABASE_URL}} or expose PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE."
        )

    return DEFAULT_SQLITE_URL


DATABASE_URL = _ensure_postgres_sslmode(_resolve_database_url())
OWNER_EMAIL = (os.getenv("OWNER_EMAIL") or _default_seed_value("owner@demo.com")).strip().lower()
OWNER_PASSWORD = (os.getenv("OWNER_PASSWORD") or _default_seed_value("123456")).strip()
DEMO_OWNER_EMAIL = (os.getenv("DEMO_OWNER_EMAIL") or _default_seed_value("owner@demo.com")).strip().lower()
DEMO_OWNER_PASSWORD = (os.getenv("DEMO_OWNER_PASSWORD") or _default_seed_value("123456")).strip()
MERCHANT_DEMO_EMAIL = (os.getenv("MERCHANT_DEMO_EMAIL") or _default_seed_value("merchant@demo.com")).strip().lower()
MERCHANT_DEMO_PASSWORD = (os.getenv("MERCHANT_DEMO_PASSWORD") or _default_seed_value("123456")).strip()
BUYER_DEMO_EMAIL = (os.getenv("BUYER_DEMO_EMAIL") or _default_seed_value("user@demo.com")).strip().lower()
BUYER_DEMO_PASSWORD = (os.getenv("BUYER_DEMO_PASSWORD") or _default_seed_value("123456")).strip()
ENABLE_DEMO_MERCHANT = _env_flag("ENABLE_DEMO_MERCHANT", not IS_PRODUCTION)
ENABLE_DEMO_LOGINS = _env_flag("ENABLE_DEMO_LOGINS", not IS_PRODUCTION)
ROTATE_SEEDED_PASSWORDS = _env_flag("ROTATE_SEEDED_PASSWORDS", False)
ALLOW_SQLITE_IN_PRODUCTION = _env_flag("ALLOW_SQLITE_IN_PRODUCTION", False)
BCRYPT_ROUNDS = max(_env_int("BCRYPT_ROUNDS", 10), 4)


def is_bcrypt_hash(value: str | None) -> bool:
    return str(value or "").strip().startswith("$2")


def hash_password(password: str) -> str:
    raw_password = str(password or "")
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(stored_hash: str | None, password: str) -> bool:
    stored_value = str(stored_hash or "").strip()
    raw_password = str(password or "")
    if not stored_value:
        return False
    if is_bcrypt_hash(stored_value):
        try:
            return bcrypt.checkpw(raw_password.encode("utf-8"), stored_value.encode("utf-8"))
        except ValueError:
            return False
    return check_password_hash(stored_value, raw_password)


def preserve_seeded_password(user: User, seeded_password: str) -> None:
    stored_value = str(getattr(user, "password_hash", "") or "").strip()
    if ROTATE_SEEDED_PASSWORDS or not stored_value:
        user.password_hash = hash_password(seeded_password)
        user.password_changed_at = datetime.utcnow()
        return
    if not user.password_changed_at:
        user.password_changed_at = user.created_at or datetime.utcnow()


def require_persistent_database_configuration() -> None:
    if not IS_PRODUCTION or ALLOW_SQLITE_IN_PRODUCTION:
        return
    if not DATABASE_URL.startswith("sqlite"):
        return
    raise RuntimeError(
        "Production startup refused because no persistent PostgreSQL database is configured. "
        "Set DATABASE_URL/DATABASE_PRIVATE_URL/PGHOST... to a real Postgres connection, or "
        "set ALLOW_SQLITE_IN_PRODUCTION=1 only if you intentionally want non-persistent SQLite storage."
    )

SQLALCHEMY_ENGINE_KWARGS = {
    "future": True,
    "pool_pre_ping": True,
}

if DATABASE_URL.startswith("sqlite"):
    SQLALCHEMY_ENGINE_KWARGS["connect_args"] = {"check_same_thread": False}
else:
    SQLALCHEMY_ENGINE_KWARGS.update(
        {
            "pool_size": _env_int("DB_POOL_SIZE", 12),
            "max_overflow": _env_int("DB_MAX_OVERFLOW", 24),
            "pool_recycle": _env_int("DB_POOL_RECYCLE", 1800),
        }
    )

def _create_engine_with_fallback(database_url: str):
    try:
        return create_engine(database_url, **SQLALCHEMY_ENGINE_KWARGS), database_url
    except (ArgumentError, ValueError) as exc:
        if database_url == DEFAULT_SQLITE_URL:
            raise
        logger.warning(
            "Invalid DATABASE_URL %r. Falling back to local SQLite so the app can boot: %s",
            database_url,
            exc,
        )
        fallback_kwargs = {
            "future": True,
            "pool_pre_ping": True,
            "connect_args": {"check_same_thread": False},
        }
        return create_engine(DEFAULT_SQLITE_URL, **fallback_kwargs), DEFAULT_SQLITE_URL


engine, ACTIVE_DATABASE_URL = _create_engine_with_fallback(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
_db_initialized = False


def _uses_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    if not ACTIVE_DATABASE_URL.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA foreign_keys=ON;")
    cursor.close()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    banner_title: Mapped[str] = mapped_column(String(180), default="", nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")
    discounts: Mapped[list["CategoryDiscount"]] = relationship(back_populates="category")


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), unique=True, nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    original_price: Mapped[float] = mapped_column(Float, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    reviews_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tag: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    highlights: Mapped[str] = mapped_column(Text, default="", nullable=False)
    specifications: Mapped[str] = mapped_column(Text, default="", nullable=False)
    secondary_categories: Mapped[str] = mapped_column(Text, default="", nullable=False)
    delivery_note: Mapped[str] = mapped_column(
        String(255), default="Delivery in 2-5 business days", nullable=False
    )
    featured: Mapped[bool] = mapped_column(default=False, nullable=False)
    deal_of_the_day: Mapped[bool] = mapped_column(default=False, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    seller_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(40), default="owner", nullable=False)

    category: Mapped[Category] = relationship(back_populates="products")
    seller: Mapped["User | None"] = relationship(back_populates="listed_products", foreign_keys=[seller_id])
    reviews: Mapped[list["Review"]] = relationship(back_populates="product")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    mobile: Mapped[str] = mapped_column(String(40), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    unique_code: Mapped[str] = mapped_column(String(10), default="", nullable=False)
    account_type: Mapped[str] = mapped_column(String(40), default="buyer", nullable=False)
    shop_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    gstin: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    profile_image: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    password_history: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_device: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_login_browser: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_login_platform: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_login_ip: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_login_method: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ban_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    banned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    banned_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    addresses: Mapped[list["Address"]] = relationship(back_populates="user")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
    wishlist_items: Mapped[list["WishlistItem"]] = relationship(back_populates="user")
    chat_messages: Mapped[list["ChatMessage"]] = relationship(back_populates="user")
    change_logs: Mapped[list["UserChangeLog"]] = relationship(back_populates="user")
    listed_products: Mapped[list["Product"]] = relationship(
        back_populates="seller",
        foreign_keys="Product.seller_id",
    )


class CategoryDiscount(Base, TimestampMixin):
    __tablename__ = "category_discounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    discount_percent: Mapped[float] = mapped_column(Float, nullable=False)
    include_secondary: Mapped[bool] = mapped_column(default=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    affected_products: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    category: Mapped[Category] = relationship(back_populates="discounts")


class Address(Base, TimestampMixin):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="Home", nullable=False)
    street: Mapped[str] = mapped_column(String(255), nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(120), nullable=False)
    pincode: Mapped[str] = mapped_column(String(12), nullable=False)
    landmark: Mapped[str] = mapped_column(String(180), default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)

    user: Mapped[User] = relationship(back_populates="addresses")


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="Placed", nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(80), default="UPI / Card", nullable=False)
    cancel_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="Placed", nullable=False)
    cancel_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    order: Mapped[Order] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(back_populates="order_items")


class Review(Base, TimestampMixin):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    author_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    rating: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    image: Mapped[str] = mapped_column(Text, default="", nullable=False)

    product: Mapped[Product] = relationship(back_populates="reviews")


class WishlistItem(Base, TimestampMixin):
    __tablename__ = "wishlist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)

    user: Mapped[User] = relationship(back_populates="wishlist_items")


class OtpCode(Base, TimestampMixin):
    __tablename__ = "otp_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    mobile: Mapped[str] = mapped_column(String(40), nullable=False)
    code: Mapped[str] = mapped_column(String(6), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ChatMessage(Base, TimestampMixin):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    intent: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    page: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User | None] = relationship(back_populates="chat_messages")


class UserChangeLog(Base, TimestampMixin):
    __tablename__ = "user_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    field_name: Mapped[str] = mapped_column(String(120), nullable=False)
    old_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    new_value: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_by: Mapped[str] = mapped_column(String(40), default="user", nullable=False)

    user: Mapped[User] = relationship(back_populates="change_logs")


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_product(product: Product) -> dict:
    category = getattr(product, "category", None)
    stock_value = max(int(product.stock or 0), 0)
    product_role = str(getattr(product, "role", "") or "").strip().lower()
    if product_role not in {"owner", "merchant"}:
        product_role = "merchant" if getattr(product, "seller_id", None) else "owner"
    if stock_value <= 0:
        stock_status = "Out of Stock"
        stock_status_key = "out_of_stock"
    elif stock_value <= 5:
        stock_status = "Low Stock"
        stock_status_key = "low_stock"
    else:
        stock_status = "In Stock"
        stock_status_key = "in_stock"
    return {
        "id": product.id,
        "name": product.name,
        "slug": product.slug,
        "image": product.image or "images/swift.png",
        "price": product.price,
        "original_price": product.original_price,
        "rating": product.rating,
        "reviews_count": product.reviews_count,
        "stock": stock_value,
        "is_in_stock": stock_value > 0,
        "stock_status": stock_status,
        "stock_status_key": stock_status_key,
        "tag": product.tag,
        "description": product.description,
        "highlights": [item.strip() for item in str(product.highlights or "").split("|") if item.strip()],
        "specifications": _parse_key_value_blob(product.specifications or ""),
        "secondary_categories": [item.strip() for item in (product.secondary_categories or "").split("|") if item.strip()],
        "delivery_note": product.delivery_note,
        "featured": product.featured,
        "deal_of_the_day": product.deal_of_the_day,
        "created_at": _isoformat_or_none(getattr(product, "created_at", None)),
        "updated_at": _isoformat_or_none(getattr(product, "updated_at", None)),
        "user_id": product.seller_id,
        "seller_id": product.seller_id,
        "role": product_role,
        "seller_name": (
            f"{product.seller.first_name} {product.seller.last_name}".strip()
            if getattr(product, "seller", None)
            else ""
        ),
        "seller_shop_name": product.seller.shop_name if getattr(product, "seller", None) else "",
        "category": {
            "id": category.id if category else product.category_id,
            "name": category.name if category else "Uncategorized",
            "slug": category.slug if category else "uncategorized",
        },
        "discount_percent": int(
            round((1 - (product.price / product.original_price)) * 100)
        )
        if product.original_price
        else 0,
    }


def serialize_user(user: User) -> dict:
    sorted_addresses = sorted(user.addresses, key=lambda item: (not item.is_default, item.created_at))
    primary_address = sorted_addresses[0] if sorted_addresses else None
    return {
        "id": user.id,
        "unique_code": user.unique_code,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": f"{user.first_name} {user.last_name}".strip(),
        "email": user.email,
        "mobile": user.mobile,
        "account_type": user.account_type,
        "role": user.account_type,
        "shop_name": user.shop_name,
        "gstin": user.gstin,
        "profile_image": user.profile_image,
        "created_at": _isoformat_or_none(getattr(user, "created_at", None)),
        "password_changed_at": _isoformat_or_none(user.password_changed_at),
        "last_login_at": _isoformat_or_none(user.last_login_at),
        "last_login_device": user.last_login_device,
        "last_login_browser": user.last_login_browser,
        "last_login_platform": user.last_login_platform,
        "last_login_ip": user.last_login_ip,
        "last_login_method": user.last_login_method,
        "is_banned": bool(user.is_banned),
        "ban_reason": user.ban_reason,
        "banned_at": _isoformat_or_none(user.banned_at),
        "banned_by_user_id": user.banned_by_user_id,
        "account_status": "Banned" if user.is_banned else "Active",
        "password_history_count": len(get_password_history(user)),
        "address": serialize_address(primary_address) if primary_address else None,
        "addresses": [serialize_address(address) for address in sorted_addresses],
        "is_owner": user.account_type == "owner",
    }


def serialize_address(address: Address | None) -> dict | None:
    if not address:
        return None

    return {
        "id": address.id,
        "label": address.label,
        "street": address.street,
        "city": address.city,
        "state": address.state,
        "pincode": address.pincode,
        "landmark": address.landmark,
        "is_default": address.is_default,
    }


def serialize_order(order: Order) -> dict:
    tracking = _build_delivery_tracking(order)
    effective_status = _resolve_order_status(order, tracking["current_status"])
    order_status = str(order.status or "Placed")
    customer = getattr(order, "user", None)
    created_at = getattr(order, "created_at", None)
    return {
        "id": order.id,
        "status": effective_status,
        "original_status": order.status,
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
        "shipping_address": order.shipping_address,
        "cancel_reason": order.cancel_reason,
        "canceled_at": _isoformat_or_none(order.canceled_at),
        "created_at": _isoformat_or_none(created_at),
        "created_date": created_at.strftime("%d %b %Y") if created_at else "Unknown date",
        "created_time": created_at.strftime("%I:%M %p") if created_at else "Unknown time",
        "customer": {
            "id": customer.id if customer else order.user_id,
            "full_name": f"{customer.first_name} {customer.last_name}".strip() if customer else "Removed customer account",
            "email": customer.email if customer else "Account unavailable",
            "mobile": customer.mobile if customer else "",
            "account_type": customer.account_type if customer else "unknown",
            "shop_name": customer.shop_name if customer else "",
        },
        "delivery_tracking": tracking,
        "items": [
            {
                "order_item_id": item.id,
                "product_id": item.product_id,
                "name": item.product.name if item.product else f"Removed Product #{item.product_id}",
                "slug": item.product.slug if item.product else "",
                "image": item.product.image if item.product and item.product.image else "images/swift.png",
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "line_total": (item.quantity or 0) * (item.unit_price or 0),
                "status": item.status or ("Cancelled" if order_status.lower() == "cancelled" else order_status),
                "cancel_reason": item.cancel_reason,
                "canceled_at": _isoformat_or_none(item.canceled_at),
            }
            for item in order.items
        ],
    }


def _resolve_order_status(order: Order, fallback_status: str) -> str:
    if fallback_status == "Order Placed":
        fallback_status = "Placed"
    order_status = str(order.status or "Placed")
    item_statuses = [
        (item.status or order_status or "Placed").strip().lower()
        for item in order.items
    ]
    if not item_statuses:
        return fallback_status
    cancelled_count = sum(status == "cancelled" for status in item_statuses)
    if cancelled_count == len(item_statuses):
        return "Cancelled"
    if cancelled_count:
        return "Partially Cancelled"
    return fallback_status


def _build_delivery_tracking(order: Order) -> dict:
    order_status = str(order.status or "Placed")
    created_at = getattr(order, "created_at", None) or getattr(order, "updated_at", None) or datetime.utcnow()
    if order_status.lower() == "cancelled":
        cancelled_at = order.canceled_at or order.updated_at or created_at
        return {
            "current_status": "Cancelled",
            "current_step": 1,
            "estimated_delivery_date": None,
            "estimated_delivery_days": 0,
            "timeline": [
                {
                    "label": "Order Placed",
                    "timestamp": created_at.isoformat(),
                    "completed": True,
                    "active": False,
                },
                {
                    "label": "Cancelled",
                    "timestamp": cancelled_at.isoformat(),
                    "completed": True,
                    "active": True,
                },
            ],
        }

    seed = (order.id * 11) + created_at.day + (created_at.month * 3)
    confirm_hours = 1 + (seed % 6)
    packed_days = 1 + (seed % 2)
    shipped_days = packed_days + 1 + (seed % 2)
    delivered_days = shipped_days + 2 + ((seed // 3) % 3)
    out_for_delivery_days = delivered_days

    checkpoints = [
        ("Order Placed", created_at),
        ("Confirmed", created_at + timedelta(hours=confirm_hours)),
        ("Packed", created_at + timedelta(days=packed_days)),
        ("Shipped", created_at + timedelta(days=shipped_days)),
        ("Out for Delivery", created_at + timedelta(days=out_for_delivery_days)),
        ("Delivered", created_at + timedelta(days=delivered_days)),
    ]

    now = datetime.utcnow()
    current_status = checkpoints[0][0]
    current_index = 0
    for index, (label, eta) in enumerate(checkpoints):
        if now >= eta:
            current_status = label
            current_index = index

    return {
        "current_status": current_status,
        "current_step": current_index,
        "estimated_delivery_date": checkpoints[-1][1].date().isoformat(),
        "estimated_delivery_days": delivered_days,
        "timeline": [
            {
                "label": label,
                "timestamp": eta.isoformat(),
                "completed": index <= current_index,
                "active": index == current_index,
            }
            for index, (label, eta) in enumerate(checkpoints)
        ],
    }


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return

    require_persistent_database_configuration()
    Base.metadata.create_all(bind=engine, checkfirst=True)
    ensure_schema_updates()
    seed_data()
    ensure_owner_account()
    ensure_demo_owner_account()
    ensure_merchant_demo_account()
    ensure_historical_change_logs()
    if _should_sync_imported_gallery_products_on_startup():
        sync_imported_gallery_products()
    _db_initialized = True


def create_otp(session, *, purpose: str, email: str, mobile: str, code: str) -> OtpCode:
    otp = OtpCode(
        purpose=purpose,
        email=email,
        mobile=mobile,
        code=code,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )
    session.add(otp)
    session.flush()
    return otp


def generate_unique_code(session) -> str:
    while True:
        candidate = f"{random.randint(10**9, (10**10) - 1)}"
        exists = session.query(User).filter(User.unique_code == candidate).first()
        if not exists:
            return candidate


def get_password_history(user: User) -> list[str]:
    try:
        value = json.loads(user.password_history or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def push_password_history(user: User, previous_hash: str) -> None:
    history = get_password_history(user)
    if previous_hash:
        history.insert(0, previous_hash)
    user.password_history = json.dumps(history[:5])


def log_user_change(session, *, user_id: int, field_name: str, old_value: str | None, new_value: str | None, changed_by: str = "user") -> None:
    old_text = str(old_value or "").strip()
    new_text = str(new_value or "").strip()
    if old_text == new_text:
        return
    session.add(
        UserChangeLog(
            user_id=user_id,
            field_name=field_name,
            old_value=old_text,
            new_value=new_text,
            changed_by=changed_by,
        )
    )


def ensure_historical_change_logs() -> None:
    with session_scope() as session:
        existing_account_user_ids = {
            user_id
            for (user_id,) in session.query(UserChangeLog.user_id)
            .filter(UserChangeLog.field_name == "account_created")
            .all()
        }
        existing_order_signatures = {
            (log.user_id, log.new_value)
            for log in session.query(UserChangeLog)
            .filter(UserChangeLog.field_name == "order_created")
            .all()
        }

        for user in session.query(User).order_by(User.created_at.asc(), User.id.asc()).all():
            if user.id in existing_account_user_ids:
                continue
            created_at = user.created_at or datetime.utcnow()
            session.add(
                UserChangeLog(
                    user_id=user.id,
                    field_name="account_created",
                    old_value="",
                    new_value=f"{user.account_type} account created",
                    changed_by="backfill",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )

        for order in session.query(Order).order_by(Order.created_at.asc(), Order.id.asc()).all():
            created_at = order.created_at or datetime.utcnow()
            message = f"Order #{order.id} placed for {round(float(order.total_amount or 0), 2)}"
            signature = (order.user_id, message)
            if signature in existing_order_signatures:
                continue
            session.add(
                UserChangeLog(
                    user_id=order.user_id,
                    field_name="order_created",
                    old_value="",
                    new_value=message,
                    changed_by="backfill",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )


def ensure_schema_updates() -> None:
    if not _uses_sqlite():
        with engine.begin() as connection:
            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            if "products" in tables:
                product_columns = {column["name"] for column in inspector.get_columns("products")}
                if "role" not in product_columns:
                    connection.execute(
                        text("ALTER TABLE products ADD COLUMN role VARCHAR(40) NOT NULL DEFAULT 'owner'")
                    )
                connection.execute(
                    text("UPDATE products SET role = 'merchant' WHERE seller_id IS NOT NULL AND (role IS NULL OR role = '' OR role = 'owner')")
                )
                connection.execute(
                    text("UPDATE products SET role = 'owner' WHERE seller_id IS NULL AND (role IS NULL OR role = '')")
                )
        return

    with engine.begin() as connection:
        user_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        }
        if "account_type" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN account_type VARCHAR(40) NOT NULL DEFAULT 'buyer'")
            )
        if "shop_name" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN shop_name VARCHAR(255) NOT NULL DEFAULT ''")
            )
        if "gstin" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN gstin VARCHAR(32) NOT NULL DEFAULT ''")
            )
        if "profile_image" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN profile_image VARCHAR(255) NOT NULL DEFAULT ''")
            )
        if "unique_code" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN unique_code VARCHAR(10) NOT NULL DEFAULT ''")
            )
        if "password_history" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN password_history TEXT NOT NULL DEFAULT '[]'")
            )
        if "password_changed_at" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN password_changed_at DATETIME")
            )
        if "last_login_at" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_at DATETIME")
            )
        if "last_login_device" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_device VARCHAR(80) NOT NULL DEFAULT ''")
            )
        if "last_login_browser" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_browser VARCHAR(80) NOT NULL DEFAULT ''")
            )
        if "last_login_platform" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_platform VARCHAR(80) NOT NULL DEFAULT ''")
            )
        if "last_login_ip" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_ip VARCHAR(80) NOT NULL DEFAULT ''")
            )
        if "last_login_method" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN last_login_method VARCHAR(40) NOT NULL DEFAULT ''")
            )
        if "is_banned" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN is_banned BOOLEAN NOT NULL DEFAULT 0")
            )
        if "ban_reason" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN ban_reason TEXT NOT NULL DEFAULT ''")
            )
        if "banned_at" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN banned_at DATETIME")
            )
        if "banned_by_user_id" not in user_columns:
            connection.execute(
                text("ALTER TABLE users ADD COLUMN banned_by_user_id INTEGER")
            )
        connection.execute(
            text("UPDATE users SET account_type = 'merchant' WHERE account_type = 'seller'")
        )

        review_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(reviews)").fetchall()
        }
        if "author_user_id" not in review_columns:
            connection.execute(
                text("ALTER TABLE reviews ADD COLUMN author_user_id INTEGER")
            )
        if "image" not in review_columns:
            connection.execute(
                text("ALTER TABLE reviews ADD COLUMN image TEXT NOT NULL DEFAULT ''")
            )

        address_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(addresses)").fetchall()
        }
        if "label" not in address_columns:
            connection.execute(
                text("ALTER TABLE addresses ADD COLUMN label VARCHAR(120) NOT NULL DEFAULT 'Home'")
            )
        if "is_default" not in address_columns:
            connection.execute(
                text("ALTER TABLE addresses ADD COLUMN is_default BOOLEAN NOT NULL DEFAULT 0")
            )

        product_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(products)").fetchall()
        }
        if "seller_id" not in product_columns:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN seller_id INTEGER")
            )
        if "secondary_categories" not in product_columns:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN secondary_categories TEXT NOT NULL DEFAULT ''")
            )
        if "role" not in product_columns:
            connection.execute(
                text("ALTER TABLE products ADD COLUMN role VARCHAR(40) NOT NULL DEFAULT 'owner'")
            )
        connection.execute(
            text("UPDATE products SET role = 'merchant' WHERE seller_id IS NOT NULL AND (role IS NULL OR role = '' OR role = 'owner')")
        )
        connection.execute(
            text("UPDATE products SET role = 'owner' WHERE seller_id IS NULL AND (role IS NULL OR role = '')")
        )

        order_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(orders)").fetchall()
        }
        if "cancel_reason" not in order_columns:
            connection.execute(
                text("ALTER TABLE orders ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''")
            )
        if "canceled_at" not in order_columns:
            connection.execute(
                text("ALTER TABLE orders ADD COLUMN canceled_at DATETIME")
            )

        order_item_columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(order_items)").fetchall()
        }
        if "status" not in order_item_columns:
            connection.execute(
                text("ALTER TABLE order_items ADD COLUMN status VARCHAR(40) NOT NULL DEFAULT 'Placed'")
            )
        if "cancel_reason" not in order_item_columns:
            connection.execute(
                text("ALTER TABLE order_items ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''")
            )
        if "canceled_at" not in order_item_columns:
            connection.execute(
                text("ALTER TABLE order_items ADD COLUMN canceled_at DATETIME")
            )

    with session_scope() as session:
        users = session.query(User).all()
        for user in users:
            if not user.unique_code:
                user.unique_code = generate_unique_code(session)
            if not user.password_history:
                user.password_history = "[]"
            if not user.password_changed_at:
                user.password_changed_at = user.created_at

            sorted_addresses = sorted(user.addresses, key=lambda item: item.created_at)
            if sorted_addresses and not any(address.is_default for address in sorted_addresses):
                sorted_addresses[0].is_default = True
            for index, address in enumerate(sorted_addresses):
                if not address.label:
                    address.label = "Home" if index == 0 else f"Address {index + 1}"

        for item in session.query(OrderItem).all():
            if not item.status:
                item.status = "Cancelled" if item.order and item.order.status.lower() == "cancelled" else "Placed"
            if item.status.lower() == "cancelled" and not item.canceled_at:
                item.canceled_at = item.order.canceled_at if item.order else item.created_at

        for product in session.query(Product).all():
            normalized_role = str(product.role or "").strip().lower()
            if normalized_role not in {"owner", "merchant"}:
                product.role = "merchant" if product.seller_id else "owner"
            elif product.seller_id and normalized_role != "merchant":
                product.role = "merchant"
            elif not product.seller_id and normalized_role != "owner":
                product.role = "owner"


def _should_sync_imported_gallery_products_on_startup() -> bool:
    configured = os.getenv("SWIFTCART_SYNC_IMPORTED_GALLERY")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on"}

    if _uses_sqlite():
        return True

    with session_scope() as session:
        return session.query(Product.id).first() is None


def sync_imported_gallery_products() -> None:
    excluded_names = {
        "swift.png",
        "Swiftcart_logo3.png",
        "back.png",
        "Payment.jpeg",
        "Kurta.png",
        "kurta2.png",
        "jacket_kurta.png",
        "Bandhani_kurtas.webp",
        "Pastelbaghkurtas.png",
        "shaded_kurtas.png",
        "shirt.png",
        "Shirt3.png",
        "snitch.png",
        "Bewakkof.webp",
        "Woodland.png",
        "vastrado.png",
        "sonata.png",
        "ranbir_kapoor.webp",
    }
    image_dir = BASE_DIR.parent / "frontend" / "images"
    if not image_dir.exists():
        return

    with session_scope() as session:
        category = session.query(Category).filter(Category.slug == "research-picks").first()
        if not category:
            category = Category(
                name="Research Picks",
                slug="research-picks",
                description="Curated extended-catalog products converted into complete marketplace listings.",
                banner_title="Curated research-based product picks",
            )
            session.add(category)
            session.flush()

        existing_products = {
            product.image: product
            for product in session.query(Product).filter(Product.category_id == category.id).all()
        }
        existing_images = {image for (image,) in session.query(Product.image).all()}
        importable = []
        for path in sorted(image_dir.iterdir()):
            if not path.is_file() or path.stat().st_size == 0:
                continue
            if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            if path.name in excluded_names:
                continue
            rel = f"images/{path.name}"
            if rel in existing_images:
                continue
            importable.append(rel)

        all_imported_images = sorted(existing_products.keys() | set(importable))

        for index, rel in enumerate(all_imported_images, start=1):
            if index == 63:
                existing = existing_products.get(rel)
                if existing:
                    session.delete(existing)
                continue
            image_name = Path(rel).name
            benchmark = IMPORTED_PRODUCT_MARKET_DATA.get(image_name, {})
            cost_price, selling_price, original_price = _estimate_imported_pricing(index, benchmark)
            product_name = benchmark.get("name", f"Research Pick {index:02d}")
            slug = f"{_slugify(product_name)[:52]}-{index:02d}".strip("-")
            rating = round(4.0 + (((index - 1) % 7) * 0.1), 1)
            reviews_count = 18 + ((index - 1) * 9 % 160)
            stock = 6 + ((index - 1) % 22)
            tag = benchmark.get("tag", _research_pick_tag(index))
            benchmark_note = benchmark.get(
                "benchmark",
                "Comparable India marketplace pricing, Mar 2026",
            )
            benchmark_note = _sanitize_benchmark_note(benchmark_note)
            description = (
                f"{product_name} listed using current India market pricing references. "
                f"Pricing reference: {benchmark_note}. Estimated sourcing cost: INR {cost_price}."
            )
            highlights = (
                "Market-aligned pricing|SwiftCart catalog listing|Available for wishlist and reviews|"
                "Pricing reference refreshed from current India market data"
            )
            specifications = (
                _build_imported_specifications(
                    index=index,
                    product_name=product_name,
                    tag=tag,
                    benchmark_note=benchmark_note,
                    cost_price=cost_price,
                    selling_price=selling_price,
                    original_price=original_price,
                )
            )

            if rel in existing_products:
                product = existing_products[rel]
                product.name = product_name
                product.slug = slug
                product.price = selling_price
                product.original_price = original_price
                product.rating = rating
                product.reviews_count = reviews_count
                product.stock = stock
                product.tag = tag
                product.description = description
                product.highlights = highlights
                product.specifications = specifications
                product.delivery_note = "Delivery in 3-6 business days"
                product.featured = index <= 8
                product.deal_of_the_day = index <= 4
                continue

            if session.query(Product).filter(Product.slug == slug).first():
                continue

            session.add(
                Product(
                    name=product_name,
                    slug=slug,
                    image=rel,
                    price=selling_price,
                    original_price=original_price,
                    rating=rating,
                    reviews_count=reviews_count,
                    stock=stock,
                    tag=tag,
                    description=description,
                    highlights=highlights,
                    specifications=specifications,
                    delivery_note="Delivery in 3-6 business days",
                    featured=index <= 8,
                    deal_of_the_day=index <= 4,
                    category_id=category.id,
                    role="owner",
                )
            )


def seed_data() -> None:
    with session_scope() as session:
        category_rows = [
            {
                "name": "Ethnic Wear",
                "slug": "ethnic-wear",
                "description": "Festive kurtas, premium ethnic fits, and occasion-ready looks.",
                "banner_title": "Wedding and festive styles",
            },
            {
                "name": "Shirts & Tees",
                "slug": "shirts-tees",
                "description": "Sharp shirts and printed casual tees for everyday rotation.",
                "banner_title": "Fresh casual and office fits",
            },
            {
                "name": "Footwear",
                "slug": "footwear",
                "description": "Durable footwear and outdoor-ready utility styles.",
                "banner_title": "Comfort with grip",
            },
            {
                "name": "Accessories",
                "slug": "accessories",
                "description": "Reliable finishing touches for daily wear.",
                "banner_title": "Watches and styling essentials",
            },
        ]

        existing_categories = {
            category.slug: category
            for category in session.query(Category).all()
        }
        for row in category_rows:
            category = existing_categories.get(row["slug"])
            if category:
                if not category.description:
                    category.description = row["description"]
                if not category.banner_title:
                    category.banner_title = row["banner_title"]
                continue
            category = Category(**row)
            session.add(category)
            session.flush()
            existing_categories[row["slug"]] = category

        category_map = {
            row["slug"]: existing_categories[row["slug"]].id
            for row in category_rows
            if row["slug"] in existing_categories
        }
        product_rows = [
            {
                "name": "Classic Kurta",
                "slug": "classic-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/Kurta.png",
                "price": 999,
                "original_price": 1799,
                "rating": 4.2,
                "reviews_count": 77,
                "stock": 26,
                "tag": "Daily Wear",
                "description": "A lightweight cotton kurta designed for everyday comfort with a polished festive edge.",
                "highlights": "Pure cotton fabric|Breathable all-day comfort|Tailored regular fit|Made in India",
                "specifications": "Fabric=Cotton|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-4 business days",
                "featured": True,
                "deal_of_the_day": False,
            },
            {
                "name": "Designer Kurta",
                "slug": "designer-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/kurta2.png",
                "price": 1299,
                "original_price": 2199,
                "rating": 4.4,
                "reviews_count": 118,
                "stock": 19,
                "tag": "Trending",
                "description": "A refined designer kurta with richer detail for celebrations, gifting, and special evenings.",
                "highlights": "Soft blended fabric|Elegant embroidered texture|Festive-ready styling|Easy-care finish",
                "specifications": "Fabric=Cotton Blend|Fit=Slim|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-5 business days",
                "featured": True,
                "deal_of_the_day": True,
            },
            {
                "name": "Jacket Kurta",
                "slug": "jacket-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/jacket_kurta.png",
                "price": 1899,
                "original_price": 3199,
                "rating": 4.5,
                "reviews_count": 200,
                "stock": 12,
                "tag": "Occasion Wear",
                "description": "A premium kurta set paired with a sharp jacket for weddings, receptions, and festive events.",
                "highlights": "Kurta with matching jacket|Statement festive silhouette|Comfortable lining|Premium finish",
                "specifications": "Fabric=Silk Blend|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Express delivery in metro cities",
                "featured": True,
                "deal_of_the_day": False,
            },
            {
                "name": "Bandhani Kurta",
                "slug": "bandhani-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/Bandhani_kurtas.webp",
                "price": 1499,
                "original_price": 2599,
                "rating": 4.3,
                "reviews_count": 120,
                "stock": 18,
                "tag": "Best Seller",
                "description": "Traditional Bandhani-inspired styling with vibrant color and comfortable premium cotton fabric.",
                "highlights": "Traditional print|Soft hand feel|Easy festive styling|Lightweight build",
                "specifications": "Fabric=Cotton|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 3-5 business days",
                "featured": True,
                "deal_of_the_day": True,
            },
            {
                "name": "Pastel Kurta",
                "slug": "pastel-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/Pastelbaghkurtas.png",
                "price": 1399,
                "original_price": 2399,
                "rating": 4.1,
                "reviews_count": 82,
                "stock": 17,
                "tag": "Fresh Pick",
                "description": "A pastel-tone kurta that balances understated color with soft fabric and crisp finishing.",
                "highlights": "Pastel color palette|Light festive drape|Comfort-first construction|Minimal styling",
                "specifications": "Fabric=Cotton Rayon|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-5 business days",
                "featured": False,
                "deal_of_the_day": False,
            },
            {
                "name": "Shaded Kurta",
                "slug": "shaded-kurta",
                "category_slug": "ethnic-wear",
                "image": "images/shaded_kurtas.png",
                "price": 1199,
                "original_price": 1999,
                "rating": 4.0,
                "reviews_count": 69,
                "stock": 15,
                "tag": "Value Buy",
                "description": "A shaded color kurta with a modern finish that works for both casual and festive dressing.",
                "highlights": "Gradient-inspired finish|Soft-touch fabric|Versatile look|Everyday value",
                "specifications": "Fabric=Cotton Blend|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 3-6 business days",
                "featured": False,
                "deal_of_the_day": False,
            },
            {
                "name": "Casual Shirt",
                "slug": "casual-shirt",
                "category_slug": "shirts-tees",
                "image": "images/shirt.png",
                "price": 899,
                "original_price": 1499,
                "rating": 4.0,
                "reviews_count": 54,
                "stock": 31,
                "tag": "Casual",
                "description": "An easygoing shirt built for everyday wear with a neat collar and lightweight structure.",
                "highlights": "Soft casual fabric|Smart collar profile|Comfortable fit|Easy to pair",
                "specifications": "Fabric=Cotton Blend|Fit=Regular|Sleeve=Half Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-4 business days",
                "featured": False,
                "deal_of_the_day": False,
            },
            {
                "name": "Formal Shirt",
                "slug": "formal-shirt",
                "category_slug": "shirts-tees",
                "image": "images/Shirt3.png",
                "price": 1499,
                "original_price": 2499,
                "rating": 4.2,
                "reviews_count": 95,
                "stock": 28,
                "tag": "Office Wear",
                "description": "A polished formal shirt with a crisp look, tailored finish, and dependable comfort.",
                "highlights": "Wrinkle-resistant finish|Structured collar|Office-ready style|Breathable weave",
                "specifications": "Fabric=Cotton|Fit=Slim|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-4 business days",
                "featured": True,
                "deal_of_the_day": False,
            },
            {
                "name": "Snitch Wear",
                "slug": "snitch-wear",
                "category_slug": "shirts-tees",
                "image": "images/snitch.png",
                "price": 1999,
                "original_price": 3299,
                "rating": 4.0,
                "reviews_count": 60,
                "stock": 13,
                "tag": "Street Style",
                "description": "A modern fashion-forward shirt with a sharper silhouette and elevated casual detailing.",
                "highlights": "Modern slim fit|Statement styling|Premium look|Lightweight comfort",
                "specifications": "Fabric=Linen Blend|Fit=Slim|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 3-5 business days",
                "featured": True,
                "deal_of_the_day": True,
            },
            {
                "name": "Bewakoof Style",
                "slug": "bewakoof-style",
                "category_slug": "shirts-tees",
                "image": "images/Bewakkof.webp",
                "price": 999,
                "original_price": 1799,
                "rating": 4.1,
                "reviews_count": 89,
                "stock": 22,
                "tag": "Graphic Tee",
                "description": "A playful printed tee for relaxed outfits, weekend plans, and everyday comfort.",
                "highlights": "Graphic front print|Soft jersey knit|Relaxed styling|Durable color finish",
                "specifications": "Fabric=Poly-Cotton|Fit=Slim|Sleeve=Half Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-4 business days",
                "featured": False,
                "deal_of_the_day": False,
            },
            {
                "name": "Woodland Style",
                "slug": "woodland-style",
                "category_slug": "footwear",
                "image": "images/Woodland.png",
                "price": 2499,
                "original_price": 3999,
                "rating": 4.4,
                "reviews_count": 300,
                "stock": 14,
                "tag": "Outdoor",
                "description": "Rugged outdoor shoes with strong grip, durable construction, and dependable traction.",
                "highlights": "Durable outsole grip|Outdoor-ready build|Supportive cushioning|Long-wear comfort",
                "specifications": "Material=Leather|Use=Outdoor|Grip=Heavy Traction|Origin=India",
                "delivery_note": "Priority delivery available",
                "featured": True,
                "deal_of_the_day": True,
            },
            {
                "name": "Vastrado Collection",
                "slug": "vastrado-collection",
                "category_slug": "ethnic-wear",
                "image": "images/vastrado.png",
                "price": 1799,
                "original_price": 2899,
                "rating": 4.2,
                "reviews_count": 104,
                "stock": 16,
                "tag": "Ethnic",
                "description": "A polished ethnic collection piece that blends comfort, detail, and occasion-ready styling.",
                "highlights": "Rich festive palette|Comfort fit|Elegant detailing|Premium presentation",
                "specifications": "Fabric=Cotton Silk|Fit=Regular|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Delivery in 2-5 business days",
                "featured": False,
                "deal_of_the_day": False,
            },
            {
                "name": "Sonata Watch",
                "slug": "sonata-watch",
                "category_slug": "accessories",
                "image": "images/sonata.png",
                "price": 2999,
                "original_price": 4599,
                "rating": 4.3,
                "reviews_count": 143,
                "stock": 11,
                "tag": "Accessories",
                "description": "A sleek wristwatch built to elevate daily outfits with a clean dial and dependable movement.",
                "highlights": "Modern dial design|Comfortable strap|Daily wear durability|Classic finish",
                "specifications": "Movement=Quartz|Strap=Synthetic|Water Resistance=3 ATM|Origin=India",
                "delivery_note": "Delivery in 2-4 business days",
                "featured": True,
                "deal_of_the_day": False,
            },
            {
                "name": "Celebrity Style",
                "slug": "celebrity-style",
                "category_slug": "ethnic-wear",
                "image": "images/ranbir_kapoor.webp",
                "price": 3999,
                "original_price": 5999,
                "rating": 4.6,
                "reviews_count": 156,
                "stock": 9,
                "tag": "Premium",
                "description": "A premium fashion pick inspired by celebrity styling with standout finishing and fit.",
                "highlights": "Premium silhouette|Statement profile|High-finish detailing|Occasion-ready",
                "specifications": "Fabric=Premium Blend|Fit=Tailored|Sleeve=Full Sleeve|Origin=India",
                "delivery_note": "Premium delivery in 1-3 business days",
                "featured": True,
                "deal_of_the_day": False,
            },
        ]

        existing_products = {
            product.slug: product
            for product in session.query(Product).all()
        }
        products: list[Product] = []
        for row in product_rows:
            if row["slug"] in existing_products:
                products.append(existing_products[row["slug"]])
                continue
            product = Product(
                category_id=category_map[row["category_slug"]],
                name=row["name"],
                slug=row["slug"],
                image=row["image"],
                price=row["price"],
                original_price=row["original_price"],
                rating=row["rating"],
                reviews_count=row["reviews_count"],
                stock=row["stock"],
                tag=row["tag"],
                description=row["description"],
                highlights=row["highlights"],
                specifications=row["specifications"],
                delivery_note=row["delivery_note"],
                featured=row["featured"],
                deal_of_the_day=row["deal_of_the_day"],
                role="owner",
            )
            session.add(product)
            products.append(product)
            existing_products[row["slug"]] = product
        session.flush()

        if not session.query(Product.id).filter(Product.featured.is_(True)).first():
            fallback_featured = (
                session.query(Product)
                .order_by(Product.rating.desc(), Product.reviews_count.desc(), Product.created_at.asc())
                .limit(8)
                .all()
            )
            for product in fallback_featured:
                product.featured = True

        if not session.query(Product.id).filter(Product.deal_of_the_day.is_(True)).first():
            fallback_deals = (
                session.query(Product)
                .order_by(Product.rating.desc(), Product.reviews_count.desc(), Product.created_at.asc())
                .limit(4)
                .all()
            )
            for product in fallback_deals:
                product.deal_of_the_day = True

        demo_user = (
            session.query(User)
            .filter(User.email.in_([BUYER_DEMO_EMAIL, "demo@swiftcart.com"]))
            .order_by(User.created_at.asc())
            .first()
        )
        if not demo_user:
            demo_user = User(
                first_name="Prince",
                last_name="Kumar",
                email=BUYER_DEMO_EMAIL,
                mobile="+918229069530",
                password_hash=hash_password(BUYER_DEMO_PASSWORD),
                unique_code=generate_unique_code(session),
                account_type="buyer",
                password_changed_at=datetime.utcnow(),
            )
            session.add(demo_user)
            session.flush()
        else:
            demo_user.email = BUYER_DEMO_EMAIL
            demo_user.account_type = "buyer"
            preserve_seeded_password(demo_user, BUYER_DEMO_PASSWORD)

        if demo_user and not demo_user.addresses:
            session.add(
                Address(
                    user_id=demo_user.id,
                    label="Home",
                    street="Embassy Tech Village, Outer Ring Road",
                    city="Bengaluru",
                    state="Karnataka",
                    pincode="560103",
                    landmark="Near Tech Park Gate 2",
                    is_default=True,
                )
            )

        review_rows = [
            ("bandhani-kurta", "Aarav", 4.0, "Comfortable and festive", "The print looks vibrant and the fabric feels easy for long events."),
            ("jacket-kurta", "Riya", 5.0, "Perfect for weddings", "The jacket finish stands out and the fit looked premium straight away."),
            ("woodland-style", "Vikram", 4.5, "Strong grip", "Feels sturdy outdoors and the sole has a lot of grip."),
            ("sonata-watch", "Neha", 4.0, "Clean and classy", "A neat watch for daily wear with a smart dial size."),
        ]
        existing_review_keys = {
            (
                review.product_id,
                str(review.author_name or "").strip().lower(),
                str(review.title or "").strip().lower(),
            )
            for review in session.query(Review).all()
        }
        for slug, author, rating, title, comment in review_rows:
            product = existing_products.get(slug)
            if not product:
                continue
            review_key = (product.id, author.strip().lower(), title.strip().lower())
            if review_key in existing_review_keys:
                continue
            session.add(
                Review(
                    product_id=product.id,
                    author_name=author,
                    rating=rating,
                    title=title,
                    comment=comment,
                )
            )
            existing_review_keys.add(review_key)


def ensure_owner_account() -> None:
    if not OWNER_PASSWORD:
        logger.warning("Skipping automatic owner seeding because OWNER_PASSWORD is not configured.")
        return
    with session_scope() as session:
        legacy_owner_emails = (OWNER_EMAIL.lower(), "owner@swiftcart.com", "prince12345@gmail.com")
        owner = (
            session.query(User)
            .filter(
                text(
                    "lower(email) IN (:configured_email, :legacy_owner_email, :legacy_seed_email)"
                )
            )
            .params(
                configured_email=legacy_owner_emails[0],
                legacy_owner_email=legacy_owner_emails[1],
                legacy_seed_email=legacy_owner_emails[2],
            )
            .order_by(User.created_at.asc())
            .first()
        )
        if owner:
            owner.account_type = "owner"
            if owner.email.strip().lower() != OWNER_EMAIL.lower():
                owner.email = OWNER_EMAIL
            preserve_seeded_password(owner, OWNER_PASSWORD)
            if not owner.first_name:
                owner.first_name = "Prince"
            if not owner.last_name:
                owner.last_name = "Kumar"
            if not owner.mobile:
                owner.mobile = "+910000000000"
            if not owner.unique_code:
                owner.unique_code = generate_unique_code(session)
            if not owner.shop_name:
                owner.shop_name = "SwiftCart Marketplace"
            if not owner.gstin:
                owner.gstin = "29OWNER0000X1Z0"
            return

        owner = User(
            first_name="Prince",
            last_name="Kumar",
            email=OWNER_EMAIL,
            mobile="+910000000000",
            password_hash=hash_password(OWNER_PASSWORD),
            unique_code=generate_unique_code(session),
            account_type="owner",
            shop_name="SwiftCart Marketplace",
            gstin="29OWNER0000X1Z0",
            password_changed_at=datetime.utcnow(),
        )
        session.add(owner)
        session.flush()
        session.add(
            Address(
                user_id=owner.id,
                label="HQ",
                street="SwiftCart HQ, Bengaluru",
                city="Bengaluru",
                state="Karnataka",
                pincode="560001",
                landmark="Owner operations desk",
                is_default=True,
            )
        )


def ensure_demo_owner_account() -> None:
    if not ENABLE_DEMO_LOGINS or not DEMO_OWNER_EMAIL or not DEMO_OWNER_PASSWORD:
        return

    with session_scope() as session:
        owner = session.query(User).filter(User.email == DEMO_OWNER_EMAIL).first()
        if owner:
            owner.account_type = "owner"
            owner.shop_name = owner.shop_name or "SwiftCart Demo Owner"
            owner.gstin = owner.gstin or "29DEMOOWNER0X1Z1"
            if not owner.unique_code:
                owner.unique_code = generate_unique_code(session)
            preserve_seeded_password(owner, DEMO_OWNER_PASSWORD)
        else:
            owner = User(
                first_name="Demo",
                last_name="Owner",
                email=DEMO_OWNER_EMAIL,
                mobile="+919900000001",
                password_hash=hash_password(DEMO_OWNER_PASSWORD),
                unique_code=generate_unique_code(session),
                account_type="owner",
                shop_name="SwiftCart Demo Owner",
                gstin="29DEMOOWNER0X1Z1",
                password_changed_at=datetime.utcnow(),
            )
            session.add(owner)
            session.flush()

        if not owner.addresses:
            session.add(
                Address(
                    user_id=owner.id,
                    label="HQ",
                    street="Demo Owner Desk, Bengaluru",
                    city="Bengaluru",
                    state="Karnataka",
                    pincode="560001",
                    landmark="Owner operations demo desk",
                    is_default=True,
                )
            )


def ensure_merchant_demo_account() -> None:
    if not ENABLE_DEMO_LOGINS or not MERCHANT_DEMO_PASSWORD:
        return
    with session_scope() as session:
        merchant = session.query(User).filter(User.email == MERCHANT_DEMO_EMAIL).first()
        if merchant:
            merchant.account_type = "merchant"
            merchant.shop_name = merchant.shop_name or "SwiftCart Merchant Studio"
            merchant.gstin = merchant.gstin or "29MERCHANT1234X1Z5"
            if not merchant.unique_code:
                merchant.unique_code = generate_unique_code(session)
            preserve_seeded_password(merchant, MERCHANT_DEMO_PASSWORD)
        else:
            merchant = User(
                first_name="Merchant",
                last_name="Partner",
                email=MERCHANT_DEMO_EMAIL,
                mobile="+919876543210",
                password_hash=hash_password(MERCHANT_DEMO_PASSWORD),
                unique_code=generate_unique_code(session),
                account_type="merchant",
                shop_name="SwiftCart Merchant Studio",
                gstin="29MERCHANT1234X1Z5",
                password_changed_at=datetime.utcnow(),
            )
            session.add(merchant)
            session.flush()

        if not merchant.addresses:
            session.add(
                Address(
                    user_id=merchant.id,
                    label="Shop",
                    street="Commerce Hub, MG Road",
                    city="Bengaluru",
                    state="Karnataka",
                    pincode="560001",
                    landmark="Merchant support desk",
                    is_default=True,
                )
            )

        demo_product_rows = [
            {
                "name": "Merchant Oxford Shirt",
                "slug": "merchant-oxford-shirt",
                "category_slug": "shirts-tees",
                "image": "images/Shirt3.png",
                "price": 1599,
                "original_price": 2399,
                "stock": 18,
                "tag": "Merchant Exclusive",
                "description": "An owner-approved demo merchant listing for validating merchant product separation.",
                "highlights": "Merchant managed catalog|Oxford weave|Role-separated listing|Ready for dashboard tests",
                "specifications": "Fabric=Cotton|Fit=Regular|Seller=Merchant Demo|Origin=India",
            },
            {
                "name": "Merchant Wallet Set",
                "slug": "merchant-wallet-set",
                "category_slug": "accessories",
                "image": "images/sonata.png",
                "price": 1299,
                "original_price": 1899,
                "stock": 11,
                "tag": "Merchant Pick",
                "description": "A merchant-seeded demo accessory used to verify product filtering and dashboard counts.",
                "highlights": "Merchant managed catalog|Gift-ready packaging|Dashboard seed data|Role-based visibility",
                "specifications": "Material=Leatherette|Set=Wallet Combo|Seller=Merchant Demo|Origin=India",
            },
        ]
        category_map = {
            category.slug: category
            for category in session.query(Category).filter(Category.slug.in_([row["category_slug"] for row in demo_product_rows])).all()
        }
        existing_products = {
            product.slug: product
            for product in session.query(Product).filter(Product.slug.in_([row["slug"] for row in demo_product_rows])).all()
        }
        for row in demo_product_rows:
            category = category_map.get(row["category_slug"])
            if not category:
                continue
            product = existing_products.get(row["slug"])
            if product:
                product.name = row["name"]
                product.image = row["image"]
                product.price = row["price"]
                product.original_price = row["original_price"]
                product.stock = row["stock"]
                product.tag = row["tag"]
                product.description = row["description"]
                product.highlights = row["highlights"]
                product.specifications = row["specifications"]
                product.category_id = category.id
                product.seller_id = merchant.id
                product.role = "merchant"
                continue

            session.add(
                Product(
                    name=row["name"],
                    slug=row["slug"],
                    image=row["image"],
                    price=row["price"],
                    original_price=row["original_price"],
                    rating=4.3,
                    reviews_count=24,
                    stock=row["stock"],
                    tag=row["tag"],
                    description=row["description"],
                    highlights=row["highlights"],
                    specifications=row["specifications"],
                    delivery_note="Delivery in 2-5 business days",
                    featured=False,
                    deal_of_the_day=False,
                    category_id=category.id,
                    seller_id=merchant.id,
                    role="merchant",
                )
            )


def _parse_key_value_blob(blob: str) -> dict:
    output = {}
    for pair in blob.split("|"):
        if "=" not in pair:
            continue
        key, value = pair.split("=", 1)
        output[key.strip()] = value.strip()
    return output


def _build_imported_specifications(
    *,
    index: int,
    product_name: str,
    tag: str,
    benchmark_note: str,
    cost_price: int,
    selling_price: int,
    original_price: int,
) -> str:
    lower_name = product_name.lower()
    specs = {
        "Category": "Research Picks",
        "Style Code": f"RP-{index:02d}",
        "Product Name": product_name,
        "Segment": tag,
        "Pricing Basis": "Current India market reference",
        "Selling Price": f"INR {selling_price}",
        "MRP": f"INR {original_price}",
        "Estimated Cost": f"INR {cost_price}",
        "Benchmark Source": benchmark_note,
        "Listing Type": "SwiftCart Catalog Product",
    }

    if "iphone" in lower_name:
        specs.update(
            {
                "Brand": "Apple",
                "Device Type": "Smartphone",
                "Network Class": "5G-ready premium smartphone",
                "Display Family": "Super Retina class display",
                "Operating System": "iOS",
                "Best For": "Photography, social media, daily flagship use",
            }
        )
    elif "macbook air" in lower_name:
        specs.update(
            {
                "Brand": "Apple",
                "Device Type": "Laptop",
                "Screen Size Class": "13-inch thin-and-light notebook",
                "Chip Family": "Apple Silicon",
                "Storage Class": "SSD storage configuration",
                "Operating System": "macOS",
                "Best For": "Study, work, content viewing, travel",
            }
        )
    elif "ipad pro" in lower_name or "redmi pad" in lower_name:
        specs.update(
            {
                "Brand": "Apple" if "ipad" in lower_name else "Redmi",
                "Device Type": "Tablet",
                "Connectivity": "Wi-Fi / cellular-ready tablet class",
                "Display Family": "Large-format touchscreen display",
                "Use Case": "Reading, streaming, productivity, travel",
                "Battery Focus": "Designed for all-day portable use",
            }
        )
    elif "airpods" in lower_name or "earbuds" in lower_name:
        specs.update(
            {
                "Device Type": "Wireless earbuds",
                "Connectivity": "Bluetooth",
                "Microphone": "Built-in calling microphone",
                "Charging Style": "Pocket charging case",
                "Use Case": "Music, calls, commuting, workouts",
                "Audio Profile": "Portable stereo listening",
            }
        )
    elif "power bank" in lower_name:
        specs.update(
            {
                "Device Type": "Portable charger",
                "Battery Class": "High-capacity rechargeable battery pack",
                "Charging Output": "Fast-charge compatible",
                "Portability": "Travel-friendly handheld design",
                "Use Case": "Phone, earbuds, and gadget top-up charging",
                "Safety Focus": "Built for daily carry and recharge cycles",
            }
        )
    elif "sunscreen" in lower_name:
        specs.update(
            {
                "Brand": "The Derma Co",
                "Product Type": "Face sunscreen",
                "SPF": "SPF 50",
                "Texture": "Gel cream",
                "Skin Type": "Suitable for normal to oily skin profiles",
                "Use Case": "Daily UV protection",
            }
        )
    elif "motorcycle" in lower_name or "bike" in lower_name:
        specs.update(
            {
                "Vehicle Type": "Motorcycle",
                "Pricing Type": "India ex-showroom benchmark",
                "Engine Class": "Petrol performance motorcycle",
                "Transmission": "Manual transmission class",
                "Use Case": "City riding and highway cruising",
                "Safety": "Disc brake / ABS class benchmark",
            }
        )
    elif any(keyword in lower_name for keyword in ["sofa", "chair", "table", "bench", "shelf"]):
        specs.update(
            {
                "Product Type": "Furniture",
                "Material Class": "Wood / metal / upholstered home furniture",
                "Room Fit": "Living room or lounge placement",
                "Assembly": "Delivered as furniture item benchmark",
                "Use Case": "Home seating or decor setup",
                "Finish": "Modern marketplace furniture styling",
            }
        )
    elif any(keyword in lower_name for keyword in ["kurta", "dress", "shirt", "tunic", "shrug", "night suit", "co-ord", "saree"]):
        specs.update(
            {
                "Product Type": "Fashion apparel",
                "Fabric Profile": "Marketplace fashion fabric blend",
                "Fit": "Regular contemporary fit",
                "Occasion": "Daily wear / festive / casual styling",
                "Care": "Gentle wash recommended",
                "Best For": "Everyday and occasion-led wardrobe use",
            }
        )
    elif any(keyword in lower_name for keyword in ["monitor", "projector", "hub", "charger", "console", "breathalyzer"]):
        specs.update(
            {
                "Product Type": "Electronics accessory",
                "Connectivity": "Accessory-grade device connectivity",
                "Power Profile": "Plug-and-use electronics category",
                "Use Case": "Desk setup, travel, or utility use",
                "Build Focus": "Portable consumer electronics format",
                "Benchmark Segment": "Current India gadget pricing",
            }
        )
    else:
        specs.update(
            {
                "Use Case": "Extended marketplace catalog listing",
                "Catalog Note": "Curated from extended catalog assets",
            }
        )

    return "|".join(f"{key}={value}" for key, value in specs.items())


def _estimate_imported_pricing(index: int, benchmark: dict | None = None) -> tuple[int, int, int]:
    if benchmark:
        return (
            int(benchmark.get("cost", 0)),
            int(benchmark.get("price", 0)),
            int(benchmark.get("original_price", 0)),
        )

    base_costs = [449, 599, 749, 899, 1099, 1299, 1499, 1799, 2199, 2599]
    margin_map = [1.42, 1.46, 1.5, 1.54, 1.58]
    mrp_map = [1.18, 1.22, 1.26, 1.3]

    base_cost = base_costs[(index - 1) % len(base_costs)]
    tier_lift = ((index - 1) // len(base_costs)) * 90
    estimated_cost = base_cost + tier_lift

    margin = margin_map[(index - 1) % len(margin_map)]
    selling_price = int(round((estimated_cost * margin) / 50.0) * 50)
    selling_price = max(selling_price, estimated_cost + 150)

    mrp_multiplier = mrp_map[(index - 1) % len(mrp_map)]
    original_price = int(round((selling_price * mrp_multiplier) / 100.0) * 100)
    if original_price <= selling_price:
        original_price = int(round((selling_price + 300) / 100.0) * 100)

    return estimated_cost, selling_price, original_price


def _research_pick_tag(index: int) -> str:
    tags = [
        "Cost Plus Pick",
        "Value Research Pick",
        "Marketplace Match",
        "Premium Research Pick",
        "Fast-Moving Pick",
        "High Margin Pick",
    ]
    return tags[(index - 1) % len(tags)]


def _slugify(value: str) -> str:
    value = value.lower()
    value = sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")
