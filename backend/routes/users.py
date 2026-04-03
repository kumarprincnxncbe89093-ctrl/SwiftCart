import base64
import json
import os
import random
import secrets
from datetime import datetime, timedelta
import ipaddress
from pathlib import Path
from urllib.parse import urlencode

from flask import Blueprint, jsonify, redirect, request
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from werkzeug.utils import secure_filename

from backend.auth import create_auth_token, require_authenticated_user
from backend.models import (
    Address,
    BASE_DIR,
    ENABLE_DEMO_LOGINS,
    OtpCode,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    Product,
    User,
    WishlistItem,
    create_otp,
    generate_unique_code,
    hash_password,
    is_bcrypt_hash,
    get_password_history,
    log_user_change,
    push_password_history,
    serialize_address,
    serialize_product,
    serialize_user,
    session_scope,
    verify_password,
)


users_bp = Blueprint("users", __name__)
PROFILE_UPLOAD_DIR = BASE_DIR.parent / "frontend" / "uploads" / "profiles"
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CAPTCHA_TTL_SECONDS = 300
CAPTCHA_SALT = "swiftcart-captcha"
OTP_PREVIEW_OVERRIDE = os.getenv("SWIFTCART_EXPOSE_OTP_PREVIEW")
LEGACY_DEMO_LOGIN_EMAILS = {
    "owner@demo.com",
    "merchant@demo.com",
    "user@demo.com",
    "demo@swiftcart.com",
}


def _title_case(value: str) -> str:
    parts = [part for part in value.strip().split() if part]
    return " ".join(part[:1].upper() + part[1:].lower() for part in parts)


def _sentence_case(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ""
    return cleaned[:1].upper() + cleaned[1:]


def _is_local_request() -> bool:
    host = request.host.split(":", 1)[0].strip().lower()
    if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".local"):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _should_show_otp_preview() -> bool:
    if OTP_PREVIEW_OVERRIDE is not None:
        return OTP_PREVIEW_OVERRIDE.strip().lower() in {"1", "true", "yes", "on"}
    if _is_local_request():
        return True
    return (os.getenv("FLASK_ENV") or "").strip().lower() != "production"


def _require_owner(session):
    user, error = require_authenticated_user(session, allowed_roles={"owner"})
    if error:
        return None, error
    return user, None


def _banned_account_response(user: User):
    reason = str(user.ban_reason or "").strip() or "Contact the owner for reactivation."
    return (
        jsonify(
            {
                "message": f"Your account has been banned. {reason}",
                "is_banned": True,
                "force_logout": True,
            }
        ),
        403,
    )


def _auth_response(user: User) -> dict:
    payload = serialize_user(user)
    token = create_auth_token(user)
    payload["auth_token"] = token
    return {
        "token": token,
        "user": payload,
    }


def _require_same_user(session, user_id: int):
    return require_authenticated_user(session, expected_user_id=user_id)


def _ensure_user_is_active(user: User):
    if user and user.is_banned:
        return _banned_account_response(user)
    return None


def _upgrade_password_hash_if_needed(user: User, raw_password: str) -> None:
    if not user or not raw_password or is_bcrypt_hash(user.password_hash):
        return
    user.password_hash = hash_password(raw_password)
    user.password_changed_at = datetime.utcnow()


def _repair_or_bootstrap_owner_account(session, email: str, password: str) -> User | None:
    normalized_owner_email = OWNER_EMAIL.strip().lower()
    configured_owner_password = OWNER_PASSWORD.strip()
    if not normalized_owner_email or not configured_owner_password:
        return None
    if str(email or "").strip().lower() != normalized_owner_email:
        return None
    if password != configured_owner_password:
        return None

    owner = (
        session.query(User)
        .filter(
            or_(
                func.lower(User.email) == normalized_owner_email,
                func.lower(User.email) == "owner@swiftcart.com",
                func.lower(User.email) == "prince12345@gmail.com",
            )
        )
        .order_by(User.id.asc())
        .first()
    )

    if owner is None:
        owner = User(
            first_name="Prince",
            last_name="Kumar",
            email=normalized_owner_email,
            mobile="+910000000000",
            password_hash=hash_password(configured_owner_password),
            unique_code=generate_unique_code(session),
            account_type="owner",
            shop_name="SwiftCart Marketplace",
            gstin="29OWNER0000X1Z0",
            password_changed_at=datetime.utcnow(),
        )
        session.add(owner)
        session.flush()
    else:
        owner.account_type = "owner"
        owner.email = normalized_owner_email
        owner.password_hash = hash_password(configured_owner_password)
        owner.password_changed_at = datetime.utcnow()
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

    if not owner.addresses:
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

    return owner


def _sync_owner_credentials_if_needed(session, user: User, password: str) -> bool:
    normalized_owner_email = OWNER_EMAIL.strip().lower()
    configured_owner_password = OWNER_PASSWORD.strip()
    if not configured_owner_password:
        return False
    if not user:
        return False
    if password != configured_owner_password:
        return False
    if str(user.account_type or "").strip().lower() != "owner" and str(user.email or "").strip().lower() != normalized_owner_email:
        return False
    if normalized_owner_email and str(user.email or "").strip().lower() != normalized_owner_email:
        user.email = normalized_owner_email
    user.account_type = "owner"
    user.password_hash = hash_password(configured_owner_password)
    user.password_changed_at = datetime.utcnow()
    if not user.unique_code:
        user.unique_code = generate_unique_code(session)
    return True


def _next_address_label(user: User) -> str:
    existing_labels = {address.label.strip().lower() for address in user.addresses if address.label}
    defaults = ["Home", "Work", "Office", "Family", "Other"]
    for label in defaults:
        if label.lower() not in existing_labels:
            return label
    return f"Address {len(user.addresses) + 1}"


def _apply_address_updates(session, *, user: User, address: Address, payload: dict, changed_by: str = "user") -> None:
    next_values = {
        "label": _title_case(payload.get("label", "")) or (address.label or _next_address_label(user)),
        "street": _sentence_case(payload.get("street", "")),
        "city": _title_case(payload.get("city", "")),
        "state": _title_case(payload.get("state", "")),
        "pincode": str(payload.get("pincode", "")).strip(),
        "landmark": _title_case(payload.get("landmark", "")),
    }
    current_values = {
        "label": getattr(address, "label", ""),
        "street": getattr(address, "street", ""),
        "city": getattr(address, "city", ""),
        "state": getattr(address, "state", ""),
        "pincode": getattr(address, "pincode", ""),
        "landmark": getattr(address, "landmark", ""),
    }
    for field_name, next_value in next_values.items():
        log_user_change(
            session,
            user_id=user.id,
            field_name=f"address_{field_name}",
            old_value=current_values.get(field_name, ""),
            new_value=next_value,
            changed_by=changed_by,
        )
        setattr(address, field_name, next_value)


def _normalize_mobile(value: str) -> str:
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 10:
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    if raw.startswith("+"):
        return raw
    return f"+{digits}"


def _normalize_login_identifier(value: str) -> str:
    return str(value or "").strip()


def _request_payload() -> dict:
    json_payload = request.get_json(silent=True)
    if isinstance(json_payload, dict) and json_payload:
        return json_payload
    if request.form:
        return request.form.to_dict(flat=True)
    return {}


def _is_disabled_demo_account_email(value: str) -> bool:
    if ENABLE_DEMO_LOGINS:
        return False
    return str(value or "").strip().lower() in LEGACY_DEMO_LOGIN_EMAILS


def _find_user_by_login_identifier(session, identifier: str) -> User | None:
    normalized = _normalize_login_identifier(identifier)
    if not normalized:
        return None

    normalized_lower = normalized.lower()
    user = (
        session.query(User)
        .filter(
            or_(
                func.lower(User.email) == normalized_lower,
                User.unique_code == normalized,
            )
        )
        .order_by(User.created_at.asc())
        .first()
    )
    if user and _is_disabled_demo_account_email(user.email):
        return None
    return user


def _mobile_variants(value: str) -> list[str]:
    raw = str(value or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    variants = {raw, _normalize_mobile(raw)}
    if digits:
        variants.add(digits)
        if len(digits) >= 10:
            tail = digits[-10:]
            variants.update({tail, f"91{tail}", f"+91{tail}"})
    return [variant for variant in variants if variant]


def _find_users_by_mobile(session, mobile: str) -> list[User]:
    variants = _mobile_variants(mobile)
    users: list[User] = []
    for variant in variants:
        matched = session.query(User).filter(User.mobile == variant).order_by(User.created_at.asc()).all()
        for user in matched:
            if _is_disabled_demo_account_email(user.email):
                continue
            if all(existing.id != user.id for existing in users):
                users.append(user)
    return users


def _detect_login_context() -> dict:
    agent = request.headers.get("User-Agent", "")
    lowered = agent.lower()
    platform = "Unknown"
    if "iphone" in lowered or "ios" in lowered:
        platform = "iOS"
    elif "android" in lowered:
        platform = "Android"
    elif "mac os" in lowered or "macintosh" in lowered:
        platform = "macOS"
    elif "windows" in lowered:
        platform = "Windows"
    elif "linux" in lowered:
        platform = "Linux"

    browser = "Browser"
    if "edg/" in lowered:
        browser = "Edge"
    elif "chrome/" in lowered and "edg/" not in lowered:
        browser = "Chrome"
    elif "safari/" in lowered and "chrome/" not in lowered:
        browser = "Safari"
    elif "firefox/" in lowered:
        browser = "Firefox"

    if any(keyword in lowered for keyword in ["iphone", "android", "mobile"]):
        device = "Mobile"
    elif any(keyword in lowered for keyword in ["ipad", "tablet"]):
        device = "Tablet"
    else:
        device = "Desktop"

    forwarded_for = request.headers.get("X-Forwarded-For", "")
    ip_address = forwarded_for.split(",")[0].strip() if forwarded_for else (request.remote_addr or "")
    return {
        "device": device,
        "browser": browser,
        "platform": platform,
        "ip": ip_address,
    }


def _stamp_login_context(user: User, *, method: str) -> None:
    context = _detect_login_context()
    user.last_login_at = datetime.utcnow()
    user.last_login_device = context["device"]
    user.last_login_browser = context["browser"]
    user.last_login_platform = context["platform"]
    user.last_login_ip = context["ip"]
    user.last_login_method = method


def _captcha_serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("SECRET_KEY", "swiftcart-dev-secret")
    return URLSafeTimedSerializer(secret, salt=CAPTCHA_SALT)


def _create_captcha_challenge() -> dict:
    left = random.randint(1, 9)
    right = random.randint(1, 9)
    operator = random.choice(["+", "-"])
    if operator == "-":
        left, right = max(left, right), min(left, right)
    answer = left + right if operator == "+" else left - right
    challenge_id = _captcha_serializer().dumps({"answer": str(answer)})
    return {
        "captcha_id": challenge_id,
        "prompt": f"What is {left} {operator} {right}?",
        "expires_in_seconds": CAPTCHA_TTL_SECONDS,
    }


def _verify_captcha(captcha_id: str, captcha_answer: str) -> tuple[bool, str]:
    raw_captcha_id = str(captcha_id or "").strip()
    if not raw_captcha_id:
        return False, "Human verification expired. Refresh the verification and try again."
    try:
        payload = _captcha_serializer().loads(raw_captcha_id, max_age=CAPTCHA_TTL_SECONDS)
    except SignatureExpired:
        return False, "Human verification expired. Refresh the verification and try again."
    except BadSignature:
        return False, "Human verification expired. Refresh the verification and try again."
    if str(payload.get("answer", "")).strip() != str(captcha_answer or "").strip():
        return False, "Human verification answer is incorrect."
    return True, ""


@users_bp.get("/auth/captcha")
def auth_captcha():
    return jsonify(_create_captcha_challenge())


@users_bp.post("/auth/request-otp")
def request_otp():
    payload = request.get_json(silent=True) or {}
    identifier = _normalize_login_identifier(payload.get("email", ""))
    email = identifier.lower()
    mobile = _normalize_mobile(payload.get("mobile", ""))
    purpose = payload.get("purpose", "register").strip() or "register"
    captcha_id = payload.get("captcha_id", "")
    captcha_answer = payload.get("captcha_answer", "")

    if purpose in {"login", "recover"}:
        is_valid_captcha, captcha_message = _verify_captcha(captcha_id, captcha_answer)
        if not is_valid_captcha:
            return jsonify({"message": captcha_message}), 400

    with session_scope() as session:
        if purpose == "register":
            if not email or not mobile:
                return jsonify({"message": "Email and mobile are required for OTP verification."}), 400
            existing_user = session.query(User).filter(User.email == email).first()
            if existing_user:
                return jsonify({"message": "An account with this email already exists."}), 409
        elif purpose in {"login", "recover"}:
            linked_accounts = []
            if identifier:
                existing_user = _find_user_by_login_identifier(session, identifier)
                if not existing_user:
                    return jsonify({"message": "No account found for this email address or user code."}), 404
                banned_error = _ensure_user_is_active(existing_user)
                if banned_error:
                    return banned_error
                mobile = _normalize_mobile(existing_user.mobile)
                email = existing_user.email
                linked_accounts = [serialize_user(existing_user)]
            elif mobile:
                users = _find_users_by_mobile(session, mobile)
                if not users:
                    return jsonify({"message": "No account found for this mobile number."}), 404
                active_users = [user for user in users if not user.is_banned]
                if not active_users:
                    return _banned_account_response(users[0])
                linked_accounts = [serialize_user(user) for user in active_users]
                email = active_users[0].email
            else:
                return jsonify({"message": f"Provide email or mobile number for {purpose} OTP."}), 400

        otp_value = f"{random.randint(0, 999999):06d}"
        otp = create_otp(session, purpose=purpose, email=email, mobile=mobile, code=otp_value)
        response = {
            "message": "OTP sent successfully.",
            "otp_session_id": otp.id,
            "expires_in_seconds": 600,
        }
        if _should_show_otp_preview():
            response["otp_preview"] = otp_value
        if purpose in {"login", "recover"} and mobile:
            response["mobile"] = mobile
        if purpose in {"login", "recover"}:
            response["linked_accounts"] = linked_accounts
        return jsonify(
            {
                **response
            }
        )


@users_bp.post("/auth/verify-otp")
def verify_otp():
    payload = request.get_json(silent=True) or {}
    otp_session_id = payload.get("otp_session_id")
    otp_code = payload.get("otp_code", "").strip()

    if not otp_session_id or not otp_code:
        return jsonify({"message": "otp_session_id and otp_code are required."}), 400

    with session_scope() as session:
        otp = session.query(OtpCode).filter(OtpCode.id == otp_session_id).first()
        if not otp:
            return jsonify({"message": "OTP session not found."}), 404
        if otp.consumed_at:
            return jsonify({"message": "This OTP session has already been used."}), 400
        if otp.expires_at < datetime.utcnow():
            return jsonify({"message": "OTP expired. Please request a new one."}), 400
        if otp.code != otp_code:
            return jsonify({"message": "Invalid OTP code."}), 400

        otp.verified_at = datetime.utcnow()
        return jsonify({"message": "OTP verified successfully.", "otp_session_id": otp.id})


@users_bp.post("/auth/login-otp")
def login_with_otp():
    payload = request.get_json(silent=True) or {}
    otp_session_id = payload.get("otp_session_id")
    identifier = _normalize_login_identifier(payload.get("email", ""))
    mobile = _normalize_mobile(payload.get("mobile", ""))
    user_id = payload.get("user_id")

    if not otp_session_id or (not identifier and not mobile):
        return jsonify({"message": "otp_session_id with email, user code, or mobile is required."}), 400

    with session_scope() as session:
        otp = session.query(OtpCode).filter(OtpCode.id == otp_session_id).first()
        if not otp:
            return jsonify({"message": "OTP session not found."}), 404
        if otp.purpose != "login":
            return jsonify({"message": "This OTP session is not valid for login."}), 400
        if otp.verified_at is None:
            return jsonify({"message": "Verify the OTP before login."}), 400
        if otp.consumed_at is not None:
            return jsonify({"message": "This OTP session has already been used."}), 400
        if otp.expires_at < datetime.utcnow():
            return jsonify({"message": "OTP expired. Please request a new one."}), 400
        if identifier:
            user = _find_user_by_login_identifier(session, identifier)
            if not user:
                return jsonify({"message": "User not found."}), 404
            if otp.email != user.email:
                return jsonify({"message": "OTP does not match this email address or user code."}), 400
        else:
            if _normalize_mobile(otp.mobile) != mobile:
                return jsonify({"message": "OTP does not match this mobile number."}), 400
            matching_users = _find_users_by_mobile(session, mobile)
            if not matching_users:
                return jsonify({"message": "User not found."}), 404
            active_users = [item for item in matching_users if not item.is_banned]
            if not active_users:
                return _banned_account_response(matching_users[0])
            if len(active_users) > 1 and not user_id:
                return jsonify(
                    {
                        "message": "Multiple accounts use this mobile number. Choose one account.",
                        "linked_accounts": [serialize_user(user) for user in active_users],
                    }
                ), 409
            if user_id:
                user = next((item for item in active_users if item.id == int(user_id)), None)
            else:
                user = active_users[0]
        if not user:
            return jsonify({"message": "User not found."}), 404
        banned_error = _ensure_user_is_active(user)
        if banned_error:
            return banned_error

        otp.consumed_at = datetime.utcnow()
        _stamp_login_context(user, method="otp_login")
        return jsonify({"message": "OTP login successful.", **_auth_response(user)})


@users_bp.post("/auth/reset-password-otp")
def reset_password_with_otp():
    payload = request.get_json(silent=True) or {}
    otp_session_id = payload.get("otp_session_id")
    identifier = _normalize_login_identifier(payload.get("email", ""))
    mobile = _normalize_mobile(payload.get("mobile", ""))
    user_id = payload.get("user_id")
    new_password = payload.get("new_password", "")
    confirm_password = payload.get("confirm_password", "")

    if not otp_session_id or (not identifier and not mobile):
        return jsonify({"message": "otp_session_id with email, user code, or mobile is required."}), 400
    if not new_password or not confirm_password:
        return jsonify({"message": "New password and confirm password are required."}), 400
    if new_password != confirm_password:
        return jsonify({"message": "New password and confirm password must match."}), 400
    if len(new_password) < 8:
        return jsonify({"message": "New password must be at least 8 characters."}), 400

    with session_scope() as session:
        otp = session.query(OtpCode).filter(OtpCode.id == otp_session_id).first()
        if not otp:
            return jsonify({"message": "OTP session not found."}), 404
        if otp.purpose != "recover":
            return jsonify({"message": "This OTP session is not valid for password recovery."}), 400
        if otp.verified_at is None:
            return jsonify({"message": "Verify the OTP before resetting your password."}), 400
        if otp.consumed_at is not None:
            return jsonify({"message": "This OTP session has already been used."}), 400
        if otp.expires_at < datetime.utcnow():
            return jsonify({"message": "OTP expired. Please request a new one."}), 400

        if identifier:
            user = _find_user_by_login_identifier(session, identifier)
            if not user:
                return jsonify({"message": "User not found."}), 404
            if otp.email != user.email:
                return jsonify({"message": "OTP does not match this email address or user code."}), 400
        else:
            if _normalize_mobile(otp.mobile) != mobile:
                return jsonify({"message": "OTP does not match this mobile number."}), 400
            matching_users = _find_users_by_mobile(session, mobile)
            if not matching_users:
                return jsonify({"message": "User not found."}), 404
            active_users = [item for item in matching_users if not item.is_banned]
            if not active_users:
                return _banned_account_response(matching_users[0])
            if len(active_users) > 1 and not user_id:
                return jsonify(
                    {
                        "message": "Multiple accounts use this mobile number. Choose one account.",
                        "linked_accounts": [serialize_user(user) for user in active_users],
                    }
                ), 409
            if user_id:
                user = next((item for item in active_users if item.id == int(user_id)), None)
            else:
                user = active_users[0]

        if not user:
            return jsonify({"message": "User not found."}), 404
        banned_error = _ensure_user_is_active(user)
        if banned_error:
            return banned_error
        if verify_password(user.password_hash, new_password):
            return jsonify({"message": "Choose a different password from the current one."}), 400

        push_password_history(user, user.password_hash)
        log_user_change(
            session,
            user_id=user.id,
            field_name="password_hash",
            old_value=user.password_hash,
            new_value="[recovered with OTP]",
            changed_by="otp_recovery",
        )
        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.utcnow()
        otp.consumed_at = datetime.utcnow()
        return jsonify({"message": "Password reset successfully. You can login now."})


@users_bp.post("/auth/register")
def register():
    payload = request.get_json(silent=True) or {}
    required = [
        "first_name",
        "last_name",
        "mobile",
        "email",
        "account_type",
        "street",
        "city",
        "state",
        "pincode",
        "password",
        "otp_session_id",
    ]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        existing_user = session.query(User).filter(User.email == payload["email"].strip().lower()).first()
        if existing_user:
            return jsonify({"message": "An account with this email already exists."}), 409

        account_type = payload["account_type"].strip().lower()
        if account_type == "seller":
            account_type = "merchant"
        if account_type not in {"buyer", "merchant"}:
            return jsonify({"message": "account_type must be buyer or merchant."}), 400
        if account_type == "merchant" and not str(payload.get("shop_name", "")).strip():
            return jsonify({"message": "Shop name is required for merchant accounts."}), 400

        otp = session.query(OtpCode).filter(OtpCode.id == payload["otp_session_id"]).first()
        if not otp:
            return jsonify({"message": "OTP verification session not found."}), 400
        if otp.verified_at is None:
            return jsonify({"message": "Verify your OTP before creating the account."}), 400
        if otp.consumed_at is not None:
            return jsonify({"message": "This OTP session has already been used."}), 400
        if otp.expires_at < datetime.utcnow():
            return jsonify({"message": "OTP expired. Please request a new one."}), 400
        if otp.email != payload["email"].strip().lower() or _normalize_mobile(otp.mobile) != _normalize_mobile(payload["mobile"]):
            return jsonify({"message": "OTP does not match the provided email or mobile number."}), 400

        user = User(
            first_name=_title_case(payload["first_name"]),
            last_name=_title_case(payload["last_name"]),
            email=payload["email"].strip().lower(),
            mobile=_normalize_mobile(payload["mobile"]),
            password_hash=hash_password(payload["password"]),
            unique_code=generate_unique_code(session),
            account_type=account_type,
            shop_name=_title_case(payload.get("shop_name", "")),
            gstin=payload.get("gstin", "").strip().upper(),
            password_changed_at=datetime.utcnow(),
        )
        session.add(user)
        session.flush()

        address = Address(
            user_id=user.id,
            label="Home",
            street=_sentence_case(payload["street"]),
            city=_title_case(payload["city"]),
            state=_title_case(payload["state"]),
            pincode=payload["pincode"].strip(),
            landmark=_title_case(payload.get("landmark", "")),
            is_default=True,
        )
        session.add(address)
        session.flush()
        session.refresh(user)
        otp.consumed_at = datetime.utcnow()

        return jsonify({"message": "Account created successfully.", **_auth_response(user)}), 201


@users_bp.post("/auth/login")
def login():
    payload = _request_payload()
    identifier = _normalize_login_identifier(payload.get("email", ""))
    password = payload.get("password", "")
    captcha_id = payload.get("captcha_id", "")
    captcha_answer = payload.get("captcha_answer", "")

    is_valid_captcha, captcha_message = _verify_captcha(captcha_id, captcha_answer)
    if not is_valid_captcha:
        return jsonify({"message": captcha_message}), 400

    with session_scope() as session:
        user = _find_user_by_login_identifier(session, identifier)
        if not user:
            repaired_owner = _repair_or_bootstrap_owner_account(session, identifier, password)
            if repaired_owner:
                user = repaired_owner
            else:
                return jsonify({"message": "Invalid email or user code."}), 401

        password_ok = verify_password(user.password_hash, password)
        if not password_ok:
            password_ok = _sync_owner_credentials_if_needed(session, user, password)
        if not password_ok:
            return jsonify({"message": "Invalid password."}), 401

        _upgrade_password_hash_if_needed(user, password)
        banned_error = _ensure_user_is_active(user)
        if banned_error:
            return banned_error

        _stamp_login_context(user, method="password_login")
        return jsonify(
            {
                "message": "Login successful.",
                **_auth_response(user),
            }
        )


def _redirect_path_for_user(payload: dict) -> str:
    user = payload.get("user", {}) or {}
    if user.get("is_owner"):
        return "/owner-workspace"
    if str(user.get("account_type", "")).strip().lower() in {"merchant", "seller"}:
        return "/Merchant.html"
    return "/Account_Details.html"


def _encode_user_payload(user_payload: dict) -> str:
    serialized = json.dumps(user_payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(serialized).decode("ascii").rstrip("=")


def complete_login_form_submission():
    payload = request.form.to_dict(flat=True)
    identifier = _normalize_login_identifier(payload.get("email", ""))
    password = payload.get("password", "")
    captcha_id = payload.get("captcha_id", "")
    captcha_answer = payload.get("captcha_answer", "")

    is_valid_captcha, captcha_message = _verify_captcha(captcha_id, captcha_answer)
    if not is_valid_captcha:
        return redirect(f"/login?{urlencode({'error': captcha_message})}", code=303)

    with session_scope() as session:
        user = _find_user_by_login_identifier(session, identifier)
        if not user:
            repaired_owner = _repair_or_bootstrap_owner_account(session, identifier, password)
            if repaired_owner:
                user = repaired_owner
            else:
                return redirect(f"/login?{urlencode({'error': 'Invalid email or user code.'})}", code=303)

        password_ok = verify_password(user.password_hash, password)
        if not password_ok:
            password_ok = _sync_owner_credentials_if_needed(session, user, password)
        if not password_ok:
            return redirect(f"/login?{urlencode({'error': 'Invalid password.'})}", code=303)

        _upgrade_password_hash_if_needed(user, password)
        banned_error = _ensure_user_is_active(user)
        if banned_error:
            response, _status_code = banned_error
            message = (response.get_json(silent=True) or {}).get("message") or "Your account is not active."
            return redirect(f"/login?{urlencode({'error': message})}", code=303)

        _stamp_login_context(user, method="password_login")
        auth_payload = _auth_response(user)
        query = urlencode(
            {
                "token": auth_payload["token"],
                "user": _encode_user_payload(auth_payload["user"]),
                "redirect": _redirect_path_for_user(auth_payload),
            }
        )
        return redirect(f"/auth-complete?{query}", code=303)


@users_bp.post("/users/<int:user_id>/change-password")
def change_password(user_id: int):
    payload = request.get_json(silent=True) or {}
    current_password = payload.get("current_password", "")
    new_password = payload.get("new_password", "")
    confirm_password = payload.get("confirm_password", "")

    if not current_password or not new_password or not confirm_password:
        return jsonify({"message": "All password fields are required."}), 400
    if new_password != confirm_password:
        return jsonify({"message": "New password and confirm password must match."}), 400
    if len(new_password) < 8:
        return jsonify({"message": "New password must be at least 8 characters."}), 400

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        if not verify_password(user.password_hash, current_password):
            return jsonify({"message": "Current password is incorrect."}), 400
        if verify_password(user.password_hash, new_password):
            return jsonify({"message": "Choose a different password from the current one."}), 400

        push_password_history(user, user.password_hash)
        log_user_change(
            session,
            user_id=user.id,
            field_name="password_hash",
            old_value=user.password_hash,
            new_value="[updated secure hash]",
            changed_by="user",
        )
        user.password_hash = hash_password(new_password)
        user.password_changed_at = datetime.utcnow()

        return jsonify(
            {
                "message": "Password updated successfully.",
                **_auth_response(user),
                "password_history_count": len(get_password_history(user)),
            }
        )


@users_bp.get("/users/<int:user_id>/profile")
def get_profile(user_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        payload = serialize_user(user)
        payload["auth_token"] = create_auth_token(user)
        return jsonify(payload)


@users_bp.put("/users/<int:user_id>/profile")
def update_profile(user_id: int):
    payload = request.get_json(silent=True) or {}

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error

        next_email = payload.get("email", user.email).strip().lower()
        if not next_email or "@" not in next_email:
            return jsonify({"message": "Enter a valid email address."}), 400
        if next_email != user.email:
            existing = session.query(User).filter(User.email == next_email, User.id != user.id).first()
            if existing:
                return jsonify({"message": "Another account already uses this email."}), 409
            log_user_change(session, user_id=user.id, field_name="email", old_value=user.email, new_value=next_email, changed_by="user")
            user.email = next_email

        next_first_name = _title_case(payload.get("first_name", user.first_name))
        next_last_name = _title_case(payload.get("last_name", user.last_name))
        next_mobile = _normalize_mobile(payload.get("mobile", user.mobile))
        next_shop_name = _title_case(payload.get("shop_name", user.shop_name))
        next_gstin = str(payload.get("gstin", user.gstin)).strip().upper()

        if not next_first_name or not next_last_name:
            return jsonify({"message": "First name and last name are required."}), 400
        if not next_mobile:
            return jsonify({"message": "Enter a valid mobile number with country code."}), 400

        log_user_change(session, user_id=user.id, field_name="first_name", old_value=user.first_name, new_value=next_first_name, changed_by="user")
        log_user_change(session, user_id=user.id, field_name="last_name", old_value=user.last_name, new_value=next_last_name, changed_by="user")
        log_user_change(session, user_id=user.id, field_name="mobile", old_value=user.mobile, new_value=next_mobile, changed_by="user")
        log_user_change(session, user_id=user.id, field_name="shop_name", old_value=user.shop_name, new_value=next_shop_name, changed_by="user")
        log_user_change(session, user_id=user.id, field_name="gstin", old_value=user.gstin, new_value=next_gstin, changed_by="user")

        user.first_name = next_first_name
        user.last_name = next_last_name
        user.mobile = next_mobile
        user.shop_name = next_shop_name if user.account_type in {"merchant", "seller"} else ""
        user.gstin = next_gstin if user.account_type in {"merchant", "seller"} else ""

        return jsonify({"message": "Personal information updated successfully.", **_auth_response(user)})


@users_bp.post("/users/<int:user_id>/address")
def update_address(user_id: int):
    payload = request.get_json(silent=True) or {}
    required = ["street", "city", "state", "pincode"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error

        address = next((item for item in user.addresses if item.is_default), None) or (user.addresses[0] if user.addresses else Address(user_id=user.id))
        if not user.addresses:
            address.label = "Home"
            address.is_default = True
            session.add(address)
            session.flush()

        _apply_address_updates(session, user=user, address=address, payload=payload)

        session.flush()
        session.refresh(user)
        return jsonify({"message": "Address updated successfully.", **_auth_response(user)})


@users_bp.get("/users/<int:user_id>/addresses")
def list_addresses(user_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        addresses = sorted(user.addresses, key=lambda item: (not item.is_default, item.created_at))
        return jsonify([serialize_address(address) for address in addresses])


@users_bp.post("/users/<int:user_id>/addresses")
def add_address(user_id: int):
    payload = request.get_json(silent=True) or {}
    required = ["street", "city", "state", "pincode"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error

        make_default = bool(payload.get("is_default")) or not user.addresses
        if make_default:
            for entry in user.addresses:
                entry.is_default = False

        address = Address(
            user_id=user.id,
            label=_title_case(payload.get("label", "")) or _next_address_label(user),
            street="",
            city="",
            state="",
            pincode="",
            landmark="",
            is_default=make_default,
        )
        session.add(address)
        session.flush()
        _apply_address_updates(session, user=user, address=address, payload=payload)
        session.flush()
        session.refresh(user)
        return jsonify({"message": "New address saved successfully.", **_auth_response(user)}), 201


@users_bp.put("/users/<int:user_id>/addresses/<int:address_id>")
def update_saved_address(user_id: int, address_id: int):
    payload = request.get_json(silent=True) or {}
    required = ["street", "city", "state", "pincode"]
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        return jsonify({"message": f"Missing fields: {', '.join(missing)}"}), 400

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        address = next((item for item in user.addresses if item.id == address_id), None)
        if not address:
            return jsonify({"message": "Address not found."}), 404

        if bool(payload.get("is_default")):
            for entry in user.addresses:
                entry.is_default = entry.id == address.id

        _apply_address_updates(session, user=user, address=address, payload=payload)
        session.flush()
        session.refresh(user)
        return jsonify({"message": "Saved address updated successfully.", **_auth_response(user)})


@users_bp.post("/users/<int:user_id>/addresses/<int:address_id>/default")
def set_default_address(user_id: int, address_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        address = next((item for item in user.addresses if item.id == address_id), None)
        if not address:
            return jsonify({"message": "Address not found."}), 404

        for entry in user.addresses:
            entry.is_default = entry.id == address.id
        log_user_change(
            session,
            user_id=user.id,
            field_name="default_address",
            old_value="changed",
            new_value=address.label,
            changed_by="user",
        )
        session.flush()
        session.refresh(user)
        return jsonify({"message": f"{address.label} is now your default delivery address.", **_auth_response(user)})


@users_bp.delete("/users/<int:user_id>/addresses/<int:address_id>")
def delete_saved_address(user_id: int, address_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        address = next((item for item in user.addresses if item.id == address_id), None)
        if not address:
            return jsonify({"message": "Address not found."}), 404
        if len(user.addresses) <= 1:
            return jsonify({"message": "Keep at least one saved address on the account."}), 400

        removed_label = address.label or "Address"
        removed_default = bool(address.is_default)
        remaining_addresses = [item for item in user.addresses if item.id != address.id]
        session.delete(address)
        session.flush()

        if removed_default and remaining_addresses:
            next_default = sorted(remaining_addresses, key=lambda item: item.created_at)[0]
            next_default.is_default = True
            log_user_change(
                session,
                user_id=user.id,
                field_name="default_address",
                old_value=removed_label,
                new_value=next_default.label,
                changed_by="user",
            )

        log_user_change(
            session,
            user_id=user.id,
            field_name="address_deleted",
            old_value=removed_label,
            new_value="Deleted",
            changed_by="user",
        )
        session.flush()
        session.refresh(user)
        return jsonify({"message": f"{removed_label} was removed from saved addresses.", **_auth_response(user)})


@users_bp.post("/users/<int:user_id>/profile-image")
def upload_profile_image(user_id: int):
    uploaded_file = request.files.get("image")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"message": "Choose an image to upload."}), 400

    safe_name = secure_filename(uploaded_file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        return jsonify({"message": "Only PNG, JPG, JPEG, or WEBP images are allowed."}), 400

    PROFILE_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    final_name = f"user-{user_id}-{secrets.token_hex(8)}{suffix}"
    target_path = PROFILE_UPLOAD_DIR / final_name
    uploaded_file.save(target_path)
    image_path = f"uploads/profiles/{final_name}"

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        log_user_change(
            session,
            user_id=user.id,
            field_name="profile_image",
            old_value=user.profile_image,
            new_value=image_path,
            changed_by="user",
        )
        user.profile_image = image_path
        session.flush()
        session.refresh(user)
        return jsonify({"message": "Profile image updated successfully.", **_auth_response(user)})


@users_bp.delete("/users/<int:user_id>/profile-image")
def remove_profile_image(user_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        log_user_change(
            session,
            user_id=user.id,
            field_name="profile_image",
            old_value=user.profile_image,
            new_value="",
            changed_by="user",
        )
        user.profile_image = ""
        session.flush()
        session.refresh(user)
        return jsonify({"message": "Profile image removed successfully.", **_auth_response(user)})


@users_bp.get("/users/<int:user_id>/wishlist")
def get_wishlist(user_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        wishlist_rows = (
            session.query(WishlistItem, Product)
            .join(Product, Product.id == WishlistItem.product_id)
            .options(joinedload(Product.category), joinedload(Product.seller))
            .filter(WishlistItem.user_id == user_id)
            .order_by(WishlistItem.created_at.desc(), WishlistItem.id.desc())
            .all()
        )
        products = [product for _, product in wishlist_rows]
        return jsonify([serialize_product(product) for product in products])


@users_bp.post("/users/<int:user_id>/wishlist")
def add_to_wishlist(user_id: int):
    payload = request.get_json(silent=True) or {}
    product_id = payload.get("product_id")
    if not product_id:
        return jsonify({"message": "product_id is required"}), 400

    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        existing = (
            session.query(WishlistItem)
            .filter(WishlistItem.user_id == user_id, WishlistItem.product_id == product_id)
            .first()
        )
        if existing:
            return jsonify({"message": "Product already in wishlist."})

        session.add(WishlistItem(user_id=user_id, product_id=product_id))
        return jsonify({"message": "Added to wishlist."}), 201


@users_bp.delete("/users/<int:user_id>/wishlist/<int:product_id>")
def remove_from_wishlist(user_id: int, product_id: int):
    with session_scope() as session:
        user, error = _require_same_user(session, user_id)
        if error:
            return error
        item = (
            session.query(WishlistItem)
            .filter(WishlistItem.user_id == user_id, WishlistItem.product_id == product_id)
            .first()
        )
        if not item:
            return jsonify({"message": "Wishlist item not found."}), 404

        session.delete(item)
        return jsonify({"message": "Removed from wishlist."})


@users_bp.post("/admin/users/<int:target_user_id>/ban")
def admin_ban_user(target_user_id: int):
    payload = request.get_json(silent=True) or {}
    reason = _sentence_case(payload.get("reason", "")) or "Owner disabled this account."

    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error

        user = session.query(User).filter(User.id == target_user_id).first()
        if not user:
            return jsonify({"message": "User not found."}), 404
        if user.account_type == "owner":
            return jsonify({"message": "The owner account cannot be banned."}), 403

        previous_status = "Banned" if user.is_banned else "Active"
        log_user_change(
            session,
            user_id=user.id,
            field_name="account_status",
            old_value=previous_status,
            new_value=f"Banned: {reason}",
            changed_by=f"owner:{owner.id}",
        )
        user.is_banned = True
        user.ban_reason = reason
        user.banned_at = datetime.utcnow()
        user.banned_by_user_id = owner.id
        session.flush()
        session.refresh(user)
        return jsonify(
            {
                "message": f"{user.first_name} has been banned successfully.",
                "user": serialize_user(user),
            }
        )


@users_bp.post("/admin/users/<int:target_user_id>/unban")
def admin_unban_user(target_user_id: int):
    with session_scope() as session:
        owner, error = _require_owner(session)
        if error:
            return error

        user = session.query(User).filter(User.id == target_user_id).first()
        if not user:
            return jsonify({"message": "User not found."}), 404
        if user.account_type == "owner":
            return jsonify({"message": "The owner account is always active."}), 403

        previous_status = f"Banned: {user.ban_reason}" if user.is_banned else "Active"
        log_user_change(
            session,
            user_id=user.id,
            field_name="account_status",
            old_value=previous_status,
            new_value="Active",
            changed_by=f"owner:{owner.id}",
        )
        user.is_banned = False
        user.ban_reason = ""
        user.banned_at = None
        user.banned_by_user_id = owner.id
        session.flush()
        session.refresh(user)
        return jsonify(
            {
                "message": f"{user.first_name} has been unbanned successfully.",
                "user": serialize_user(user),
            }
        )
