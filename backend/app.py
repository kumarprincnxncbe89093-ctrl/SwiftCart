from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from flask import Flask, jsonify, redirect, request, send_from_directory
from sqlalchemy.exc import DBAPIError, OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.models import DATABASE_URL, init_db
from backend.routes.orders import orders_bp
from backend.routes.products import products_bp
from backend.routes.users import complete_login_form_submission, users_bp


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = FRONTEND_DIR / "uploads" / "profiles"
DEFAULT_PUBLIC_SITE_URL = ""
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self' https:",
        "img-src 'self' data: https: blob:",
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
        "script-src 'self'",
        "font-src 'self' data: https://cdnjs.cloudflare.com",
        "connect-src 'self' https:",
        "frame-src 'self' https://maps.google.com https://www.google.com",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self' https:",
        "frame-ancestors 'none'",
        "upgrade-insecure-requests",
        "block-all-mixed-content",
    ]
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    app.config["ENV_NAME"] = os.getenv("FLASK_ENV", "production")
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "swiftcart-dev-secret")
    app.config["DB_READY"] = False
    app.config["DB_INIT_ERROR"] = ""
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        init_db()
        app.config["DB_READY"] = True
    except Exception as exc:
        app.config["DB_READY"] = False
        app.config["DB_INIT_ERROR"] = str(exc)
        logger.exception("SwiftCart started without a ready database connection.")

    app.register_blueprint(products_bp, url_prefix="/api")
    app.register_blueprint(users_bp, url_prefix="/api")
    app.register_blueprint(orders_bp, url_prefix="/api")

    def should_force_https() -> bool:
        return str(
            os.getenv(
                "FORCE_HTTPS",
                "1" if app.config["ENV_NAME"].strip().lower() == "production" else "0",
            )
        ).strip().lower() in {"1", "true", "yes", "on"}

    def should_redirect_to_canonical_host() -> bool:
        return str(os.getenv("ENABLE_CANONICAL_REDIRECT", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def normalized_host(hostname: str) -> str:
        host = (hostname or "").strip().lower().rstrip(".")
        if not host:
            return ""
        if host.startswith("["):
            return host
        if ":" in host and host.count(":") == 1:
            return host.split(":", 1)[0]
        return host

    def is_local_host(hostname: str) -> bool:
        host = normalized_host(hostname)
        return host in {"127.0.0.1", "localhost"} or host.endswith(".local")

    def canonical_origin() -> str:
        configured = (
            os.getenv("PUBLIC_SITE_URL")
            or os.getenv("CANONICAL_BASE_URL")
            or DEFAULT_PUBLIC_SITE_URL
        ).strip().rstrip("/")
        if not configured:
            return ""
        if "://" not in configured:
            configured = f"https://{configured}"
        return configured

    def canonical_host() -> str:
        origin = canonical_origin()
        if not origin:
            return ""
        return normalized_host(urlsplit(origin).netloc)

    def accepted_public_hosts() -> set[str]:
        host = canonical_host()
        if not host:
            return set()
        hosts = {host}
        if host.startswith("www."):
            hosts.add(host[4:])
        else:
            hosts.add(f"www.{host}")
        return {value for value in hosts if value}

    def database_unavailable_response():
        message = "SwiftCart cannot reach the database right now. Please try again shortly."
        if not app.config.get("DB_INIT_ERROR"):
            message = "SwiftCart is starting up. Please try again in a moment."
        return (
            jsonify(
                {
                    "message": message,
                    "status": "database_unavailable",
                    "service": "SwiftCart API",
                }
            ),
            503,
        )

    @app.before_request
    def redirect_http_to_https():
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        already_secure = request.is_secure or "https" in forwarded_proto.lower()
        if request.path in {"/healthz", "/api/health"}:
            return None
        if already_secure or not should_force_https() or is_local_host(request.host):
            return None
        secure_url = request.url.replace("http://", "https://", 1)
        redirect_code = 301 if request.method in {"GET", "HEAD", "OPTIONS"} else 307
        return redirect(secure_url, code=redirect_code)

    @app.before_request
    def redirect_to_canonical_host():
        if request.path in {"/healthz", "/api/health"}:
            return None
        if not should_redirect_to_canonical_host():
            return None
        target_origin = canonical_origin()
        target_host = canonical_host()
        current_host = normalized_host(request.host)
        if (
            not target_origin
            or not target_host
            or is_local_host(current_host)
            or current_host in accepted_public_hosts()
        ):
            return None
        target_parts = urlsplit(target_origin)
        redirect_url = urlunsplit(
            (
                target_parts.scheme or "https",
                target_parts.netloc,
                request.path,
                request.query_string.decode("utf-8", "ignore"),
                "",
            )
        )
        redirect_code = 301 if request.method in {"GET", "HEAD", "OPTIONS"} else 307
        return redirect(redirect_url, code=redirect_code)

    @app.before_request
    def gate_api_when_database_is_unavailable():
        if request.method == "OPTIONS":
            return None
        if not request.path.startswith("/api"):
            return None
        if request.path == "/api/health":
            return None
        if app.config.get("DB_READY"):
            return None
        return database_unavailable_response()

    @app.after_request
    def add_headers(response):
        origin = request.headers.get("Origin", "").strip()
        if origin and origin in ALLOWED_ORIGINS:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(self)"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
        if request.is_secure or "https" in forwarded_proto.lower():
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if normalized_host(request.host).endswith(".up.railway.app"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        canonical = canonical_origin()
        if canonical and not request.path.startswith("/api") and response.mimetype == "text/html":
            target_parts = urlsplit(canonical)
            response.headers["Link"] = (
                f"<{urlunsplit((target_parts.scheme or 'https', target_parts.netloc, request.path, request.query_string.decode('utf-8', 'ignore'), ''))}>; rel=\"canonical\""
            )
        if (
            request.path.startswith("/api")
            or response.mimetype in {"text/html", "text/css", "application/javascript", "text/javascript"}
            or request.path.endswith((".html", ".css", ".js"))
        ):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/api/health")
    def health():
        is_ready = bool(app.config.get("DB_READY"))
        payload = {
            "status": "ok" if is_ready else "degraded",
            "service": "SwiftCart API",
            "database_ready": is_ready,
            "database_engine": "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql",
        }
        if not is_ready and app.config.get("DB_INIT_ERROR"):
            payload["database_error"] = app.config["DB_INIT_ERROR"]
        return jsonify(payload), (200 if is_ready else 503)

    @app.get("/healthz")
    def live_health():
        return jsonify(
            {
                "status": "ok",
                "service": "SwiftCart API",
                "database_ready": bool(app.config.get("DB_READY")),
                "database_engine": "sqlite" if DATABASE_URL.startswith("sqlite") else "postgresql",
            }
        ), 200

    @app.get("/api/site-profile")
    def site_profile():
        support_email = (os.getenv("PUBLIC_SUPPORT_EMAIL") or "").strip()
        if support_email.lower().endswith("@demo.com"):
            support_email = ""
        support_phone = (os.getenv("PUBLIC_SUPPORT_PHONE") or "").strip()
        business_address = (
            os.getenv("PUBLIC_BUSINESS_ADDRESS") or "Bengaluru, Karnataka, India"
        ).strip()
        support_hours = (
            os.getenv("PUBLIC_SUPPORT_HOURS") or "Monday to Saturday, 10:00 AM to 6:00 PM IST"
        ).strip()
        legal_name = (os.getenv("PUBLIC_LEGAL_NAME") or "SwiftCart").strip()
        return jsonify(
            {
                "brand_name": "SwiftCart",
                "legal_name": legal_name,
                "support_email": support_email,
                "support_phone": support_phone,
                "business_address": business_address,
                "support_hours": support_hours,
            }
        )

    @app.errorhandler(OperationalError)
    @app.errorhandler(DBAPIError)
    def handle_database_error(error):
        logger.exception("Database request failed: %s", error)
        if request.path.startswith("/api"):
            return database_unavailable_response()
        return send_from_directory(FRONTEND_DIR, "index.html")

    def serve_frontend_page(filename: str):
        return send_from_directory(FRONTEND_DIR, filename)

    @app.get("/")
    def root():
        return serve_frontend_page("index.html")

    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        if request.method == "POST":
            return complete_login_form_submission()
        return serve_frontend_page("Login.html")

    @app.get("/register")
    def register_page():
        return serve_frontend_page("Account_Creation.html")

    @app.get("/checkout")
    def checkout_page():
        return serve_frontend_page("Payment.html")

    @app.get("/terms")
    def terms_page():
        return serve_frontend_page("terms.html")

    @app.get("/owner-workspace")
    def owner_workspace_page():
        return serve_frontend_page("Admin.html")

    @app.get("/<path:filename>")
    def frontend_files(filename: str):
        candidate_files = [filename]
        if "." not in Path(filename).name:
            candidate_files.append(f"{filename}.html")
        for candidate in candidate_files:
            target = FRONTEND_DIR / candidate
            if target.exists() and target.is_file():
                return send_from_directory(FRONTEND_DIR, candidate)
        return serve_frontend_page("index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        threaded=True,
    )
