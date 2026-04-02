from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy.orm import joinedload

from backend.auth import require_authenticated_user
from backend.models import Address, Order, OrderItem, Product, log_user_change, serialize_order, session_scope


orders_bp = Blueprint("orders", __name__)


def _title_case(value: str) -> str:
    parts = [part for part in str(value or "").strip().split() if part]
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


def _sentence_case(value: str) -> str:
    cleaned = " ".join(str(value or "").strip().split())
    if not cleaned:
        return ""
    return cleaned[:1].upper() + cleaned[1:]

def _recalculate_order_totals(order: Order) -> None:
    active_items = [item for item in order.items if (item.status or "Placed").lower() != "cancelled"]
    order.total_amount = (
        sum(item.unit_price * item.quantity for item in active_items) + (50 if active_items else 0)
    )


def _sync_order_status_from_items(order: Order) -> None:
    active_items = [item for item in order.items if (item.status or "Placed").lower() != "cancelled"]
    if not active_items:
        order.status = "Cancelled"
        if not order.canceled_at:
            order.canceled_at = datetime.utcnow()
        if not order.cancel_reason:
            order.cancel_reason = "All products in this order were cancelled individually."
        return

    if order.status.lower() == "cancelled":
        order.status = "Placed"
        order.cancel_reason = ""
        order.canceled_at = None


@orders_bp.post("/orders/checkout")
def checkout():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items", [])
    shipping_address = payload.get("shipping_address", {})
    customer_type = payload.get("customer_type", "normal").strip() or "normal"
    merchant_profile = payload.get("merchant_profile", {}) or {}

    if not items:
        return jsonify({"message": "At least one cart item is required"}), 400

    with session_scope() as session:
        user, error = require_authenticated_user(session)
        if error:
            return error

        requested_quantities: dict[int, int] = {}
        for item in items:
            product_id = int(item["product_id"])
            quantity = max(int(item.get("quantity", 1)), 1)
            requested_quantities[product_id] = requested_quantities.get(product_id, 0) + quantity

        product_map = {
            product.id: product
            for product in session.query(Product).filter(
                Product.id.in_(requested_quantities.keys())
            )
        }
        total = 0.0
        order_items = []
        for product_id, quantity in requested_quantities.items():
            product = product_map.get(product_id)
            if not product:
                return jsonify({"message": f"Product {product_id} not found"}), 404
            if product.stock <= 0:
                return jsonify({"message": f"{product.name} is out of stock right now."}), 409
            if quantity > product.stock:
                return jsonify(
                    {
                        "message": f"Only {product.stock} unit(s) of {product.name} are available right now.",
                    }
                ), 409

            total += product.price * quantity
            order_items.append((product, quantity))

        address_blob = ", ".join(
            value.strip()
            for value in [
                shipping_address.get("street", ""),
                shipping_address.get("city", ""),
                shipping_address.get("state", ""),
                shipping_address.get("pincode", ""),
            ]
            if value and str(value).strip()
        )
        if not address_blob:
            address_blob = "Address to be confirmed at delivery"

        if customer_type == "merchant":
            merchant_bits = [
                merchant_profile.get("business_name", "").strip(),
                merchant_profile.get("gstin", "").strip(),
                merchant_profile.get("contact_role", "").strip(),
            ]
            merchant_blob = " | ".join(bit for bit in merchant_bits if bit)
            if merchant_blob:
                address_blob = f"{address_blob} | Merchant: {merchant_blob}"

        if shipping_address:
            address = user.addresses[0] if user.addresses else Address(user_id=user.id)
            if not user.addresses:
                session.add(address)
                session.flush()
            updated_values = {
                "street": _sentence_case(shipping_address.get("street", "")),
                "city": _title_case(shipping_address.get("city", "")),
                "state": _title_case(shipping_address.get("state", "")),
                "pincode": str(shipping_address.get("pincode", "")).strip(),
            }
            for field_name, next_value in updated_values.items():
                if not next_value:
                    continue
                log_user_change(
                    session,
                    user_id=user.id,
                    field_name=f"address_{field_name}",
                    old_value=getattr(address, field_name, ""),
                    new_value=next_value,
                    changed_by="checkout",
                )
                setattr(address, field_name, next_value)

        order = Order(
            user_id=user.id,
            total_amount=total + 50,
            shipping_address=address_blob,
            payment_method=f"{payload.get('payment_method', 'UPI / Card')} · {'Merchant' if customer_type == 'merchant' else 'Normal'} Checkout",
        )
        session.add(order)
        session.flush()

        for product, quantity in order_items:
            product.stock = max(0, int(product.stock or 0) - quantity)
            session.add(
                OrderItem(
                    order_id=order.id,
                    product_id=product.id,
                    quantity=quantity,
                    unit_price=product.price,
                    status="Placed",
                )
            )

        session.flush()
        session.refresh(order)

        order = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.id == order.id)
            .first()
        )

        return jsonify({"message": "Order placed successfully.", "order": serialize_order(order)}), 201


@orders_bp.get("/users/<int:user_id>/orders")
def list_orders(user_id: int):
    with session_scope() as session:
        current_user, error = require_authenticated_user(session, expected_user_id=user_id)
        if error:
            return error
        orders = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.user_id == current_user.id)
            .order_by(Order.created_at.desc())
            .all()
        )
        return jsonify([serialize_order(order) for order in orders])


@orders_bp.post("/orders/<int:order_id>/cancel")
def cancel_order(order_id: int):
    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason", "")).strip()

    if len(reason.split()) < 10:
        return jsonify({"message": "Cancellation reason must be at least 10 words."}), 400

    with session_scope() as session:
        current_user, error = require_authenticated_user(session)
        if error:
            return error
        order = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.id == order_id, Order.user_id == current_user.id)
            .first()
        )
        if not order:
            return jsonify({"message": "Order not found."}), 404
        if order.status.lower() == "cancelled":
            return jsonify({"message": "This order is already cancelled."}), 400
        if order.status.lower() == "delivered":
            return jsonify({"message": "Delivered orders cannot be cancelled."}), 400

        order.status = "Cancelled"
        order.cancel_reason = reason
        order.canceled_at = datetime.utcnow()
        for item in order.items:
            if (item.status or "Placed").lower() != "cancelled" and item.product:
                item.product.stock = max(0, int(item.product.stock or 0)) + int(item.quantity or 0)
            item.status = "Cancelled"
            item.cancel_reason = reason
            item.canceled_at = order.canceled_at
        _recalculate_order_totals(order)
        session.flush()
        session.refresh(order)

        order = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.id == order.id)
            .first()
        )
        return jsonify({"message": "Order cancelled successfully.", "order": serialize_order(order)})


@orders_bp.post("/orders/<int:order_id>/items/<int:order_item_id>/cancel")
def cancel_order_item(order_id: int, order_item_id: int):
    payload = request.get_json(silent=True) or {}
    reason = str(payload.get("reason", "")).strip()

    if len(reason.split()) < 10:
        return jsonify({"message": "Cancellation reason must be at least 10 words."}), 400

    with session_scope() as session:
        current_user, error = require_authenticated_user(session)
        if error:
            return error
        order = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.id == order_id, Order.user_id == current_user.id)
            .first()
        )
        if not order:
            return jsonify({"message": "Order not found."}), 404
        if order.status.lower() == "delivered":
            return jsonify({"message": "Delivered orders cannot be cancelled."}), 400

        target_item = next((item for item in order.items if item.id == order_item_id), None)
        if not target_item:
            return jsonify({"message": "Order item not found."}), 404
        if (target_item.status or "Placed").lower() == "cancelled":
            return jsonify({"message": "This product is already cancelled."}), 400

        if target_item.product:
            target_item.product.stock = max(0, int(target_item.product.stock or 0)) + int(target_item.quantity or 0)
        target_item.status = "Cancelled"
        target_item.cancel_reason = reason
        target_item.canceled_at = datetime.utcnow()

        _sync_order_status_from_items(order)
        _recalculate_order_totals(order)
        session.flush()
        session.refresh(order)

        order = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .filter(Order.id == order.id)
            .first()
        )
        return jsonify({"message": "Product cancelled successfully.", "order": serialize_order(order)})
