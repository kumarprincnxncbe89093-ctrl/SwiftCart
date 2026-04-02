from datetime import datetime, timedelta
import secrets
from pathlib import Path

from flask import Blueprint, jsonify, request
from sqlalchemy import and_, inspect, or_, text
from sqlalchemy.orm import joinedload
from werkzeug.utils import secure_filename

from backend.auth import require_authenticated_user
from backend.models import (
    BASE_DIR,
    ChatMessage,
    CategoryDiscount,
    DATABASE_PATH,
    Category,
    Order,
    OrderItem,
    Product,
    Review,
    User,
    UserChangeLog,
    WishlistItem,
    engine,
    serialize_order,
    serialize_product,
    serialize_user,
    session_scope,
)


products_bp = Blueprint("products", __name__)
PRODUCT_UPLOAD_DIR = BASE_DIR.parent / "frontend" / "uploads" / "products"
ALLOWED_PRODUCT_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _title_case(value: str) -> str:
    parts = [part for part in value.strip().split() if part]
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


def _sentence_case(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""
    return cleaned[:1].upper() + cleaned[1:]


def _normalized_slug(value: str) -> str:
    cleaned = _sentence_case(value).lower()
    return "-".join(part for part in cleaned.replace("/", " ").replace("_", " ").split() if part)


def _normalize_secondary_categories(raw_value) -> str:
    if isinstance(raw_value, list):
        values = raw_value
    else:
        values = str(raw_value or "").split(",")
    cleaned = []
    for value in values:
        item = str(value).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    return "|".join(cleaned)


def _normalize_price_values(price_value, original_price_value) -> tuple[float, float]:
    try:
        price = round(float(price_value), 2)
        original_price = round(float(original_price_value), 2)
    except (TypeError, ValueError) as error:
        raise ValueError("Price and original price must be valid numbers.") from error

    if price <= 0 or original_price <= 0:
        raise ValueError("Price and original price must be greater than zero.")

    normalized_original_price = max(price, original_price)
    normalized_price = min(price, normalized_original_price)
    return normalized_price, normalized_original_price


def _normalize_stock_value(raw_stock) -> int:
    try:
        stock = int(raw_stock)
    except (TypeError, ValueError) as error:
        raise ValueError("Stock must be a whole number.") from error
    return max(stock, 0)


def _build_bank_offer(category_name: str, index: int) -> dict:
    bank_names = ["HDFC Bank", "ICICI Bank", "Axis Bank", "SBI Cards", "Kotak Bank", "IndusInd Bank"]
    discounts = [10, 12, 15, 8, 5, 7]
    caps = [1250, 1500, 2000, 900, 600, 850]
    minimums = [2999, 3999, 4999, 1999, 1499, 2499]
    return {
        "bank_name": bank_names[index % len(bank_names)],
        "category_name": category_name,
        "discount_percent": discounts[index % len(discounts)],
        "max_discount": caps[index % len(caps)],
        "minimum_order_value": minimums[index % len(minimums)],
    }


def _require_owner(session):
    user, error = require_authenticated_user(session, allowed_roles={"owner"})
    if error:
        return None, error
    return user, None


def _require_merchant(session):
    user, error = require_authenticated_user(session, allowed_roles={"merchant", "seller"})
    if error:
        return None, error
    return user, None


def _database_table_names(connection):
    return sorted(inspect(connection).get_table_names())


def _normalize_sql_statement(sql: str) -> str:
    statement = sql.strip()
    if not statement:
        raise ValueError("SQL query is required.")
    if statement.endswith(";"):
        statement = statement[:-1].strip()
    if ";" in statement:
        raise ValueError("Only one SQL statement is allowed at a time.")
    return statement


def _matching_discount_products(session, category: Category, include_secondary: bool) -> list[Product]:
    query = session.query(Product).filter(Product.category_id == category.id)
    if include_secondary:
        query = session.query(Product).filter(
            or_(
                Product.category_id == category.id,
                Product.secondary_categories.ilike(f"%{category.name}%")
            )
        )
    return query.all()


def _restore_discounted_products(products: list[Product]) -> int:
    updated_count = 0
    for product in products:
        if product.original_price and product.original_price > 0:
            product.price = float(product.original_price)
            product.deal_of_the_day = False
            updated_count += 1
    return updated_count


def _expire_category_discounts(session) -> None:
    expired_discounts = (
        session.query(CategoryDiscount)
        .options(joinedload(CategoryDiscount.category))
        .filter(CategoryDiscount.active.is_(True), CategoryDiscount.expires_at <= datetime.utcnow())
        .all()
    )
    if not expired_discounts:
        return

    for discount in expired_discounts:
        if not discount.category:
            discount.active = False
            discount.removed_at = datetime.utcnow()
            continue
        products = _matching_discount_products(session, discount.category, discount.include_secondary)
        _restore_discounted_products(products)
        discount.active = False
        discount.removed_at = datetime.utcnow()

    session.flush()


def _serialize_category_discount(discount: CategoryDiscount) -> dict:
    return {
        "id": discount.id,
        "category_id": discount.category_id,
        "category_name": discount.category.name if discount.category else "",
        "discount_percent": int(discount.discount_percent),
        "include_secondary": discount.include_secondary,
        "affected_products": discount.affected_products,
        "expires_at": discount.expires_at.isoformat(),
        "created_at": discount.created_at.isoformat(),
        "active": discount.active,
        "removed_at": discount.removed_at.isoformat() if discount.removed_at else None,
    }


def _keyword_category_slug(message: str) -> str | None:
    mapping = {
        "kurta": "ethnic-wear",
        "ethnic": "ethnic-wear",
        "shirt": "shirts-tees",
        "tee": "shirts-tees",
        "watch": "accessories",
        "accessor": "accessories",
        "shoe": "footwear",
        "footwear": "footwear",
        "sneaker": "footwear",
        "bike": "bike",
        "motorcycle": "bike",
        "laptop": "electronics",
        "tablet": "electronics",
        "monitor": "electronics",
        "power bank": "electronics",
        "phone": "electronics",
        "mobile": "electronics",
        "dress": "ethnic-wear",
    }
    lowered = message.lower()
    for keyword, category_slug in mapping.items():
        if keyword in lowered:
            return category_slug
    return None


def _extract_shopping_terms(message: str) -> list[str]:
    stop_words = {
        "i", "me", "my", "want", "need", "show", "find", "give", "please", "can", "you",
        "a", "an", "the", "for", "with", "to", "buy", "get", "need", "looking", "look",
        "something", "some", "tell", "about", "this", "that", "under", "best", "good",
    }
    cleaned = (
        message.lower()
        .replace("/", " ")
        .replace(",", " ")
        .replace(".", " ")
        .replace("?", " ")
        .replace("!", " ")
    )
    terms = []
    for part in cleaned.split():
        term = part.strip()
        if len(term) < 2 or term in stop_words or term.isdigit():
            continue
        if term not in terms:
            terms.append(term)
    return terms[:5]


def _serialize_chat_products(products: list[Product]) -> list[dict]:
    return [serialize_product(product) for product in products[:6]]


@products_bp.get("/categories")
def list_categories():
    with session_scope() as session:
        _expire_category_discounts(session)
        categories = session.query(Category).order_by(Category.name.asc()).all()
        return jsonify(
            [
                {
                    "id": category.id,
                    "name": category.name,
                    "slug": category.slug,
                    "description": category.description,
                    "banner_title": category.banner_title,
                }
                for category in categories
            ]
        )


@products_bp.get("/products")
def list_products():
    query_text = request.args.get("q", "").strip()
    category_slug = request.args.get("category", "").strip()
    tag = request.args.get("tag", "").strip()
    featured = request.args.get("featured")
    in_stock = request.args.get("in_stock")
    min_price = request.args.get("min_price")
    max_price = request.args.get("max_price")
    sort = request.args.get("sort", "featured")

    with session_scope() as session:
        _expire_category_discounts(session)
        query = session.query(Product).options(joinedload(Product.category), joinedload(Product.seller))
        if query_text or category_slug:
            query = query.join(Product.category)

        if query_text:
            terms = [term.strip() for term in query_text.lower().split() if term.strip()]
            query = query.filter(
                and_(
                    *[
                        or_(
                            Product.name.ilike(f"%{term}%"),
                            Product.description.ilike(f"%{term}%"),
                            Product.tag.ilike(f"%{term}%"),
                            Product.highlights.ilike(f"%{term}%"),
                            Product.secondary_categories.ilike(f"%{term}%"),
                            Category.name.ilike(f"%{term}%"),
                        )
                        for term in terms
                    ]
                )
            )

        if category_slug:
            query = query.filter(Category.slug == category_slug)

        if tag:
            query = query.filter(Product.tag.ilike(f"%{tag}%"))

        if featured == "true":
            query = query.filter(Product.featured.is_(True))

        if in_stock == "true":
            query = query.filter(Product.stock > 0)

        if min_price:
            query = query.filter(Product.price >= float(min_price))

        if max_price:
            query = query.filter(Product.price <= float(max_price))

        if sort == "price_asc":
            query = query.order_by(Product.price.asc())
        elif sort == "price_desc":
            query = query.order_by(Product.price.desc())
        elif sort == "rating":
            query = query.order_by(Product.rating.desc(), Product.reviews_count.desc())
        else:
            query = query.order_by(Product.featured.desc(), Product.deal_of_the_day.desc(), Product.rating.desc())

        products = query.all()
        return jsonify([serialize_product(product) for product in products])


@products_bp.get("/products/<slug>")
def product_detail(slug: str):
    with session_scope() as session:
        _expire_category_discounts(session)
        product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.reviews), joinedload(Product.seller))
            .filter(Product.slug == slug)
            .first()
        )
        if not product:
            return jsonify({"message": "Product not found"}), 404

        related = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.category_id == product.category_id, Product.id != product.id)
            .order_by(Product.featured.desc(), Product.rating.desc())
            .limit(6)
            .all()
        )
        if len(related) < 6:
            existing_ids = {product.id, *(item.id for item in related)}
            fallback_related = (
                session.query(Product)
                .options(joinedload(Product.category), joinedload(Product.seller))
                .filter(~Product.id.in_(existing_ids))
                .order_by(Product.featured.desc(), Product.rating.desc(), Product.reviews_count.desc())
                .limit(6 - len(related))
                .all()
            )
            related.extend(fallback_related)

        return jsonify(
            {
                **serialize_product(product),
                "reviews": [
                    {
                        "id": review.id,
                        "author_user_id": review.author_user_id,
                        "author_name": review.author_name,
                        "rating": review.rating,
                        "title": review.title,
                        "comment": review.comment,
                        "image": review.image,
                        "created_at": review.created_at.isoformat(),
                    }
                    for review in product.reviews
                ],
                "related_products": [serialize_product(item) for item in related],
            }
        )


@products_bp.get("/home")
def home_payload():
    with session_scope() as session:
        _expire_category_discounts(session)
        categories = session.query(Category).order_by(Category.name.asc()).all()
        featured = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.featured.is_(True))
            .order_by(Product.rating.desc())
            .limit(8)
            .all()
        )
        deals = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.deal_of_the_day.is_(True))
            .order_by(Product.rating.desc())
            .limit(6)
            .all()
        )
        newest = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .order_by(Product.created_at.desc())
            .limit(10)
            .all()
        )
        imported = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .join(Product.category)
            .filter(Category.slug == "research-picks")
            .order_by(Product.created_at.desc())
            .limit(12)
            .all()
        )
        return jsonify(
            {
                "hero": {
                    "title": "SwiftCart Marketplace",
                    "subtitle": "Discover fashion, footwear, and accessories with richer product data, offers, and real checkout flows.",
                    "highlight": "Daily deals and premium selections inspired by modern marketplace experiences.",
                },
                "categories": [
                    {
                        "id": category.id,
                        "name": category.name,
                        "slug": category.slug,
                        "description": category.description,
                        "banner_title": category.banner_title,
                    }
                    for category in categories
                ],
                "featured_products": [serialize_product(product) for product in featured],
                "deal_of_the_day": [serialize_product(product) for product in deals],
                "imported_products": [serialize_product(product) for product in imported],
                "new_arrivals": [serialize_product(product) for product in newest],
            }
        )


@products_bp.post("/products/<slug>/reviews")
def add_review(slug: str):
    payload = request.get_json(silent=True) or {}
    with session_scope() as session:
        product = session.query(Product).filter(Product.slug == slug).first()
        if not product:
            return jsonify({"message": "Product not found"}), 404

        author_user = None
        auth_header = request.headers.get("Authorization", "").strip() or request.headers.get("X-Auth-Token", "").strip()
        if auth_header:
            author_user, error = require_authenticated_user(session)
            if error:
                return error

        review = Review(
            product_id=product.id,
            author_user_id=author_user.id if author_user else None,
            author_name=(
                f"{author_user.first_name} {author_user.last_name}".strip()
                if author_user
                else (_title_case(payload.get("author_name", "Guest Shopper")) or "Guest Shopper")
            ),
            rating=float(payload.get("rating", 0)),
            title=_sentence_case(payload.get("title", "New review")) or "New review",
            comment=_sentence_case(payload.get("comment", "")) or "Good shopping experience.",
            image=payload.get("image", "").strip(),
        )
        session.add(review)
        session.flush()

        review_rows = session.query(Review).filter(Review.product_id == product.id).all()
        product.reviews_count = len(review_rows)
        product.rating = round(
            sum(item.rating for item in review_rows) / product.reviews_count, 1
        ) if product.reviews_count else 0

        return jsonify(
            {
                "message": "Review added",
                "review": {
                    "id": review.id,
                    "author_user_id": review.author_user_id,
                    "author_name": review.author_name,
                    "rating": review.rating,
                    "title": review.title,
                    "comment": review.comment,
                    "image": review.image,
                    "created_at": review.created_at.isoformat(),
                },
                "product": {
                    "id": product.id,
                    "rating": product.rating,
                    "reviews_count": product.reviews_count,
                },
            }
        ), 201


@products_bp.delete("/products/<slug>/reviews/<int:review_id>")
def delete_review(slug: str, review_id: int):
    with session_scope() as session:
        current_user, error = require_authenticated_user(session)
        if error:
            return error
        product = session.query(Product).filter(Product.slug == slug).first()
        if not product:
            return jsonify({"message": "Product not found"}), 404

        review = (
            session.query(Review)
            .filter(Review.id == review_id, Review.product_id == product.id)
            .first()
        )
        if not review:
            return jsonify({"message": "Review not found."}), 404
        if review.author_user_id != current_user.id:
            return jsonify({"message": "You can only delete your own review."}), 403

        session.delete(review)
        session.flush()

        review_rows = session.query(Review).filter(Review.product_id == product.id).all()
        product.reviews_count = len(review_rows)
        product.rating = round(
            sum(item.rating for item in review_rows) / product.reviews_count, 1
        ) if product.reviews_count else 0

        return jsonify(
            {
                "message": "Review deleted successfully.",
                "product": {
                    "id": product.id,
                    "rating": product.rating,
                    "reviews_count": product.reviews_count,
                },
            }
        )


@products_bp.post("/chatbot/message")
def chatbot_message():
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", "")).strip()
    user_id = payload.get("user_id")
    current_product_id = payload.get("current_product_id")
    cart_items = payload.get("cart_items", []) or []
    page = str(payload.get("page", "")).strip()
    history = payload.get("history", []) or []

    if not message:
        return jsonify({"message": "Chat message is required."}), 400

    lowered = message.lower()
    with session_scope() as session:
        user = None
        auth_header = request.headers.get("Authorization", "").strip() or request.headers.get("X-Auth-Token", "").strip()
        if auth_header:
            user, _ = require_authenticated_user(session)
        first_name = user.first_name if user else "there"
        current_product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.id == current_product_id)
            .first()
            if current_product_id
            else None
        )
        default_address = None
        if user and user.addresses:
            sorted_addresses = sorted(user.addresses, key=lambda item: (not item.is_default, item.created_at))
            default_address = sorted_addresses[0] if sorted_addresses else None
        recent_user_messages = [
            str(item.get("text", "")).strip().lower()
            for item in history
            if isinstance(item, dict) and item.get("role") == "user" and item.get("text")
        ]
        last_user_message = recent_user_messages[-1] if recent_user_messages else ""
        session.add(
            ChatMessage(
                user_id=user.id if user else None,
                role="user",
                intent="incoming",
                page=page,
                message=message,
            )
        )
        products_query = session.query(Product).options(joinedload(Product.category), joinedload(Product.seller))

        def respond(reply: str, *, intent: str, products=None, quick_actions=None, order=None):
            session.add(
                ChatMessage(
                    user_id=user.id if user else None,
                    role="assistant",
                    intent=intent,
                    page=page,
                    message=reply,
                )
            )
            response = {
                "reply": reply,
                "intent": intent,
                "products": products or [],
                "quick_actions": quick_actions or [],
            }
            if order is not None:
                response["order"] = order
            return jsonify(response)

        if any(keyword in lowered for keyword in ["compare", "difference", "which is better", "vs"]):
            return respond(
                (
                    f"Absolutely, {first_name}. I can compare products in a simple way for you. "
                    "Tell me the two product names, or tell me the category and your budget, and I’ll break down value, rating, and price for you."
                ),
                intent="comparison_help",
                quick_actions=["Top rated products", "Cheaper options", "Show more"],
            )

        if any(keyword in lowered for keyword in ["thanks", "thank you", "thx"]):
            return respond(
                f"You’re welcome, {first_name}. If you want, I can help you compare products, find a cheaper option, or track your latest order next.",
                intent="gratitude",
                quick_actions=["Show top deals", "Track my order", "Recommend products"],
            )

        if any(keyword in lowered for keyword in ["help me choose", "which one", "what should i buy", "confused"]):
            return respond(
                f"I can help with that, {first_name}. Tell me the product type, your budget, and whether you want value, premium quality, or best rating, and I’ll narrow it down with you.",
                intent="guided_help",
                quick_actions=["Budget products", "Top rated products", "Show footwear"],
            )

        if any(keyword in lowered for keyword in ["hello", "hi", "hey", "good morning", "good evening"]):
            return respond(
                f"Hi {first_name}, I’m right here with you. Tell me what you want to shop for, your budget, or even the kind of style you like, and I’ll help you choose step by step in a simple way.",
                intent="greeting",
                quick_actions=["Show top deals", "Track my order", "Recommend products"],
            )

        if current_product and any(keyword in lowered for keyword in ["this product", "this one", "is this good", "tell me about this", "should i buy", "worth it"]):
            seller_note = f" It is sold by {current_product.seller.shop_name}." if current_product.seller and current_product.seller.shop_name else ""
            return respond(
                (
                    f"{first_name}, {current_product.name} is currently priced at INR {int(current_product.price):,} with a "
                    f"{current_product.rating:.1f} rating from {current_product.reviews_count} review(s). "
                    f"It fits into {current_product.category.name} and is tagged as {current_product.tag.lower()}.{seller_note} "
                    "If you want, I can also suggest similar options, a cheaper alternative, or help you decide based on your budget."
                ),
                intent="current_product_help",
                products=_serialize_chat_products([current_product]),
                quick_actions=["Cheaper options", "Show more", "Compare products"],
            )

        if any(keyword in lowered for keyword in ["pincode", "deliver to", "delivery address", "my address"]):
            if default_address:
                return respond(
                    (
                        f"I’ve got your default delivery location as {default_address.label}, {default_address.city} {default_address.pincode}. "
                        "You can use that address directly during checkout, or switch to another saved address from your account before placing the order."
                    ),
                    intent="delivery_address_help",
                    quick_actions=["Track my order", "Recommend products", "Show top deals"],
                )
            return respond(
                "You have not saved a delivery address yet. Add one in your account page and I can help you use it during checkout.",
                intent="delivery_address_help",
                quick_actions=["Open account page", "Show top deals", "Recommend products"],
            )

        latest_order = None
        if user:
            latest_order = (
                session.query(Order)
                .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
                .filter(Order.user_id == user.id)
                .order_by(Order.created_at.desc())
                .first()
            )

        if any(keyword in lowered for keyword in ["order", "delivery", "track", "shipment", "where is my order"]):
            if latest_order:
                order_payload = serialize_order(latest_order)
                return respond(
                    (
                        f"{first_name}, I checked your latest order for you. Order #{order_payload['id']} is currently "
                        f"{order_payload['status']}, and I’m expecting delivery around "
                        f"{order_payload['delivery_tracking']['estimated_delivery_date']}. "
                        "If you want, I can also help you open the full orders page or suggest something similar to what you bought."
                    ),
                    intent="order_tracking",
                    order=order_payload,
                    quick_actions=["Show top deals", "Recommend gifts", "Open orders page"],
                )
            return respond(
                f"I couldn’t find an order yet, {first_name}. Once you place one, I can track the delivery for you here.",
                intent="order_tracking",
                quick_actions=["Show top deals", "Browse new arrivals", "Open cart"],
            )

        if any(keyword in lowered for keyword in ["deal", "discount", "offer", "cheap", "budget", "under"]):
            max_price = 2000 if "under" in lowered or "budget" in lowered or "cheap" in lowered else None
            query = products_query.filter(Product.stock > 0)
            if max_price:
                query = query.filter(Product.price <= max_price)
            products = (
                query.order_by(Product.deal_of_the_day.desc(), Product.rating.desc(), Product.price.asc())
                .limit(6)
                .all()
            )
            return respond(
                f"I found some strong value picks for you, {first_name}. These look like the better budget-friendly options in the catalog right now. If you want, I can narrow them by style, category, or price band next.",
                intent="deals",
                products=_serialize_chat_products(products),
                quick_actions=["Show top rated", "Suggest footwear", "Search ethnic wear"],
            )

        if any(keyword in lowered for keyword in ["more", "another", "something else", "show more"]):
            category_slug = _keyword_category_slug(last_user_message or lowered)
            query = products_query.filter(Product.stock > 0)
            if category_slug:
                query = query.join(Product.category).filter(Category.slug == category_slug)
            products = query.order_by(Product.rating.desc(), Product.reviews_count.desc()).limit(6).all()
            return respond(
                f"Sure, {first_name}. Here are a few more options you can look through. If any one feels close to what you want, I can help you compare it with a cheaper or better-rated option too.",
                intent="more_options",
                products=_serialize_chat_products(products),
                quick_actions=["Cheaper options", "Top rated products", "Track my order"],
            )

        if any(keyword in lowered for keyword in ["cheaper", "lower price", "less expensive", "budget option"]):
            category_slug = _keyword_category_slug(last_user_message or lowered)
            query = products_query.filter(Product.stock > 0)
            if category_slug:
                query = query.join(Product.category).filter(Category.slug == category_slug)
            products = query.order_by(Product.price.asc(), Product.rating.desc()).limit(6).all()
            return respond(
                f"Of course, {first_name}. I picked the lower-price options first so you can compare the affordable side of the catalog without losing track of ratings.",
                intent="cheaper_options",
                products=_serialize_chat_products(products),
                quick_actions=["Show more", "Top rated products", "Recommend products"],
            )

        if any(keyword in lowered for keyword in ["recommend", "suggest", "gift", "best", "top rated"]):
            category_slug = _keyword_category_slug(lowered)
            query = products_query.filter(Product.stock > 0)
            if category_slug:
                query = query.join(Product.category).filter(Category.slug == category_slug)
            elif cart_items:
                cart_product_ids = [item.get("product_id") for item in cart_items if item.get("product_id")]
                cart_products = (
                    products_query.filter(Product.id.in_(cart_product_ids)).all() if cart_product_ids else []
                )
                category_ids = {product.category_id for product in cart_products}
                if category_ids:
                    query = query.filter(Product.category_id.in_(category_ids), ~Product.id.in_(cart_product_ids))
            products = query.order_by(Product.rating.desc(), Product.reviews_count.desc()).limit(6).all()
            return respond(
                f"I looked through the catalog and these feel like the best match for you right now, {first_name}. If you want, I can also show a cheaper set, a more premium set, or help you compare two options side by side.",
                intent="recommendations",
                products=_serialize_chat_products(products),
                quick_actions=["Show more", "Cheaper options", "Compare products"],
            )

        if any(keyword in lowered for keyword in ["wishlist", "saved"]):
            if not user:
                return respond(
                    "Login first and I can also help with your wishlist and order tracking.",
                    intent="wishlist",
                    quick_actions=["Login", "Show top deals", "Browse products"],
                )
            wishlist_items = session.query(WishlistItem).filter(WishlistItem.user_id == user.id).count()
            return respond(
                f"You currently have {wishlist_items} item(s) saved in your wishlist, {first_name}. If you want, I can suggest the strongest item from that list or help you find a cheaper alternative.",
                intent="wishlist",
                quick_actions=["Open wishlist", "Show top rated", "Suggest gifts"],
            )

        category_slug = _keyword_category_slug(lowered)
        shopping_terms = _extract_shopping_terms(message)
        if not shopping_terms and message:
            shopping_terms = [message.lower()]
        query = products_query
        if shopping_terms or category_slug:
            query = query.join(Product.category)
        if shopping_terms:
            query = query.filter(
                and_(
                    *[
                        or_(
                            Product.name.ilike(f"%{term}%"),
                            Product.description.ilike(f"%{term}%"),
                            Product.tag.ilike(f"%{term}%"),
                            Product.highlights.ilike(f"%{term}%"),
                            Product.secondary_categories.ilike(f"%{term}%"),
                            Category.name.ilike(f"%{term}%"),
                        )
                        for term in shopping_terms
                    ]
                )
            )
        if category_slug:
            query = query.filter(Category.slug == category_slug)
        products = query.order_by(Product.rating.desc(), Product.reviews_count.desc()).limit(6).all()

        if products:
            return respond(
                f"I found these products based on what you asked for, {first_name}. If this is not exactly the style you want, tell me your budget, brand preference, or use case and I’ll refine it with you.",
                intent="product_search",
                products=_serialize_chat_products(products),
                quick_actions=["Show more", "Cheaper options", "Compare products"],
            )

        if shopping_terms:
            search_label = ", ".join(shopping_terms[:2])
            return respond(
                (
                    f"I checked the live SwiftCart catalog for {search_label}, {first_name}, and I could not find a strong direct match right now. "
                    "If you want, ask for a related category, your budget, or a nearby alternative and I’ll try a smarter recommendation."
                ),
                intent="product_not_available",
                quick_actions=["Show top deals", "Recommend products", "Top rated products"],
            )

        fallback = (
            f"I’m with you, {first_name}. Tell me what you want to buy, how much you want to spend, or whether you care more about rating, looks, or value, and I’ll guide you naturally from there."
        )
        return respond(
            fallback,
            intent="fallback",
            quick_actions=["Show top deals", "Track my order", "Top rated products"],
        )


@products_bp.get("/merchant/dashboard")
def merchant_dashboard():
    with session_scope() as session:
        _expire_category_discounts(session)
        merchant, error = _require_merchant(session)
        if error:
            return error

        products = (
            session.query(Product)
            .filter(Product.seller_id == merchant.id)
            .all()
        )
        return jsonify(
            {
                "merchant": serialize_user(merchant),
                "totals": {
                    "products": len(products),
                    "in_stock_products": sum(1 for product in products if product.stock > 0),
                    "featured_products": sum(1 for product in products if product.featured),
                    "deal_products": sum(1 for product in products if product.deal_of_the_day),
                    "reviews": sum(product.reviews_count for product in products),
                },
            }
        )


@products_bp.get("/merchant/products")
def merchant_list_products():
    with session_scope() as session:
        merchant, error = _require_merchant(session)
        if error:
            return error
        products = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.seller_id == merchant.id)
            .order_by(Product.created_at.desc())
            .all()
        )
        categories = session.query(Category).order_by(Category.name.asc()).all()
        return jsonify(
            {
                "merchant": serialize_user(merchant),
                "products": [serialize_product(product) for product in products],
                "categories": [
                    {
                        "id": category.id,
                        "name": category.name,
                        "slug": category.slug,
                    }
                    for category in categories
                ],
            }
        )


@products_bp.post("/merchant/products")
def merchant_create_product():
    payload = request.get_json(silent=True) or {}
    required = ["name", "slug", "category_id", "image", "price", "original_price", "stock"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        merchant, error = _require_merchant(session)
        if error:
            return error
        normalized_slug = _normalized_slug(payload["slug"])
        existing = session.query(Product).filter(Product.slug == normalized_slug).first()
        if existing:
            return jsonify({"message": "A product with this slug already exists."}), 409
        try:
            price, original_price = _normalize_price_values(payload["price"], payload["original_price"])
            stock = _normalize_stock_value(payload["stock"])
        except ValueError as error:
            return jsonify({"message": str(error)}), 400

        product = Product(
            name=payload["name"].strip(),
            slug=normalized_slug,
            category_id=int(payload["category_id"]),
            image=payload["image"].strip(),
            price=price,
            original_price=original_price,
            stock=stock,
            rating=float(payload.get("rating", 4.0)),
            reviews_count=int(payload.get("reviews_count", 0)),
            tag=payload.get("tag", "").strip() or "Merchant Pick",
            description=payload.get("description", "").strip() or "Merchant listed product.",
            highlights=payload.get("highlights", "").strip() or "Merchant listing|Fresh product",
            specifications=payload.get("specifications", "").strip() or "Origin=India",
            secondary_categories=_normalize_secondary_categories(payload.get("secondary_categories", "")),
            delivery_note=payload.get("delivery_note", "").strip() or "Delivery in 2-5 business days",
            featured=bool(payload.get("featured", False)),
            deal_of_the_day=bool(payload.get("deal_of_the_day", False)),
            seller_id=merchant.id,
        )
        session.add(product)
        session.flush()
        product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.id == product.id)
            .first()
        )
        return jsonify({"message": "Product created successfully.", "product": serialize_product(product)}), 201


@products_bp.put("/merchant/products/<int:product_id>")
def merchant_update_product(product_id: int):
    payload = request.get_json(silent=True) or {}
    with session_scope() as session:
        merchant, error = _require_merchant(session)
        if error:
            return error
        product = (
            session.query(Product)
            .filter(Product.id == product_id, Product.seller_id == merchant.id)
            .first()
        )
        if not product:
            return jsonify({"message": "Merchant product not found."}), 404

        for field in ["name", "slug", "image", "tag", "description", "delivery_note"]:
            if field in payload:
                setattr(product, field, str(payload[field]).strip())

        if "slug" in payload:
            normalized_slug = _normalized_slug(payload["slug"])
            existing = (
                session.query(Product)
                .filter(Product.slug == normalized_slug, Product.id != product.id)
                .first()
            )
            if existing:
                return jsonify({"message": "Another product already uses this slug."}), 409
            product.slug = normalized_slug

        if "category_id" in payload:
            product.category_id = int(payload["category_id"])
        if "price" in payload or "original_price" in payload:
            try:
                product.price, product.original_price = _normalize_price_values(
                    payload.get("price", product.price),
                    payload.get("original_price", product.original_price),
                )
            except ValueError as error:
                return jsonify({"message": str(error)}), 400
        if "stock" in payload:
            try:
                product.stock = _normalize_stock_value(payload["stock"])
            except ValueError as error:
                return jsonify({"message": str(error)}), 400
        if "featured" in payload:
            product.featured = bool(payload["featured"])
        if "deal_of_the_day" in payload:
            product.deal_of_the_day = bool(payload["deal_of_the_day"])
        if "highlights" in payload:
            product.highlights = str(payload["highlights"]).strip()
        if "specifications" in payload:
            product.specifications = str(payload["specifications"]).strip()
        if "secondary_categories" in payload:
            product.secondary_categories = _normalize_secondary_categories(payload.get("secondary_categories", ""))

        session.flush()
        product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.id == product.id)
            .first()
        )
        return jsonify({"message": "Product updated successfully.", "product": serialize_product(product)})


@products_bp.get("/admin/dashboard")
def admin_dashboard():
    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error

        _expire_category_discounts(session)
        category_count = session.query(Category).count()
        all_products = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .order_by(Product.created_at.desc())
            .all()
        )
        product_count = len(all_products)
        in_stock_count = sum(1 for product in all_products if product.stock > 0)
        out_of_stock_count = sum(1 for product in all_products if product.stock <= 0)
        low_stock_count = sum(1 for product in all_products if 0 < product.stock <= 5)
        discounted_product_count = sum(
            1 for product in all_products if float(product.original_price or 0) > float(product.price or 0)
        )
        seller_listed_count = sum(1 for product in all_products if product.seller_id is not None)
        managed_catalog_count = product_count - seller_listed_count
        featured_count = sum(1 for product in all_products if product.featured)
        user_count = session.query(User).count()
        order_count = session.query(Order).count()
        revenue = session.query(Order).all()
        wishlist_count = session.query(WishlistItem).count()
        review_count = session.query(Review).count()
        merchant_count = session.query(User).filter(User.account_type.in_(["merchant", "seller"])).count()
        all_users = (
            session.query(User)
            .options(joinedload(User.addresses))
            .order_by(User.created_at.desc())
            .all()
        )
        all_user_rows = session.query(User).all()
        all_orders = (
            session.query(Order)
            .options(joinedload(Order.items).joinedload(OrderItem.product), joinedload(Order.user))
            .order_by(Order.created_at.desc())
            .all()
        )
        all_reviews = (
            session.query(Review)
            .options(joinedload(Review.product))
            .order_by(Review.created_at.desc())
            .all()
        )
        all_chat_messages = (
            session.query(ChatMessage)
            .options(joinedload(ChatMessage.user))
            .order_by(ChatMessage.created_at.desc())
            .all()
        )
        all_change_logs = (
            session.query(UserChangeLog)
            .options(joinedload(UserChangeLog.user))
            .order_by(UserChangeLog.created_at.desc())
            .all()
        )
        now = datetime.utcnow()
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        users_last_7 = [user for user in all_user_rows if user.created_at >= seven_days_ago]
        users_last_30 = [user for user in all_user_rows if user.created_at >= thirty_days_ago]
        orders_last_7 = [order for order in revenue if order.created_at >= seven_days_ago]
        orders_last_30 = [order for order in revenue if order.created_at >= thirty_days_ago]
        cancelled_orders = [order for order in revenue if order.status.lower() == "cancelled"]

        order_activity = []
        for day_offset in range(6, -1, -1):
            day_start = (now - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            bucket = [order for order in revenue if day_start <= order.created_at < day_end]
            order_activity.append(
                {
                    "date": day_start.date().isoformat(),
                    "label": day_start.strftime("%d %b"),
                    "orders": len(bucket),
                    "revenue": round(sum(order.total_amount for order in bucket), 2),
                }
            )

        hourly_activity = []
        for hour in range(24):
            bucket = [order for order in revenue if order.created_at.hour == hour]
            hourly_activity.append(
                {
                    "hour": f"{hour:02d}:00",
                    "orders": len(bucket),
                }
            )

        finance_series = []
        order_series = []
        cancelled_series = []
        for day_offset in range(13, -1, -1):
            day_start = (now - timedelta(days=day_offset)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            bucket = [order for order in revenue if day_start <= order.created_at < day_end]
            finance_series.append(
                {
                    "date": day_start.date().isoformat(),
                    "label": day_start.strftime("%d %b"),
                    "value": round(sum(order.total_amount for order in bucket), 2),
                }
            )
            order_series.append(
                {
                    "date": day_start.date().isoformat(),
                    "label": day_start.strftime("%d %b"),
                    "value": len(bucket),
                }
            )
            cancelled_bucket = [order for order in cancelled_orders if order.canceled_at and day_start <= order.canceled_at < day_end]
            cancelled_series.append(
                {
                    "date": day_start.date().isoformat(),
                    "label": day_start.strftime("%d %b"),
                    "value": len(cancelled_bucket),
                }
            )

        category_lookup = {category.id: category for category in session.query(Category).all()}
        category_performance_map = {
            category.id: {
                "category_id": category.id,
                "category_name": category.name,
                "products": 0,
                "in_stock_products": 0,
                "out_of_stock_products": 0,
                "low_stock_products": 0,
                "ordered_units": 0,
                "cancelled_units": 0,
                "revenue": 0.0,
            }
            for category in category_lookup.values()
        }
        for product in all_products:
            if product.category_id in category_performance_map:
                category_performance_map[product.category_id]["products"] += 1
                if product.stock <= 0:
                    category_performance_map[product.category_id]["out_of_stock_products"] += 1
                else:
                    category_performance_map[product.category_id]["in_stock_products"] += 1
                if 0 < product.stock <= 5:
                    category_performance_map[product.category_id]["low_stock_products"] += 1
        for order in all_orders:
            for item in order.items:
                category_id = item.product.category_id
                if category_id not in category_performance_map:
                    continue
                category_performance_map[category_id]["ordered_units"] += item.quantity
                category_performance_map[category_id]["revenue"] += item.quantity * item.unit_price
                if order.status.lower() == "cancelled":
                    category_performance_map[category_id]["cancelled_units"] += item.quantity
        category_performance = sorted(
            category_performance_map.values(),
            key=lambda item: (item["ordered_units"], item["revenue"]),
            reverse=True,
        )
        bank_offers = [
            _build_bank_offer(entry["category_name"], index)
            for index, entry in enumerate(category_performance[:8] or [])
        ]
        active_category_discounts = (
            session.query(CategoryDiscount)
            .options(joinedload(CategoryDiscount.category))
            .filter(CategoryDiscount.active.is_(True))
            .order_by(CategoryDiscount.expires_at.asc())
            .all()
        )

        chat_messages_payload = [
            {
                "id": chat.id,
                "role": chat.role,
                "intent": chat.intent,
                "page": chat.page,
                "message": chat.message,
                "created_at": chat.created_at.isoformat(),
                "user": (
                    {
                        "id": chat.user.id,
                        "full_name": f"{chat.user.first_name} {chat.user.last_name}".strip(),
                        "email": chat.user.email,
                        "unique_code": chat.user.unique_code,
                        "account_type": chat.user.account_type,
                    }
                    if chat.user
                    else None
                ),
            }
            for chat in all_chat_messages[:60]
        ]

        linked_mobile_accounts = {}
        for member in all_users:
            linked_mobile_accounts.setdefault(member.mobile, []).append(member)
        linked_mobile_accounts = [
            {
                "mobile": mobile,
                "count": len(members),
                "accounts": [
                    {
                        "id": member.id,
                        "unique_code": member.unique_code,
                        "full_name": f"{member.first_name} {member.last_name}".strip(),
                        "email": member.email,
                        "account_type": member.account_type,
                    }
                    for member in members
                ],
            }
            for mobile, members in linked_mobile_accounts.items()
            if len(members) > 1
        ]

        user_payload = [serialize_user(member) for member in all_users]

        return jsonify(
            {
                "owner": serialize_user(owner),
                "totals": {
                    "categories": category_count,
                    "products": product_count,
                    "in_stock_products": in_stock_count,
                    "out_of_stock_products": out_of_stock_count,
                    "low_stock_products": low_stock_count,
                    "featured_products": featured_count,
                    "users": user_count,
                    "orders": order_count,
                    "wishlist_items": wishlist_count,
                    "reviews": review_count,
                    "revenue": round(sum(order.total_amount for order in revenue), 2),
                    "cancelled_orders": len(cancelled_orders),
                    "chat_messages": len(all_chat_messages),
                },
                "inventory": {
                    "seller_listed_products": seller_listed_count,
                    "platform_managed_products": managed_catalog_count,
                    "discounted_products": discounted_product_count,
                },
                "growth": {
                    "users_last_7_days": len(users_last_7),
                    "users_last_30_days": len(users_last_30),
                    "orders_last_7_days": len(orders_last_7),
                    "orders_last_30_days": len(orders_last_30),
                    "revenue_last_7_days": round(sum(order.total_amount for order in orders_last_7), 2),
                    "revenue_last_30_days": round(sum(order.total_amount for order in orders_last_30), 2),
                    "merchant_accounts": merchant_count,
                },
                "order_activity": order_activity,
                "hourly_activity": hourly_activity,
                "finance_series": finance_series,
                "order_series": order_series,
                "cancelled_series": cancelled_series,
                "category_performance": category_performance,
                "bank_offers": bank_offers,
                "active_category_discounts": [_serialize_category_discount(discount) for discount in active_category_discounts],
                "users": user_payload,
                "orders": [serialize_order(order) for order in all_orders],
                "reviews": [
                    {
                        "id": review.id,
                        "product_id": review.product_id,
                        "product_name": review.product.name,
                        "product_slug": review.product.slug,
                        "author_name": review.author_name,
                        "rating": review.rating,
                        "title": review.title,
                        "comment": review.comment,
                        "image": review.image,
                        "created_at": review.created_at.isoformat(),
                    }
                    for review in all_reviews
                ],
                "linked_mobile_accounts": linked_mobile_accounts,
                "chat_messages": chat_messages_payload,
                "user_change_logs": [
                    {
                        "id": log.id,
                        "field_name": log.field_name,
                        "old_value": log.old_value,
                        "new_value": log.new_value,
                        "changed_by": log.changed_by,
                        "created_at": log.created_at.isoformat(),
                        "user": {
                            "id": log.user.id,
                            "full_name": f"{log.user.first_name} {log.user.last_name}".strip(),
                            "email": log.user.email,
                            "unique_code": log.user.unique_code,
                        } if log.user else None,
                    }
                    for log in all_change_logs[:80]
                ],
            }
        )


@products_bp.get("/admin/database/overview")
def admin_database_overview():
    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        owner_payload = serialize_user(owner)

    with engine.connect() as connection:
        tables = []
        for table_name in _database_table_names(connection):
            safe_name = table_name.replace('"', '""')
            count = connection.exec_driver_sql(
                f'SELECT COUNT(*) FROM "{safe_name}"'
            ).scalar_one()
            tables.append({"name": table_name, "rows": count})

    return jsonify(
        {
            "owner": owner_payload,
            "database_path": str(DATABASE_PATH),
            "tables": tables,
        }
    )


@products_bp.get("/admin/database/table/<table_name>")
def admin_database_table(table_name: str):
    limit = min(max(request.args.get("limit", default=50, type=int), 1), 200)

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        owner_payload = serialize_user(owner)

    with engine.connect() as connection:
        tables = set(_database_table_names(connection))
        if table_name not in tables:
            return jsonify({"message": "Table not found."}), 404

        safe_name = table_name.replace('"', '""')
        count = connection.exec_driver_sql(
            f'SELECT COUNT(*) FROM "{safe_name}"'
        ).scalar_one()
        result = connection.exec_driver_sql(
            f'SELECT * FROM "{safe_name}" LIMIT {limit}'
        )
        rows = [dict(row) for row in result.mappings().all()]
        columns = list(result.keys())

    return jsonify(
        {
            "owner": owner_payload,
            "table": table_name,
            "limit": limit,
            "total_rows": count,
            "columns": columns,
            "rows": rows,
        }
    )


@products_bp.post("/admin/database/query")
def admin_database_query():
    payload = request.get_json(silent=True) or {}

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        owner_payload = serialize_user(owner)

    try:
        statement = _normalize_sql_statement(str(payload.get("sql", "")))
    except ValueError as error:
        return jsonify({"message": str(error)}), 400

    operation = statement.split(None, 1)[0].upper()

    with engine.begin() as connection:
        result = connection.exec_driver_sql(statement)
        if result.returns_rows:
            rows = [dict(row) for row in result.mappings().all()]
            columns = list(result.keys())
            return jsonify(
                {
                    "owner": owner_payload,
                    "operation": operation,
                    "columns": columns,
                    "rows": rows,
                    "affected_rows": len(rows),
                }
            )

        return jsonify(
            {
                "owner": owner_payload,
                "operation": operation,
                "columns": [],
                "rows": [],
                "affected_rows": result.rowcount if result.rowcount is not None else 0,
            }
        )


@products_bp.get("/admin/products")
def admin_list_products():
    with session_scope() as session:
        _expire_category_discounts(session)
        owner, error = _require_owner(session)
        if error:
            return error
        products = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .order_by(Product.created_at.desc())
            .all()
        )
        categories = session.query(Category).order_by(Category.name.asc()).all()
        return jsonify(
            {
                "owner": serialize_user(owner),
                "products": [serialize_product(product) for product in products],
                "categories": [
                    {
                        "id": category.id,
                        "name": category.name,
                        "slug": category.slug,
                    }
                    for category in categories
                ],
            }
        )


@products_bp.post("/admin/categories")
def admin_create_category():
    payload = request.get_json(silent=True) or {}
    name = _title_case(payload.get("name", ""))
    if not name:
        return jsonify({"message": "Category name is required."}), 400

    slug = _normalized_slug(payload.get("slug") or name)
    if not slug:
        return jsonify({"message": "Category slug is required."}), 400

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        existing = session.query(Category).filter(or_(Category.name == name, Category.slug == slug)).first()
        if existing:
            return jsonify({"message": "This category already exists."}), 409

        category = Category(
            name=name,
            slug=slug,
            description=_sentence_case(payload.get("description", "")) or f"{name} products on SwiftCart.",
            banner_title=_sentence_case(payload.get("banner_title", "")) or f"Explore {name}",
        )
        session.add(category)
        session.flush()
        return jsonify(
            {
                "message": "Category created successfully.",
                "category": {
                    "id": category.id,
                    "name": category.name,
                    "slug": category.slug,
                    "description": category.description,
                    "banner_title": category.banner_title,
                },
            }
        ), 201


@products_bp.post("/admin/category-discount")
def admin_apply_category_discount():
    payload = request.get_json(silent=True) or {}
    category_id = payload.get("category_id")
    discount_percent = float(payload.get("discount_percent", 0) or 0)
    include_secondary = bool(payload.get("include_secondary", True))
    duration_hours = int(payload.get("duration_hours", 24) or 24)

    if not category_id:
        return jsonify({"message": "Select a category first."}), 400
    if discount_percent <= 0 or discount_percent >= 100:
        return jsonify({"message": "Discount percent must be between 1 and 99."}), 400
    if duration_hours < 1 or duration_hours > 720:
        return jsonify({"message": "Discount duration must be between 1 and 720 hours."}), 400

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        _expire_category_discounts(session)

        category = session.query(Category).filter(Category.id == int(category_id)).first()
        if not category:
            return jsonify({"message": "Category not found."}), 404

        products = _matching_discount_products(session, category, include_secondary)
        if not products:
            return jsonify({"message": "No products found in this category."}), 404

        existing_discounts = (
            session.query(CategoryDiscount)
            .filter(CategoryDiscount.category_id == category.id, CategoryDiscount.active.is_(True))
            .all()
        )
        for discount in existing_discounts:
            discount.active = False
            discount.removed_at = datetime.utcnow()

        updated_count = 0
        for product in products:
            base_price = product.original_price if product.original_price and product.original_price >= product.price else product.price
            discounted_price = max(1, round(base_price * (1 - discount_percent / 100)))
            product.original_price = float(base_price)
            product.price = float(discounted_price)
            product.deal_of_the_day = True
            updated_count += 1

        expires_at = datetime.utcnow() + timedelta(hours=duration_hours)
        discount = CategoryDiscount(
            category_id=category.id,
            discount_percent=discount_percent,
            include_secondary=include_secondary,
            expires_at=expires_at,
            affected_products=updated_count,
            active=True,
        )
        session.add(discount)
        session.flush()

        return jsonify(
            {
                "message": f"Applied {int(discount_percent)}% discount to {updated_count} product(s) in {category.name} for {duration_hours} hour(s).",
                "category": {
                    "id": category.id,
                    "name": category.name,
                },
                "updated_count": updated_count,
                "discount_percent": int(discount_percent),
                "duration_hours": duration_hours,
                "expires_at": expires_at.isoformat(),
                "discount": _serialize_category_discount(discount),
            }
        )


@products_bp.post("/admin/category-discount/remove")
def admin_remove_category_discount():
    payload = request.get_json(silent=True) or {}
    category_id = payload.get("category_id")
    include_secondary = bool(payload.get("include_secondary", True))

    if not category_id:
        return jsonify({"message": "Select a category first."}), 400

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        _expire_category_discounts(session)

        category = session.query(Category).filter(Category.id == int(category_id)).first()
        if not category:
            return jsonify({"message": "Category not found."}), 404

        products = _matching_discount_products(session, category, include_secondary)
        if not products:
            return jsonify({"message": "No products found in this category."}), 404

        updated_count = _restore_discounted_products(products)

        active_discounts = (
            session.query(CategoryDiscount)
            .filter(CategoryDiscount.category_id == category.id, CategoryDiscount.active.is_(True))
            .all()
        )
        removed_at = datetime.utcnow()
        for discount in active_discounts:
            discount.active = False
            discount.removed_at = removed_at

        return jsonify(
            {
                "message": f"Removed category discount from {updated_count} product(s) in {category.name}.",
                "category": {
                    "id": category.id,
                    "name": category.name,
                },
                "updated_count": updated_count,
                "removed_at": removed_at.isoformat(),
            }
        )


@products_bp.post("/admin/uploads/product-image")
def admin_upload_product_image():
    uploaded_file = request.files.get("image")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"message": "Choose a product image to upload."}), 400

    safe_name = secure_filename(uploaded_file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_PRODUCT_IMAGE_SUFFIXES:
        return jsonify({"message": "Only PNG, JPG, JPEG, or WEBP files are allowed."}), 400

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error

    PRODUCT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    final_name = f"product-{secrets.token_hex(8)}{suffix}"
    target_path = PRODUCT_UPLOAD_DIR / final_name
    uploaded_file.save(target_path)
    return jsonify(
        {
            "message": "Product image uploaded successfully.",
            "image": f"uploads/products/{final_name}",
        }
    ), 201


@products_bp.post("/admin/products")
def admin_create_product():
    payload = request.get_json(silent=True) or {}
    required = ["name", "slug", "category_id", "image", "price", "original_price", "stock"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        normalized_slug = _normalized_slug(payload["slug"])
        existing = session.query(Product).filter(Product.slug == normalized_slug).first()
        if existing:
            return jsonify({"message": "A product with this slug already exists."}), 409
        try:
            price, original_price = _normalize_price_values(payload["price"], payload["original_price"])
            stock = _normalize_stock_value(payload["stock"])
        except ValueError as error:
            return jsonify({"message": str(error)}), 400

        product = Product(
            name=_sentence_case(payload["name"]),
            slug=normalized_slug,
            category_id=int(payload["category_id"]),
            image=payload["image"].strip(),
            price=price,
            original_price=original_price,
            stock=stock,
            rating=float(payload.get("rating", 4.0)),
            reviews_count=int(payload.get("reviews_count", 0)),
            tag=_sentence_case(payload.get("tag", "")) or "New Arrival",
            description=_sentence_case(payload.get("description", "")) or "New catalog item.",
            highlights=_sentence_case(payload.get("highlights", "")) or "Fresh listing|Marketplace product",
            specifications=payload.get("specifications", "").strip() or "Origin=India",
            secondary_categories=_normalize_secondary_categories(payload.get("secondary_categories", "")),
            delivery_note=_sentence_case(payload.get("delivery_note", "")) or "Delivery in 2-5 business days",
            featured=bool(payload.get("featured", False)),
            deal_of_the_day=bool(payload.get("deal_of_the_day", False)),
        )
        session.add(product)
        session.flush()
        session.refresh(product)
        product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.id == product.id)
            .first()
        )
        return jsonify({"message": "Product created successfully.", "product": serialize_product(product)}), 201


@products_bp.put("/admin/products/<int:product_id>")
def admin_update_product(product_id: int):
    payload = request.get_json(silent=True) or {}
    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        product = session.query(Product).filter(Product.id == product_id).first()
        if not product:
            return jsonify({"message": "Product not found."}), 404

        for field in ["name", "slug", "image", "tag", "description", "delivery_note"]:
            if field in payload:
                value = str(payload[field]).strip()
                if field == "name":
                    value = _sentence_case(value)
                elif field == "slug":
                    value = _normalized_slug(value)
                    existing = (
                        session.query(Product)
                        .filter(Product.slug == value, Product.id != product.id)
                        .first()
                    )
                    if existing:
                        return jsonify({"message": "Another product already uses this slug."}), 409
                elif field in {"tag", "description", "delivery_note"}:
                    value = _sentence_case(value)
                setattr(product, field, value)

        if "category_id" in payload:
            product.category_id = int(payload["category_id"])
        if "price" in payload or "original_price" in payload:
            try:
                product.price, product.original_price = _normalize_price_values(
                    payload.get("price", product.price),
                    payload.get("original_price", product.original_price),
                )
            except ValueError as error:
                return jsonify({"message": str(error)}), 400
        if "stock" in payload:
            try:
                product.stock = _normalize_stock_value(payload["stock"])
            except ValueError as error:
                return jsonify({"message": str(error)}), 400
        if "rating" in payload:
            product.rating = float(payload["rating"])
        if "reviews_count" in payload:
            product.reviews_count = int(payload["reviews_count"])
        if "featured" in payload:
            product.featured = bool(payload["featured"])
        if "deal_of_the_day" in payload:
            product.deal_of_the_day = bool(payload["deal_of_the_day"])
        if "highlights" in payload:
            product.highlights = str(payload["highlights"]).strip()
        if "specifications" in payload:
            product.specifications = str(payload["specifications"]).strip()
        if "secondary_categories" in payload:
            product.secondary_categories = _normalize_secondary_categories(payload.get("secondary_categories", ""))

        session.flush()
        session.refresh(product)
        product = (
            session.query(Product)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(Product.id == product.id)
            .first()
        )
        return jsonify({"message": "Product updated successfully.", "product": serialize_product(product)})


@products_bp.delete("/admin/products/<int:product_id>")
def admin_delete_product(product_id: int):
    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error
        product = session.query(Product).filter(Product.id == product_id).first()
        if not product:
            return jsonify({"message": "Product not found."}), 404

        product_name = product.name
        session.delete(product)
        return jsonify({"message": f"{product_name} deleted successfully."})
