from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from backend.models import (
    Address,
    Category,
    Order,
    OrderItem,
    Product,
    User,
    UserChangeLog,
    generate_unique_code,
    init_db,
    session_scope,
)


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalized_text(value) -> str:
    return " ".join(str(value or "").strip().split())


def _row_signature(*parts) -> tuple:
    return tuple(_normalized_text(part).lower() for part in parts)


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def restore_from_sqlite(source_path: Path) -> dict:
    if not source_path.exists():
        raise FileNotFoundError(f"Source SQLite database not found: {source_path}")

    source = sqlite3.connect(source_path)
    source.row_factory = sqlite3.Row
    try:
        source_tables = _table_names(source)
        required_tables = {"users", "products", "orders", "order_items"}
        missing_tables = sorted(required_tables - source_tables)
        if missing_tables:
            raise RuntimeError(
                f"Source database is missing required tables: {', '.join(missing_tables)}"
            )

        source_users = source.execute("SELECT * FROM users ORDER BY created_at ASC, id ASC").fetchall()
        source_categories = (
            source.execute("SELECT * FROM categories ORDER BY created_at ASC, id ASC").fetchall()
            if "categories" in source_tables
            else []
        )
        source_products = source.execute("SELECT id, slug, name FROM products").fetchall()
        source_product_rows = source.execute("SELECT * FROM products ORDER BY created_at ASC, id ASC").fetchall()
        source_orders = source.execute("SELECT * FROM orders ORDER BY created_at ASC, id ASC").fetchall()
        source_order_items = source.execute("SELECT * FROM order_items ORDER BY created_at ASC, id ASC").fetchall()
        source_addresses = (
            source.execute("SELECT * FROM addresses ORDER BY created_at ASC, id ASC").fetchall()
            if "addresses" in source_tables
            else []
        )
        source_change_logs = (
            source.execute("SELECT * FROM user_change_logs ORDER BY created_at ASC, id ASC").fetchall()
            if "user_change_logs" in source_tables
            else []
        )

        source_categories_by_id = {row["id"]: dict(row) for row in source_categories}
        source_products_by_id = {row["id"]: dict(row) for row in source_product_rows}
        source_items_by_order_id: dict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in source_order_items:
            source_items_by_order_id[row["order_id"]].append(row)

        summary = {
            "users_created": 0,
            "categories_created": 0,
            "products_created": 0,
            "addresses_created": 0,
            "orders_created": 0,
            "order_items_created": 0,
            "change_logs_created": 0,
            "orders_skipped_missing_products": 0,
        }

        with session_scope() as session:
            target_users_by_email = {
                str(user.email or "").strip().lower(): user
                for user in session.query(User).all()
            }
            target_products_by_slug = {
                str(product.slug or "").strip().lower(): product
                for product in session.query(Product).all()
            }
            target_categories_by_slug = {
                str(category.slug or "").strip().lower(): category
                for category in session.query(Category).all()
            }
            user_id_map: dict[int, int] = {}

            for row in source_users:
                email = str(row["email"] or "").strip().lower()
                if not email:
                    continue
                target_user = target_users_by_email.get(email)
                if target_user is None:
                    unique_code = _normalized_text(row["unique_code"])
                    if unique_code and session.query(User).filter(User.unique_code == unique_code).first():
                        unique_code = generate_unique_code(session)
                    created_at = _parse_datetime(row["created_at"])
                    updated_at = _parse_datetime(row["updated_at"])
                    target_user = User(
                        first_name=_normalized_text(row["first_name"]) or "User",
                        last_name=_normalized_text(row["last_name"]) or "Account",
                        email=email,
                        mobile=_normalized_text(row["mobile"]),
                        password_hash=_normalized_text(row["password_hash"]),
                        unique_code=unique_code or generate_unique_code(session),
                        account_type=_normalized_text(row["account_type"]) or "buyer",
                        shop_name=_normalized_text(row["shop_name"]),
                        gstin=_normalized_text(row["gstin"]),
                        profile_image=_normalized_text(row["profile_image"]),
                        password_history=_normalized_text(row["password_history"]) or "[]",
                        password_changed_at=_parse_datetime(row["password_changed_at"]),
                        last_login_at=_parse_datetime(row["last_login_at"]),
                        last_login_device=_normalized_text(row["last_login_device"]),
                        last_login_browser=_normalized_text(row["last_login_browser"]),
                        last_login_platform=_normalized_text(row["last_login_platform"]),
                        last_login_ip=_normalized_text(row["last_login_ip"]),
                        last_login_method=_normalized_text(row["last_login_method"]),
                        is_banned=bool(row["is_banned"]),
                        ban_reason=_normalized_text(row["ban_reason"]),
                        banned_at=_parse_datetime(row["banned_at"]),
                        banned_by_user_id=row["banned_by_user_id"],
                    )
                    if created_at:
                        target_user.created_at = created_at
                    if updated_at:
                        target_user.updated_at = updated_at
                    session.add(target_user)
                    session.flush()
                    target_users_by_email[email] = target_user
                    summary["users_created"] += 1
                user_id_map[row["id"]] = target_user.id

            def ensure_target_category(source_category_id: int | None):
                source_category = source_categories_by_id.get(source_category_id or 0)
                if not source_category:
                    return None
                source_slug = str(source_category.get("slug") or "").strip().lower()
                if not source_slug:
                    return None
                target_category = target_categories_by_slug.get(source_slug)
                if target_category is not None:
                    return target_category
                created_at = _parse_datetime(source_category.get("created_at"))
                updated_at = _parse_datetime(source_category.get("updated_at"))
                target_category = Category(
                    name=_normalized_text(source_category.get("name")),
                    slug=source_slug,
                    description=_normalized_text(source_category.get("description")),
                    banner_title=_normalized_text(source_category.get("banner_title")),
                )
                if created_at:
                    target_category.created_at = created_at
                if updated_at:
                    target_category.updated_at = updated_at
                session.add(target_category)
                session.flush()
                target_categories_by_slug[source_slug] = target_category
                summary["categories_created"] += 1
                return target_category

            def ensure_target_product(source_product_id: int):
                source_product = source_products_by_id.get(source_product_id)
                if not source_product:
                    return None
                source_slug = str(source_product.get("slug") or "").strip().lower()
                if not source_slug:
                    return None
                target_product = target_products_by_slug.get(source_slug)
                if target_product is not None:
                    return target_product
                target_category = ensure_target_category(source_product.get("category_id"))
                if target_category is None:
                    return None
                created_at = _parse_datetime(source_product.get("created_at"))
                updated_at = _parse_datetime(source_product.get("updated_at"))
                target_product = Product(
                    name=_normalized_text(source_product.get("name")) or "Restored product",
                    slug=source_slug,
                    image=_normalized_text(source_product.get("image")) or "images/swift.png",
                    price=float(source_product.get("price") or 0),
                    original_price=float(source_product.get("original_price") or 0),
                    rating=float(source_product.get("rating") or 0),
                    reviews_count=int(source_product.get("reviews_count") or 0),
                    stock=int(source_product.get("stock") or 0),
                    tag=_normalized_text(source_product.get("tag")),
                    description=_normalized_text(source_product.get("description")),
                    highlights=_normalized_text(source_product.get("highlights")),
                    specifications=_normalized_text(source_product.get("specifications")),
                    delivery_note=_normalized_text(source_product.get("delivery_note")),
                    featured=bool(source_product.get("featured")),
                    deal_of_the_day=bool(source_product.get("deal_of_the_day")),
                    category_id=target_category.id,
                    seller_id=user_id_map.get(source_product.get("seller_id")),
                    secondary_categories=_normalized_text(source_product.get("secondary_categories")),
                    role=_normalized_text(source_product.get("role")) or ("merchant" if source_product.get("seller_id") else "owner"),
                )
                if created_at:
                    target_product.created_at = created_at
                if updated_at:
                    target_product.updated_at = updated_at
                session.add(target_product)
                session.flush()
                target_products_by_slug[source_slug] = target_product
                summary["products_created"] += 1
                return target_product

            existing_address_signatures = {
                user.id: {
                    _row_signature(address.label, address.street, address.city, address.state, address.pincode, address.landmark)
                    for address in user.addresses
                }
                for user in session.query(User).all()
            }
            for row in source_addresses:
                target_user_id = user_id_map.get(row["user_id"])
                if not target_user_id:
                    continue
                signature = _row_signature(
                    row["label"],
                    row["street"],
                    row["city"],
                    row["state"],
                    row["pincode"],
                    row["landmark"],
                )
                known_signatures = existing_address_signatures.setdefault(target_user_id, set())
                if signature in known_signatures:
                    continue
                address = Address(
                    user_id=target_user_id,
                    label=_normalized_text(row["label"]) or "Home",
                    street=_normalized_text(row["street"]),
                    city=_normalized_text(row["city"]),
                    state=_normalized_text(row["state"]),
                    pincode=_normalized_text(row["pincode"]),
                    landmark=_normalized_text(row["landmark"]),
                    is_default=bool(row["is_default"]),
                )
                created_at = _parse_datetime(row["created_at"])
                updated_at = _parse_datetime(row["updated_at"])
                if created_at:
                    address.created_at = created_at
                if updated_at:
                    address.updated_at = updated_at
                session.add(address)
                known_signatures.add(signature)
                summary["addresses_created"] += 1

            existing_order_signatures = {
                _row_signature(
                    order.user_id,
                    order.total_amount,
                    order.shipping_address,
                    order.payment_method,
                    order.created_at.isoformat() if order.created_at else "",
                )
                for order in session.query(Order).all()
            }
            order_id_map: dict[int, int] = {}
            for row in source_orders:
                target_user_id = user_id_map.get(row["user_id"])
                if not target_user_id:
                    continue

                source_items = source_items_by_order_id.get(row["id"], [])
                mapped_items = []
                missing_product = False
                for item in source_items:
                    target_product = ensure_target_product(item["product_id"])
                    if target_product is None:
                        missing_product = True
                        break
                    mapped_items.append((item, target_product))
                if missing_product:
                    summary["orders_skipped_missing_products"] += 1
                    continue

                created_at = _parse_datetime(row["created_at"])
                signature = _row_signature(
                    target_user_id,
                    row["total_amount"],
                    row["shipping_address"],
                    row["payment_method"],
                    created_at.isoformat() if created_at else "",
                )
                if signature in existing_order_signatures:
                    continue

                order = Order(
                    user_id=target_user_id,
                    status=_normalized_text(row["status"]) or "Placed",
                    total_amount=float(row["total_amount"] or 0),
                    shipping_address=_normalized_text(row["shipping_address"]),
                    payment_method=_normalized_text(row["payment_method"]) or "UPI / Card",
                    cancel_reason=_normalized_text(row["cancel_reason"]),
                    canceled_at=_parse_datetime(row["canceled_at"]),
                )
                updated_at = _parse_datetime(row["updated_at"])
                if created_at:
                    order.created_at = created_at
                if updated_at:
                    order.updated_at = updated_at
                session.add(order)
                session.flush()
                order_id_map[row["id"]] = order.id
                existing_order_signatures.add(signature)
                summary["orders_created"] += 1

                for item_row, target_product in mapped_items:
                    order_item = OrderItem(
                        order_id=order.id,
                        product_id=target_product.id,
                        quantity=int(item_row["quantity"] or 0),
                        unit_price=float(item_row["unit_price"] or 0),
                        status=_normalized_text(item_row["status"]) or "Placed",
                        cancel_reason=_normalized_text(item_row["cancel_reason"]),
                        canceled_at=_parse_datetime(item_row["canceled_at"]),
                    )
                    item_created_at = _parse_datetime(item_row["created_at"])
                    item_updated_at = _parse_datetime(item_row["updated_at"])
                    if item_created_at:
                        order_item.created_at = item_created_at
                    if item_updated_at:
                        order_item.updated_at = item_updated_at
                    session.add(order_item)
                    summary["order_items_created"] += 1

            if source_change_logs:
                existing_log_signatures = {
                    _row_signature(
                        log.user_id,
                        log.field_name,
                        log.old_value,
                        log.new_value,
                        log.changed_by,
                        log.created_at.isoformat() if log.created_at else "",
                    )
                    for log in session.query(UserChangeLog).all()
                }
                for row in source_change_logs:
                    target_user_id = user_id_map.get(row["user_id"])
                    if not target_user_id:
                        continue
                    created_at = _parse_datetime(row["created_at"])
                    signature = _row_signature(
                        target_user_id,
                        row["field_name"],
                        row["old_value"],
                        row["new_value"],
                        row["changed_by"],
                        created_at.isoformat() if created_at else "",
                    )
                    if signature in existing_log_signatures:
                        continue
                    change_log = UserChangeLog(
                        user_id=target_user_id,
                        field_name=_normalized_text(row["field_name"]),
                        old_value=_normalized_text(row["old_value"]),
                        new_value=_normalized_text(row["new_value"]),
                        changed_by=_normalized_text(row["changed_by"]) or "restore",
                    )
                    updated_at = _parse_datetime(row["updated_at"])
                    if created_at:
                        change_log.created_at = created_at
                    if updated_at:
                        change_log.updated_at = updated_at
                    session.add(change_log)
                    existing_log_signatures.add(signature)
                    summary["change_logs_created"] += 1

        return summary
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore users, addresses, orders, order items, and change logs from a SQLite backup into the configured primary database."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Path to the source SQLite database file that contains the older SwiftCart data.",
    )
    args = parser.parse_args()

    init_db()
    summary = restore_from_sqlite(Path(args.source).expanduser().resolve())
    print(summary)


if __name__ == "__main__":
    main()
