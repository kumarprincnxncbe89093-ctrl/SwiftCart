from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory
from sqlalchemy.exc import DBAPIError, OperationalError
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.models import init_db
from backend.routes.orders import orders_bp
from backend.routes.products import products_bp
from backend.routes.users import users_bp


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
UPLOADS_DIR = FRONTEND_DIR / "uploads" / "profiles"
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
    app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path="")
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

    def is_local_host(hostname: str) -> bool:
        host = hostname.split(":", 1)[0].strip().lower()
        return host in {"127.0.0.1", "localhost"} or host.endswith(".local")

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
        if already_secure or not should_force_https() or is_local_host(request.host):
            return None
        secure_url = request.url.replace("http://", "https://", 1)
        redirect_code = 301 if request.method in {"GET", "HEAD", "OPTIONS"} else 307
        return redirect(secure_url, code=redirect_code)

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
        if request.host.endswith(".up.railway.app"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
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
        }
        if not is_ready and app.config.get("DB_INIT_ERROR"):
            payload["database_error"] = app.config["DB_INIT_ERROR"]
        return jsonify(payload), (200 if is_ready else 503)

    @app.errorhandler(OperationalError)
    @app.errorhandler(DBAPIError)
    def handle_database_error(error):
        logger.exception("Database request failed: %s", error)
        if request.path.startswith("/api"):
            return database_unavailable_response()
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/")
    def root():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/checkout")
    def checkout_page():
        return send_from_directory(FRONTEND_DIR, "Payment.html")

    @app.get("/owner-workspace")
    def owner_workspace_page():
        return send_from_directory(FRONTEND_DIR, "Admin.html")

    @app.get("/<path:filename>")
    def frontend_files(filename: str):
        target = FRONTEND_DIR / filename
        if target.exists():
            return send_from_directory(FRONTEND_DIR, filename)
        return send_from_directory(FRONTEND_DIR, "index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5000")),
        threaded=True,
    )
