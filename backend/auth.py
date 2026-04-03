from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
from flask import jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from backend.models import User


AUTH_TOKEN_SALT = "swiftcart-auth-token"
JWT_ALGORITHM = "HS256"


def _env_int(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, str(default))).strip()
    try:
        return int(raw_value)
    except ValueError:
        return default


AUTH_TOKEN_MAX_AGE_SECONDS = _env_int("AUTH_TOKEN_MAX_AGE_SECONDS", 86400)


def _secret_key() -> str:
    return os.getenv("SECRET_KEY", "swiftcart-dev-secret")


def _legacy_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret_key(), salt=AUTH_TOKEN_SALT)


def _password_marker(user: User) -> str:
    return user.password_changed_at.isoformat() if user.password_changed_at else ""


def create_auth_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "id": user.id,
        "role": user.account_type,
        "pwd": _password_marker(user),
        "iat": now,
        "exp": now + timedelta(seconds=AUTH_TOKEN_MAX_AGE_SECONDS),
    }
    return jwt.encode(payload, _secret_key(), algorithm=JWT_ALGORITHM)


def _extract_auth_token() -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return request.headers.get("X-Auth-Token", "").strip()


def _decode_auth_token(token: str) -> dict:
    try:
        return jwt.decode(token, _secret_key(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise SignatureExpired(str(error)) from error
    except jwt.InvalidTokenError:
        try:
            return _legacy_serializer().loads(token, max_age=AUTH_TOKEN_MAX_AGE_SECONDS)
        except SignatureExpired:
            raise
        except BadSignature as error:
            raise BadSignature(str(error)) from error


def require_authenticated_user(
    session,
    *,
    expected_user_id: int | None = None,
    allowed_roles: set[str] | None = None,
):
    token = _extract_auth_token()
    if not token:
        return None, (jsonify({"message": "Authentication is required."}), 401)

    try:
        payload = _decode_auth_token(token)
    except SignatureExpired:
        return None, (jsonify({"message": "Your session has expired. Please login again.", "force_logout": True}), 401)
    except BadSignature:
        return None, (jsonify({"message": "Your session is invalid. Please login again.", "force_logout": True}), 401)

    user_id = payload.get("id", payload.get("user_id"))
    if not isinstance(user_id, int):
        return None, (jsonify({"message": "Invalid session payload.", "force_logout": True}), 401)

    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        return None, (jsonify({"message": "User not found for this session.", "force_logout": True}), 401)

    if payload.get("pwd", "") != _password_marker(user):
        return None, (jsonify({"message": "Your session is no longer valid. Please login again.", "force_logout": True}), 401)

    if user.is_banned:
        reason = str(user.ban_reason or "").strip() or "Contact the owner for reactivation."
        return None, (
            jsonify(
                {
                    "message": f"Your account has been banned. {reason}",
                    "is_banned": True,
                    "force_logout": True,
                }
            ),
            403,
        )

    if expected_user_id is not None and user.id != expected_user_id:
        return None, (jsonify({"message": "You do not have permission to access this resource."}), 403)

    if allowed_roles and user.account_type not in allowed_roles:
        return None, (jsonify({"message": "You do not have permission to perform this action."}), 403)

    return user, None
